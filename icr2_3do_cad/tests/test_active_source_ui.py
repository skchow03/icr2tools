"""Qt Active SWITCH DISTANCE filter integration with editable N3 statements."""
import os
import sys
import unittest
from pathlib import Path

from n3_compile import compile_n3_text

HAS_DISPLAY = bool(os.environ.get("DISPLAY") or
                   os.environ.get("WAYLAND_DISPLAY") or
                   sys.platform in ("win32", "darwin"))

SOURCE = """3D VERSION 3.0;
% unrelated annotation
a: [<0,0,0>];
b: [<100,0,0>];
c: [<0,100,0>];
d: [<0,0,100>];
e: [<0,100,100>];
near_poly: POLY <44> {a,b,c};
far_poly: POLY <55> {a,b,e};
near_face: FACE (a,b,d), near_poly;
far_list: LIST {far_poly};
far_material: MATERIAL GROUP=3, far_list;
lod: SWITCH DISTANCE (a) > {(1000 ? far_material), (0 ? near_face)};
root: LIST {lod};
"""


@unittest.skipUnless(HAS_DISPLAY, "Qt needs a desktop or Xvfb")
class ActiveDistanceFilterQtTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        try:
            from PySide6.QtWidgets import QApplication
            from source_tab import SourcePane
        except (ImportError, SystemExit) as exc:
            raise unittest.SkipTest(f"Qt unavailable: {exc}")
        cls.app = QApplication.instance() or QApplication([])
        cls.pane = SourcePane()
        cls.model, _ = compile_n3_text(
            SOURCE, "switch_filter.3d", associate_planes=False)

    def setUp(self):
        pane = self.pane
        pane._show_all_filters()
        pane.set_source(SOURCE, Path("switch_filter.3d"))
        pane.set_distance_filter_context(self.model, 0, (0, 0, 0))
        pane.current_distance_only.setChecked(True)
        pane._debounce.stop()

    @classmethod
    def tearDownClass(cls):
        cls.pane.close()

    def names(self):
        return {entry.preview.split(":", 1)[0].strip()
                for entry in self.pane.filtered_model.entries}

    def test_only_active_res_branch_with_required_declarations(self):
        pane = self.pane
        self.assertTrue(pane.current_distance_only.isChecked())
        self.assertIs(pane.source_stack.currentWidget(), pane.filtered_page)
        self.assertEqual(
            self.names(),
            {"a", "b", "c", "d", "near_poly", "near_face", "lod", "root"})
        self.assertIn("Active LOD", pane.filter_button.text())
        self.assertEqual(pane.get_source(), SOURCE)
        self.assertFalse(pane.dirty)
        self.assertFalse(pane.pending)
        self.assertNotIn("% unrelated annotation", [
            e.preview for e in pane.filtered_model.entries])

    def test_distance_changes_filter_without_reapplying_category_checkboxes(self):
        pane = self.pane
        pane._only_filter("POLY")
        self.assertEqual(self.names(), {"near_poly"})
        pane.set_distance_filter_context(self.model, 1000, (0, 0, 0))
        self.assertEqual(self.names(), {"far_poly"})
        self.assertEqual(pane._filter_checks["POLY"].isChecked(), True)
        self.assertTrue(pane.current_distance_only.isChecked())
        pane.set_distance_filter_context(self.model, "auto", (0, 0, 0))
        self.assertEqual(self.names(), {"near_poly"})
        pane.set_distance_filter_context(self.model, "auto", (1500, 0, 0))
        self.assertEqual(self.names(), {"far_poly"})
        pane.set_distance_filter_context(self.model, None, (0, 0, 0))
        self.assertEqual(self.names(), {"near_poly", "far_poly"})
        self.assertTrue(pane.current_distance_only.isChecked())

    def test_distance_and_category_and_text_filters_are_composable(self):
        pane = self.pane
        pane._only_filter("Vertices")
        self.assertEqual(self.names(), {"a", "b", "c", "d"})
        pane.set_distance_filter_context(self.model, 1500, (0, 0, 0))
        self.assertEqual(self.names(), {"a", "b", "e"})
        pane._filter_checks["POLY"].setChecked(True)
        self.assertEqual(self.names(), {"a", "b", "e", "far_poly"})
        pane.filter_search.setText("far")
        self.assertEqual(self.names(), {"far_poly"})
        pane.filter_search.clear()
        self.assertEqual(self.names(), {"a", "b", "e", "far_poly"})

    def test_show_all_resets_distance_filter_and_text_is_unchanged(self):
        pane = self.pane
        pane._show_all_filters()
        self.assertFalse(pane.current_distance_only.isChecked())
        self.assertIs(pane.source_stack.currentWidget(), pane.editor)
        self.assertEqual(pane.get_source(), SOURCE)

    def test_edit_under_distance_filter_keeps_row_and_hidden_branch(self):
        from PySide6.QtCore import Qt
        from PySide6.QtWidgets import QApplication
        pane = self.pane
        pane._only_filter("POLY")
        self.assertEqual(self.names(), {"near_poly"})
        row = pane.filtered_model.index(0)
        self.assertTrue(pane.filtered_model.setData(
            row, "near_poly: POLY <66> {a,b,c};", Qt.ItemDataRole.EditRole))
        QApplication.processEvents()
        self.assertIs(pane.source_stack.currentWidget(), pane.filtered_page)
        self.assertEqual(self.names(), {"near_poly"})
        self.assertIn("last valid model", pane.filter_status.text())
        self.assertIn("far_poly: POLY <55>", pane.get_source())
        self.assertTrue(pane.pending)
        self.assertTrue(pane.dirty)
        new_model, _ = compile_n3_text(pane.get_source(), "edited.3d",
                                       associate_planes=False)
        pane.set_distance_filter_context(new_model, 0, (0, 0, 0))
        pane.mark_valid(pane.revision, new_model)
        self.assertEqual(self.names(), {"near_poly"})
        self.assertFalse(pane.pending)

    def test_renamed_active_poly_remains_until_compiled_and_renames_hidden_refs(self):
        from PySide6.QtCore import Qt
        from PySide6.QtWidgets import QApplication
        pane = self.pane
        pane._only_filter("POLY")
        row = pane.filtered_model.index(0)
        self.assertTrue(pane.filtered_model.setData(
            row, "front: POLY <44> {a,b,c};", Qt.ItemDataRole.EditRole))
        QApplication.processEvents()
        self.assertIn("front", self.names())
        pane._rename_timer.stop()
        pane._commit_pending_rename()
        QApplication.processEvents()
        self.assertIn("near_face: FACE (a,b,d), front;", pane.get_source())
        self.assertIn("front", self.names())
        updated, _ = compile_n3_text(pane.get_source(), "rename.3d",
                                     associate_planes=False)
        pane.set_distance_filter_context(updated, 0, (0, 0, 0))
        pane.mark_valid(pane.revision, updated)
        self.assertEqual(self.names(), {"front"})

    def test_missing_context_does_not_hide_everything(self):
        pane = self.pane
        pane.set_distance_filter_context(None, 0, None)
        self.assertGreater(len(pane.filtered_model.entries), 0)
        self.assertIn("waiting for model", pane.filter_status.text())

    def test_camera_update_during_inline_edit_preserves_editor_text(self):
        from PySide6.QtWidgets import QApplication, QPlainTextEdit
        pane = self.pane
        pane.show()
        pane._only_filter("POLY")
        QApplication.processEvents()
        pane.filtered_list.edit(pane.filtered_model.index(0))
        QApplication.processEvents()
        editor = next(
            widget for widget in pane.filtered_list.findChildren(QPlainTextEdit)
            if widget.isVisible())
        editor.setPlainText("near_poly: POLY <77> {a,b,c};")
        pane.set_distance_filter_context(self.model, 1500, (0, 0, 0))
        self.assertEqual(editor.toPlainText(), "near_poly: POLY <77> {a,b,c};")
        self.assertIs(pane.source_stack.currentWidget(), pane.filtered_page)
        delegate = pane.filtered_list.itemDelegate()
        delegate.commitData.emit(editor)
        delegate.closeEditor.emit(editor)
        QApplication.processEvents()
        self.assertIn("near_poly: POLY <77>", pane.get_source())
        self.assertIn("far_poly", self.names())
        pane.hide()


if __name__ == "__main__":
    unittest.main()
