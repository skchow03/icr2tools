"""Stage 3 modeling jobs: safe blockout creation and bounded recipe revisions.

This module is an AI *execution contract*. An AI may propose a JSON plan, but
this deterministic code validates it, calls Stage 2, compares revisions, and
produces CAD-editable N3/3DO artifacts. No LLM is executed in GitHub Actions.

Unlike an arbitrary 3DO binary patcher, revision mode deliberately accepts
ONLY Stage 2 JSON recipes. Original proprietary carsets and arbitrary
recompiled BSP trees are not rewritten.
"""
from __future__ import annotations

from copy import deepcopy
from hashlib import sha256
import json
from pathlib import Path
import shutil
import tempfile

from .blockouts import vintage_open_wheel_recipe
from .parametric import RecipeError, generate_source
from .stage2 import generate_package, validate_source

JOB_SCHEMA = "icr2.n3.job.v1"
MAX_EDITS = 128
MAX_JSON_BYTES = 4 * 1024 * 1024


def _load_json(path):
    path = Path(path)
    if path.stat().st_size > MAX_JSON_BYTES:
        raise RecipeError(f"{path}: JSON exceeds 4 MiB safety limit")
    try:
        return json.loads(path.read_text(encoding="utf-8-sig"))
    except json.JSONDecodeError as exc:
        raise RecipeError(f"{path}: invalid JSON: {exc}") from exc


def _check_keys(obj, allowed, required, where):
    if not isinstance(obj, dict):
        raise RecipeError(f"{where}: expected JSON object")
    extra = set(obj) - set(allowed)
    absent = set(required) - set(obj)
    if extra:
        raise RecipeError(f"{where}: unexpected keys {', '.join(sorted(extra))}")
    if absent:
        raise RecipeError(f"{where}: missing keys {', '.join(sorted(absent))}")


def _name(obj, where):
    if not isinstance(obj, str) or not obj:
        raise RecipeError(f"{where}: expected nonempty component name")
    return obj


def _canonical_hash(value):
    return sha256(json.dumps(
        value, sort_keys=True, separators=(",", ":"), ensure_ascii=True
    ).encode("utf-8")).hexdigest()


def _recipe_index(recipe):
    return {op["name"]: op for op in recipe["operations"]}


def _safe_base(path, repository_root):
    """Only allow repository-relative recipe paths; reject ../ and symlinks out."""
    if not isinstance(path, str):
        raise RecipeError("base_recipe: expected repository-relative path")
    path_obj = Path(path)
    if (path_obj.is_absolute() or not path_obj.parts or
            ".." in path_obj.parts or path_obj.suffix.lower() != ".json"):
        raise RecipeError("base_recipe: expected .json path inside repository, without '..'")
    root = Path(repository_root).resolve()
    located = (root / path_obj).resolve()
    if not located.is_relative_to(root):
        raise RecipeError("base_recipe resolves outside the repository")
    if not located.is_file():
        raise FileNotFoundError(located)
    return located


def _quality_spec(config):
    if config is None:
        return {"max_polygons": 20000, "max_abs_polygon_delta": None,
                "must_preserve": []}
    _check_keys(
        config, {"max_polygons", "max_abs_polygon_delta", "must_preserve"},
        set(), "quality")
    maximum = config.get("max_polygons", 20000)
    delta = config.get("max_abs_polygon_delta")
    preserved = config.get("must_preserve", [])
    if (type(maximum) is not int or not 1 <= maximum <= 60000):
        raise RecipeError("quality.max_polygons: expected integer 1..60000")
    if delta is not None and (type(delta) is not int or
                              not 0 <= delta <= 60000):
        raise RecipeError("quality.max_abs_polygon_delta: expected integer 0..60000")
    if not isinstance(preserved, list) or not all(
            isinstance(x, str) and x for x in preserved):
        raise RecipeError("quality.must_preserve: expected component name list")
    if len(set(preserved)) != len(preserved):
        raise RecipeError("quality.must_preserve contains duplicate components")
    return {
        "max_polygons": maximum,
        "max_abs_polygon_delta": delta,
        "must_preserve": preserved,
    }


