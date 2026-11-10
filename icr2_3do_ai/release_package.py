"""Review-only, deterministic release-candidate ZIP for ICR2 AI models.

This is a packaging and provenance tool, not a binary compiler, public
GitHub Release publisher, game installer or redistribution authorization.
It consumes already validated Stage 1-3 outputs and never edits inputs.
"""
from __future__ import annotations

import argparse
from hashlib import sha256
import json
from pathlib import Path
import re
import tempfile
from zipfile import ZIP_DEFLATED, ZipFile, ZipInfo

from .stage2 import validate_path


MODEL_FILES = (
    "WASP.3D", "FWHEEL.3D", "RWHEEL.3D",
    "WASP.3do", "FWHEEL.3do", "RWHEEL.3do", "HELMET.3do",
    "assembly_manifest.json",
)
WASP_RECIPES = (
    "marmon_wasp_1911_lowpoly.json",
    "marmon_wasp_front_wheel.json",
    "marmon_wasp_rear_wheel.json",
)
ZIP_TIMESTAMP = (1980, 1, 1, 0, 0, 0)
MAX_FILE_BYTES = 100 * 1024 * 1024
MAX_PACKAGE_BYTES = 250 * 1024 * 1024


def _blob(path: Path) -> bytes:
    if not path.is_file() or path.is_symlink():
        raise ValueError(f"Required regular file absent or symlink: {path}")
    if path.stat().st_size > MAX_FILE_BYTES:
        raise ValueError(f"Release input exceeds {MAX_FILE_BYTES} bytes: {path}")
    return path.read_bytes()


def _document(path: Path) -> dict:
    value = json.loads(_blob(path))
    if not isinstance(value, dict):
        raise ValueError(f"Expected JSON object in {path}")
    return value


def _check_sources(model_dir: Path) -> None:
    # Do not rely merely on the presence of files or a previous CI claim.
    for name in MODEL_FILES:
        _blob(model_dir / name)
    for name in ("WASP", "FWHEEL", "RWHEEL"):
        source = validate_path(model_dir / f"{name}.3D")
        binary = validate_path(model_dir / f"{name}.3do")
        if (source["binary_sha256"] != binary["binary_sha256"] or
                source["parser_warnings"] or binary["parser_warnings"]):
            raise ValueError(f"{name}: N3 recompile and binary diverge or warn")
    helmet = validate_path(model_dir / "HELMET.3do")
    if helmet["parser_warnings"]:
        raise ValueError("HELMET: binary parser warning")
    assembly = _document(model_dir / "assembly_manifest.json")
    hashes = assembly.get("sha256")
    if not isinstance(hashes, dict):
        raise ValueError("Wasp assembly manifest missing input binary hashes")
    for name in ("WASP.3do", "FWHEEL.3do", "RWHEEL.3do", "HELMET.3do"):
        expected = hashes.get(name)
        if expected != sha256(_blob(model_dir / name)).hexdigest():
            raise ValueError(f"{name}: assembly manifest digest mismatch")


def _check_visual(preview_dir: Path, comparison_dir: Path) -> tuple[list[str], dict]:
    preview = _document(preview_dir / "preview.json")
    comparison = _document(comparison_dir / "comparison.json")
    if preview.get("schema") != "icr2.visual-preview.v1":
        raise ValueError("Unrecognized preview report schema")
    if comparison.get("schema") != "icr2.visual-regression.v1":
        raise ValueError("Unrecognized comparison report schema")
    if preview.get("warnings") or comparison.get("warnings"):
        raise ValueError("Missing assets or visual warnings: review before release")
    if not comparison.get("threshold_passed"):
        raise ValueError("Visual regression threshold was not met")
    if comparison.get("maximum_changed_fraction") != 0:
        raise ValueError("Reference baseline comparison is not pixel-identical")
    cameras = preview.get("cameras")
    if not isinstance(cameras, list) or not cameras or len(cameras) != len(set(cameras)):
        raise ValueError("Invalid preview camera collection")
    if cameras != comparison.get("cameras"):
        raise ValueError("Preview and regression camera sets differ")
    views = preview.get("views", {})
    stats = preview.get("statistics", {})
    compare_views = comparison.get("views", {})
    if not isinstance(views, dict) or not isinstance(stats, dict) or not isinstance(compare_views, dict):
        raise ValueError("Missing per-camera preview and comparison metadata")
    for name in cameras:
        if name not in ("front","rear","left","right","top",
                        "front-left","front-right","rear-left","rear-right"):
            raise ValueError(f"Invalid preview camera {name!r}")
        info = views.get(name)
        if not isinstance(info, dict) or info.get("file") != f"{name}.png":
            raise ValueError(f"{name}: incomplete preview file entry")
        filename = info["file"]
        image = _blob(preview_dir / filename)
        if sha256(image).hexdigest() != info.get("sha256"):
            raise ValueError(f"{name}: preview image digest mismatch")
        stat = stats.get(name)
        if not isinstance(stat, dict) or stat.get("rendered_sprites", 0) < 1:
            raise ValueError(f"{name}: expected a rendered driver helmet PMP sprite")
        diff = compare_views.get(name)
        if not isinstance(diff, dict) or diff.get("changed_pixels") != 0:
            raise ValueError(f"{name}: baseline difference was not zero")
        for suffix in ("before","after","diff","comparison"):
            _blob(comparison_dir / f"{name}-{suffix}.png")
    return cameras, comparison


