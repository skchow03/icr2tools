"""Real Qt modifier-click and source Back navigation regression tests."""
import os
import sys
import unittest
from pathlib import Path

DISPLAY = bool(os.environ.get("DISPLAY") or
               os.environ.get("WAYLAND_DISPLAY") or
               sys.platform in ("win32", "darwin"))

SOURCE = """3D VERSION 3.0;
p: [<0,0,0>];
q: [<100,0,0>];
r: [<0,100,0>];
body_poly: POLY <49> {p,q,r};
branch: LIST {body_poly};
root: LIST {branch};
% body_poly and branch in comments must never navigate
mip: MATERIAL ("body_poly.mip", branch);
"""


@unittest.skipUnless(DISPLAY, "Requires desktop Qt or Xvfb")
class SourcePointerNavigationUITests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        try:
            from PySide6.QtCore import Qt, QPoint
            from PySide6.QtGui import QTextCursor
            from PySide6.QtTest import QTest
            from PySide6.QtWidgets import QApplication
            from source_tab import SourcePane
            from source_rename import qt_utf16_offset
        except (ImportError, SystemExit) as error:
            raise unittest.SkipTest(str(error))
        cls.Qt = Qt
        cls.QPoint = QPoint
        cls.QTextCursor = QTextCursor
        cls.QTest = QTest
        cls.utf16 = staticmethod(qt_utf16_offset)
        cls.app = QApplication.instance() or QApplication([])
        cls.pane = SourcePane()
        cls.pane.resize(1100, 700)
        cls.pane.show()
        cls.app.processEvents()

    @classmethod
    def tearDownClass(cls):
        cls.pane.reset()
        cls.pane.close()

    def setUp(self):
        self.pane.set_source(SOURCE, Path("navigation.3d"))
        self.app.processEvents()

    def click(self, line, text, modifier):
        editor = self.pane.editor
        block = editor.document().findBlockByNumber(line)
        row = block.text()
        start = row.index(text)
        end = start + len(text)
        first = self.QTextCursor(block)
        first.setPosition(block.position() + self.utf16(row, start))
        last = self.QTextCursor(block)
        last.setPosition(block.position() + self.utf16(row, end))
        editor.setTextCursor(first)
        editor.centerCursor()
        self.app.processEvents()
        a = editor.cursorRect(first)
        b = editor.cursorRect(last)
        self.assertGreater(b.x(), a.x(), text)
        pt = self.QPoint((a.x() + b.x()) // 2, a.center().y())
        self.QTest.mouseClick(
            editor.viewport(), self.Qt.MouseButton.LeftButton,
            modifier, pt)
        self.app.processEvents()

    def test_ctrl_click_follows_pointer_and_back_returns_to_reference(self):
        pane = self.pane
        original = pane.editor.toPlainText()
        self.assertFalse(pane.pointer_back_button.isEnabled())
        self.click(6, "branch", self.Qt.KeyboardModifier.ControlModifier)
        self.assertEqual(pane.editor.textCursor().selectedText(), "branch")
        self.assertEqual(pane.editor.textCursor().blockNumber(), 5)
        self.assertTrue(pane.pointer_back_button.isEnabled())
        self.click(5, "body_poly", self.Qt.KeyboardModifier.ShiftModifier)
        self.assertEqual(pane.editor.textCursor().selectedText(), "body_poly")
        self.assertEqual(pane.editor.textCursor().blockNumber(), 4)
        self.assertTrue(pane.go_back_pointer())
        self.assertEqual(pane.editor.textCursor().blockNumber(), 5)
        self.assertEqual(pane.editor.textCursor().selectedText(), "body_poly")
        pane.pointer_back_button.click()
        self.assertEqual(pane.editor.textCursor().blockNumber(), 6)
        self.assertEqual(pane.editor.textCursor().selectedText(), "branch")
        self.assertFalse(pane.pointer_back_button.isEnabled())
        self.assertEqual(pane.editor.toPlainText(), original)
        self.assertFalse(pane.dirty)

    def test_clicks_on_comments_strings_declarations_do_not_navigate(self):
        pane = self.pane
        for line, text in ((4, "body_poly"), (7, "body_poly"), (8, "body_poly.mip")):
            with self.subTest(line=line):
                self.click(line, text, self.Qt.KeyboardModifier.ControlModifier)
                self.assertFalse(pane.pointer_back_button.isEnabled())

    def test_back_history_clears_on_new_model_and_reset(self):
        pane = self.pane
        self.click(6, "branch", self.Qt.KeyboardModifier.ControlModifier)
        self.assertTrue(pane.pointer_back_button.isEnabled())
        pane.set_source("other: LIST {other};", Path("other.3d"))
        self.assertFalse(pane.pointer_back_button.isEnabled())
        self.assertFalse(pane.go_back_pointer())
        pane.reset()
        self.assertFalse(pane.pointer_back_button.isEnabled())


if __name__ == "__main__":
    unittest.main()
