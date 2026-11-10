"""Phase 3 headless screenshot-style visual regression tests (no OpenGL)."""
from __future__ import annotations

from pathlib import Path
import json
import tempfile
import unittest

import numpy as np
from PIL import Image

from icr2_3do_ai.parametric import generate_source
from icr2_3do_ai.stage2 import validate_source
from icr2_3do_ai.visual_regression import (
    CAMERAS, compare_previews, render_previews,
)

ROOT = Path(__file__).resolve().parents[2]
FIXTURES = ROOT / "icr2_3do_cad" / "fixtures"
DEMO = ROOT / "icr2_3do_ai" / "recipes" / "phase2_assembly_demo.json"

def color_sheet(color):
    return {"schema": "icr2.n3.recipe.v1", "operations": [
        {"type": "polygon", "name": "sample", "axis": "z", "at": 0,
         "outline": [[-2,-1], [2,-1], [2,1], [-2,1]],
         "color": color}]}



class PreviewRegressionTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.folder = Path(temporary.name)

    def test_compiled_face_gates_cull_from_camera_direction(self):
        recipe = json.loads(DEMO.read_text())
        source, _ = generate_source(recipe)
        model, _ = validate_source(source)
        before = self.folder / "assembly.3do"
        before.write_bytes(model.raw)
        preview = render_previews(before, self.folder/"camera",
                                  cameras=["front","rear","left"],
                                  width=320,height=220,
                                  textures=False)
        self.assertEqual(set(preview["views"]), {"front","rear","left"})
        for name in preview["views"]:
            self.assertEqual(Image.open(self.folder/"camera"/f"{name}.png").size,
                             (320,220))
            self.assertTrue(preview["views"][name]["sha256"])
        self.assertGreater(preview["statistics"]["front"]["tested_planes"],0)

    def test_standalone_helmet_decodes_and_renders_directional_pmp(self):
        rendered = render_previews(
            FIXTURES/"helmet.3do", self.folder/"helm",
            cameras=("front","rear","left","right"),
            width=320,height=320, objects_folder=FIXTURES,
            strict_assets=True)
        self.assertGreater(
            sum(v["rendered_sprites"] for v in rendered["statistics"].values()),0)
        for camera in ("front","rear","left","right"):
            pixels = np.asarray(Image.open(self.folder/"helm"/f"{camera}.png"))
            colored = np.any(pixels != np.array([246,248,251]),axis=2)
            self.assertGreater(int(colored.sum()),0)
        self.assertFalse(rendered["warnings"])

    def test_identical_model_has_zero_pixel_differences(self):
        file = FIXTURES/"indycar.3do"
        report = compare_previews(
            file,file,self.folder/"identical",
            cameras=("front","rear-left"),width=320,height=220,
            objects_folder=FIXTURES,texture_folder=FIXTURES)
        self.assertEqual(report["maximum_changed_fraction"],0)
        self.assertTrue(report["threshold_passed"])
        for name in report["cameras"]:
            self.assertEqual(report["views"][name]["changed_pixels"],0)
            self.assertTrue((self.folder/"identical"/f"{name}-diff.png").is_file())
            self.assertEqual(Image.open(
                self.folder/"identical"/f"{name}-comparison.png").size,
                (960,220))

    def test_changed_palette_color_triggers_measurable_visual_diff(self):
        raw = color_sheet(33)
        before_source,_ = generate_source(raw)
        model,_ = validate_source(before_source)
        old = self.folder/"before.3do"
        old.write_bytes(model.raw)
        raw["operations"][0]["color"] = 158
        after_source,_ = generate_source(raw)
        model,_ = validate_source(after_source)
        changed = self.folder/"after.3do"
        changed.write_bytes(model.raw)
        report = compare_previews(
            old,changed,self.folder/"different",
            cameras=["top"],width=350,height=260,textures=False)
        self.assertGreater(report["maximum_changed_fraction"],0)
        self.assertGreater(report["views"]["top"]["changed_pixels"],0)

    def test_diff_threshold_failure_still_publishes_report(self):
        raw=color_sheet(33)
        src,_=generate_source(raw)
        model,_=validate_source(src)
        a=self.folder/"a.3do";a.write_bytes(model.raw)
        raw["operations"][0]["color"]=158
        src,_=generate_source(raw)
        model,_=validate_source(src)
        b=self.folder/"b.3do";b.write_bytes(model.raw)
        report=compare_previews(
            a,b,self.folder/"threshold",cameras=["top"],width=200,
            height=160,max_diff_ratio=0,textures=False)
        self.assertFalse(report["threshold_passed"])
        self.assertTrue((self.folder/"threshold"/"comparison.json").exists())

    def test_outputs_not_overwritten_and_bad_cameras_rejected(self):
        p = FIXTURES/"helmet.3do"
        rendered = render_previews(
            p, self.folder/"once", cameras=["front"],width=180,height=180,
            objects_folder=FIXTURES)
        self.assertTrue(rendered["views"]["front"])
        with self.assertRaises(FileExistsError):
            render_previews(p, self.folder/"once",cameras=["front"],
                            objects_folder=FIXTURES)
        with self.assertRaises(ValueError):
            render_previews(p,self.folder/"bad",cameras=["diagonal"])
        self.assertFalse((self.folder/"bad").exists())
        with self.assertRaises(ValueError):
            render_previews(p,self.folder/"bad",cameras=["front"],
                            width=100000)

    def test_camera_matrix_has_supported_angles(self):
        for name in ("front","rear","left","right","top",
                     "front-left","front-right","rear-left","rear-right"):
            self.assertIn(name,CAMERAS)
        result=render_previews(
            FIXTURES/"fwheel.3do",self.folder/"wheel",
            cameras=("top","right"),width=160,height=160,
            objects_folder=FIXTURES)
        self.assertEqual(len(result["views"]),2)


if __name__ == "__main__":
    unittest.main()
