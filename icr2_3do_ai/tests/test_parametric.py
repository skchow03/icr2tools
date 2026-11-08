"""Headless Stage 2 source-generation tests; no Qt/OpenGL or LLM."""
from __future__ import annotations

import copy
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

from icr2_3do_ai.parametric import RecipeError, generate_source
from icr2_3do_ai.stage2 import generate_package, validate_path, validate_source
from icr2_3do_ai.inspector import analyze_model

ROOT = Path(__file__).resolve().parents[2]


def basic_recipe():
    return {
        "schema": "icr2.n3.recipe.v1",
        "coordinate_scale": 6000,
        "operations": [
            {
                "type": "loft", "name": "nosecone", "axis": "x",
                "sections": [
                    {"at": 0, "width": 4, "height": 2, "center": [0, 1]},
                    {"at": 2, "width": 3, "height": 1.5, "center": [0, 0.9]},
                    {"at": 6, "width": 1, "height": 0.5, "center": [0, 0.75]},
                ],
                "material": "body",
                "uv": {"axes": ["x", "z"], "pixels_per_unit": [28, 50],
                       "offset": [0, 300]},
                "color": 78,
            },
            {
                "type": "extrude", "name": "leftpod", "axis": "z",
                "outline": [[1, -4], [4, -4], [4, -2], [1, -2]],
                "from": 0.25, "to": 1.25, "color": 85,
            },
            {"type": "mirror", "name": "rightpod", "source": "leftpod",
             "axis": "y"},
        ],
    }


def polygon_normal(points):
    a, b, c = points[:3]
    u = [b[i] - a[i] for i in range(3)]
    v = [c[i] - a[i] for i in range(3)]
    return (u[1]*v[2]-u[2]*v[1],
            u[2]*v[0]-u[0]*v[2],
            u[0]*v[1]-u[1]*v[0])


