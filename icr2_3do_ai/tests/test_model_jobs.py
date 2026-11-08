"""Stage 3 modeling jobs: structured, deterministic, headless regression tests."""
from __future__ import annotations

from copy import deepcopy
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

from icr2_3do_ai.blockouts import vintage_open_wheel_recipe
from icr2_3do_ai.model_jobs import plan_recipe, run_job
from icr2_3do_ai.parametric import RecipeError, generate_source
from icr2_3do_ai.stage2 import validate_path, validate_source

ROOT = Path(__file__).resolve().parents[2]
JOBS = ROOT / "icr2_3do_ai" / "jobs"
RECIPES = ROOT / "icr2_3do_ai" / "recipes"


class Stage3JobsTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.temp = Path(temp.name)

    def _job(self, spec):
        path = self.temp / "job.json"
        path.write_text(json.dumps(spec, indent=2), encoding="utf-8")
        return path

    def _blockout(self):
        return {
            "schema": "icr2.n3.job.v1", "mode": "blockout",
            "template": "vintage_open_wheel",
            "parameters": {"spokes_per_wheel": 4},
        }

    def _revision(self):
        base = json.loads((RECIPES / "example_indycar_nose.json").read_text())
        op = deepcopy(base["operations"][0])
        op["sections"][-1]["at"] = 7.0
        return {
            "schema": "icr2.n3.job.v1", "mode": "revise",
            "base_recipe": "icr2_3do_ai/recipes/example_indycar_nose.json",
            "edits": [{"action": "replace", "target": "nose", "operation": op}],
            "quality": {"max_polygons": 500,
                        "max_abs_polygon_delta": 0,
                        "must_preserve": ["left_pod", "right_pod"]},
        }

    def test_vintage_car_blockout_compiles_with_expected_components(self):
        recipe, historical = vintage_open_wheel_recipe({"spokes_per_wheel": 4})
        self.assertFalse(historical["historical_verified"])
        self.assertEqual(recipe["coordinate_scale"], 6000)
        names = [op["name"] for op in recipe["operations"]]
        self.assertEqual(len(names), len(set(names)))
        self.assertIn("streamlined_body", names)
        self.assertIn("cockpit_placeholder", names)
        self.assertIn("mirror_stalk", names)
        self.assertIn("mirror_head", names)
        for name in ("tire_fl", "tire_fr", "tire_rl", "tire_rr",
                     "hub_fl", "hub_fr", "hub_rl", "hub_rr"):
            self.assertIn(name, names)
        self.assertEqual(sum(x.startswith("spoke_") for x in names), 16)
        source, manifest = generate_source(recipe)
        model, check = validate_source(source)
        self.assertTrue(check["compiled"])
        self.assertEqual(len(model.polygons), manifest["polygon_count"])
        self.assertGreater(len(model.polygons), 300)
        self.assertLess(len(model.polygons), 1500)
        self.assertFalse(model.mip_names)
        self.assertIn("streamlined_body_geo", source)
        self.assertIn("mirror_head_geo", source)
        self.assertEqual(model.n3_coordinate_scale, 1)

    def test_symmetric_wheels_and_body_bounds(self):
        recipe, historical = vintage_open_wheel_recipe({"spokes_per_wheel": 0})
        source, _ = generate_source(recipe)
        model, _ = validate_source(source)
        labels = model.n3_label_offsets
        fl = model.vertices[labels["tire_fl_v0000"]].xyz
        fr = model.vertices[labels["tire_fr_v0000"]].xyz
        rl = model.vertices[labels["tire_rl_v0000"]].xyz
        # Ring 0 is the minimum Y edge on both wheels. Symmetric
        # wheels' *centers*, not same-index tire sidewalls, must mirror.
        fl_other = model.vertices[labels["tire_fl_v0012"]].xyz
        fr_other = model.vertices[labels["tire_fr_v0012"]].xyz
        self.assertEqual(fl[0], fr[0])
        self.assertEqual(fl[1] + fl_other[1], -(fr[1] + fr_other[1]))
        self.assertEqual(fl[2], fr[2])
        self.assertGreater(fl[0], rl[0])
        self.assertIn("% COMPONENT: cockpit_placeholder", source)

    def test_checked_in_job_examples_are_compilable(self):
        for job in sorted(JOBS.glob("*.json")):
            with self.subTest(job=job.name):
                spec = json.loads(job.read_text())
                recipe, report = plan_recipe(spec, repository_root=ROOT)
                source, manifest = generate_source(recipe)
                _, checked = validate_source(source)
                self.assertEqual(checked["polygons"], manifest["polygon_count"])
                self.assertTrue(report["quality_gates"]["passed"])

    def test_safe_revision_tracks_only_targeted_component(self):
        recipe, report = plan_recipe(self._revision(), repository_root=ROOT)
        self.assertEqual(report["modified"], ["nose"])
        self.assertEqual(report["added"], [])
        self.assertEqual(report["removed"], [])
        self.assertEqual(report["unchanged"], ["left_pod", "right_pod"])
        self.assertEqual(report["quality_gates"]["baseline_polygon_count"],
                         report["quality_gates"]["candidate_polygon_count"])
        self.assertEqual(recipe["operations"][0]["sections"][-1]["at"], 7.0)

    def test_revision_rejects_unrelated_component_changes(self):
        spec = self._revision()
        spec["quality"]["must_preserve"].append("nose")
        with self.assertRaisesRegex(RecipeError, "must_preserve"):
            plan_recipe(spec, repository_root=ROOT)

    def test_revision_rejects_invalid_geometry_and_dangling_mirror(self):
        bad = self._revision()
        bad["edits"][0]["operation"]["sections"][-1]["width"] = -10
        with self.assertRaises(RecipeError):
            plan_recipe(bad, repository_root=ROOT)

        bad = self._revision()
        bad["edits"] = [{"action": "remove", "target": "left_pod"}]
        # right_pod mirror still depends on left_pod.
        with self.assertRaises(RecipeError):
            plan_recipe(bad, repository_root=ROOT)

    def test_revision_rejects_stale_base_and_path_traversal(self):
        bad = self._revision()
        bad["base_recipe_sha256"] = "0" * 64
        with self.assertRaisesRegex(RecipeError, "SHA256 mismatch"):
            plan_recipe(bad, repository_root=ROOT)

        for path in ("/tmp/secret.json", "../secret.json",
                     "icr2_3do_ai/../../secret.json"):
            bad = self._revision()
            bad["base_recipe"] = path
            with self.subTest(path=path), self.assertRaises(RecipeError):
                plan_recipe(bad, repository_root=ROOT)

    def test_quality_polygon_budget_and_edit_conflicts(self):
        bad = self._revision()
        bad["quality"]["max_polygons"] = 3
        with self.assertRaisesRegex(RecipeError, "max_polygons"):
            plan_recipe(bad, repository_root=ROOT)

        bad = self._revision()
        bad["edits"].append(deepcopy(bad["edits"][0]))
        with self.assertRaisesRegex(RecipeError, "already edited"):
            plan_recipe(bad, repository_root=ROOT)

    def test_failed_job_never_creates_requested_output(self):
        spec = self._blockout()
        spec["parameters"]["overall_length_ft"] = 1000
        job = self._job(spec)
        target = self.temp / "output"
        with self.assertRaises(RecipeError):
            run_job(job, target)
        self.assertFalse(target.exists())
        self.assertEqual(json.loads(job.read_text()), spec)

    def test_blockout_job_writes_editable_source_and_diagnostics(self):
        spec = self._blockout()
        job = self._job(spec)
        original = job.read_bytes()
        output = self.temp / "completed"
        result = run_job(job, output, with_views=True)
        self.assertTrue(result["quality_gates_passed"])
        self.assertFalse(result["historically_verified"])
        for file in (
            "job.json", "change_report.json", "generated_recipe.json",
            "generated/model.3D", "generated/model.3do",
            "generated/validation.json", "generated/manifest.json",
            "generated/analysis/summary.json", "generated/analysis/geometry.json",
            "generated/analysis/scene_graph.json",
            "generated/analysis/views/side.png",
        ):
            self.assertTrue((output/file).is_file(), file)
        change = json.loads((output/"change_report.json").read_text())
        self.assertIn("historical_verified", change["design_assumptions"])
        self.assertFalse(change["design_assumptions"]["historical_verified"])
        self.assertEqual(validate_path(output/"generated/model.3do")["polygons"],
                         result["polygon_count"])
        self.assertEqual(job.read_bytes(), original)
        with self.assertRaises(FileExistsError):
            run_job(job, output)

    def test_revision_job_publishes_before_and_after(self):
        job = self._job(self._revision())
        out = self.temp / "revision"
        data = run_job(job, out, with_views=False)
        self.assertEqual(data["mode"], "revise")
        self.assertIsNone(data["historically_verified"])
        self.assertTrue((out/"baseline/model.3D").is_file())
        self.assertTrue((out/"baseline/model.3do").is_file())
        self.assertTrue((out/"generated/model.3D").is_file())
        self.assertTrue((out/"generated/model.3do").is_file())
        report = json.loads((out/"change_report.json").read_text())
        self.assertEqual(report["modified"], ["nose"])
        self.assertEqual(report["unchanged"], ["left_pod", "right_pod"])
        self.assertEqual(validate_path(out/"baseline/model.3do")["polygons"],
                         validate_path(out/"generated/model.3do")["polygons"])

    def test_cli_stage3_job_works_without_gui(self):
        job = self._job(self._blockout())
        target = self.temp / "cli_out"
        cmd = [sys.executable, "-m", "icr2_3do_ai", "build-job",
               str(job), "-o", str(target), "--no-views"]
        run = subprocess.run(
            cmd, cwd=ROOT, capture_output=True, text=True, timeout=90)
        self.assertEqual(run.returncode, 0, run.stderr)
        obj = json.loads(run.stdout)
        self.assertTrue(obj["quality_gates_passed"])
        self.assertTrue((target/"generated/model.3D").is_file())


if __name__ == "__main__":
    unittest.main()
