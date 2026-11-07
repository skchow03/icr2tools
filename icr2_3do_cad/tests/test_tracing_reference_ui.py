"""Qt tracing-image controls: import, calibration, visibility and lifecycle."""
import os
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import numpy as np

HAS_DISPLAY = bool(os.environ.get("DISPLAY") or os.environ.get("WAYLAND_DISPLAY")
                   or sys.platform in ("win32", "darwin"))
ROOT = Path(__file__).resolve().parents[1]


@unittest.skipUnless(HAS_DISPLAY, "Requires Qt desktop or Xvfb")
class TracingReferenceUITests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        try:
            from PySide6.QtWidgets import QApplication, QFileDialog, QMessageBox
            from PySide6.QtGui import QImage
            from icr2_3do_cad import Window
            from three_do import Model
            from menus import update_model_actions
        except (ImportError, SystemExit) as exc:
            raise unittest.SkipTest(str(exc))
        cls.app = QApplication.instance() or QApplication([])
        cls.window = Window()
        cls.Model = Model
        cls.QImage = QImage
        cls.QFileDialog = QFileDialog
        cls.QMessageBox = QMessageBox
        cls.update_actions = staticmethod(update_model_actions)
        cls.temp = tempfile.TemporaryDirectory()
        cls.photo = Path(cls.temp.name) / "profile.png"
        img = QImage(200, 100, QImage.Format.Format_RGBA8888)
        img.fill(0xff4477bb)
        assert img.save(str(cls.photo))

    @classmethod
    def tearDownClass(cls):
        cls.window.clear_tracing_reference_image()
        cls.window.close()
        cls.temp.cleanup()

    def setUp(self):
        w = self.window
        w.worker = None
        w.model_path = ROOT / "fixtures" / "roadcar.3do"
        w.viewer._model = self.Model(w.model_path, associate_planes=False)
        w.viewer._mesh = SimpleNamespace(
            center=np.array([1000.0, 2000.0, 3000.0]), scale=1000.0)
        w._loaded_file_path = w.model_path
        self.update_actions(w)

    def tearDown(self):
        w = self.window
        w.clear_tracing_reference_image()
        w.viewer._model = None
        w.viewer._mesh = None
        w.model_path = None
        w._loaded_file_path = None
        self.update_actions(w)

    def load_photo(self):
        with patch.object(
                self.QFileDialog, "getOpenFileName",
                return_value=(str(self.photo), "")):
            self.window.load_tracing_reference_image()
        return self.window.viewer.tracing_reference

    def test_model_required_and_asset_menu_actions(self):
        w = self.window
        self.assertTrue(w.menu_actions["tracing_load"].isEnabled())
        self.assertFalse(w.menu_actions["tracing_adjust"].isEnabled())
        self.assertFalse(w.menu_actions["tracing_remove"].isEnabled())
        w.viewer._mesh = None
        with patch.object(self.QMessageBox, "information") as notice:
            w.load_tracing_reference_image()
        notice.assert_called_once()
        self.assertIsNone(w.viewer.tracing_reference)

    def test_import_preserves_open_geometry_and_shows_nonmodal_editor(self):
        w = self.window
        model = w.viewer._model
        original_raw = model.raw
        with patch.object(w, "load") as compile_model:
            ref = self.load_photo()
        compile_model.assert_not_called()
        self.assertIs(w.viewer._model, model)
        self.assertEqual(w.viewer._model.raw, original_raw)
        self.assertEqual(ref.path, self.photo)
        self.assertEqual(ref.plane, "Side")
        self.assertEqual(ref.width, 200)
        self.assertEqual(ref.height, 100)
        self.assertFalse(w.viewer.perspective)
        self.assertIsNotNone(w.tracing_dialog)
        self.assertFalse(w.tracing_dialog.isModal())
        self.assertTrue(w.menu_actions["tracing_adjust"].isEnabled())
        self.assertTrue(w.menu_actions["tracing_remove"].isEnabled())
        w.tracing_dialog.close()
        self.assertIs(w.viewer.tracing_reference, ref)

    def test_two_point_click_calibration_updates_live_model_space_scale(self):
        from PySide6.QtCore import Qt, QPoint
        from PySide6.QtTest import QTest
        w = self.window
        self.load_photo()
        dialog = w.tracing_dialog
        dialog.show()
        self.app.processEvents()
        dialog.distance.setValue(6000.0)
        rect = dialog.canvas.image_rect()
        self.assertGreater(rect.width(), 0)
        self.assertGreater(rect.height(), 0)
        def target(x_frac, y_frac):
            return QPoint(round(rect.left()+rect.width()*x_frac),
                          round(rect.top()+rect.height()*y_frac))
        dialog.pick_a.click()
        QTest.mouseClick(dialog.canvas, Qt.MouseButton.LeftButton,
                         pos=target(.2, .5))
        self.assertEqual(dialog.canvas.pick_target, "B")
        QTest.mouseClick(dialog.canvas, Qt.MouseButton.LeftButton,
                         pos=target(.8, .5))
        self.assertIsNone(dialog.canvas.pick_target)
        ref = w.viewer.tracing_reference
        self.assertIsNotNone(ref.point_a)
        self.assertIsNotNone(ref.point_b)
        self.assertEqual(ref.calibration_distance, 6000.0)
        self.assertAlmostEqual(ref.units_per_pixel, 50.0, delta=2)
        self.assertAlmostEqual(ref.rotation_degrees, 0, delta=2)
        from tracing_reference import image_point_to_world
        world_a = image_point_to_world(ref, *ref.point_a)
        world_b = image_point_to_world(ref, *ref.point_b)
        self.assertAlmostEqual(world_b[0]-world_a[0], 6000, places=3)
        self.assertAlmostEqual(world_b[1]-world_a[1], 0, places=3)

    def test_switch_plane_and_opacity_are_independent_of_editing(self):
        w = self.window
        self.load_photo()
        dialog = w.tracing_dialog
        model = w.viewer._model
        bytes_before = model.raw
        dialog.plane.setCurrentIndex(dialog.plane.findData("Front"))
        self.assertEqual(w.viewer.tracing_reference.plane, "Front")
        self.assertEqual(w.viewer.tracing_reference.world_anchor,
                         (1000.0, 3000.0))
        dialog.opacity.setValue(30)
        self.assertAlmostEqual(w.viewer.tracing_reference.opacity, 0.3)
        dialog.visible.setChecked(False)
        self.assertFalse(w.viewer.tracing_reference.visible)
        dialog.world_u.setValue(1400)
        self.assertEqual(w.viewer.tracing_reference.world_anchor[0], 1400)
        dialog.align.click()
        self.assertFalse(w.viewer.perspective)
        self.assertIs(w.viewer._model, model)
        self.assertEqual(model.raw, bytes_before)

    def test_invalid_image_keeps_previous_reference(self):
        w = self.window
        original = self.load_photo()
        bad = Path(self.temp.name) / "bad.png"
        bad.write_bytes(b"not an image")
        with patch.object(
                self.QFileDialog, "getOpenFileName",
                return_value=(str(bad), "")), patch.object(
                self.QMessageBox, "warning") as warning:
            w.load_tracing_reference_image()
        warning.assert_called_once()
        self.assertEqual(w.viewer.tracing_reference, original)

    def test_remove_and_reopen_image_does_not_modify_model(self):
        w = self.window
        original = w.viewer._model.raw
        self.load_photo()
        w.clear_tracing_reference_image()
        self.assertIsNone(w.viewer.tracing_reference)
        self.assertIsNone(w.tracing_dialog)
        self.assertFalse(w.menu_actions["tracing_adjust"].isEnabled())
        self.assertEqual(w.viewer._model.raw, original)


if __name__ == "__main__":
    unittest.main()
