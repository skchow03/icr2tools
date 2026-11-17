"""Regression tests for UV atlas guides and non-destructive ICR2 MIP patches."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
import tempfile
import unittest

import numpy as np
from PIL import Image

from icr2_3do_ai.mip_workbench import (
    PLAN_SCHEMA, build_mip, export_template,
)
from texture_preview import load_mip


ROOT = Path(__file__).resolve().parents[2]
FIX = ROOT / "icr2_3do_cad" / "fixtures"
PALETTE = ROOT / "icr2_3do_cad" / "gamepal.pcx"
SOURCE = """3D VERSION 3.0;
a: [<0,0,0>, T=<1,1>];
b: [<1000,0,0>, T=<8,1>];
c: [<0,1000,0>, T=<1,8>];
surface: POLY [T] <42> {a,b,c};
skin: MATERIAL MIP="skin", GROUP=3, surface;
root: LIST {skin};
"""


class MipWorkbenchTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.home = Path(self.temp.name)
        self.model = self.home / "sample.3D"
        self.model.write_text(SOURCE, encoding="utf-8")
        self.base = FIX / "ind96.mip"
        self.project = self.home / "project"
        export_template(
            model=self.model, mip=self.base, palette=PALETTE,
            output=self.project, material="skin")
        self.plan = self.home / "plan.json"
        self.art = self.home / "art.png"
        Image.new("RGBA", (30, 30), (255, 0, 255, 255)).save(self.art)

    def write_plan(self, layers):
        self.plan.write_text(json.dumps({
            "schema": PLAN_SCHEMA, "layers": layers,
        }), encoding="utf-8")

    def test_uv_guide_is_pixel_exact_and_source_files_are_read_only(self):
        meta = json.loads((self.project / "manifest.json").read_text())
        self.assertEqual(meta["polygon_count"], 1)
        self.assertEqual(meta["selection"], "explicit material skin")
        self.assertEqual(meta["polygons"][0]["uvs"],
                         [[1.0, 1.0], [8.0, 1.0], [1.0, 8.0]])
        size = load_mip(self.base)[0].size
        self.assertEqual(Image.open(self.project / "uv_guide.png").size, size)
        self.assertEqual(Image.open(self.project / "base.png").size, size)
        self.assertEqual(Image.open(self.project / "uv_preview_4x.png").size,
                         (size[0] * 4, size[1] * 4))
        self.assertEqual(meta["base_mip"]["sha256"],
                         hashlib.sha256(self.base.read_bytes()).hexdigest())
        with self.assertRaises(FileExistsError):
            export_template(model=self.model, mip=self.base,
                            palette=PALETTE, output=self.project,
                            material="skin")

    def test_build_changes_only_declared_art_region(self):
        self.write_plan([{
            "name": "hood", "rect": [2, 3, 8, 9],
            "art": "art.png", "fit": "stretch",
        }])
        target = self.home / "newskin.mip"
        summary = build_mip(project=self.project, plan=self.plan, output=target)
        old = np.asarray(load_mip(self.base)[0], dtype=np.uint8)
        new = np.asarray(load_mip(target)[0], dtype=np.uint8)
        outside = np.ones(old.shape, dtype=bool)
        outside[3:12, 2:10] = False
        self.assertTrue(np.array_equal(old[outside], new[outside]))
        self.assertGreater(int(np.count_nonzero(old != new)), 0)
        self.assertTrue(np.all((new[3:12, 2:10] >= 32)
                               & (new[3:12, 2:10] <= 175)))
        self.assertEqual(summary["changed_outside_slots"], 0)
        self.assertTrue(target.with_suffix(".png").is_file())
        self.assertTrue((self.home / "newskin_report.json").is_file())
        self.assertNotEqual(target.read_bytes(), self.base.read_bytes())

    def test_reject_overlaps_and_protect_original_mip(self):
        self.write_plan([
            {"rect": [0, 0, 8, 8], "art": "art.png"},
            {"rect": [4, 4, 8, 8], "art": "art.png"},
        ])
        target = self.home / "bad.mip"
        with self.assertRaisesRegex(ValueError, "Overlapping"):
            build_mip(project=self.project, plan=self.plan, output=target)
        self.assertFalse(target.exists())
        self.write_plan([{"rect": [0, 0, 8, 8], "art": "art.png"}])
        with self.assertRaises(FileExistsError):
            build_mip(project=self.project, plan=self.plan, output=self.base)

    def test_hash_mismatch_and_outside_rect_fail_closed(self):
        self.write_plan([{"rect": [99999, 1, 8, 8], "art": "art.png"}])
        with self.assertRaisesRegex(ValueError, "outside"):
            build_mip(project=self.project, plan=self.plan,
                      output=self.home / "bad.mip")
        self.write_plan([{"rect": [1, 1, 8, 8], "art": "art.png"}])
        bad_palette = self.home / "wrong.pcx"
        bad_palette.write_bytes(PALETTE.read_bytes() + b"x")
        with self.assertRaisesRegex(ValueError, "differs"):
            build_mip(project=self.project, plan=self.plan,
                      output=self.home / "bad.mip",
                      palette_path=bad_palette)


if __name__ == "__main__":
    unittest.main()
