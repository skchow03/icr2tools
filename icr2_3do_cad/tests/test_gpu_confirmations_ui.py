"""Qt regression for destructive confirmations in the GPU source viewer.

Run under Xvfb on CI. Respond to real QMessageBoxes rather than mocking
messagebox.question, so button text/default/Escape behavior is exercised.
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


@unittest.skipUnless(HAS_DISPLAY, "Needs Qt desktop or Xvfb")
class ExplicitConfirmationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        try:
            from PySide6.QtWidgets import QApplication
            from gpu_viewer.main import Window
        except (ImportError, SystemExit) as exc:
            raise unittest.SkipTest(f"GPU Qt dependencies unavailable: {exc}")
        cls.app = QApplication.instance() or QApplication([])
        cls.Window = Window

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.window = self.Window()

    def tearDown(self):
        self.window.source_pane.reset()
        self.window.worker = None
        self.window.close()
        self.app.processEvents()

    def _interact(self, operation, action_label, selection="Cancel"):
        from PySide6.QtCore import Qt, QTimer
        from PySide6.QtTest import QTest
        from PySide6.QtWidgets import QApplication, QMessageBox

        observed = {}

        def respond():
            dialog = QApplication.activeModalWidget()
            try:
                if not isinstance(dialog, QMessageBox):
                    raise AssertionError(
                        f"Expected QMessageBox, found {type(dialog)}")
                buttons = {button.text().replace("&", ""): button
                           for button in dialog.buttons()}
                observed["buttons"] = set(buttons)
                observed["default"] = dialog.defaultButton().text().replace(
                    "&", "")
                observed["escape"] = dialog.escapeButton().text().replace(
                    "&", "")
                observed["title"] = dialog.windowTitle()
                observed["message"] = dialog.text()
                if selection == "Enter":
                    QTest.keyClick(dialog, Qt.Key.Key_Return)
                elif selection == "Escape":
                    QTest.keyClick(dialog, Qt.Key.Key_Escape)
                elif selection == "Window close":
                    dialog.close()
                else:
                    buttons[selection].click()
            except Exception as error:
                observed["error"] = error
                if dialog is not None:
                    dialog.reject()

        QTimer.singleShot(0, respond)
        outcome = operation()
        if "error" in observed:
            raise observed["error"]
        self.assertEqual(observed["buttons"], {action_label, "Cancel"})
        self.assertEqual(observed["default"], "Cancel")
        self.assertEqual(observed["escape"], "Cancel")
        return outcome, observed

    def test_discard_uses_named_action_and_cancel_is_safe_default(self):
        from gpu_viewer.confirmations import confirm_destructive_action

        for choice, expected in (
                ("Cancel", False),
                ("Enter", False),
                ("Escape", False),
                ("Window close", False),
                ("Discard changes", True)):
            with self.subTest(choice=choice):
                outcome, observed = self._interact(
                    lambda: confirm_destructive_action(
                        self.window, "Unsaved source",
                        "Opening another model discards changes.",
                        "Discard changes"),
                    "Discard changes", choice)
                self.assertIs(outcome, expected)
                self.assertEqual(observed["title"], "Unsaved source")

    def test_overwrite_uses_clear_label_not_yes_no(self):
        from gpu_viewer.confirmations import confirm_destructive_action

        for choice, expected in (("Cancel", False),
                                 ("Overwrite original", True)):
            with self.subTest(choice=choice):
                result, _ = self._interact(
                    lambda: confirm_destructive_action(
                        self.window, "Overwrite original",
                        "Existing file contents will be lost.",
                        "Overwrite original"),
                    "Overwrite original", choice)
                self.assertIs(result, expected)

    def test_open_model_cancel_keeps_dirty_source_and_original_path(self):
        pane = self.window.source_pane
        original = Path(self.temp.name) / "old.3d"
        next_file = Path(self.temp.name) / "new.3do"
        pane.set_source("3D VERSION 3.0;\n", original)
        pane.editor.insertPlainText("% unsaved change\n")
        text_before = pane.get_source()
        self.window.model_path = original
        with patch.object(self.window, "_busy", return_value=False):
            result, observed = self._interact(
                lambda: self.window.load(next_file),
                "Discard changes", "Cancel")
        self.assertIsNone(result)
        self.assertTrue(pane.dirty)
        self.assertTrue(pane.ready)
        self.assertEqual(pane.get_source(), text_before)
        self.assertEqual(self.window.model_path, original)
        self.assertIn(next_file.name, observed["message"])

    def test_open_model_discard_resets_editor_and_starts_new_load(self):
        pane = self.window.source_pane
        pane.set_source("3D VERSION 3.0;\n",
                        Path(self.temp.name) / "old.3d")
        pane.editor.insertPlainText("% unsaved change\n")
        next_file = Path(self.temp.name) / "new.3do"
        with patch.object(self.window, "_busy", return_value=False), patch(
                "gpu_viewer.main.LoadWorker") as worker:
            self._interact(lambda: self.window.load(next_file),
                           "Discard changes", "Discard changes")
            worker.assert_called_once()
            worker.return_value.start.assert_called_once()
        self.assertFalse(pane.ready)
        self.assertFalse(pane.dirty)
        self.assertEqual(self.window.model_path, next_file)

    def test_close_cancel_keeps_editable_source(self):
        from PySide6.QtGui import QCloseEvent
        pane = self.window.source_pane
        pane.set_source("3D VERSION 3.0;\n",
                        Path(self.temp.name) / "old.3d")
        pane.editor.insertPlainText("% unsaved change\n")
        event = QCloseEvent()
        self._interact(lambda: self.window.closeEvent(event),
                       "Discard changes", "Cancel")
        self.assertFalse(event.isAccepted())
        self.assertTrue(pane.ready)
        self.assertTrue(pane.dirty)

    def test_overwrite_cancel_protects_original_then_explicitly_allows_save(self):
        original = Path(self.temp.name) / "original.3d"
        original.write_text("3D VERSION 3.0;\n", encoding="utf-8")
        pane = self.window.source_pane
        pane.set_source(original.read_text(encoding="utf-8"), original)
        pane.editor.insertPlainText("% new unsaved text\n")
        self.window._source_save_target = original
        result, _ = self._interact(
            lambda: self.window._save_source(),
            "Overwrite original", "Cancel")
        self.assertFalse(result)
        self.assertTrue(pane.dirty)
        self.assertEqual(original.read_text(encoding="utf-8"),
                         "3D VERSION 3.0;\n")
        result, _ = self._interact(
            lambda: self.window._save_source(),
            "Overwrite original", "Overwrite original")
        self.assertTrue(result)
        self.assertFalse(pane.dirty)
        self.assertEqual(original.read_text(encoding="utf-8"),
                         pane.get_source())


if __name__ == "__main__":
    unittest.main()
