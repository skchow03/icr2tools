"""Qt source-editor rename and colored-row regressions (Xvfb/desktop)."""
import os
import sys
import unittest
from pathlib import Path

DISPLAY = bool(os.environ.get("DISPLAY") or os.environ.get("WAYLAND_DISPLAY")
               or sys.platform in ("win32", "darwin"))

SOURCE = """3D VERSION 3.0;
% front is a comment, not a reference
front: [<0,0,0>];
right: [<100,0,0>];
top: [<0,100,0>];
panel: POLY <44>
  {front, right, top};
face: FACE (front,right,top), panel;
root: LIST {face, panel};
% MIP "front" remains untouched
"""


@unittest.skipUnless(DISPLAY, "Qt source editor needs a display or Xvfb")
class SourceEditorRenameUITests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        try:
            from PySide6.QtWidgets import QApplication
            from gpu_viewer.source_tab import SourcePane
        except (ImportError, SystemExit) as exc:
            raise unittest.SkipTest(f"Qt dependencies unavailable: {exc}")
        cls.app = QApplication.instance() or QApplication([])
        cls.pane = SourcePane()

    def setUp(self):
        self.pane.set_source(SOURCE, Path("labels.3d"))
        self.pane.auto_rename.setChecked(True)

    @classmethod
    def tearDownClass(cls):
        cls.pane.close()

    def rename_label(self, line, name):
        from PySide6.QtGui import QTextCursor
        block = self.pane.editor.document().findBlockByNumber(line)
        cursor = QTextCursor(block)
        cursor.movePosition(QTextCursor.MoveOperation.Right,
                            QTextCursor.MoveMode.KeepAnchor,
                            len(block.text().split(":", 1)[0]))
        self.pane.editor.setTextCursor(cursor)
        self.pane.editor.insertPlainText(name)
        self.pane._rename_timer.stop()
        self.pane._commit_pending_rename()

    def test_default_rename_propagates_only_symbol_references(self):
        self.assertTrue(self.pane.auto_rename.isChecked())
        self.rename_label(2, "nose")
        text = self.pane.get_source()
        self.assertIn("nose: [<0,0,0>];", text)
        self.assertIn("{nose, right, top};", text)
        self.assertIn("FACE (nose,right,top)", text)
        self.assertIn("% front is a comment", text)
        self.assertIn('% MIP "front"', text)
        self.assertTrue(self.pane.pending)
        history = self.pane.change_log.toPlainText()
        self.assertIn("Auto-rename references: front → nose", history)
        self.assertIn("2 references updated", history)
        self.assertIn("line 7: front → nose", history)
        self.assertIn("line 8: front → nose", history)
        self.assertNotIn("line 2: front → nose", history)

    def test_renaming_poly_changes_both_references(self):
        self.rename_label(5, "wing")
        self.assertIn("wing: POLY <44>", self.pane.get_source())
        self.assertIn("FACE (front,right,top), wing;", self.pane.get_source())
        self.assertIn("LIST {face, wing};", self.pane.get_source())

    def test_disabling_auto_rename_preserves_old_references(self):
        self.pane.auto_rename.setChecked(False)
        self.rename_label(2, "nose")
        self.assertIn("nose: [<0,0,0>];", self.pane.get_source())
        self.assertIn("{front, right, top};", self.pane.get_source())
        self.assertEqual(self.pane._rename_pending, None)
        self.assertEqual(self.pane.change_log.toPlainText(), "")

    def test_collision_does_not_rewrite_other_declarations(self):
        self.rename_label(2, "right")
        text = self.pane.get_source()
        self.assertIn("right: [<0,0,0>]", text)
        self.assertIn("right: [<100,0,0>]", text)
        self.assertIn("{front, right, top}", text)
        self.assertEqual(self.pane.change_log.toPlainText(), "")

    def test_change_log_is_four_rows_tall_and_clearable_without_edits(self):
        from PySide6.QtWidgets import QPushButton
        pane = self.pane
        height = pane.change_log.height()
        row = pane.change_log.fontMetrics().lineSpacing()
        self.assertGreaterEqual(height, row * 4)
        self.assertLess(height, row * 6)
        self.assertTrue(pane.change_log.isReadOnly())
        self.assertEqual(pane.change_log.objectName(), "automaticSourceChangeLog")
        self.rename_label(2, "nose")
        old_source = pane.get_source()
        old_revision = pane.revision
        clear = next(button for button in pane.findChildren(QPushButton)
                     if button.text() == "Clear log")
        clear.click()
        self.assertEqual(pane.change_log.toPlainText(), "")
        self.assertEqual(pane.get_source(), old_source)
        self.assertEqual(pane.revision, old_revision)

    def test_log_survives_compile_and_save_but_resets_for_a_new_file(self):
        pane = self.pane
        self.rename_label(5, "wing")
        history = pane.change_log.toPlainText()
        self.assertIn("panel → wing", history)
        from types import SimpleNamespace
        pane.mark_valid(pane.revision, SimpleNamespace(
            vertices={1: object()}, polygons={1: object()}))
        pane.mark_saved()
        self.assertEqual(pane.change_log.toPlainText(), history)
        pane.set_source(SOURCE, Path("other.3d"))
        self.assertEqual(pane.change_log.toPlainText(), "")
        self.assertFalse(pane.dirty)
        self.assertFalse(pane.pending)

    def test_ordinary_typing_does_not_log_programmatic_rewrites(self):
        pane = self.pane
        pane.editor.moveCursor(pane.editor.textCursor().MoveOperation.End)
        pane.editor.insertPlainText("% ordinary user comment")
        self.assertEqual(pane.change_log.toPlainText(), "")

    def test_visibility_colors_multiline_poly_and_clears(self):
        from PySide6.QtGui import QTextCursor
        block = self.pane.editor.document().findBlockByNumber(5)
        self.pane.editor.setTextCursor(QTextCursor(block))
        self.assertEqual(self.pane.current_target(), ("polygon", "panel"))
        for visible, expected in (
                (True, self.pane.colors["source_visible_background"].lower()),
                (False, self.pane.colors["source_hidden_background"].lower())):
            self.pane.set_polygon_visibility(visible)
            selections = self.pane.editor.extraSelections()
            self.assertEqual(len(selections), 2)
            self.assertEqual(
                [x.cursor.blockNumber() for x in selections], [5, 6])
            self.assertTrue(all(
                x.format.background().color().name() == expected
                for x in selections))
        self.pane.set_polygon_visibility(None)
        self.assertEqual(self.pane.editor.extraSelections(), [])


if __name__ == "__main__":
    unittest.main()