def _revision(job, repository_root):
    _check_keys(job, {
        "schema", "mode", "goal", "base_recipe", "base_recipe_sha256",
        "edits", "quality",
    }, {"schema", "mode", "base_recipe", "edits"}, "revision job")
    base_file = _safe_base(job["base_recipe"], repository_root)
    raw = base_file.read_bytes()
    if "base_recipe_sha256" in job:
        expected = job["base_recipe_sha256"]
        if not isinstance(expected, str) or not expected == sha256(raw).hexdigest():
            raise RecipeError("base_recipe SHA256 mismatch; re-inspect the starting model")
    original = _load_json(base_file)
    # Validate the baseline with exactly the Stage 2 generator/compiler.
    old_src, old_manifest = generate_source(original)
    validate_source(old_src)
    modified = deepcopy(original)
    operations = modified["operations"]
    edits = job["edits"]
    if not isinstance(edits, list) or not 1 <= len(edits) <= MAX_EDITS:
        raise RecipeError(f"edits: expected 1-{MAX_EDITS} ordered changes")
    touched = set()
    changes = []
    for i, edit in enumerate(edits):
        where = f"edits[{i}]"
        _check_keys(edit, {"action", "target", "operation"},
                    {"action"}, where)
        action = edit["action"]
        index = {x["name"]: j for j, x in enumerate(operations)}
        if action == "add":
            _check_keys(edit, {"action", "operation"}, {"action", "operation"}, where)
            operation = edit["operation"]
            if not isinstance(operation, dict):
                raise RecipeError(f"{where}: operation must be an object")
            name = _name(operation.get("name"), where + ".operation.name")
            if name in index or name in touched:
                raise RecipeError(f"{where}: component already exists or was edited: {name}")
            operations.append(deepcopy(operation))
        elif action in ("replace", "remove"):
            _check_keys(edit,
                        {"action", "target", "operation"} if action == "replace"
                        else {"action", "target"},
                        {"action", "target", "operation"} if action == "replace"
                        else {"action", "target"}, where)
            name = _name(edit["target"], where + ".target")
            if name not in index or name in touched:
                raise RecipeError(f"{where}: target missing or already edited: {name}")
            if action == "replace":
                operation = edit["operation"]
                if not isinstance(operation, dict) or operation.get("name") != name:
                    raise RecipeError(f"{where}: replacement must keep component name {name}")
                operations[index[name]] = deepcopy(operation)
            else:
                operations.pop(index[name])
        else:
            raise RecipeError(f"{where}: action must be add, replace, or remove")
        touched.add(name)
        changes.append({"action": action, "name": name})
    # Final generation validates references (e.g. mirrors of removed parts),
    # geometry, UV ranges, non-degenerate faces and all operation schemas.
    new_src, new_manifest = generate_source(modified)
    validate_source(new_src)
    old_map = _recipe_index(original)
    new_map = _recipe_index(modified)
    for name in set(old_map).intersection(new_map).difference(touched):
        if _canonical_hash(old_map[name]) != _canonical_hash(new_map[name]):
            raise RecipeError(f"Untargeted component changed: {name}")
    return modified, old_manifest, new_manifest, {
        "mode": "revise",
        "base_recipe": str(base_file),
        "original_sha256": sha256(raw).hexdigest(),
        "changes_requested": changes,
        "added": sorted(set(new_map) - set(old_map)),
        "removed": sorted(set(old_map) - set(new_map)),
        "modified": sorted(
            name for name in set(old_map).intersection(new_map)
            if _canonical_hash(old_map[name]) != _canonical_hash(new_map[name])),
        "unchanged": sorted(
            name for name in set(old_map).intersection(new_map)
            if _canonical_hash(old_map[name]) == _canonical_hash(new_map[name])),
        "baseline_recipe": original,
    }


