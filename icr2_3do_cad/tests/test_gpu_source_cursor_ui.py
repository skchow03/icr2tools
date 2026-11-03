"""Qt source-to-viewport cursor inspection tests (requires Xvfb/desktop)."""
import os
import sys
import unittest
from pathlib import Path

from n3_compile import compile_n3_text

HAS_DISPLAY = bool(os.environ.get("DISPLAY") or
                   os.environ.get("WAYLAND_DISPLAY") or
                   sys.platform in ("win32", "darwin"))

SOURCE = """3D VERSION 3.0;
a: [<0,0,0>];
b: [<100,0,0>];
c: [<0,100,0>];
surface: POLY <32> {a,b,c};
root: LIST {surface};
"""


@unittest.skipUnless(HAS_DISPLAY, "Requires a desktop or xvfb-run")
class GPUCursorUITests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        try:
            from PySide6.QtWidgets import QApplication
            from gpu_viewer.main import Window
        except (ImportError, SystemExit) as error:
            raise unittest.SkipTest(f"GPU viewer dependencies unavailable: {error}")
        cls.app = QApplication.instance() or QApplication([])
        cls.window = Window()
        cls.model, _ = compile_n3_text(SOURCE, "example.3d",
                                       associate_planes=False)
        cls.window.viewer._model = cls.model
        cls.pane = cls.window.source_pane
        cls.pane.set_source(SOURCE, Path("example.3d"))
        cls.window.source_toggle.setChecked(True)

    @classmethod
    def tearDownClass(cls):
        cls.window.close()

    def move_to_line(self, line):
        from PySide6.QtGui import QTextCursor
        block = self.pane.editor.document().findBlockByNumber(line)
        self.assertTrue(block.isValid())
        self.pane.editor.setTextCursor(QTextCursor(block))

    def test_polygon_and_vertex_cursor_targets(self):
        self.move_to_line(4)
        self.assertEqual(self.window.viewer.inspection_kind, "polygon")
        self.assertEqual(
            self.window.viewer.inspection_offset,
            self.model.n3_label_offsets["surface"])
        self.move_to_line(2)
        self.assertEqual(self.window.viewer.inspection_kind, "vertex")
        self.assertEqual(
            self.window.viewer.inspection_offset,
            self.model.n3_label_offsets["b"])
        self.move_to_line(5)
        self.assertIsNone(self.window.viewer.inspection_kind)
        self.move_to_line(0)
        self.assertIsNone(self.window.viewer.inspection_offset)

    def test_unvalidated_source_clears_overlay_until_valid_again(self):
        self.move_to_line(4)
        self.assertEqual(self.window.viewer.inspection_kind, "polygon")
        # Whitespace-only edit makes source pending but keeps parse semantics.
        self.pane.editor.insertPlainText(" ")
        self.assertTrue(self.pane.pending)
        self.assertIsNone(self.window.viewer.inspection_kind)
        self.pane._debounce.stop()
        self.pane.mark_valid(self.pane.revision, self.model)
        self.assertFalse(self.pane.pending)
        self.assertEqual(self.window.viewer.inspection_kind, "polygon")
        self.pane.mark_error(self.pane.revision, "line 5: bad source")
        self.assertIsNone(self.window.viewer.inspection_kind)

    def test_closed_source_hides_inspection(self):
        # Revert to validated editor state for this test.
        self.pane.set_source(SOURCE, Path("example.3d"))
        self.move_to_line(1)
        self.assertEqual(self.window.viewer.inspection_kind, "vertex")
        self.window.source_toggle.setChecked(False)
        self.assertIsNone(self.window.viewer.inspection_kind)
        self.window.source_toggle.setChecked(True)
        self.assertEqual(self.window.viewer.inspection_kind, "vertex")


if __name__ == "__main__":
    unittest.main()
