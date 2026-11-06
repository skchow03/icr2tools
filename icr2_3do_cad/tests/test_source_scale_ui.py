"""Qt 3DO CAD uniform model scale: menu/dialog, Undo and source safety."""
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
a: [<0,0,0>, T=<0,0>];
b: [<100,0,0>, T=<127,0>];
c: [<0,100,0>, T=<0,127>];
p: POLY [T] <44> {a,b,c};
root: LIST {MATERIAL MIP="wall", GROUP=3, p};
"""


@unittest.skipUnless(HAS_DISPLAY, "Requires Qt desktop or Xvfb")
class GPUScaleModelUITests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        try:
            from PySide6.QtWidgets import QApplication
            from icr2_3do_cad import Window
        except (ImportError, SystemExit) as exc:
            raise unittest.SkipTest(str(exc))
        cls.app = QApplication.instance() or QApplication([])
        cls.window = Window()
        cls.pane = cls.window.source_pane
        cls.model, _ = compile_n3_text(
            SOURCE, "scale_source.3d", associate_planes=False)
        cls.window.viewer._model = cls.model
        cls.window.source_toggle.setChecked(True)

    @classmethod
    def tearDownClass(cls):
        cls.pane.reset()
        cls.window.close()

    def setUp(self):
        self.pane.set_source(SOURCE, Path("scale_source.3d"))
        self.pane._debounce.stop()
        self.pane._rename_timer.stop()
        self.pane._show_all_filters()

    def tearDown(self):
        self.pane._debounce.stop()
        self.pane._rename_timer.stop()
        self.pane.set_source(SOURCE, Path("scale_source.3d"))

    def test_atomic_source_scale_and_one_undo_with_log(self):
        pane = self.pane
        original_revision = pane.revision
        result = pane.scale_model("2")
        pane._debounce.stop()
        self.assertEqual(result.points, 3)
        self.assertEqual(result.multiplier, 2)
        self.assertIn("b: [<200,0,0>, T=<127,0>]", pane.get_source())
        self.assertTrue(pane.dirty)
        self.assertTrue(pane.pending)
        self.assertEqual(pane.revision, original_revision + 1)
        self.assertIn("Uniform scale ×2", pane.change_log.toPlainText())
        self.assertEqual(pane._rename_pending, None)
        self.assertTrue(pane.editor.document().isUndoAvailable())

        pane.editor.undo()
        pane._debounce.stop()
        self.assertEqual(pane.get_source(), SOURCE)
        self.assertFalse(pane.dirty)
        self.assertEqual(pane.revision, original_revision + 2)
        # Change log is historical and is not erased by Undo.
        self.assertIn("Uniform scale ×2", pane.change_log.toPlainText())
        pane.editor.redo()
        pane._debounce.stop()
        self.assertEqual(pane.get_source(), result.source)

    def test_divide_with_filter_preserves_hidden_source(self):
        pane = self.pane
        pane._only_filter("POLY")
        self.assertIs(pane.source_stack.currentWidget(), pane.filtered_page)
        result = pane.scale_model("4", divide=True)
        pane._debounce.stop()
        self.assertIn("b: [<25,0,0>, T=<127,0>]", pane.get_source())
        self.assertIn("p: POLY [T] <44> {a,b,c};", pane.get_source())
        self.assertEqual(len(pane.filtered_model.entries), 1)
        self.assertTrue(pane.pending)
        self.assertEqual(result.points, 3)
        pane.editor.undo()
        self.assertEqual(pane.get_source(), SOURCE)

    def test_pending_or_invalid_input_does_not_touch_source(self):
        pane = self.pane
        with self.assertRaisesRegex(ValueError, "factor of 1"):
            pane.scale_model("1")
        self.assertEqual(pane.get_source(), SOURCE)
        self.assertFalse(pane.dirty)
        self.assertEqual(pane.change_log.toPlainText(), "")

        pane.editor.insertPlainText("% pending")
        pane._debounce.stop()
        before = pane.get_source()
        with self.assertRaisesRegex(ValueError, "pending"):
            pane.scale_model("2")
        self.assertEqual(pane.get_source(), before)
        self.assertEqual(pane.change_log.toPlainText(), "")

    def test_dialog_multiply_divide_validation_cancel_and_accept(self):
        from PySide6.QtWidgets import QDialog
        from scale_dialog import ScaleModelDialog
        dialog = ScaleModelDialog(self.window)
        self.assertEqual(dialog.factor_text, "2")
        self.assertFalse(dialog.divide)
        self.assertTrue(dialog.apply_button.isEnabled())
        self.assertIn("2", dialog.preview.text())
        dialog.factor.setText("0")
        self.assertFalse(dialog.apply_button.isEnabled())
        dialog.factor.setText("6000")
        dialog.operation.setCurrentIndex(1)
        self.assertTrue(dialog.divide)
        self.assertIn("0.00016666", dialog.preview.text())
        dialog.cancel_button.click()
        self.assertEqual(dialog.result(), int(QDialog.DialogCode.Rejected))
        self.assertEqual(self.pane.get_source(), SOURCE)
        dialog2 = ScaleModelDialog(self.window)
        dialog2.apply_button.click()
        self.assertEqual(dialog2.result(), int(QDialog.DialogCode.Accepted))

    def test_edit_menu_action_uses_dialog_and_updates_canonical_source(self):
        from PySide6.QtWidgets import QDialog
        edit = next(action.menu() for action in self.window.menuBar().actions()
                    if action.text().replace("&", "") == "Edit")
        menu_action = next(
            action for action in edit.actions()
            if action.text().replace("&", "") == "Scale Model…")
        with patch("icr2_3do_cad.ScaleModelDialog") as make_dialog:
            dialog = make_dialog.return_value
            dialog.exec.return_value = QDialog.DialogCode.Rejected
            menu_action.trigger()
            self.assertEqual(self.pane.get_source(), SOURCE)
            dialog.exec.return_value = QDialog.DialogCode.Accepted
            dialog.factor_text = "2"
            dialog.divide = False
            menu_action.trigger()
        self.pane._debounce.stop()
        self.assertIn("b: [<200,0,0>, T=<127,0>]", self.pane.get_source())
        self.assertTrue(self.pane.dirty)


if __name__ == "__main__":
    unittest.main()
