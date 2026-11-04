"""Regression checks for the GPU viewer's standard desktop menus.

Requires the GPU viewer dependencies and a Qt desktop (or xvfb-run).
No OpenGL model is loaded, so these tests do not exercise rendering.
"""
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch


HAS_DISPLAY = bool(os.environ.get("DISPLAY") or
                   os.environ.get("WAYLAND_DISPLAY") or
                   sys.platform in ("win32", "darwin"))


@unittest.skipUnless(HAS_DISPLAY, "Requires a desktop or xvfb-run")
class GPUViewerMenuTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        try:
            from PySide6.QtCore import QSettings
            from PySide6.QtWidgets import QApplication, QFileDialog
            from PySide6.QtGui import QCloseEvent
            from gpu_viewer.main import Window
            import gpu_viewer.menus as menus
        except (ImportError, SystemExit) as error:
            raise unittest.SkipTest(f"GPU viewer requirements unavailable: {error}")
        cls.app = QApplication.instance() or QApplication([])
        cls.tmp = tempfile.TemporaryDirectory()
        cls.menus = menus
        cls.QFileDialog = QFileDialog
        cls.QCloseEvent = QCloseEvent
        settings_path = str(Path(cls.tmp.name) / "recent.ini")
        cls.settings_patch = patch.object(
            menus, "_settings",
            side_effect=lambda: QSettings(
                settings_path, QSettings.Format.IniFormat))
        cls.settings_patch.start()
        cls.window = Window()

    @classmethod
    def tearDownClass(cls):
        cls.window.source_pane.reset()
        cls.window.close()
        cls.settings_patch.stop()
        cls.tmp.cleanup()

    def setUp(self):
        self.window.source_pane.reset()
        self.window._source_save_target = None
        self.menus.clear_recent_files(self.window)

    def tearDown(self):
        self.window.source_pane.reset()

    def _menu(self, title):
        for action in self.window.menuBar().actions():
            if action.text().replace("&", "") == title:
                return action.menu()
        self.fail(f"Missing menu {title}")

    def _action(self, menu, title):
        for action in menu.actions():
            if action.text().replace("&", "") == title:
                return action
        self.fail(f"Missing action {title}")

    def test_standard_commands_and_shortcuts(self):
        self.assertEqual(
            [a.text().replace("&", "") for a in
             self.window.menuBar().actions()],
            ["File", "View", "Model", "Assets", "Help"])
        file_menu = self._menu("File")
        for title in ("Open Model…", "Save Source", "Save Source As…",
                      "Export Compiled 3DO…", "Exit"):
            self._action(file_menu, title)
        self.assertEqual(
            self._action(file_menu, "Open Model…").shortcut().toString(),
            "Ctrl+O")
        self.assertEqual(
            self._action(file_menu, "Save Source").shortcut().toString(),
            "Ctrl+S")
        self.assertEqual(
            self._action(file_menu, "Save Source As…").shortcut().toString(),
            "Ctrl+Shift+S")
        for key in ("save", "save_as", "export", "reload"):
            self.assertFalse(self.window.menu_actions[key].isEnabled())

    def test_view_menu_tracks_existing_widgets(self):
        view = self._menu("View")
        source = self._action(view, "Show .3D Source")
        self.assertTrue(source.isChecked())
        source.setChecked(False)
        self.assertFalse(self.window.source_toggle.isChecked())
        self.window.source_toggle.setChecked(True)
        self.assertTrue(source.isChecked())

        display = self._action(view, "Display Options").menu()
        textures = self._action(display, "Textures")
        textures.setChecked(False)
        self.assertFalse(self.window.show_textures.isChecked())
        self.window.show_textures.setChecked(True)
        self.assertTrue(textures.isChecked())

        model = self._menu("Model")
        workspace = self._action(model, "Workspace").menu()
        track = self._action(workspace, "Track")
        track.trigger()
        self.assertEqual(self.window.workspace_tabs.currentIndex(), 1)
        self.assertTrue(track.isChecked())
        self.window.workspace_tabs.setCurrentIndex(2)

    def test_settings_actions_open_correct_dialogs(self):
        with patch.object(self.window, "open_settings_dialog") as show:
            self._action(self._menu("View"), "Display Settings…").trigger()
            show.assert_called_once_with("display")
        with patch.object(self.window, "open_settings_dialog") as show:
            self._action(self._menu("View"), "Advanced Diagnostics…").trigger()
            show.assert_called_once_with("advanced")
        with patch.object(self.window, "open_settings_dialog") as show:
            self._action(self._menu("Model"), "Track Settings…").trigger()
            show.assert_called_once_with("model", workspace=1)
        with patch.object(self.window, "open_settings_dialog") as show:
            self._action(self._menu("Assets"), "Asset Settings…").trigger()
            show.assert_called_once_with("assets")

    def test_save_and_save_as_track_clean_source(self):
        source = self.window.source_pane
        with tempfile.TemporaryDirectory() as directory:
            original = Path(directory) / "input.3d"
            original.write_text("3D VERSION 3.0;\n", encoding="utf-8")
            source.set_source(original.read_text(encoding="utf-8"), original)
            source.editor.insertPlainText("% first edit\n")
            self.assertTrue(source.dirty)
            destination = Path(directory) / "saved.3d"
            with patch.object(
                    self.QFileDialog, "getSaveFileName",
                    return_value=(str(destination), "")) as dialog:
                self.assertTrue(self.window._save_source())
                dialog.assert_called_once()
            self.assertFalse(source.dirty)
            self.assertIn("% first edit", destination.read_text(encoding="utf-8"))
            source.editor.insertPlainText("% second edit\n")
            self.assertTrue(source.dirty)
            with patch.object(
                    self.QFileDialog, "getSaveFileName",
                    side_effect=AssertionError("Save should reuse chosen path")):
                self.assertTrue(self.window._save_source())
            self.assertFalse(source.dirty)
            self.assertIn("% second edit", destination.read_text(encoding="utf-8"))
            another = Path(directory) / "saved_as.3d"
            with patch.object(
                    self.QFileDialog, "getSaveFileName",
                    return_value=(str(another), "")):
                self.assertTrue(self.window._save_source(save_as=True))
            self.assertEqual(self.window._source_save_target, another)
            self.assertTrue(another.exists())
            self.assertEqual(original.read_text(encoding="utf-8"),
                             "3D VERSION 3.0;\n")

    def test_recent_file_menu_routes_to_loader_and_can_clear(self):
        with tempfile.TemporaryDirectory() as directory:
            first = Path(directory) / "first.3d"
            second = Path(directory) / "second.3do"
            first.touch()
            second.touch()
            self.menus.remember_recent_model(self.window, first)
            self.menus.remember_recent_model(self.window, second)
            menu = self.window.recent_models_menu
            entries = [action for action in menu.actions()
                       if action.text().startswith("&")]
            self.assertEqual(len(entries), 2)
            self.assertIn("second.3do", entries[0].text())
            with patch.object(self.window, "load") as load:
                entries[0].trigger()
                load.assert_called_once_with(second.resolve())
            self.menus.clear_recent_files(self.window)
            self.assertFalse(
                self._action(menu, "Clear Recent Files").isEnabled())

    def test_exit_does_not_discard_source_without_confirmation(self):
        from PySide6.QtWidgets import QMessageBox

        pane = self.window.source_pane
        pane.set_source("3D VERSION 3.0;\n", Path(self.tmp.name) / "model.3d")
        pane.editor.insertPlainText("% unsaved\n")
        self.assertTrue(pane.dirty)
        event = self.QCloseEvent()
        with patch.object(QMessageBox, "question",
                          return_value=QMessageBox.StandardButton.No):
            self.window.closeEvent(event)
        self.assertFalse(event.isAccepted())


if __name__ == "__main__":
    unittest.main()
