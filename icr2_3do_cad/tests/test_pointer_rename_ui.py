"""Qt F2 pointer rename shortcut in full and inline-filtered N3 Source."""
import os
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

HAS_DISPLAY = bool(os.environ.get("DISPLAY") or
                   os.environ.get("WAYLAND_DISPLAY") or
                   sys.platform in ("win32", "darwin"))

SOURCE = """3D VERSION 3.0;
% pointer panel, 📌; preserve this comment
a: [<0,0,0>];
b: [<100,0,0>];
c: [<0,100,0>];
panel: POLY <44>
  {a, b, c};
face: FACE (a,b,c), panel;
root: LIST {face, panel};
% "panel" stays quoted
"""


@unittest.skipUnless(HAS_DISPLAY, "Qt requires a desktop or Xvfb")
class F2PointerRenameQtTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        try:
            from PySide6.QtWidgets import QApplication
            from source_tab import SourcePane
        except (ImportError, SystemExit) as exc:
            raise unittest.SkipTest(f"Qt dependencies unavailable: {exc}")
        cls.app = QApplication.instance() or QApplication([])
        cls.pane = SourcePane()

    def setUp(self):
        self.pane._show_all_filters()
        self.pane.set_source(SOURCE, Path("f2.3d"))
        self.pane.auto_rename.setChecked(True)
        self.pane.show()
        self.app.processEvents()

    def tearDown(self):
        self.pane._debounce.stop()
        self.pane._rename_timer.stop()
        self.pane.hide()
        self.app.processEvents()

    @classmethod
    def tearDownClass(cls):
        cls.pane.close()

    def go_to_line(self, n):
        from PySide6.QtGui import QTextCursor
        block = self.pane.editor.document().findBlockByNumber(n)
        self.pane.editor.setTextCursor(QTextCursor(block))

    def send_f2(self, widget, name):
        from PySide6.QtCore import Qt
        from PySide6.QtTest import QTest
        widget.setFocus()
        self.app.processEvents()
        with patch("source_tab.QInputDialog.getText",
                   return_value=(name, True)) as prompt:
            QTest.keyClick(widget, Qt.Key.Key_F2)
            self.app.processEvents()
            prompt.assert_called_once()

    def test_f2_on_multiline_poly_continuation_in_full_editor(self):
        pane = self.pane
        self.go_to_line(6)  # continuation, not the POLY label itself
        self.send_f2(pane.editor, "wing")
        expected = SOURCE.replace("panel: POLY", "wing: POLY").replace(
            "), panel;", "), wing;").replace("{face, panel}", "{face, wing}")
        self.assertEqual(pane.get_source(), expected)
        self.assertIn("  {a, b, c};", pane.get_source())
        self.assertIn('📌', pane.get_source())
        self.assertTrue(pane.pending)
        self.assertTrue(pane.dirty)
        self.assertEqual(pane._rename_pending, None)
        history = pane.change_log.toPlainText()
        self.assertIn("F2 pointer rename: panel → wing", history)
        self.assertIn("2 references updated", history)
        self.assertIn("line 8: panel → wing", history)
        self.assertIn("line 9: panel → wing", history)
        self.assertNotIn("line 6: panel → wing", history)

    def test_f2_in_filtered_list_renames_without_exiting_filter(self):
        pane = self.pane
        pane._only_filter("POLY")
        index = pane.filtered_model.index(0)
        pane.filtered_list.setCurrentIndex(index)
        self.send_f2(pane.filtered_list, "new_panel")
        self.assertIs(pane.source_stack.currentWidget(), pane.filtered_page)
        self.assertTrue(pane._filter_checks["POLY"].isChecked())
        self.assertEqual(len(pane.filtered_model.entries), 1)
        self.assertIn("new_panel: POLY <44>", pane.get_source())
        self.assertIn("face: FACE (a,b,c), new_panel;", pane.get_source())
        self.assertIn("root: LIST {face, new_panel};", pane.get_source())
        self.assertIn("% pointer panel", pane.get_source())
        self.assertIn('"panel" stays quoted', pane.get_source())

    def test_f2_respects_disabled_auto_reference_rename(self):
        pane = self.pane
        pane.auto_rename.setChecked(False)
        pane._only_filter("POLY")
        pane.filtered_list.setCurrentIndex(pane.filtered_model.index(0))
        self.send_f2(pane.filtered_list, "panel_two")
        self.assertEqual(
            pane.get_source(), SOURCE.replace(
                "panel: POLY", "panel_two: POLY"))
        self.assertEqual(pane._rename_pending, None)
        self.assertIs(pane.source_stack.currentWidget(), pane.filtered_page)
        self.assertIn("0 references updated", pane.change_log.toPlainText())

    def test_f2_name_only_undo_is_one_step(self):
        pane = self.pane
        self.go_to_line(5)
        pane._apply_pointer_rename(5, "wing")
        self.assertNotEqual(pane.get_source(), SOURCE)
        pane.editor.undo()
        self.assertEqual(pane.get_source(), SOURCE)

    def test_f2_rejects_invalid_and_collision_without_mutation(self):
        pane = self.pane
        self.go_to_line(5)
        old_revision = pane.revision
        for value in ("a", "POLY", "bad label", "99thing"):
            with self.subTest(value=value), patch(
                    "source_tab.QInputDialog.getText",
                    return_value=(value, True)), patch(
                    "source_tab.QMessageBox.warning") as warning:
                pane.rename_selected_pointer()
                warning.assert_called_once()
                self.assertEqual(pane.get_source(), SOURCE)
                self.assertEqual(pane.revision, old_revision)
        self.assertFalse(pane.dirty)
        self.assertFalse(pane.pending)
        self.assertEqual(pane.change_log.toPlainText(), "")

    def test_f2_on_comment_does_not_prompt_or_change_source(self):
        pane = self.pane
        self.go_to_line(1)
        with patch("source_tab.QInputDialog.getText") as prompt:
            pane.rename_selected_pointer()
            prompt.assert_not_called()
        self.assertIn("Select a named N3 declaration", pane.status.text())
        self.assertEqual(pane.get_source(), SOURCE)

    def test_cancel_prompt_keeps_full_document_unchanged(self):
        pane = self.pane
        self.go_to_line(5)
        with patch("source_tab.QInputDialog.getText",
                   return_value=("new_panel", False)):
            pane.rename_selected_pointer()
        self.assertEqual(pane.get_source(), SOURCE)
        self.assertFalse(pane.pending)


if __name__ == "__main__":
    unittest.main()
