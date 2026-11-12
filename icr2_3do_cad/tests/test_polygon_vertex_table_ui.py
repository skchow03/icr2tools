"""Qt smoke test: selected-POLY table below viewport updates canonical N3."""
import os
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

DISPLAY = bool(os.environ.get("DISPLAY") or
               os.environ.get("WAYLAND_DISPLAY") or
               sys.platform in ("win32", "darwin"))

SOURCE = """3D VERSION 3.0;
a: [<0,0,0>, T=<10,20>];
b: [<100,0,0>, T=<30,40>];
c: [<0,100,0>, T=<50,60>];
paint: POLY [T] <49> {a,b,c};
root: LIST {paint};
"""


@unittest.skipUnless(DISPLAY, "Requires Qt desktop or Xvfb")
class PolygonVertexTableUITests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        try:
            from PySide6.QtWidgets import QApplication
            from PySide6.QtGui import QTextCursor
            from PySide6.QtCore import Qt
            from icr2_3do_cad import Window
            from n3_compile import compile_n3_text
        except (ImportError, SystemExit) as exc:
            raise unittest.SkipTest(str(exc))
        cls.Qt = Qt
        cls.QTextCursor = QTextCursor
        cls.app = QApplication.instance() or QApplication([])
        cls.window = Window()
        cls.model, _ = compile_n3_text(
            SOURCE, "poly_ui.3d", associate_planes=False)

    @classmethod
    def tearDownClass(cls):
        cls.window.source_pane.reset()
        cls.window.close()

    def setUp(self):
        window = self.window
        window._source_invalid = False
        window.viewer._model = self.model
        window.source_pane.set_source(SOURCE, Path("poly_ui.3d"))
        window.source_pane._debounce.stop()
        block = window.source_pane.editor.document().findBlockByNumber(4)
        window.source_pane.editor.setTextCursor(self.QTextCursor(block))
        window._source_target_changed(("polygon", "paint"))

    def tearDown(self):
        self.window.source_pane._debounce.stop()

    def test_table_below_viewport_shows_polygon_vertices(self):
        window = self.window
        table = window.poly_vertex_table
        self.assertIs(window.poly_vertex_panel.parentWidget(),
                      window.viewport_panel)
        self.assertIs(
            window.viewport_layout.itemAt(3).widget(),
            window.poly_vertex_panel)
        self.assertFalse(window.poly_vertex_panel.isHidden())
        self.assertEqual(table.rowCount(), 3)
        self.assertEqual(table.columnCount(), 6)
        self.assertEqual(
            [table.item(0, i).text() for i in range(6)],
            ["a", "0", "0", "0", "10", "20"])
        self.assertFalse(bool(
            table.item(0, 0).flags() &
            self.Qt.ItemFlag.ItemIsEditable))
        self.assertTrue(bool(
            table.item(0, 5).flags() &
            self.Qt.ItemFlag.ItemIsEditable))

    def test_edit_uv_flows_into_source_as_one_undo_step(self):
        window = self.window
        pane = window.source_pane
        before = pane.editor.toPlainText()
        origin = pane.editor.textCursor().position()
        with patch.object(pane, "apply_now") as apply:
            window.poly_vertex_table.item(0, 4).setText("64")
        self.assertEqual(apply.call_count, 1)
        self.assertIn("a: [<0,0,0>, T=<64,20>];", pane.editor.toPlainText())
        self.assertTrue(pane.pending)
        self.assertTrue(pane.dirty)
        self.assertFalse(window.poly_vertex_table.isEnabled())
        self.assertEqual(pane.editor.textCursor().position(), origin)
        pane.editor.undo()
        self.assertEqual(pane.editor.toPlainText(), before)

    def test_edit_xyz_preserves_neighboring_source_and_undo(self):
        window = self.window
        pane = window.source_pane
        with patch.object(pane, "apply_now") as apply:
            window.poly_vertex_table.item(1, 1).setText("125")
        apply.assert_called_once()
        self.assertIn("b: [<125,0,0>, T=<30,40>];",
                      pane.editor.toPlainText())
        self.assertIn("a: [<0,0,0>, T=<10,20>];",
                      pane.editor.toPlainText())
        pane.editor.undo()
        self.assertEqual(pane.editor.toPlainText(), SOURCE)

    def test_invalid_cell_is_reverted_without_source_change(self):
        window = self.window
        pane = window.source_pane
        with patch("icr2_3do_cad.QMessageBox.warning") as warning:
            window.poly_vertex_table.item(0, 4).setText("70000")
        warning.assert_called_once()
        self.assertEqual(window.poly_vertex_table.item(0, 4).text(), "10")
        self.assertEqual(pane.editor.toPlainText(), SOURCE)
        self.assertFalse(pane.pending)

    def test_columns_fit_long_pointer_names_and_remain_resizable(self):
        from PySide6.QtWidgets import QHeaderView
        from n3_compile import compile_n3_text

        long_name = "front_left_top_outer_texture_mapping_vertex_123456"
        source = SOURCE.replace("a:", f"{long_name}:").replace(
            "{a,b,c}", f"{{{long_name},b,c}}")
        model, _ = compile_n3_text(
            source, "poly_long_names.3d", associate_planes=False)
        window = self.window
        window.viewer._model = model
        window.source_pane.set_source(source, Path("poly_long_names.3d"))
        window.source_pane._debounce.stop()
        block = window.source_pane.editor.document().findBlockByNumber(4)
        window.source_pane.editor.setTextCursor(self.QTextCursor(block))
        window._source_target_changed(("polygon", "paint"))

        table = window.poly_vertex_table
        header = table.horizontalHeader()
        self.assertEqual(table.item(0, 0).text(), long_name)
        for column in range(table.columnCount()):
            self.assertEqual(
                header.sectionResizeMode(column),
                QHeaderView.ResizeMode.Interactive)
            self.assertGreaterEqual(
                table.columnWidth(column), table.sizeHintForColumn(column))
        self.assertEqual(
            table.horizontalScrollBarPolicy(),
            self.Qt.ScrollBarPolicy.ScrollBarAsNeeded)

        header.resizeSection(0, 160)
        self.assertEqual(header.sectionSize(0), 160)
        # Repeated selection of the same POLY does not undo a manual width.
        window._refresh_polygon_vertex_table(("polygon", "paint"))
        self.assertEqual(header.sectionSize(0), 160)

    def test_non_polygon_selection_hides_table(self):
        self.window._source_target_changed(("vertex", "a"))
        self.assertTrue(self.window.poly_vertex_panel.isHidden())


if __name__ == "__main__":
    unittest.main()
