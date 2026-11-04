"""End-to-end GPU window palette selection on opening .3D and .3DO models.

Runs under Xvfb to exercise real LoadWorker signals, UI updates, and GL
palette propagation; never modifies original model or palette assets.
"""
import os
import shutil
import sys
import tempfile
import unittest
from pathlib import Path

import numpy as np

from gpu_viewer.textures import load_palette


HAS_DISPLAY = bool(os.environ.get("DISPLAY") or
                   os.environ.get("WAYLAND_DISPLAY") or
                   sys.platform in ("win32", "darwin"))
ROOT = Path(__file__).resolve().parents[1]

SOURCE = """3D VERSION 3.0;
a: [<0,0,0>];
b: [<100,0,0>];
c: [<0,100,0>];
surface: POLY <32> {a,b,c};
root: LIST {surface};
"""


@unittest.skipUnless(HAS_DISPLAY, "Qt GPU tests require a desktop or Xvfb")
class ModelAutoPaletteQtTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        try:
            from PySide6.QtWidgets import QApplication
            from gpu_viewer.main import Window
        except (ImportError, SystemExit) as err:
            raise unittest.SkipTest(f"GPU viewer dependencies unavailable: {err}")
        cls.app = QApplication.instance() or QApplication([])
        cls.window = Window()
        cls.window.resize(950, 700)
        cls.window.show()
        cls.app.processEvents()
        cls.temp = tempfile.TemporaryDirectory()
        cls.folder = Path(cls.temp.name)
        cls.palette_data = bytearray((ROOT / "gamepal.pcx").read_bytes())

    @classmethod
    def tearDownClass(cls):
        cls.window.close()
        cls.app.processEvents()
        cls.temp.cleanup()

    def mkpalette(self, folder, name, seed=1):
        folder.mkdir(parents=True, exist_ok=True)
        candidate = folder / name
        contents = bytearray(self.palette_data)
        contents[-768:] = bytes((i * 7 + seed) % 256 for i in range(768))
        candidate.write_bytes(contents)
        return candidate

    def make3d(self, folder, name="asset.3d"):
        folder.mkdir(parents=True, exist_ok=True)
        path = folder / name
        path.write_text(SOURCE, encoding="utf-8")
        return path

    def wait_loaded(self, path, *, reuse=False):
        previous_stats = self.window._info
        self.window.load(path, reuse_model=reuse)
        worker = self.window.worker
        self.assertIsNotNone(worker)
        # Waiting for the thread isn't enough: queued Qt signals need to be
        # delivered on the GUI thread to install the mesh/palette.
        for _ in range(300):
            worker.wait(25)
            self.app.processEvents()
            if (self.window._info is not previous_stats and
                    self.window._info.get("file") == path.name):
                self.app.processEvents()
                return self.window._info
        self.fail(f"GPU worker did not install model: {path}")

    def test_new_file_auto_palette_both_formats_and_manual_reload(self):
        self.window._apply_palette(ROOT / "gamepal.pcx")
        first = self.make3d(self.folder / "source", "test.3D")
        first_sunny = self.mkpalette(first.parent, "SUNNY.PCX", 13)
        info = self.wait_loaded(first)
        self.assertEqual(self.window.palette_path, first_sunny)
        self.assertTrue(info["palette_auto"])
        self.assertEqual(info["palette_path"], first_sunny)
        self.assertIn("model folder", self.window.palette_status.text())
        self.assertTrue(np.array_equal(
            self.window.viewer._palette, load_palette(first_sunny)))

        # Opening another asset chooses the NEW folder rather than retaining
        # the previous asset's SUNNY.PCX.
        second_dir = self.folder / "binary"
        second_dir.mkdir()
        second = second_dir / "roadcar.3do"
        shutil.copyfile(ROOT / "fixtures" / "roadcar.3do", second)
        second_sunny = self.mkpalette(second_dir, "SuNnY.PcX", 71)
        info = self.wait_loaded(second)
        self.assertTrue(info["palette_auto"])
        self.assertEqual(self.window.palette_path, second_sunny)
        self.assertTrue(np.array_equal(
            self.window.viewer._palette, load_palette(second_sunny)))
        self.assertFalse(np.array_equal(
            self.window.viewer._palette, load_palette(first_sunny)))

        # A user-selected PCX takes precedence on reloading the SAME asset.
        manual = self.mkpalette(self.folder / "palettes", "manual.pcx", 29)
        self.window._apply_palette(manual)
        self.assertEqual(self.window.palette_path, manual)
        info = self.wait_loaded(second, reuse=True)
        self.assertFalse(info["palette_auto"])
        self.assertEqual(self.window.palette_path, manual)
        self.assertTrue(np.array_equal(
            self.window.viewer._palette, load_palette(manual)))

    def test_missing_and_malformed_local_sunny_do_not_block_loading(self):
        previous = self.window.palette_path
        without = self.make3d(self.folder / "none", "plain.3d")
        info = self.wait_loaded(without)
        self.assertFalse(info["palette_auto"])
        self.assertIsNone(info["palette_warning"])
        self.assertTrue(self.window.load_error_dialog.isHidden())
        self.assertIn("no reported load issues",
                      self.window.load_error_summary.text())
        self.assertEqual(self.window.palette_path, previous)

        broken = self.make3d(self.folder / "broken", "badpalette.3d")
        (broken.parent / "SUNNY.PCX").write_bytes(b"invalid PCX")
        info = self.wait_loaded(broken)
        self.assertFalse(info["palette_auto"])
        self.assertIn("SUNNY.PCX", info["palette_warning"])
        self.assertIn("using", info["palette_warning"])
        self.assertFalse(self.window.load_error_dialog.isHidden())
        self.assertIn("SUNNY.PCX", self.window.load_error_text.toPlainText())
        self.window.load_error_dialog.close()
        self.assertEqual(self.window.palette_path, previous)
        self.assertIn("SUNNY.PCX", self.window.statusBar().currentMessage())
        self.assertTrue(np.array_equal(
            self.window.viewer._palette, load_palette(previous)))

    def test_missing_dynamic_and_mip_open_combined_error_log(self):
        source = """3D VERSION 3.0;
a: [<0,0,0>, T=<0,0>];
b: [<100,0,0>, T=<128,0>];
c: [<0,100,0>, T=<0,128>];
surface: MATERIAL MIP="nomip123", GROUP=3, POLY [T] <44> {a,b,c};
wheel: DYNAMIC 0, 0, 0, 0, 0, 0, 1, EXTERN "nxref123";
root: LIST {surface, wheel};
"""
        folder = self.folder / "missing_refs"
        path = self.make3d(folder, "missing_refs.3d")
        path.write_text(source, encoding="utf-8")
        stats = self.wait_loaded(path)
        self.assertTrue(stats["external_warnings"])
        self.assertIn("nomip123", stats["missing_textures"])
        self.assertFalse(self.window.load_error_dialog.isHidden())
        report = self.window.load_error_text.toPlainText()
        self.assertIn("Referenced objects", report)
        self.assertIn("nxref123", report)
        self.assertIn("Missing MIP textures", report)
        self.assertIn("nomip123", report)
        self.window.load_error_dialog.close()

    def test_failed_geometry_does_not_commit_detected_palette(self):
        previous = self.window.palette_path
        invalid = self.folder / "invalidmodel"
        model = self.make3d(invalid, "invalid.3d")
        model.write_text("not valid 3D source", encoding="utf-8")
        alternate = self.mkpalette(invalid, "SUNNY.PCX", 99)
        from unittest.mock import patch
        with patch("gpu_viewer.main.QMessageBox.critical"):
            self.window.load(model)
            worker = self.window.worker
            for _ in range(300):
                worker.wait(25)
                self.app.processEvents()
                if not worker.isRunning():
                    self.app.processEvents()
                    break
        self.assertEqual(self.window.palette_path, previous)
        self.assertNotEqual(self.window.palette_path, alternate)


if __name__ == "__main__":
    unittest.main()