def _insert(files: dict[str, bytes], key: str, path: Path):
    if key in files or ".." in Path(key).parts or key.startswith("/"):
        raise ValueError(f"Unsafe or duplicate bundle member: {key}")
    files[key] = _blob(path)


def candidate_bytes(model_dir, preview_dir, comparison_dir, recipes_dir, *,
                    source_commit: str) -> tuple[bytes, dict]:
    """Build deterministic ZIP bytes without modifying any input directory."""
    if not isinstance(source_commit, str) or not re.fullmatch(r"[0-9a-f]{40}", source_commit):
        raise ValueError("source_commit must be a full lowercase 40-hex git SHA")
    model_dir = Path(model_dir)
    preview_dir = Path(preview_dir)
    comparison_dir = Path(comparison_dir)
    recipes_dir = Path(recipes_dir)
    _check_sources(model_dir)
    cameras, comparison = _check_visual(preview_dir, comparison_dir)
    members: dict[str, bytes] = {}
    for filename in MODEL_FILES:
        _insert(members, f"models/{filename}", model_dir / filename)
    for filename in WASP_RECIPES:
        _insert(members, f"recipes/{filename}", recipes_dir / filename)
    _insert(members, "visuals/preview.json", preview_dir / "preview.json")
    _insert(members, "visuals/comparison.json", comparison_dir / "comparison.json")
    for camera in cameras:
        _insert(members, f"visuals/preview/{camera}.png",
                preview_dir / f"{camera}.png")
        for suffix in ("before","after","diff","comparison"):
            filename = f"{camera}-{suffix}.png"
            _insert(members, f"visuals/comparison/{filename}",
                    comparison_dir / filename)
    if sum(map(len, members.values())) > MAX_PACKAGE_BYTES:
        raise ValueError("Combined inputs exceed release-candidate size budget")
    details = [
        {"path": name, "bytes": len(value),
         "sha256": sha256(value).hexdigest()}
        for name, value in sorted(members.items())
    ]
    manifest = {
        "schema": "icr2.n3.release-candidate.v1",
        "status": "review-only-unpublished",
        "source_commit": source_commit,
        "model": "Marmon Wasp 1911 V29",
        "cameras": cameras,
        "comparison_maximum_changed_fraction": comparison["maximum_changed_fraction"],
        "binary_sha256": {
            name: sha256(members[f"models/{name}"]).hexdigest()
            for name in ("WASP.3do", "FWHEEL.3do", "RWHEEL.3do", "HELMET.3do")
        },
        "files": details,
        "caveats": [
            "Only a review candidate: not an automatic GitHub Release or carset installer.",
            "External PMP sprite files are NOT included; supply legitimate local assets.",
            "OpenGL/game-engine renderer and real-time sprite behavior are not validated.",
            "Source game binaries and texture licenses must be respected before distribution.",
        ],
    }
    members["release_manifest.json"] = (
        json.dumps(manifest, sort_keys=True, indent=2) + "\n"
    ).encode("utf-8")
    members["SHA256SUMS"] = (
        "".join(f"{sha256(value).hexdigest()}  {name}\n"
                for name, value in sorted(members.items()))
    ).encode("ascii")
    # ZIP writing to bytes via memory file avoids temporary output partials.
    from io import BytesIO
    buffer = BytesIO()
    with ZipFile(buffer, "w", compression=ZIP_DEFLATED, compresslevel=6) as archive:
        for name, value in sorted(members.items()):
            info = ZipInfo(name, ZIP_TIMESTAMP)
            info.compress_type = ZIP_DEFLATED
            info.external_attr = 0o100644 << 16
            archive.writestr(info, value, compress_type=ZIP_DEFLATED,
                             compresslevel=6)
    return buffer.getvalue(), manifest


def create_candidate(model_dir, preview_dir, comparison_dir, recipes_dir,
                     output, *, source_commit: str):
    output = Path(output)
    if output.exists():
        raise FileExistsError(f"Output directory already exists: {output}")
    for src in (model_dir, preview_dir, comparison_dir, recipes_dir):
        src = Path(src).resolve()
        if src == output.resolve() or output.resolve() in src.parents:
            raise ValueError("Output cannot replace a source directory")
    data, manifest = candidate_bytes(
        model_dir, preview_dir, comparison_dir, recipes_dir,
        source_commit=source_commit)
    output.parent.mkdir(parents=True, exist_ok=True)
    import shutil
    temporary = Path(tempfile.mkdtemp(prefix=".3do-release-", dir=output.parent))
    try:
        (temporary / "release-candidate.zip").write_bytes(data)
        (temporary / "release_manifest.json").write_text(
            json.dumps(manifest, indent=2, sort_keys=True)+"\n",
            encoding="utf-8")
        if output.exists():
            raise FileExistsError(f"Output created concurrently: {output}")
        temporary.rename(output)
    finally:
        if temporary.exists():
            shutil.rmtree(temporary)
    return manifest


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--models", type=Path, required=True)
    parser.add_argument("--previews", type=Path, required=True)
    parser.add_argument("--comparison", type=Path, required=True)
    parser.add_argument("--recipes", type=Path, required=True)
    parser.add_argument("--source-commit", required=True)
    parser.add_argument("-o", "--output", type=Path, required=True)
    args = parser.parse_args(argv)
    result = create_candidate(
        args.models, args.previews, args.comparison, args.recipes,
        args.output, source_commit=args.source_commit)
    print(json.dumps({
        "output_directory": str(args.output),
        "model": result["model"],
        "files": len(result["files"]),
        "status": result["status"],
    }, indent=2))


if __name__ == "__main__":
    main()
