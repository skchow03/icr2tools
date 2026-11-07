"""Qt regression tests for source-row highlights and opt-in mirror editing."""
import os
import sys
import unittest
from unittest.mock import patch

HAS_DISPLAY = bool(os.environ.get("DISPLAY") or os.environ.get("WAYLAND_DISPLAY")
                   or sys.platform in ("win32", "darwin"))

SOURCE = """3D VERSION 3.0;
left: [<100,20,30>, T=<12,34>];
right: [<-100,20,30>, T=<56,78>];
root: NIL;
"""


@unittest.skipUnless(HAS_DISPLAY, "Requires Qt desktop or Xvfb")
class N3SymmetryUITests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        try:
            from PySide6.QtWidgets import QApplication, QMessageBox, QInputDialog
            from PySide6.QtGui import QTextCursor
            from source_tab import SourcePane
        except (ImportError, SystemExit) as error:
            raise unittest.SkipTest(str(error))
        cls.app = QApplication.instance() or QApplication([])
        cls.SourcePane = SourcePane
        cls.QTextCursor = QTextCursor
        cls.QMessageBox = QMessageBox
        cls.QInputDialog = QInputDialog

    def setUp(self):
        self.pane = self.SourcePane()
        self.pane.set_source(SOURCE, "symmetry.3d")
        self.pane._debounce.stop()
        self.sent = []
        self.pane.compileRequested.connect(
            lambda rev, text: self.sent.append((rev, text)))
        self.assertFalse(self.pane.symmetry_enabled.isChecked())

    def tearDown(self):
        self.pane._debounce.stop()
        self.pane.close()
        self.pane.deleteLater()
        self.app.processEvents()

    def update_coord(self, old, new):
        editor = self.pane.editor
        source = editor.toPlainText()
        start = source.index(old)
        cursor = self.QTextCursor(editor.document())
        cursor.setPosition(start)
        cursor.setPosition(start+len(old),
                           self.QTextCursor.MoveMode.KeepAnchor)
        cursor.insertText(new)
        self.pane._debounce.stop()

    def test_vertex_green_highlight_and_polygon_styling(self):
        pane = self.pane
        row = pane.editor.document().findBlockByNumber(1)
        pane.editor.setTextCursor(self.QTextCursor(row))
        pane.set_polygon_visibility(True)
        self.assertEqual(pane.current_target(), ("vertex", "left"))
        marks = pane.editor.extraSelections()
        self.assertTrue(marks)
        self.assertEqual(
            marks[-1].format.background().color().name(),
            pane.colors["source_visible_background"].lower())
        self.assertEqual(marks[-1].cursor.blockNumber(), 1)
        # Switching to another unrelated row clears the vertex highlight.
        other = pane.editor.document().findBlockByNumber(3)
        pane.editor.setTextCursor(self.QTextCursor(other))
        self.assertFalse(pane.editor.extraSelections())
        self.assertEqual(pane.symmetry_plane.currentData(), "X")

    def test_default_off_leaves_the_other_side_alone(self):
        self.update_coord("<100,20,30>", "<150,20,40>")
        self.pane.apply_now()
        self.assertIn("right: [<-100,20,30>", self.sent[-1][1])

    def test_automatic_mirror_is_one_undo_with_existing_edit(self):
        pane = self.pane
        pane.symmetry_enabled.setChecked(True)
        self.update_coord("<100,20,30>", "<145,23,41>")
        pane.apply_now()
        self.assertIn("right: [<-145,23,41>, T=<56,78>]", self.sent[-1][1])
        self.assertIn("left: [<145,23,41>, T=<12,34>]", self.sent[-1][1])
        self.assertIn("right: [<-145,23,41>", pane.editor.toPlainText())
        self.assertIn("Mirrored XYZ", pane.change_log.toPlainText())
        pane.editor.undo()
        self.assertEqual(pane.editor.toPlainText(), SOURCE)

    def test_missing_match_notifies_and_keeps_independent_vertex(self):
        self.pane.symmetry_enabled.setChecked(True)
        self.pane.symmetry_plane.setCurrentIndex(
            self.pane.symmetry_plane.findData("Z"))
        self.update_coord("<100,20,30>", "<111,24,32>")
        with patch.object(self.QMessageBox, "warning") as warning:
            self.pane.apply_now()
        warning.assert_called_once()
        self.assertIn("right: [<-100,20,30>", self.sent[-1][1])
        self.assertIn("no mirrored vertex", self.pane.change_log.toPlainText())

    def test_duplicate_coordinates_require_user_choice_and_preserve_uv(self):
        duplicate = SOURCE.replace(
            "root: NIL;", "alternate: [<-100,20,30>, T=<91,92>];\nroot: NIL;")
        self.pane.set_source(duplicate, "symmetry.3d")
        self.pane.symmetry_enabled.setChecked(True)
        self.update_coord("<100,20,30>", "<125,66,-80>")
        with patch.object(
                self.QInputDialog, "getItem",
                return_value=("alternate — source line 4: -100, 20, 30", True)
                ) as choice:
            self.pane.apply_now()
        choice.assert_called_once()
        result = self.sent[-1][1]
        self.assertIn("alternate: [<-125,66,-80>, T=<91,92>]", result)
        self.assertIn("right: [<-100,20,30>, T=<56,78>]", result)

    def test_mode_off_again_and_reset_on_new_model(self):
        pane = self.pane
        pane.symmetry_enabled.setChecked(True)
        pane.symmetry_plane.setCurrentIndex(
            pane.symmetry_plane.findData("Y"))
        pane.symmetry_plane_at.setValue(123)
        self.assertTrue(pane.symmetry_plane.isEnabled())
        pane.set_source(SOURCE, "another_model.3d")
        self.assertFalse(pane.symmetry_enabled.isChecked())
        self.assertFalse(pane.symmetry_plane.isEnabled())
        self.assertEqual(pane._symmetry_baseline, SOURCE)


if __name__ == "__main__":
    unittest.main()
