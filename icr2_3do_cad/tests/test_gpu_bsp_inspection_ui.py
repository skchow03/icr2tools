"""Qt selection routing for BSP 3-tuple viewport winding inspection."""
import os
import sys
import unittest
from pathlib import Path

from n3_compile import compile_n3_text

DISPLAY = bool(os.environ.get("DISPLAY") or os.environ.get("WAYLAND_DISPLAY")
               or sys.platform in ("win32", "darwin"))

SOURCE = """3D VERSION 3.0;
a: [<0,0,0>];
b: [<1000,0,0>];
c: [<0,1000,0>];
p1: [<0,0,500>];
p2: [<1000,0,500>];
p3: [<0,1000,500>];
panel: POLY <44> {a,b,c};
split: BSPF (p1, p2, p3), NIL, panel, NIL;
root: LIST {split};
"""


@unittest.skipUnless(DISPLAY, "Requires Qt desktop / Xvfb")
class BSPSourceSelectionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        try:
            from PySide6.QtWidgets import QApplication
            from gpu_viewer.main import Window
        except (ImportError, SystemExit) as exc:
            raise unittest.SkipTest(str(exc))
        cls.app = QApplication.instance() or QApplication([])
        cls.window = Window()
        cls.pane = cls.window.source_pane
        cls.model, _ = compile_n3_text(
            SOURCE, "bsp_selection.3d", associate_planes=False)
        cls.window.viewer._model = cls.model
        cls.window.source_toggle.setChecked(True)

    @classmethod
    def tearDownClass(cls):
        cls.pane.reset()
        cls.window.close()

    def setUp(self):
        self.pane._show_all_filters()
        self.pane.set_source(SOURCE, Path("bsp_selection.3d"))

    def tearDown(self):
        self.pane._debounce.stop()
        self.pane._rename_timer.stop()
        self.pane.reset()

    def go_to(self, line):
        from PySide6.QtGui import QTextCursor
        block = self.pane.editor.document().findBlockByNumber(line)
        self.pane.editor.setTextCursor(QTextCursor(block))

    def test_bsp_selects_three_ordered_points_distinct_from_vertex(self):
        self.go_to(8)
        viewport = self.window.viewer
        self.assertEqual(self.pane.current_target(), ("bsp", "split"))
        self.assertEqual(viewport.inspection_kind, "bsp")
        self.assertIsNone(viewport.inspection_offset)
        self.assertEqual(viewport.inspection_points,
                         ((0., 0., 500.), (1000., 0., 500.),
                          (0., 1000., 500.)))
        colors = viewport.colors
        self.assertNotEqual(colors["viewport_bsp_vertex"],
                            colors["viewport_vertex_dot"])
        self.go_to(2)
        self.assertEqual(viewport.inspection_kind, "vertex")
        self.assertIsNone(viewport.inspection_points)
        self.assertEqual(viewport.inspection_offset,
                         self.model.n3_label_offsets["b"])

    def test_filtered_bsp_row_shows_winding_then_clear_on_unrelated_row(self):
        self.pane._only_filter("BSP")
        self.assertEqual(len(self.pane.filtered_model.entries), 1)
        index = self.pane.filtered_model.index(0)
        self.pane.filtered_list.setCurrentIndex(index)
        self.assertEqual(self.pane.current_target(), ("bsp", "split"))
        self.assertEqual(self.window.viewer.inspection_kind, "bsp")
        self.pane._show_all_filters()
        self.go_to(9)
        self.assertIsNone(self.window.viewer.inspection_kind)
        self.assertIsNone(self.window.viewer.inspection_points)

    def test_binary_export_root_bsp_highlights_from_full_and_filtered_source(self):
        from three_do import Model
        from text_3d import export_compilable_text
        from test_gpu_bsp_inspection import ROOT_BSP_SOURCE

        authored, _ = compile_n3_text(
            ROOT_BSP_SOURCE, "root_plane.3d", associate_planes=False)
        binary = Model("root_plane.3do", raw_data=authored.raw,
                       associate_planes=False)
        generated = export_compilable_text(binary)
        self.window.viewer._model = binary
        try:
            self.pane.set_source(generated, Path("root_plane.3d"))
            lines = generated.splitlines()
            root_line = next(i for i, row in enumerate(lines)
                             if row.startswith("root: BSPF "))
            self.go_to(root_line)
            self.assertEqual(self.pane.current_target(), ("bsp", "root"))
            self.assertEqual(self.window.viewer.inspection_kind, "bsp")
            expected = ((1686000., 0., 1056000.),
                        (1686000., 0., 0.),
                        (0., 0., 0.))
            self.assertEqual(self.window.viewer.inspection_points, expected)
            self.pane._only_filter("BSP")
            row = next(i for i, entry in
                       enumerate(self.pane.filtered_model.entries)
                       if entry.first_line == root_line)
            self.pane.filtered_list.setCurrentIndex(
                self.pane.filtered_model.index(row))
            self.assertEqual(self.pane.current_target(), ("bsp", "root"))
            self.assertEqual(self.window.viewer.inspection_points, expected)
            self.assertFalse(self.pane.dirty)
        finally:
            self.window.viewer._model = self.model
            self.pane._show_all_filters()

    def test_invalid_or_pending_source_hides_plane_arrows(self):
        self.go_to(8)
        self.assertEqual(self.window.viewer.inspection_kind, "bsp")
        self.pane.editor.insertPlainText(" ")
        self.assertTrue(self.pane.pending)
        self.assertIsNone(self.window.viewer.inspection_kind)
        self.assertIsNone(self.window.viewer.inspection_points)
        self.pane.mark_valid(self.pane.revision, self.model)
        self.assertEqual(self.window.viewer.inspection_kind, "bsp")
        self.pane.mark_error(self.pane.revision, "line 9: invalid BSP")
        self.assertIsNone(self.window.viewer.inspection_kind)

    def test_toggling_source_hides_and_restores_winding(self):
        self.go_to(8)
        self.window.source_toggle.setChecked(False)
        self.assertIsNone(self.window.viewer.inspection_kind)
        self.window.source_toggle.setChecked(True)
        self.assertEqual(self.window.viewer.inspection_kind, "bsp")


if __name__ == "__main__":
    unittest.main()
