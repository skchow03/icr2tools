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

    def test_collision_does_not_rewrite_other_declarations(self):
        self.rename_label(2, "right")
        text = self.pane.get_source()
        self.assertIn("right: [<0,0,0>]", text)
        self.assertIn("right: [<100,0,0>]", text)
        self.assertIn("{front, right, top}", text)

    def test_visibility_colors_multiline_poly_and_clears(self):
        from PySide6.QtGui import QTextCursor
        block = self.pane.editor.document().findBlockByNumber(5)
        self.pane.editor.setTextCursor(QTextCursor(block))
        self.assertEqual(self.pane.current_target(), ("polygon", "panel"))
        for visible, expected in ((True, "#b5e3bb"), (False, "#f1ada1")):
            self.pane.set_polygon_visibility(visible)
            selections = self.pane.editor.extraSelections()
            self.assertEqual(len(selections), 3)
            self.assertEqual(
                [x.cursor.blockNumber() for x in selections], [5, 6, 5])
            self.assertTrue(all(
                x.format.background().color().name() == expected
                for x in selections[:2]))
            self.assertLess(selections[-1].format.background().color().alpha(), 255)
        self.pane.set_polygon_visibility(None)
        self.assertEqual(
            [x.cursor.blockNumber()
             for x in self.pane.editor.extraSelections()], [5])


if __name__ == "__main__":
    unittest.main()
