"""Phase 2 structural assembly tests; compile against the existing N3 backend."""
from __future__ import annotations

import copy
import json
from pathlib import Path
import tempfile
import unittest

from icr2_3do_ai.parametric import RecipeError, generate_source
from icr2_3do_ai.stage2 import generate_package, validate_source

DEMO = Path(__file__).resolve().parents[1] / "recipes" / "phase2_assembly_demo.json"


def demo():
    return json.loads(DEMO.read_text(encoding="utf-8"))


class AssemblyTests(unittest.TestCase):
    def test_compiled_reference_scene_has_structured_n3_nodes(self):
        source, manifest = generate_source(demo())
        model, result = validate_source(source)
        self.assertTrue(result["compiled"])
        self.assertEqual(result["polygons"], 4)
        self.assertEqual(manifest["polygon_count"], 4)
        self.assertEqual(manifest["assembly"]["coordinate_system"], "source")
        self.assertEqual(
            [x["model"] for x in manifest["assembly"]["externals"]],
            ["HELMET", "FWHEEL", "FWHEEL"])
        self.assertIn("radiator_front_p0000: FACE (", source)
        self.assertIn("vehicle_sort: BSPA (", source)
        self.assertIn("nose_sort: BSPN (", source)
        self.assertIn("pilot: LIST {torso_geo, helmet};", source)
        self.assertIn('EXTERN "HELMET";', source)
        self.assertIn('EXTERN "FWHEEL";', source)
        self.assertEqual(manifest["surface_checks"]["counts"], {})
        self.assertFalse(result["parser_warnings"])
        self.assertIn("root", model.n3_label_offsets)

    def test_driver_helmet_moves_without_moving_seatback(self):
        recipe = demo()
        source, manifest = generate_source(recipe)
        self.assertIn(
            'helmet: DYNAMIC 36300, 0, 1200, 1800, 0, 0, 1, EXTERN "HELMET";',
            source)
        self.assertIn("torso_v0000: [<", source)
        self.assertIn("seatback_v0000: [<35400,", source)
        self.assertEqual(
            manifest["assembly"]["externals"][0]["at_game_raw"],
            [36300, 0, 1200])
        self.assertEqual(manifest["assembly"]["groups"][0]["members"],
                         ["torso", "helmet"])

    def test_transform_is_deterministic(self):
        a, m1 = generate_source(demo())
        b, m2 = generate_source(demo())
        self.assertEqual(a, b)
        self.assertEqual(m1, m2)

    def test_compile_as_new_package_without_rewriting_external_assets(self):
        with tempfile.TemporaryDirectory() as temp:
            recipe_path = Path(temp) / "recipe.json"
            recipe_path.write_text(json.dumps(demo()), encoding="utf-8")
            out = Path(temp) / "built"
            package = generate_package(recipe_path, out, with_analysis=False)
            self.assertTrue((out / "model.3D").exists())
            self.assertTrue((out / "model.3do").exists())
            self.assertEqual(package["validation"]["polygons"], 4)
            self.assertFalse((out / "HELMET.3do").exists())
            self.assertFalse((out / "FWHEEL.3do").exists())

    def test_face_gate_rejects_backwards_and_coplanar_camera(self):
        for camera in ([0, 0, 0], [-2, 0, 0]):
            recipe = demo()
            recipe["assembly"]["gates"][0]["visible_from"] = camera
            with self.subTest(camera=camera), self.assertRaises(RecipeError):
                generate_source(recipe)

    def test_face_gate_rejects_duplicate_polygon(self):
        recipe = demo()
        recipe["assembly"]["gates"][0]["faces"] = [0, 0]
        with self.assertRaises(RecipeError):
            generate_source(recipe)

    def test_reject_unknown_or_duplicate_painter_references(self):
        recipe = demo()
        recipe["assembly"]["nodes"][1]["children"].append("missing")
        with self.assertRaises(RecipeError):
            generate_source(recipe)
        recipe = demo()
        recipe["assembly"]["nodes"][1]["children"].append("torso")
        with self.assertRaises(RecipeError):
            generate_source(recipe)
        recipe = demo()
        recipe["assembly"]["nodes"][0]["children"][0] = "vehicle_sort"
        with self.assertRaises(RecipeError):
            generate_source(recipe)

    def test_reject_unsupported_or_ambiguous_transforms(self):
        for mutation in (
            {"rotate_z_quarters": 1.5},
            {"scale": -1},
            {"scale_x": 2},
            {"rotate": {"axis": "x", "degrees": 30}},
        ):
            recipe = demo()
            recipe["assembly"]["groups"][0]["transform"] = mutation
            with self.subTest(mutation=mutation), self.assertRaises(RecipeError):
                generate_source(recipe)

    def test_noninteger_uniform_scale_rejected(self):
        recipe = {
            "schema": "icr2.n3.recipe.v1",
            "operations": [
                {"type": "polygon", "name": "sheet", "axis": "z",
                 "at": 0, "outline": [[1, 0], [2, 0], [2, 2], [1, 2]]}
            ],
            "assembly": {
                "coordinate_system": "game",
                "anchors": [{"name": "origin", "at": [0, 0, 0]}],
                "groups": [{"name": "scaled", "members": ["sheet"],
                            "anchor": "origin",
                            "transform": {"scale": "0.5"}}],
            },
        }
        with self.assertRaises(RecipeError):
            generate_source(recipe)

    def test_reject_unknown_anchor_and_bad_external_name(self):
        recipe = demo()
        recipe["assembly"]["externals"][0]["at"] = {"anchor": "not_known"}
        with self.assertRaises(RecipeError):
            generate_source(recipe)
        recipe = demo()
        recipe["assembly"]["externals"][0]["model"] = "HELMET.3do"
        with self.assertRaises(RecipeError):
            generate_source(recipe)

    def test_game_frame_does_not_allow_second_coordinate_conversion(self):
        recipe = demo()
        recipe["assembly"]["coordinate_system"] = "game"
        with self.assertRaises(RecipeError):
            generate_source(recipe)

    def test_legacy_recipe_uses_original_flat_list_path(self):
        legacy = {
            "schema": "icr2.n3.recipe.v1",
            "operations": [
                {"type": "polygon", "name": "panel", "axis": "z", "at": 0,
                 "outline": [[0, 0], [2, 0], [2, 2], [0, 2]]}
            ],
        }
        source, manifest = generate_source(legacy)
        self.assertIn("root: LIST {panel_geo};", source)
        self.assertNotIn("assembly", manifest)
        self.assertNotIn("FACE (", source)
        validate_source(source)


if __name__ == "__main__":
    unittest.main()