def plan_recipe(job, *, repository_root):
    """Translate one strictly structured job into an ordinary Stage 2 recipe."""
    _check_keys(job, {
        "schema", "mode", "goal", "template", "parameters", "base_recipe",
        "base_recipe_sha256", "edits", "quality",
    }, {"schema", "mode"}, "job")
    if job["schema"] != JOB_SCHEMA:
        raise RecipeError(f"job.schema: expected {JOB_SCHEMA}")
    goal = job.get("goal", "")
    if not isinstance(goal, str) or len(goal) > 2000:
        raise RecipeError("goal: expected text up to 2000 characters")
    quality = _quality_spec(job.get("quality"))
    if job["mode"] == "blockout":
        _check_keys(job, {
            "schema", "mode", "goal", "template", "parameters", "quality",
        }, {"schema", "mode", "template"}, "blockout job")
        if job["template"] != "vintage_open_wheel":
            raise RecipeError("template: currently only 'vintage_open_wheel' is supported")
        recipe, metadata = vintage_open_wheel_recipe(job.get("parameters"))
        baseline = None
        change_report = {
            "mode": "blockout", "goal": goal,
            "template": job["template"], "design_assumptions": metadata,
            "note": "The goal is descriptive metadata, not natural-language instructions "
                    "executed automatically by Python.",
        }
    elif job["mode"] == "revise":
        recipe, baseline, _, change_report = _revision(job, repository_root)
        change_report["goal"] = goal
    else:
        raise RecipeError("mode: expected 'blockout' or 'revise'")
    _, proposed_manifest = generate_source(recipe)
    if proposed_manifest["polygon_count"] > quality["max_polygons"]:
        raise RecipeError("quality.max_polygons exceeded")
    if baseline is not None and quality["max_abs_polygon_delta"] is not None:
        if abs(proposed_manifest["polygon_count"] -
               baseline["polygon_count"]) > quality["max_abs_polygon_delta"]:
            raise RecipeError("quality.max_abs_polygon_delta exceeded")
    if quality["must_preserve"]:
        if baseline is None:
            raise RecipeError("quality.must_preserve is only valid for revise jobs")
        before = _recipe_index(change_report["baseline_recipe"])
        after = _recipe_index(recipe)
        for name in quality["must_preserve"]:
            if name not in before or name not in after:
                raise RecipeError(f"quality.must_preserve: component missing: {name}")
            if _canonical_hash(before[name]) != _canonical_hash(after[name]):
                raise RecipeError(f"quality.must_preserve: component changed: {name}")
    change_report.pop("baseline_recipe", None)
    change_report["quality_gates"] = {
        "passed": True, "limits": quality,
        "baseline_polygon_count": (
            baseline["polygon_count"] if baseline is not None else None),
        "candidate_polygon_count": proposed_manifest["polygon_count"],
        "candidate_component_count": proposed_manifest["component_count"],
        "checks": [
            "Stage 2 recipe validation", "N3 compiler + binary parser round-trip",
            "Required component preservation", "Explicit polygon-count budget",
        ],
    }
    return recipe, change_report


def run_job(job_file, output, *, repository_root=None, with_views=True):
    """Generate source, compiled 3DO and Stage 1 diagnostics transactionally.

    All build stages happen in a temporary sibling directory. On success
    only, publish it at a new destination. No original N3, 3DO, recipe or
    reference file is rewritten. Output paths must not already exist.
    """
    job_file, output = Path(job_file), Path(output)
    if not job_file.is_file():
        raise FileNotFoundError(job_file)
    if output.exists():
        raise FileExistsError(f"Output directory already exists: {output}")
    if repository_root is None:
        repository_root = Path(__file__).resolve().parents[1]
    job = _load_json(job_file)
    recipe, report = plan_recipe(job, repository_root=repository_root)
    output.parent.mkdir(parents=True, exist_ok=True)
    working = Path(tempfile.mkdtemp(prefix=".icr2-model-job-", dir=output.parent))
    try:
        (working / "job.json").write_text(
            json.dumps(job, indent=2, sort_keys=True) + "\n",
            encoding="utf-8")
        recipe_path = working / "generated_recipe.json"
        recipe_path.write_text(
            json.dumps(recipe, indent=2, sort_keys=True) + "\n",
            encoding="utf-8")
        stage2 = generate_package(
            recipe_path, working / "generated", with_views=with_views)
        if not stage2["validation"]["compiled"]:
            raise RecipeError("Stage 2 returned an unvalidated model")
        if stage2["manifest"]["polygon_count"] != report["quality_gates"][
                "candidate_polygon_count"]:
            raise RecipeError("Candidate manifest differs from validated job")
        if job["mode"] == "revise":
            base_path = _safe_base(job["base_recipe"], repository_root)
            generate_package(
                base_path, working / "baseline", with_views=with_views)
        report["output_layout"] = {
            "editable_source": "generated/model.3D",
            "compiled_model": "generated/model.3do",
            "candidate_analysis": "generated/analysis/",
            "baseline_analysis": "baseline/analysis/" if job["mode"] == "revise" else None,
        }
        (working / "change_report.json").write_text(
            json.dumps(report, indent=2, sort_keys=True) + "\n",
            encoding="utf-8")
        if output.exists():
            raise FileExistsError(f"Output directory created concurrently: {output}")
        working.rename(output)
    finally:
        if working.exists():
            shutil.rmtree(working)
    return {
        "output_directory": str(output),
        "mode": job["mode"],
        "polygon_count": stage2["validation"]["polygons"],
        "component_count": stage2["manifest"]["component_count"],
        "quality_gates_passed": True,
        "historically_verified": False if job["mode"] == "blockout" else None,
    }
