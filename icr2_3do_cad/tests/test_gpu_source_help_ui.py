"""Qt interaction: live N3 command hints, tooltips and filtered inline editing."""
import os
import sys
import unittest
from pathlib import Path

HAS_DISPLAY = bool(os.environ.get("DISPLAY") or
                   os.environ.get("WAYLAND_DISPLAY") or
                   sys.platform in ("win32", "darwin"))

SOURCE = """3D VERSION 3.0;
p0: [<0,0,0>, T=<0,0>];
p1: [<100,0,0>, T=<50,0>];
p2: [<0,100,0>, T=<0,50>];
panel: POLY [T] <44>
    {p0,p1,p2};
node: BSPF (p0,
    p1, p2), NIL, panel, NIL;
root: LIST {node};
"""


@unittest.skipUnless(HAS_DISPLAY, "Requires Qt desktop or Xvfb")
class N3ContextHelpQtTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        try:
            from PySide6.QtWidgets import QApplication
            from gpu_viewer.source_tab import SourcePane
        except (ImportError, SystemExit) as exc:
            raise unittest.SkipTest(str(exc))
        cls.app = QApplication.instance() or QApplication([])
        cls.pane = SourcePane()
        cls.pane.resize(920, 680)
        cls.pane.show()
        cls.app.processEvents()

    @classmethod
    def tearDownClass(cls):
        cls.pane.reset()
        cls.pane.close()

    def setUp(self):
        self.pane.set_source(SOURCE, Path("help_example.3d"))
        self.pane._show_all_filters()
        self.pane._debounce.stop()
        self.app.processEvents()

    def tearDown(self):
        from PySide6.QtWidgets import QToolTip
        QToolTip.hideText()
        self.pane._debounce.stop()
        self.pane._rename_timer.stop()
        self.pane._show_all_filters()
        self.pane.set_source(SOURCE, Path("help_example.3d"))

    def _line(self, number):
        from PySide6.QtGui import QTextCursor
        block = self.pane.editor.document().findBlockByNumber(number)
        self.pane.editor.setTextCursor(QTextCursor(block))
        self.app.processEvents()

    def test_live_hint_tracks_multiline_and_typed_commands_without_edit(self):
        pane = self.pane
        revision = pane.revision
        self._line(4)
        self.assertIn("POLY [T]", pane.syntax_help.text())
        self.assertIn("Syntax:", pane.syntax_help.text())
        self._line(5)
        self.assertIn("POLY [T]", pane.syntax_help.text())
        self._line(6)
        self.assertIn("BSPF", pane.syntax_help.text())
        self._line(7)
        self.assertIn("BSPF", pane.syntax_help.text())
        self._line(8)
        self.assertIn("LIST", pane.syntax_help.text())
        self._line(1)
        self.assertIn("Vertex", pane.syntax_help.text())
        self._line(0)
        self.assertIn("3D VERSION", pane.syntax_help.text())
        self.assertEqual(pane.get_source(), SOURCE)
        self.assertEqual(pane.revision, revision)
        self.assertFalse(pane.dirty)
        self.assertFalse(pane.pending)

    def test_tooltip_by_hover_and_explicit_shortcut_is_read_only(self):
        from PySide6.QtCore import QEvent, QPoint, Qt
        from PySide6.QtGui import QHelpEvent
        from PySide6.QtTest import QTest
        from PySide6.QtWidgets import QToolTip
        pane = self.pane
        self._line(6)
        revision = pane.revision
        pane.editor.setFocus()
        pane.show_syntax_help()
        self.assertIn("BSPF", QToolTip.text())
        self.assertIn("child1, child2, child3", QToolTip.text())
        QToolTip.hideText()
        QTest.keyClick(pane.editor, Qt.Key.Key_Space,
                       Qt.KeyboardModifier.ControlModifier |
                       Qt.KeyboardModifier.ShiftModifier)
        self.app.processEvents()
        self.assertIn("BSPF", QToolTip.text())
        QToolTip.hideText()
        # Simulate a hover over the BSP keyword on its first source line.
        point = pane.editor.cursorRect().center()
        hover = QHelpEvent(
            QEvent.Type.ToolTip, point,
            pane.editor.viewport().mapToGlobal(point))
        self.app.sendEvent(pane.editor.viewport(), hover)
        self.assertIn("BSPF", QToolTip.text())
        self.assertEqual(pane.get_source(), SOURCE)
        self.assertEqual(pane.revision, revision)
        self.assertFalse(pane.pending)

    def test_filtered_rows_have_tooltip_and_inline_edit_help(self):
        from PySide6.QtCore import Qt
        from PySide6.QtWidgets import QPlainTextEdit
        from PySide6.QtTest import QTest

        pane = self.pane
        pane._only_filter("BSP")
        self.app.processEvents()
        self.assertEqual(len(pane.filtered_model.entries), 1)
        index = pane.filtered_model.index(0)
        pane.filtered_list.setCurrentIndex(index)
        self.app.processEvents()
        self.assertIn("BSPF", pane.syntax_help.text())
        info = pane.filtered_model.data(index, Qt.ItemDataRole.ToolTipRole)
        self.assertIn("Syntax:", info)
        self.assertIn("partition", info.lower())
        pane.filtered_list.edit(index)
        self.app.processEvents()
        editor = next(x for x in
                      pane.filtered_list.findChildren(QPlainTextEdit)
                      if x.isVisible())
        self.assertIn("BSPF", pane.syntax_help.text())
        editor.setPlainText(
            "node: MATERIAL MIP=\"face\", GROUP=4, panel;")
        self.app.processEvents()
        self.assertIn("MATERIAL", pane.syntax_help.text())
        self.assertEqual(pane.get_source(), SOURCE)
        self.assertFalse(pane.dirty)
        # Escape reverts the filtered edit without modifying canonical text.
        QTest.keyClick(editor, Qt.Key.Key_Escape)
        self.app.processEvents()
        self.assertEqual(pane.get_source(), SOURCE)
        self.assertFalse(pane.dirty)

    def test_partially_typed_commands_update_help_without_compile(self):
        pane = self.pane
        self._line(8)
        cursor = pane.editor.textCursor()
        cursor.movePosition(cursor.MoveOperation.EndOfBlock)
        pane.editor.setTextCursor(cursor)
        pane.editor.insertPlainText("\nnewname: SWITCH")
        self.app.processEvents()
        pane._debounce.stop()
        self.assertIn("SWITCH DISTANCE", pane.syntax_help.text())
        self.assertTrue(pane.pending)
        self.assertIn("newname: SWITCH", pane.get_source())
        # The hint is guidance only; it does not request another compilation.
        revision = pane.revision
        pane._update_syntax_help()
        self.assertEqual(pane.revision, revision)

    def test_help_reverts_on_source_reset_and_preserves_selection_workflow(self):
        pane = self.pane
        self._line(7)
        self.assertIn("BSPF", pane.syntax_help.text())
        pane.reset()
        self.assertIn("N3 help", pane.syntax_help.text())
        self.assertFalse(pane.ready)
        pane.show_syntax_help()
        self.assertFalse(pane.pending)
        pane.set_source(SOURCE, Path("help_example.3d"))
        self._line(4)
        self.assertIn("POLY [T]", pane.syntax_help.text())


if __name__ == "__main__":
    unittest.main()
