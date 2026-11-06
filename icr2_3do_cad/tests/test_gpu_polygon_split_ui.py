"""GPU polygon split panel: selection, commit, and single-step Source undo."""
import os
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

from n3_compile import compile_n3_text


HAS_DISPLAY = bool(os.environ.get("DISPLAY") or
                   os.environ.get("WAYLAND_DISPLAY") or
                   sys.platform in ("win32", "darwin"))

SOURCE = """3D VERSION 3.0;
a: [<0,0,0>];
b: [<100,0,0>];
c: [<100,100,0>];
d: [<0,100,0>];
face: POLY <42> {a,b,c,d};
root: LIST {face};
"""


@unittest.skipUnless(HAS_DISPLAY, "Requires Qt or Xvfb")
class GPUSplitUITests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        try:
            from PySide6.QtWidgets import QApplication
            from gpu_viewer.main import Window
        except (ImportError, SystemExit) as error:
            raise unittest.SkipTest(str(error))
        cls.app = QApplication.instance() or QApplication([])
        cls.window = Window()
        cls.model, _ = compile_n3_text(
            SOURCE, "split_ui.3d", associate_planes=False)
        cls.window.viewer._model = cls.model
        cls.pane = cls.window.source_pane

    @classmethod
    def tearDownClass(cls):
        cls.pane.reset()
        cls.window.close()

    def setUp(self):
        self.window.viewer._model = self.model
        self.pane.set_source(SOURCE, Path("split_ui.3d"))
        self.pane._debounce.stop()
        self.window._set_split_target(None)
        self.window.split_button.setChecked(False)
        self.window.split_mode_combo.setCurrentIndex(0)

    def tearDown(self):
        self.pane._debounce.stop()
        self.window._pending_split_label = None
        self.window.split_button.setChecked(False)
        self.pane.set_source(SOURCE, Path("split_ui.3d"))

    def test_panel_below_viewport_and_edge_controls(self):
        self.assertIs(self.window.viewport_layout.itemAt(1).widget(),
                      self.window.viewer)
        self.assertIs(self.window.viewport_layout.itemAt(2).widget(),
                      self.window.split_panel)
        self.assertTrue(self.window.split_panel.isHidden())
        self.window.split_button.setChecked(True)
        self.assertFalse(self.window.split_panel.isHidden())
        self.assertEqual(self.window.pick_mode_combo.currentData(), "polygon")
        self.window._set_split_target(self.model.n3_label_offsets["face"])
        self.assertEqual(self.window.split_edge_a.count(), 4)
        self.assertEqual(self.window.split_edge_b.currentData(), 2)
        self.assertEqual(self.window.split_vertex_a.itemText(0), "#1  a")
        self.assertEqual(self.window.split_vertex_b.itemText(2), "#3  c")
        self.assertEqual(self.window.split_edge_a.itemText(0), "#1  a → b")
        self.assertEqual(self.window.split_edge_b.itemText(3), "#4  d → a")
        self.assertTrue(self.window.split_apply_button.isEnabled())
        self.window.split_edge_b.setCurrentIndex(0)
        self.assertFalse(self.window.split_apply_button.isEnabled())
        self.window.split_edge_b.setCurrentIndex(2)
        self.assertTrue(self.window.split_apply_button.isEnabled())

    def test_renamed_project_pointers_replace_offsets_in_both_selectors(self):
        renamed = (SOURCE.replace("a: [", "front_left: [")
                   .replace("b: [", "front_right: [")
                   .replace("c: [", "rear_right: [")
                   .replace("d: [", "rear_left: [")
                   .replace("{a,b,c,d}", "{front_left,front_right,rear_right,rear_left}"))
        model, _ = compile_n3_text(
            renamed, "renamed_split.3d", associate_planes=False)
        self.window.viewer._model = model
        self.pane.set_source(renamed, Path("renamed_split.3d"))
        self.window._set_split_target(model.n3_label_offsets["face"])
        self.assertEqual(
            self.window.split_vertex_a.itemText(0), "#1  front_left")
        self.assertEqual(
            self.window.split_edge_a.itemText(0),
            "#1  front_left → front_right")
        self.assertEqual(
            self.window.split_edge_b.itemText(2),
            "#3  rear_right → rear_left")
        # The cut still uses positional indices, not string labels or
        # mutable body offsets. Offsets are available only on hover.
        self.assertEqual(self.window.split_vertex_b.itemData(3), 3)
        from PySide6.QtCore import Qt
        tooltip = self.window.split_vertex_a.itemData(
            0, Qt.ItemDataRole.ToolTipRole)
        self.assertIn("@", tooltip)

    def test_binary_offsets_fallback_to_generated_pointer_names(self):
        from three_do import Model
        binary = Model("unlabeled.3do", raw_data=self.model.raw,
                       associate_planes=False)
        self.window.viewer._model = binary
        self.window._set_split_target(next(iter(binary.polygons)))
        first_ref = binary.polygons[next(iter(binary.polygons))].refs[0]
        self.assertEqual(
            self.window.split_vertex_a.itemText(0), f"#1  _{first_ref}")

    def test_existing_diagonal_commits_as_one_source_undo(self):
        from PySide6.QtWidgets import QMessageBox
        self.window.split_button.setChecked(True)
        self.window._set_split_target(self.model.n3_label_offsets["face"])
        self.window.split_mode_combo.setCurrentIndex(1)
        self.assertTrue(self.window.split_apply_button.isEnabled())
        with (patch("gpu_viewer.main.QMessageBox.question",
                    return_value=QMessageBox.StandardButton.Yes),
              patch.object(self.pane, "apply_now")):
            self.window._commit_polygon_split()
        self.pane._debounce.stop()
        self.assertTrue(self.pane.pending)
        self.assertIn("face: LIST {", self.pane.get_source())
        self.assertIn("Split POLY", self.pane.change_log.toPlainText())
        self.assertEqual(len(compile_n3_text(
            self.pane.get_source(), "split_ui.3d",
            associate_planes=False)[0].polygons), 2)
        self.pane.editor.undo()
        self.pane._debounce.stop()
        self.assertEqual(self.pane.get_source(), SOURCE)
        self.assertFalse(self.pane.dirty)


if __name__ == "__main__":
    unittest.main()
