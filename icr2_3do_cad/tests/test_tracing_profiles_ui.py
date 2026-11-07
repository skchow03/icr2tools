"""Qt saved reference profiles: reuse across models without touching geometry."""
import os
import sys
import tempfile
import unittest
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import numpy as np

HAS_DISPLAY = bool(os.environ.get("DISPLAY") or os.environ.get("WAYLAND_DISPLAY")
                   or sys.platform in ("win32", "darwin"))
ROOT = Path(__file__).resolve().parents[1]


@unittest.skipUnless(HAS_DISPLAY, "Requires Qt desktop or Xvfb")
class SavedTracingProfilesUITests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        try:
            from PySide6.QtWidgets import QApplication, QFileDialog, QInputDialog
            from PySide6.QtWidgets import QMessageBox
            from PySide6.QtGui import QImage
            from icr2_3do_cad import Window
            from three_do import Model
            from tracing_profiles import TracingProfileStore
            from menus import update_model_actions
        except (ImportError, SystemExit) as exc:
            raise unittest.SkipTest(str(exc))
        cls.app = QApplication.instance() or QApplication([])
        cls.Window = Window
        cls.Model = Model
        cls.QImage = QImage
        cls.QFileDialog = QFileDialog
        cls.QInputDialog = QInputDialog
        cls.QMessageBox = QMessageBox
        cls.TracingProfileStore = TracingProfileStore
        cls.update_actions = staticmethod(update_model_actions)
        cls.tmp = tempfile.TemporaryDirectory()
        cls.image_path = Path(cls.tmp.name) / "photo.png"
        image = QImage(240, 80, QImage.Format.Format_RGBA8888)
        image.fill(0xff44aabb)
        assert image.save(str(cls.image_path))

    @classmethod
    def tearDownClass(cls):
        cls.tmp.cleanup()

    def setUp(self):
        self.w = self.Window()
        self.w.tracing_profile_store = self.TracingProfileStore(
            Path(self.tmp.name) / "profiles-test.json")
        self.w.tracing_profile_store.path.unlink(missing_ok=True)
        self.w.model_path = ROOT / "fixtures" / "roadcar.3do"
        self.w.viewer._model = self.Model(
            self.w.model_path, associate_planes=False)
        self.w.viewer._mesh = SimpleNamespace(
            center=np.array((1000., 2000., 3000.)), scale=1000.)
        self.raw = self.w.viewer._model.raw
        self.update_actions(self.w)

    def tearDown(self):
        self.w.clear_tracing_reference_image()
        self.w.close()
        self.app.processEvents()

    def open_photo(self):
        with patch.object(
                self.QFileDialog, "getOpenFileName",
                return_value=(str(self.image_path), "")):
            self.w.load_tracing_reference_image()
        return self.w.viewer.tracing_reference

    def save_named(self, name="Car 1995", overwrite=False):
        with patch.object(
                self.QInputDialog, "getText", return_value=(name, True)), \
             patch.object(self.QMessageBox, "question",
                          return_value=self.QMessageBox.StandardButton.Yes):
            self.w.save_tracing_profile()

    def test_menu_and_calibration_window_expose_profile_controls(self):
        w = self.w
        self.assertFalse(w.menu_actions["tracing_save"].isEnabled())
        self.assertTrue(w.menu_actions["tracing_restore"].isEnabled())
        self.assertTrue(w.menu_actions["tracing_delete_profile"].isEnabled())
        self.open_photo()
        self.assertTrue(w.menu_actions["tracing_save"].isEnabled())
        dlg = w.tracing_dialog
        self.assertIsNotNone(dlg.profile_combo)
        self.assertIsNotNone(dlg.profile_placement)
        self.assertEqual(dlg.profile_placement.currentData(), "relative")
        self.assertFalse(dlg.profile_load_button.isEnabled())
        self.save_named()
        self.assertEqual(dlg.profile_combo.currentData(), "Car 1995")
        self.assertTrue(dlg.profile_load_button.isEnabled())
        self.assertTrue(dlg.profile_delete_button.isEnabled())

    def test_save_then_restore_same_and_different_models(self):
        w = self.w
        ref = self.open_photo()
        ref = replace(
            ref, plane="Front", anchor_pixel=(45., 30.),
            point_a=(45., 30.), point_b=(180., 30.),
            calibration_distance=2700., world_anchor=(1500., 3400.),
            units_per_pixel=20., opacity=0.2, rotation_degrees=12.)
        w._tracing_reference_changed(ref)
        self.save_named("Façade template")
        self.assertEqual(
            w.tracing_profile_store.names(), ["Façade template"])
        w.clear_tracing_reference_image()
        # Simulate reopening the application: a fresh store instance reads disk.
        w.tracing_profile_store = self.TracingProfileStore(
            w.tracing_profile_store.path)
        w.load_saved_tracing_profile("Façade template")
        self.assertEqual(w.viewer.tracing_reference, ref)
        self.assertIs(w.viewer._model.path, w.viewer._model.path)
        w.clear_tracing_reference_image()
        w.viewer._mesh = SimpleNamespace(
            center=np.array((11000., -8000., 23000.)), scale=4000.)
        # Front is X/Z, so anchor shifts (+10000,+20000), but units/pixel
        # and the saved measured distance remain unchanged.
        w.load_saved_tracing_profile("Façade template")
        loaded = w.viewer.tracing_reference
        self.assertEqual(loaded.world_anchor, (11500., 23400.))
        self.assertEqual(loaded.point_a, (45., 30.))
        self.assertEqual(loaded.point_b, (180., 30.))
        self.assertEqual(loaded.calibration_distance, 2700.)
        self.assertEqual(loaded.units_per_pixel, 20.)
        self.assertEqual(loaded.rotation_degrees, 12.)
        self.assertEqual(loaded.opacity, .2)
        self.assertEqual(w.viewer._model.raw, self.raw)

    def test_exact_coordinate_mode_restores_original_position(self):
        w = self.w
        ref = self.open_photo()
        ref = replace(ref, world_anchor=(2400., 3200.))
        w._tracing_reference_changed(ref)
        self.save_named()
        w.viewer._mesh = SimpleNamespace(
            center=np.array((50000., 80000., 90000.)), scale=7500.)
        w.tracing_dialog.profile_placement.setCurrentIndex(
            w.tracing_dialog.profile_placement.findData("absolute"))
        w.tracing_dialog.profile_load_button.click()
        self.assertEqual(w.viewer.tracing_reference.world_anchor,
                         (2400., 3200.))

    def test_missing_image_does_not_replace_current_reference_or_delete_profile(self):
        w = self.w
        original = self.open_photo()
        self.save_named()
        missing = Path(self.tmp.name) / "missing.png"
        from dataclasses import replace
        w._tracing_reference_changed(replace(original, path=missing))
        self.save_named("Missing photo")
        w._tracing_reference_changed(original)
        with patch.object(self.QMessageBox, "warning") as warn:
            w.load_saved_tracing_profile("Missing photo")
        warn.assert_called_once()
        self.assertEqual(w.viewer.tracing_reference, original)
        self.assertEqual(
            w.tracing_profile_store.names(), ["Car 1995", "Missing photo"])

    def test_delete_profile_never_deletes_current_image_or_reference(self):
        w = self.w
        ref = self.open_photo()
        self.save_named()
        with patch.object(
                self.QMessageBox, "question",
                return_value=self.QMessageBox.StandardButton.Yes):
            w.delete_tracing_profile("Car 1995")
        self.assertEqual(w.tracing_profile_store.names(), [])
        self.assertEqual(w.viewer.tracing_reference, ref)
        self.assertTrue(self.image_path.is_file())
        self.assertEqual(w.viewer._model.raw, self.raw)


if __name__ == "__main__":
    unittest.main()
