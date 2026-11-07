"""Qt commands for applying a driver wrapper to an already-open model."""
import os
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

HAS_DISPLAY = bool(
    os.environ.get("DISPLAY") or os.environ.get("WAYLAND_DISPLAY") or
    sys.platform in ("win32", "darwin"))
ROOT = Path(__file__).resolve().parents[1]
FIX = ROOT / "fixtures"


@unittest.skipUnless(HAS_DISPLAY, "Requires desktop or Xvfb")
class CarAppearanceOverlayUITests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        try:
            from PySide6.QtWidgets import QApplication
            from icr2_3do_cad import Window
            from three_do import Model
            from car_appearance import read_car_appearance
            from menus import update_model_actions
        except (ImportError, SystemExit) as error:
            raise unittest.SkipTest(str(error))
        cls.app = QApplication.instance() or QApplication([])
        cls.window = Window()
        cls.Model = Model
        cls.update_model_actions = staticmethod(update_model_actions)
        cls.wrapper = read_car_appearance(FIX / "cit74.3do")

    @classmethod
    def tearDownClass(cls):
        cls.window.close()

    def setUp(self):
        window = self.window
        window.worker = None
        window.model_path = FIX / "roadcar.3do"
        window.viewer._model = self.Model(window.model_path, associate_planes=False)
        window._loaded_file_path = window.model_path
        window._source_queued = None
        window._source_busy_revision = None
        window._appearance_change_pending = False
        window._appearance_candidate = None
        window.car_appearance_overlay = None
        window._native_car_appearance = None
        window.source_pane.reset()
        window._update_window_title()
        self.update_model_actions(window)

    def tearDown(self):
        self.window.worker = None
        self.window.car_appearance_overlay = None
        self.window._appearance_change_pending = False
        self.window._appearance_candidate = None
        self.window.viewer._model = None
        self.window.model_path = None
        self.window._loaded_file_path = None
        self.window.source_pane.reset()
        self.update_model_actions(self.window)

    def test_asset_menu_and_car_controls_enable_with_open_model(self):
        window = self.window
        self.assertTrue(window.menu_actions["appearance_overlay"].isEnabled())
        self.assertTrue(window.apply_car_appearance_button.isEnabled())
        self.assertFalse(window.menu_actions["clear_appearance_overlay"].isEnabled())
        with patch.object(window, "load") as reload:
            window._change_car_appearance_overlay(self.wrapper)
            reload.assert_called_once_with(window.model_path, reuse_model=True)
        self.assertIs(window._appearance_candidate, self.wrapper)
        # The active preview changes only when the worker/GL path succeeds.
        self.assertIsNone(window.car_appearance_overlay)

    def test_dialog_accepts_mismatched_carshape_without_opening_it(self):
        window = self.window
        from PySide6.QtWidgets import QFileDialog
        original = window.viewer._model
        with patch.object(QFileDialog, "getOpenFileName",
                          return_value=(str(self.wrapper.path), "")), \
             patch.object(window, "load") as reload:
            window.choose_car_appearance_overlay()
            reload.assert_called_once_with(window.model_path, reuse_model=True)
        self.assertEqual(window.model_path.name, "roadcar.3do")
        self.assertEqual(window._appearance_candidate.geometry_name, "indycar")
        self.assertIs(window.viewer._model, original)

    def test_invalid_wrapper_does_not_replace_current_preview(self):
        window = self.window
        window.car_appearance_overlay = self.wrapper
        from PySide6.QtWidgets import QFileDialog, QMessageBox
        with patch.object(QFileDialog, "getOpenFileName",
                          return_value=(str(window.model_path), "")), \
             patch.object(QMessageBox, "warning") as warning, \
             patch.object(window, "load") as reload:
            window.choose_car_appearance_overlay()
        warning.assert_called_once()
        reload.assert_not_called()
        self.assertIs(window.car_appearance_overlay, self.wrapper)

    def test_clearing_preview_returns_to_native_appearance(self):
        window = self.window
        window.car_appearance_overlay = self.wrapper
        self.update_model_actions(window)
        self.assertTrue(window.menu_actions["clear_appearance_overlay"].isEnabled())
        with patch.object(window, "load") as reload:
            window.clear_car_appearance_overlay()
            reload.assert_called_once_with(window.model_path, reuse_model=True)
        self.assertTrue(window._appearance_change_pending)
        self.assertIsNone(window._appearance_candidate)
        self.assertIs(window.car_appearance_overlay, self.wrapper)

    def test_manual_preview_name_is_visible_but_source_file_is_unchanged(self):
        window = self.window
        window.car_appearance_overlay = self.wrapper
        window._update_window_title()
        self.assertIn("roadcar.3do", window.windowTitle())
        self.assertIn("Preview: cit74.3do", window.windowTitle())

    def test_source_compile_in_progress_blocks_change_without_discarding_text(self):
        window = self.window
        from PySide6.QtWidgets import QMessageBox
        window._source_busy_revision = 12
        with patch.object(QMessageBox, "information") as notice, \
             patch.object(window, "load") as reload:
            window._change_car_appearance_overlay(self.wrapper)
        notice.assert_called_once()
        reload.assert_not_called()
        self.assertFalse(window._appearance_change_pending)

    def test_background_loader_previews_without_substituting_geometry(self):
        from icr2_3do_cad import LoadWorker
        window = self.window
        model_before = window.viewer._model
        binary_before = model_before.raw
        worker = LoadWorker(
            window.model_path, ROOT / "gamepal.pcx",
            existing_model=model_before, appearance_override=self.wrapper)
        ready = []
        failures = []
        worker.ready.connect(lambda *args: ready.append(args))
        worker.failed.connect(failures.append)
        # Run the same QThread work synchronously to inspect the signal data.
        worker.run()
        self.assertFalse(failures, failures)
        self.assertEqual(len(ready), 1)
        mesh, stats, model, atlas, palette, scene = ready[0]
        self.assertIs(model, model_before)
        self.assertEqual(model.raw, binary_before)
        self.assertIs(scene.appearance, self.wrapper)
        self.assertEqual(stats["appearance_file"], "cit74.3do")
        self.assertTrue(stats["appearance_reference_mismatch"])
        self.assertEqual(stats["geometry_file"], "roadcar.3do")
        self.assertGreater(mesh.triangle_count, 0)

    def test_source_recompile_worker_retains_appearance(self):
        from icr2_3do_cad import LoadWorker
        source = ("3D VERSION 3.0;\\n"
                  "a: [<0,0,0>];\\n"
                  "b: [<100,0,0>];\\n"
                  "c: [<0,100,0>];\\n"
                  "surface: POLY <44> {a,b,c};\\n"
                  "root: LIST {surface};\\n")
        worker = LoadWorker(
            Path("source_preview.3d"), ROOT / "gamepal.pcx",
            source_text=source, source_path=Path("source_preview.3d"),
            appearance_override=self.wrapper)
        ready, failures = [], []
        worker.ready.connect(lambda *args: ready.append(args))
        worker.failed.connect(failures.append)
        worker.run()
        self.assertFalse(failures, failures)
        self.assertEqual(len(ready), 1)
        _, stats, model, _, _, scene = ready[0]
        self.assertEqual(stats["appearance_file"], "cit74.3do")
        self.assertIs(scene.appearance, self.wrapper)
        root_color = scene.geometry.polygons[
            scene.polygon_lookup[0, next(iter(model.polygons))]].color
        self.assertEqual(root_color, self.wrapper.map_color(44))

    def test_worker_receives_existing_geometry_and_requested_preview(self):
        window = self.window
        with patch("icr2_3do_cad.LoadWorker") as create, \
             patch.object(window, "_begin_load_activity"), \
             patch.object(window, "_begin_load_progress"):
            window._change_car_appearance_overlay(self.wrapper)
        kwargs = create.call_args.kwargs
        self.assertIs(kwargs["existing_model"], window.viewer._model)
        self.assertIs(kwargs["appearance_override"], self.wrapper)
        self.assertIsNone(kwargs["source_text"])
        self.assertEqual(window.model_path.name, "roadcar.3do")


if __name__ == "__main__":
    unittest.main()
