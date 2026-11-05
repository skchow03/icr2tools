"""Qt Source-pane category checkbox filters and original-line navigation."""
import os
import sys
import unittest
from pathlib import Path

HAS_DISPLAY = bool(os.environ.get("DISPLAY") or
                   os.environ.get("WAYLAND_DISPLAY") or
                   sys.platform in ("win32", "darwin"))

SOURCE = """3D VERSION 3.0;
% global comment
a: [<0,0,0>];
b: [<100,0,0>];
c: [<0,100,0>];
panel: POLY <44>
   {a,b,c};
root: LIST {panel};
% second comment
"""


@unittest.skipUnless(HAS_DISPLAY, "Qt requires desktop or Xvfb")
class SourceFilterQtTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        try:
            from PySide6.QtWidgets import QApplication
            from gpu_viewer.source_tab import SourcePane
        except (ImportError, SystemExit) as error:
            raise unittest.SkipTest(f"Qt not installed: {error}")
        cls.app = QApplication.instance() or QApplication([])
        cls.pane = SourcePane()

    def setUp(self):
        self.pane.set_source(SOURCE, Path("filtered.3d"))
        self.pane._show_all_filters()
        self.pane._debounce.stop()

    @classmethod
    def tearDownClass(cls):
        cls.pane.close()

    def test_checked_dropdown_counts_and_only_isolation(self):
        pane = self.pane
        pane._filter_menu_opening()
        self.assertEqual(len(pane._filter_checks), 13)
        self.assertTrue(all(box.isChecked()
                            for box in pane._filter_checks.values()))
        self.assertIn("(2)", pane._filter_checks["Comments (%)"].text())
        pane._only_filter("POLY")
        self.assertIs(pane.source_stack.currentWidget(), pane.filtered_page)
        self.assertEqual(len(pane.filtered_model.entries), 1)
        entry = pane.filtered_model.entries[0]
        self.assertEqual(entry.category, "POLY")
        self.assertEqual((entry.first_line, entry.last_line), (5, 6))
        self.assertFalse(pane.dirty)
        self.assertFalse(pane.pending)
        self.assertEqual(pane.get_source(), SOURCE)
        self.assertTrue(pane.auto_rename.isChecked())

    def test_multiple_types_and_exclusions(self):
        pane = self.pane
        pane._only_filter("Comments (%)")
        self.assertEqual(len(pane.filtered_model.entries), 2)
        pane._filter_checks["Vertices"].setChecked(True)
        self.assertEqual(len(pane.filtered_model.entries), 5)
        self.assertEqual(
            {e.category for e in pane.filtered_model.entries},
            {"Comments (%)", "Vertices"})
        pane._filter_checks["Comments (%)"].setChecked(False)
        self.assertEqual(len(pane.filtered_model.entries), 3)
        pane._hide_all_filters()
        self.assertEqual(pane.filtered_model.rowCount(), 0)
        self.assertIs(pane.source_stack.currentWidget(), pane.filtered_page)
        pane._show_all_filters()
        self.assertIs(pane.source_stack.currentWidget(), pane.editor)
        self.assertEqual(pane.get_source(), SOURCE)

    def test_search_and_select_jump_to_original_line(self):
        pane = self.pane
        pane._only_filter("POLY")
        pane.filter_search.setText("panel")
        self.assertEqual(len(pane.filtered_model.entries), 1)
        index = pane.filtered_model.index(0)
        pane.filtered_list.setCurrentIndex(index)
        self.assertEqual(pane.editor.textCursor().blockNumber(), 5)
        self.assertEqual(pane.current_target(), ("polygon", "panel"))
        self.assertIs(pane.source_stack.currentWidget(), pane.filtered_page)
        self.assertEqual(pane.get_source(), SOURCE)
        pane._edit_filtered_entry(index)
        self.assertIs(pane.source_stack.currentWidget(), pane.editor)
        self.assertEqual(pane.editor.textCursor().blockNumber(), 5)
        self.assertEqual(pane.filter_search.text(), "")
        self.assertEqual(pane.get_source(), SOURCE)

    def test_filtered_navigation_still_emits_geometry_target(self):
        pane = self.pane
        captured = []
        pane.cursorTargetChanged.connect(captured.append)
        try:
            pane._only_filter("Vertices")
            i = next(i for i, entry in enumerate(pane.filtered_model.entries)
                     if entry.first_line == 3)
            pane.filtered_list.setCurrentIndex(pane.filtered_model.index(i))
            self.assertEqual(pane.current_target(), ("vertex", "b"))
            self.assertIn(("vertex", "b"), captured)
        finally:
            pane.cursorTargetChanged.disconnect(captured.append)

    def test_filtered_poly_retains_green_salmon_inspection_state(self):
        from PySide6.QtCore import Qt
        pane = self.pane
        pane._only_filter("POLY")
        index = pane.filtered_model.index(0)
        pane.filtered_list.setCurrentIndex(index)
        self.assertEqual(pane.current_target(), ("polygon", "panel"))
        for visible, color, status in (
                (True, pane.colors["source_visible_background"].lower(), "[VISIBLE]"),
                (False, pane.colors["source_hidden_background"].lower(), "[NOT DRAWN]")):
            pane.set_polygon_visibility(visible)
            self.assertEqual(
                pane.filtered_model.data(
                    index, Qt.ItemDataRole.BackgroundRole).name(), color)
            self.assertIn(status, pane.filtered_model.data(
                index, Qt.ItemDataRole.DisplayRole))
        pane.set_polygon_visibility(None)
        self.assertIsNone(pane.filtered_model.data(
            index, Qt.ItemDataRole.BackgroundRole))

    def test_filtered_results_rebuild_after_source_edit(self):
        pane = self.pane
        pane._only_filter("POLY")
        pane._show_all_filters()
        cursor = pane.editor.textCursor()
        cursor.movePosition(cursor.MoveOperation.End)
        pane.editor.setTextCursor(cursor)
        pane.editor.insertPlainText("second: POLY <55> {a,b,c};\n")
        pane._debounce.stop()
        self.assertTrue(pane.pending)
        pane._only_filter("POLY")
        self.assertEqual(len(pane.filtered_model.entries), 2)
        self.assertIn("second: POLY", pane.filtered_model.entries[1].preview)
        self.assertIn("second: POLY", pane.get_source())

    def test_filtered_poly_edit_preserves_hidden_source_and_filter(self):
        from PySide6.QtCore import Qt, QTimer
        from PySide6.QtWidgets import QApplication
        pane = self.pane
        pane._only_filter("POLY")
        index = pane.filtered_model.index(0)
        self.assertTrue(index.flags() & Qt.ItemFlag.ItemIsEditable)
        before = pane.get_source()
        edited = pane.filtered_model.data(index, Qt.ItemDataRole.EditRole)
        self.assertEqual(edited, "panel: POLY <44>\n   {a,b,c};")
        self.assertTrue(pane.filtered_model.setData(
            index, edited.replace("<44>", "<55>"), Qt.ItemDataRole.EditRole))
        QApplication.processEvents()
        self.assertIs(pane.source_stack.currentWidget(), pane.filtered_page)
        self.assertEqual(
            pane.filter_button.text(),
            "Filter statements (1/13)")
        self.assertIn("panel: POLY <55>", pane.get_source())
        self.assertTrue(pane.dirty)
        self.assertTrue(pane.pending)
        self.assertEqual(pane.get_source().replace("<55>", "<44>"), before)
        self.assertEqual(len(pane.filtered_model.entries), 1)
        self.assertIn("<55>", pane.filtered_model.entries[0].preview)
        self.assertTrue(pane.editor.document().isUndoAvailable())
        pane._debounce.stop()
        pane.editor.undo()
        QApplication.processEvents()
        self.assertEqual(pane.get_source(), before)

    def test_filtered_multiline_edit_and_comment_preservation(self):
        from PySide6.QtCore import Qt
        from PySide6.QtWidgets import QApplication
        pane = self.pane
        pane._only_filter("POLY")
        index = pane.filtered_model.index(0)
        edited = "panel: POLY <44>\n   {a, b,\n    c};"
        self.assertTrue(pane.filtered_model.setData(
            index, edited, Qt.ItemDataRole.EditRole))
        QApplication.processEvents()
        self.assertEqual(pane.get_source().splitlines()[1], "% global comment")
        self.assertEqual(pane.get_source().splitlines()[-1], "% second comment")
        self.assertIn("root: LIST {panel};", pane.get_source())
        self.assertEqual(
            (pane.filtered_model.entries[0].first_line,
             pane.filtered_model.entries[0].last_line), (5, 7))
        self.assertEqual(pane.get_source().count("POLY"), 1)
        self.assertIs(pane.source_stack.currentWidget(), pane.filtered_page)

    def test_filtered_edit_retains_search_until_match_changes(self):
        from PySide6.QtCore import Qt
        from PySide6.QtWidgets import QApplication
        pane = self.pane
        pane._only_filter("POLY")
        pane.filter_search.setText("panel")
        index = pane.filtered_model.index(0)
        assert pane.filtered_model.setData(
            index, "wing: POLY <44>\n   {a,b,c};", Qt.ItemDataRole.EditRole)
        QApplication.processEvents()
        self.assertEqual(pane.filter_search.text(), "panel")
        self.assertEqual(len(pane.filtered_model.entries), 0)
        self.assertIs(pane.source_stack.currentWidget(), pane.filtered_page)
        self.assertIn("wing: POLY", pane.get_source())
        pane.filter_search.clear()
        self.assertEqual(len(pane.filtered_model.entries), 1)

    def test_filtered_pointer_rename_updates_hidden_references(self):
        from PySide6.QtCore import Qt
        from PySide6.QtWidgets import QApplication
        pane = self.pane
        self.assertTrue(pane.auto_rename.isChecked())
        pane._only_filter("POLY")
        index = pane.filtered_model.index(0)
        self.assertTrue(pane.filtered_model.setData(
            index, "wing: POLY <44>\n   {a,b,c};",
            Qt.ItemDataRole.EditRole))
        pane._rename_timer.stop()
        pane._commit_pending_rename()
        QApplication.processEvents()
        self.assertIn("root: LIST {wing};", pane.get_source())
        self.assertEqual(pane.get_source().splitlines()[1], "% global comment")
        self.assertEqual(len(pane.filtered_model.entries), 1)
        self.assertIs(pane.source_stack.currentWidget(), pane.filtered_page)

    def test_actual_inline_editor_commits_without_switching_mode(self):
        from PySide6.QtCore import Qt
        from PySide6.QtWidgets import QApplication, QPlainTextEdit
        pane = self.pane
        pane.show()
        pane._only_filter("POLY")
        QApplication.processEvents()
        index = pane.filtered_model.index(0)
        pane.filtered_list.edit(index)
        QApplication.processEvents()
        editor = next(
            child for child in pane.filtered_list.findChildren(QPlainTextEdit)
            if child.isVisible())
        self.assertEqual(editor.toPlainText(),
                         "panel: POLY <44>\n   {a,b,c};")
        editor.setPlainText(editor.toPlainText().replace("<44>", "<77>"))
        # Exercise the actual keyboard shortcut, not an artificial
        # setData call: Ctrl+Enter commits while the filter remains active.
        from PySide6.QtTest import QTest
        QTest.keyClick(editor, Qt.Key.Key_Return,
                       Qt.KeyboardModifier.ControlModifier)
        QApplication.processEvents()
        self.assertIs(pane.source_stack.currentWidget(), pane.filtered_page)
        self.assertIn("panel: POLY <77>", pane.get_source())
        self.assertEqual(len(pane.filtered_model.entries), 1)
        pane.hide()

    def test_escape_cancels_inline_edit_and_keeps_active_filter(self):
        from PySide6.QtCore import Qt
        from PySide6.QtTest import QTest
        from PySide6.QtWidgets import QApplication, QPlainTextEdit
        pane = self.pane
        pane.show()
        pane._only_filter("POLY")
        QApplication.processEvents()
        pane.filtered_list.edit(pane.filtered_model.index(0))
        QApplication.processEvents()
        editor = next(
            child for child in pane.filtered_list.findChildren(QPlainTextEdit)
            if child.isVisible())
        editor.setPlainText("panel: POLY <999>\n   {a,b,c};")
        QTest.keyClick(editor, Qt.Key.Key_Escape)
        QApplication.processEvents()
        self.assertEqual(pane.get_source(), SOURCE)
        self.assertFalse(pane.dirty)
        self.assertFalse(pane.pending)
        self.assertIs(pane.source_stack.currentWidget(), pane.filtered_page)
        self.assertEqual(len(pane.filtered_model.entries), 1)
        pane.hide()

    def test_find_error_returns_to_full_editable_source(self):
        pane = self.pane
        pane._only_filter("LIST")
        pane.mark_error(pane.revision, "line 8: missing reference")
        pane.goto_error()
        self.assertIs(pane.source_stack.currentWidget(), pane.editor)
        self.assertEqual(pane.editor.textCursor().blockNumber(), 7)


if __name__ == "__main__":
    unittest.main()
