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
            from icr2_3do_cad import Window
        except (ImportError, SystemExit) as error:
            raise unittest.SkipTest(f"3DO CAD dependencies unavailable: {error}")
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
        # A deliberate invalid source edit must not open the exit prompt
        # during headless Qt test cleanup.
        cls.window.source_pane.reset()
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

    def test_viewport_click_reveals_source_and_selects_named_vertex(self):
        self.pane.set_source(SOURCE, Path("example.3d"))
        self.window.source_toggle.setChecked(False)
        target = self.model.n3_label_offsets["b"]
        self.window._viewport_vertex_picked(target)
        self.assertTrue(self.window.source_toggle.isChecked())
        self.assertEqual(self.pane.current_target(), ("vertex", "b"))
        self.assertEqual(self.pane.editor.textCursor().blockNumber(), 2)
        self.assertEqual(self.pane.editor.textCursor().selectedText(), "b")
        self.assertEqual(self.window.viewer.inspection_kind, "vertex")
        self.assertEqual(self.window.viewer.inspection_offset, target)
        self.assertFalse(self.pane.dirty)

    def test_filtered_source_jumps_to_original_declaration(self):
        self.pane.set_source(SOURCE, Path("example.3d"))
        self.pane._only_filter("POLY")
        self.assertIs(self.pane.source_stack.currentWidget(),
                      self.pane.filtered_page)
        self.window._viewport_vertex_picked(self.model.n3_label_offsets["c"])
        self.assertIs(self.pane.source_stack.currentWidget(),
                      self.pane.editor)
        self.assertEqual(self.pane.current_target(), ("vertex", "c"))
        self.assertEqual(self.pane.editor.textCursor().blockNumber(), 3)
        self.assertEqual(self.pane.get_source(), SOURCE)

    def test_vertex_pick_waits_for_async_source_and_rejects_old_model(self):
        from unittest.mock import patch
        self.pane.reset()
        self.window.source_toggle.setChecked(True)
        offset = self.model.n3_label_offsets["a"]
        with patch.object(self.window, "_ensure_source_loaded") as ensure:
            self.window._viewport_vertex_picked(offset)
            ensure.assert_called()
        self.assertEqual(self.window._pending_vertex_pick, (self.model, offset))
        self.window._source_exported(self.model, SOURCE, Path("example.3d"))
        self.assertEqual(self.pane.current_target(), ("vertex", "a"))
        self.assertIsNone(self.window._pending_vertex_pick)
        self.pane.reset()
        with patch.object(self.window, "_ensure_source_loaded"):
            self.window._viewport_vertex_picked(offset)
        stale = self.window._pending_vertex_pick
        self.assertIsNotNone(stale)
        from types import SimpleNamespace
        self.window.viewer._model = SimpleNamespace(vertices={})
        self.window._source_exported(self.model, SOURCE, Path("example.3d"))
        self.assertFalse(self.pane.ready)
        self.window.viewer._model = self.model
        self.window._pending_vertex_pick = None
        self.pane.set_source(SOURCE, Path("example.3d"))

    def test_mouse_click_picks_but_drag_and_shift_pan_do_not(self):
        from unittest.mock import patch
        from PySide6.QtCore import Qt, QEvent, QPointF
        from PySide6.QtGui import QMouseEvent
        self.pane.set_source(SOURCE, Path("example.3d"))
        viewport = self.window.viewer
        target = self.model.n3_label_offsets["b"]
        def ev(kind, pos, button, buttons, mods=Qt.KeyboardModifier.NoModifier):
            return QMouseEvent(
                kind, QPointF(*pos), button, buttons, mods)
        left = Qt.MouseButton.LeftButton
        with patch.object(viewport, "pick_nearest_vertex",
                          return_value=target) as pick:
            viewport.mousePressEvent(
                ev(QEvent.Type.MouseButtonPress, (20, 20), left, left))
            viewport.mouseReleaseEvent(
                ev(QEvent.Type.MouseButtonRelease, (20, 20),
                   left, Qt.MouseButton.NoButton))
            pick.assert_called_once()
            self.assertEqual(self.pane.current_target(), ("vertex", "b"))
            pick.reset_mock()
            viewport.mousePressEvent(
                ev(QEvent.Type.MouseButtonPress, (20, 20), left, left))
            viewport.mouseMoveEvent(
                ev(QEvent.Type.MouseMove, (60, 20),
                   Qt.MouseButton.NoButton, left))
            viewport.mouseReleaseEvent(
                ev(QEvent.Type.MouseButtonRelease, (60, 20),
                   left, Qt.MouseButton.NoButton))
            pick.assert_not_called()
            viewport.mousePressEvent(
                ev(QEvent.Type.MouseButtonPress, (20, 20), left, left,
                   Qt.KeyboardModifier.ShiftModifier))
            viewport.mouseReleaseEvent(
                ev(QEvent.Type.MouseButtonRelease, (20, 20),
                   left, Qt.MouseButton.NoButton,
                   Qt.KeyboardModifier.ShiftModifier))
            pick.assert_not_called()

    def test_poly_mode_requires_activation_and_click_selects_polygon(self):
        from unittest.mock import patch
        from PySide6.QtCore import Qt, QEvent, QPointF
        from PySide6.QtGui import QMouseEvent

        self.pane.set_source(SOURCE, Path("example.3d"))
        viewport = self.window.viewer
        self.window.pick_mode_combo.setCurrentIndex(0)
        self.assertEqual(viewport.pick_mode, "vertex")
        left = Qt.MouseButton.LeftButton

        def click(pos=(30, 30), shift=False):
            modifiers = (Qt.KeyboardModifier.ShiftModifier if shift
                         else Qt.KeyboardModifier.NoModifier)
            viewport.mousePressEvent(QMouseEvent(
                QEvent.Type.MouseButtonPress, QPointF(*pos), left, left,
                modifiers))
            viewport.mouseReleaseEvent(QMouseEvent(
                QEvent.Type.MouseButtonRelease, QPointF(*pos), left,
                Qt.MouseButton.NoButton, modifiers))

        poly = self.model.n3_label_offsets["surface"]
        vertex = self.model.n3_label_offsets["b"]
        with (patch.object(viewport, "pick_nearest_vertex", return_value=vertex)
              as pick_vertex,
              patch.object(viewport, "pick_nearest_polygon", return_value=poly)
              as pick_poly):
            click()
            pick_vertex.assert_called_once()
            pick_poly.assert_not_called()
            self.assertEqual(self.pane.current_target(), ("vertex", "b"))

            self.window.pick_mode_combo.setCurrentIndex(1)
            self.assertEqual(viewport.pick_mode, "polygon")
            self.window.source_toggle.setChecked(False)
            click()
            pick_poly.assert_called_once()
            self.assertTrue(self.window.source_toggle.isChecked())
            self.assertEqual(self.pane.current_target(), ("polygon", "surface"))
            self.assertEqual(self.pane.editor.textCursor().blockNumber(), 4)
            self.assertEqual(self.pane.editor.textCursor().selectedText(),
                             "surface")
            self.assertEqual(viewport.inspection_kind, "polygon")
            self.assertEqual(viewport.inspection_offset, poly)
            self.assertFalse(self.pane.dirty)
            pick_poly.reset_mock()

            click(shift=True)
            pick_poly.assert_not_called()
            viewport.mousePressEvent(QMouseEvent(
                QEvent.Type.MouseButtonPress, QPointF(10, 10),
                left, left, Qt.KeyboardModifier.NoModifier))
            viewport.mouseMoveEvent(QMouseEvent(
                QEvent.Type.MouseMove, QPointF(50, 10),
                Qt.MouseButton.NoButton, left,
                Qt.KeyboardModifier.NoModifier))
            viewport.mouseReleaseEvent(QMouseEvent(
                QEvent.Type.MouseButtonRelease, QPointF(50, 10),
                left, Qt.MouseButton.NoButton,
                Qt.KeyboardModifier.NoModifier))
            pick_poly.assert_not_called()
        self.window.pick_mode_combo.setCurrentIndex(0)

    def test_picked_poly_scrolls_to_filtered_row(self):
        self.pane.set_source(SOURCE, Path("example.3d"))
        target = self.model.n3_label_offsets["surface"]
        self.pane._only_filter("POLY")
        self.assertIs(self.pane.source_stack.currentWidget(),
                      self.pane.filtered_page)
        self.window._viewport_polygon_picked(target)
        self.assertIs(self.pane.source_stack.currentWidget(),
                      self.pane.filtered_page)
        row = self.pane.filtered_list.currentIndex().row()
        self.assertEqual(self.pane.filtered_model.entries[row].first_line, 4)
        self.assertEqual(self.pane.current_target(), ("polygon", "surface"))

        # A different active type filter cannot silently hide the picked row.
        self.pane._only_filter("Vertices")
        self.window._viewport_polygon_picked(target)
        self.assertIs(self.pane.source_stack.currentWidget(),
                      self.pane.filtered_page)
        row = self.pane.filtered_list.currentIndex().row()
        self.assertEqual(self.pane.filtered_model.entries[row].category, "POLY")
        self.assertEqual(self.pane.filtered_model.entries[row].first_line, 4)
        self.assertEqual(self.pane.get_source(), SOURCE)

    def test_inline_material_polygon_row_inspects_actual_child_geometry(self):
        from PySide6.QtCore import Qt
        from PySide6.QtGui import QTextCursor
        from PySide6.QtWidgets import QTextEdit
        source = (
            "3D VERSION 3.0;\n"
            "c1: [<0,0,0>, T=<0,0>];\n"
            "c0: [<100,0,0>, T=<127,0>];\n"
            "d0: [<100,100,0>, T=<127,127>];\n"
            "d1: [<0,100,0>, T=<0,127>];\n"
            'rs1: MATERIAL MIP="usag", GROUP=3, '
            'POLY [T] <208> {c1, c0, d0, d1};\n'
            'bk1: MATERIAL MIP="usag", GROUP=3, '
            'POLY [T] <26> {d1, d0, c0, c1};\n'
            "root: LIST {rs1,bk1};\n"
        )
        model, _ = compile_n3_text(
            source, "nested_poly.3d", associate_planes=False)
        self.window.viewer._model = model
        try:
            pane = self.pane
            self.window.source_toggle.setChecked(True)
            pane.set_source(source, Path("nested_poly.3d"))
            for line, name, color in ((5, "rs1", 208), (6, "bk1", 26)):
                block = pane.editor.document().findBlockByNumber(line)
                pane.editor.setTextCursor(QTextCursor(block))
                self.assertEqual(pane.current_target(), ("polygon", name))
                wrapper = model.n3_label_offsets[name]
                self.assertNotIn(wrapper, model.polygons)
                self.assertEqual(self.window.viewer.inspection_kind, "polygon")
                poly_offset = model.children[wrapper][0]
                self.assertEqual(self.window.viewer.inspection_offset, poly_offset)
                self.assertEqual(model.polygons[poly_offset].color, color)

            # Selecting a filtered MATERIAL row is also selecting its POLY.
            pane._only_filter("MATERIAL")
            self.assertEqual(len(pane.filtered_model.entries), 2)
            for row, name in enumerate(("rs1", "bk1")):
                pane.filtered_list.setCurrentIndex(pane.filtered_model.index(row))
                self.assertEqual(pane.current_target(), ("polygon", name))
                self.assertEqual(self.window.viewer.inspection_offset,
                                 model.children[model.n3_label_offsets[name]][0])
                pane.set_polygon_visibility(True)
                idx = pane.filtered_model.index(row)
                self.assertIn("[VISIBLE]", pane.filtered_model.data(
                    idx, Qt.ItemDataRole.DisplayRole))
                self.assertEqual(pane.filtered_model.data(
                    idx, Qt.ItemDataRole.BackgroundRole).name(),
                    pane.colors["source_visible_background"].lower())

            # POLY-only filtering should include nested polygons despite the
            # row retaining its MATERIAL type and editable text.
            pane._only_filter("POLY")
            self.assertEqual(len(pane.filtered_model.entries), 2)
            self.assertEqual(
                {e.category for e in pane.filtered_model.entries},
                {"MATERIAL"})
            self.assertFalse(pane.dirty)
            self.assertFalse(pane.pending)
            self.assertEqual(pane.get_source(), source)

            # Picking the real compiled polygon returns to its MATERIAL row.
            pane._only_filter("Vertices")
            target = model.children[model.n3_label_offsets["bk1"]][0]
            self.window._viewport_polygon_picked(target)
            self.assertEqual(pane.current_target(), ("polygon", "bk1"))
            self.assertEqual(pane.editor.textCursor().blockNumber(), 6)
            self.assertEqual(self.window.viewer.inspection_offset, target)
            self.assertIs(pane.source_stack.currentWidget(),
                          pane.filtered_page)
            self.assertFalse(pane.dirty)
            self.assertEqual(pane.get_source(), source)
        finally:
            self.window.viewer._model = self.model
            self.pane._show_all_filters()
            self.pane.set_source(SOURCE, Path("example.3d"))
            self.window.source_toggle.setChecked(True)

    def test_binary_generated_polygon_label_is_navigable(self):
        import tempfile
        from three_do import Model
        from text_3d import export_compilable_text
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "compiled.3do"
            path.write_bytes(self.model.raw)
            binary = Model(path, associate_planes=False)
            source = export_compilable_text(binary)
            self.pane.set_source(source, path.with_suffix(".3d"))
            self.window.viewer._model = binary
            try:
                off = next(iter(binary.polygons))
                self.window._viewport_polygon_picked(off)
                self.assertEqual(
                    self.pane.current_target(), ("polygon", f"_{off}"))
                self.assertEqual(self.window.viewer.inspection_offset, off)
            finally:
                self.window.viewer._model = self.model
                self.pane.set_source(SOURCE, Path("example.3d"))

    def test_polygon_pick_waits_for_async_source_and_rejects_stale_model(self):
        from unittest.mock import patch
        from types import SimpleNamespace
        self.pane.reset()
        self.window.source_toggle.setChecked(True)
        poly = self.model.n3_label_offsets["surface"]
        with patch.object(self.window, "_ensure_source_loaded") as ensure:
            self.window._viewport_polygon_picked(poly)
            ensure.assert_called()
        self.assertEqual(self.window._pending_polygon_pick, (self.model, poly))
        self.window._source_exported(self.model, SOURCE, Path("example.3d"))
        self.assertEqual(self.pane.current_target(), ("polygon", "surface"))
        self.assertIsNone(self.window._pending_polygon_pick)
        self.pane.reset()
        with patch.object(self.window, "_ensure_source_loaded"):
            self.window._viewport_polygon_picked(poly)
        self.assertIsNotNone(self.window._pending_polygon_pick)
        self.window.viewer._model = SimpleNamespace(polygons={})
        self.window._source_exported(self.model, SOURCE, Path("example.3d"))
        self.assertFalse(self.pane.ready)
        self.window.viewer._model = self.model
        self.window._pending_polygon_pick = None
        self.pane.set_source(SOURCE, Path("example.3d"))

    def test_binary_generated_vertex_pointer_is_navigable(self):
        import tempfile
        from three_do import Model
        from text_3d import export_compilable_text
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "compiled.3do"
            path.write_bytes(self.model.raw)
            binary = Model(path, associate_planes=False)
            source = export_compilable_text(binary)
            self.pane.set_source(source, path.with_suffix(".3d"))
            self.window.viewer._model = binary
            try:
                off = next(iter(binary.vertices))
                self.window._viewport_vertex_picked(off)
                self.assertEqual(
                    self.pane.current_target(), ("vertex", f"_{off}"))
                self.assertEqual(
                    self.window.viewer.inspection_offset, off)
            finally:
                self.window.viewer._model = self.model
                self.pane.set_source(SOURCE, Path("example.3d"))

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