class ParametricN3Tests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.folder = Path(self.temp.name)

    def test_compiles_loft_extrude_and_mirror_with_named_source(self):
        source, manifest = generate_source(basic_recipe())
        model, validated = validate_source(source)
        self.assertEqual(manifest["component_count"], 3)
        self.assertEqual(manifest["vertex_count"], 28)  # 12 + 8 + 8
        self.assertEqual(manifest["polygon_count"], 38)  # 18 + 10 + 10
        self.assertEqual(validated["vertices"], 28)
        self.assertEqual(validated["polygons"], 38)
        self.assertEqual(validated["textured_polygons"], 18)
        self.assertEqual(model.mip_names, ["body"])
        self.assertEqual(len(model.polygons), len(model.polygon_materials) + 20)
        self.assertIn("% ICR2_COORD_SCALE: 1", source)
        self.assertIn("nosecone_geo: LIST {", source)
        self.assertIn('nosecone_mat: MATERIAL MIP="body", GROUP=3,', source)
        self.assertIn("root: LIST {nosecone_mat, leftpod_geo, rightpod_geo};", source)
        self.assertIn("T=<", source)
        self.assertTrue(any(v.uv and v.uv[1] > 255 for v in model.vertices.values()))
        self.assertEqual(manifest["components"][0]["bounds_raw"]["max"][0], 36000)
        self.assertFalse(model.warnings)

    def test_generated_surfaces_keep_outward_winding_at_caps(self):
        src, manifest = generate_source({
            "schema": "icr2.n3.recipe.v1",
            "operations": [{
                "type": "extrude", "name": "prism", "axis": "z",
                "outline": [[-2, -2], [2, -2], [2, 2], [-2, 2]],
                "from": -1, "to": 3, "color": 40,
            }],
        })
        model, _ = validate_source(src)
        # Compiler Model has source labels for exact caps.
        labels = model.n3_label_offsets
        first = model.polygons[labels["prism_p0000"]]
        last = model.polygons[labels["prism_p0009"]]
        def normal(poly):
            return polygon_normal(
                [model.vertices[i].xyz for i in poly.unique_refs])
        self.assertLess(normal(first)[2], 0)
        self.assertGreater(normal(last)[2], 0)
        self.assertEqual(manifest["polygon_count"], 10)

    def test_clockwise_outline_normalizes_to_same_outward_surface(self):
        one = basic_recipe()
        base = one["operations"][1]
        two = copy.deepcopy(one)
        two["operations"][1]["outline"] = list(reversed(base["outline"]))
        original, _ = generate_source(one)
        reversed_source, _ = generate_source(two)
        self.assertEqual(original, reversed_source)

    def test_mirroring_reflects_points_and_corrects_face_winding(self):
        recipe = {
            "schema": "icr2.n3.recipe.v1",
            "operations": [
                {"type": "extrude", "name": "left", "axis": "z",
                 "outline": [[0,-5], [2,-5], [2,-3], [0,-3]],
                 "from": 0, "to": 2},
                {"type": "mirror", "name": "right", "source": "left",
                 "axis": "y", "at": 0},
            ],
        }
        source, _ = generate_source(recipe)
        model, _ = validate_source(source)
        labels = model.n3_label_offsets
        for i in range(8):
            l = model.vertices[labels[f"left_v{i:04d}"]].xyz
            r = model.vertices[labels[f"right_v{i:04d}"]].xyz
            self.assertEqual(r, (l[0], -l[1], l[2]))
        for i in range(10):
            lp = model.polygons[labels[f"left_p{i:04d}"]]
            rp = model.polygons[labels[f"right_p{i:04d}"]]
            ln = polygon_normal([model.vertices[v].xyz for v in lp.unique_refs])
            rn = polygon_normal([model.vertices[v].xyz for v in rp.unique_refs])
            self.assertEqual(rn, (ln[0], -ln[1], ln[2]))

    def test_no_implicit_coordinate_scaling_on_fractional_recipe(self):
        recipe = basic_recipe()
        text, _ = generate_source(recipe)
        model, _ = validate_source(text)
        self.assertEqual(model.n3_coordinate_scale, 1)
        self.assertIn("7500", text)  # 1.25 recipe units => raw 7,500

    def test_reject_bad_or_unsafe_recipes(self):
        examples = []
        bad = basic_recipe()
        bad["coordinate_scale"] = 0
        examples.append(bad)
        bad = basic_recipe()
        bad["operations"][1]["outline"] = [[0,0],[1,1],[0,1],[1,0]]
        examples.append(bad)  # nonconvex/self-crossing
        bad = basic_recipe()
        bad["operations"][1]["from"] = 10
        examples.append(bad)  # decreasing extrusion
        bad = basic_recipe()
        bad["operations"][0]["sections"][1]["width"] = -2
        examples.append(bad)
        bad = basic_recipe()
        bad["operations"][0]["sections"][2]["outline"] = [[0,0],[1,0],[0,1]]
        bad["operations"][0]["sections"][2].pop("width")
        bad["operations"][0]["sections"][2].pop("height")
        bad["operations"][0]["sections"][2].pop("center")
        examples.append(bad)  # mismatched number of points
        bad = basic_recipe()
        bad["operations"][2]["source"] = "missing"
        examples.append(bad)
        bad = basic_recipe()
        bad["operations"][1]["name"] = "root"
        examples.append(bad)
        bad = basic_recipe()
        bad["operations"][0]["material"] = "ninecharx"
        examples.append(bad)
        bad = basic_recipe()
        bad["operations"][0]["uv"]["offset"] = [-100000,0]
        examples.append(bad)
        bad = basic_recipe()
        bad["operations"][0]["strange"] = "unknown"
        examples.append(bad)
        bad = basic_recipe()
        bad["operations"][0]["sections"][0]["width"] = 0.00001
        examples.append(bad)  # quantized face degeneracy
        for i, case in enumerate(examples):
            with self.subTest(case=i), self.assertRaises(RecipeError):
                generate_source(case)

    def test_package_produces_compiled_model_and_stage1_reports(self):
        recipe = self.folder / "nose.json"
        recipe.write_text(json.dumps(basic_recipe()), encoding="utf-8")
        original = recipe.read_bytes()
        destination = self.folder / "generated"
        result = generate_package(recipe, destination, with_views=True)
        self.assertTrue(result["validation"]["compiled"])
        self.assertEqual(result["manifest"]["polygon_count"], 38)
        for part in ("recipe.json", "model.3D", "model.3do",
                     "manifest.json", "validation.json",
                     "analysis/summary.json", "analysis/geometry.json",
                     "analysis/scene_graph.json", "analysis/materials.json",
                     "analysis/diagnostics.json", "analysis/views/side.png",
                     "analysis/views/top.png", "analysis/views/front.png"):
            self.assertTrue((destination / part).is_file(), part)
        self.assertEqual(recipe.read_bytes(), original)
        self.assertEqual((destination / "recipe.json").read_bytes(), original)
        self.assertEqual(validate_path(destination / "model.3D")["polygons"], 38)
        self.assertEqual(validate_path(destination / "model.3do")["polygons"], 38)
        inspect = analyze_model(destination / "model.3do")
        self.assertEqual(inspect["summary"]["counts"]["polygons"], 38)
        self.assertEqual(inspect["summary"]["counts"]["components"], 3)
        with self.assertRaises(FileExistsError):
            generate_package(recipe, destination)
        self.assertEqual(recipe.read_bytes(), original)

    def test_invalid_recipe_creates_no_output_folder(self):
        recipe = self.folder / "bad.json"
        invalid = basic_recipe()
        invalid["operations"][1]["from"] = "99999999999999"
        recipe.write_text(json.dumps(invalid))
        target = self.folder / "not_created"
        with self.assertRaises(RecipeError):
            generate_package(recipe, target)
        self.assertFalse(target.exists())

    def test_cli_generate_validate_and_stage1_inspect(self):
        recipe = self.folder / "from_cli.json"
        recipe.write_text(json.dumps(basic_recipe()))
        out = self.folder / "cli"
        for args in (
            ["generate", str(recipe), "-o", str(out), "--views"],
            ["validate", str(out / "model.3D")],
            ["validate", str(out / "model.3do")],
            ["inspect", str(out / "model.3do"), "-o",
             str(self.folder / "external_report")],
        ):
            process = subprocess.run(
                [sys.executable, "-m", "icr2_3do_ai", *args],
                cwd=ROOT, capture_output=True, text=True, timeout=90)
            self.assertEqual(process.returncode, 0, process.stderr)
            self.assertIsInstance(json.loads(process.stdout), dict)

    def test_reject_duplicate_names_and_unclear_uv_or_texture(self):
        recipe = basic_recipe()
        recipe["operations"][2]["name"] = "LEFTPOD"
        with self.assertRaisesRegex(RecipeError, "duplicate component"):
            generate_source(recipe)
        recipe = basic_recipe()
        recipe["operations"][0].pop("uv")
        with self.assertRaisesRegex(RecipeError, "material and uv"):
            generate_source(recipe)
        recipe = basic_recipe()
        recipe["operations"][0]["uv"]["axes"] = ["x", "x"]
        with self.assertRaises(RecipeError):
            generate_source(recipe)


if __name__ == "__main__":
    unittest.main()
