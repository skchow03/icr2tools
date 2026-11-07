"""Desktop regressions for the direct vertex gizmo and undoable source edits."""
import os
import sys
import unittest
from types import SimpleNamespace
from unittest.mock import patch

HAS_DISPLAY = bool(os.environ.get("DISPLAY") or os.environ.get("WAYLAND_DISPLAY")
                   or sys.platform in ("win32","darwin"))
SOURCE = """3D VERSION 3.0;
left: [<100,20,30>, T=<10,11>];
right: [<-100,20,30>, T=<12,13>];
root: LIST {left,right};
"""


@unittest.skipUnless(HAS_DISPLAY, "Qt desktop or Xvfb required")
class VertexMoveUITests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        try:
            from PySide6.QtWidgets import QApplication
            from PySide6.QtCore import QPointF, QEvent, Qt, QPoint
            from PySide6.QtGui import QMouseEvent
            from PySide6.QtTest import QTest
            from icr2_3do_cad import GLViewport
            from source_tab import SourcePane
        except (ImportError, SystemExit) as exc:
            raise unittest.SkipTest(str(exc))
        cls.app = QApplication.instance() or QApplication([])
        cls.GLViewport=GLViewport
        cls.SourcePane=SourcePane
        cls.QPointF=QPointF
        cls.QPoint=QPoint
        cls.QMouseEvent=QMouseEvent
        cls.QEvent=QEvent
        cls.QTest=QTest
        cls.Qt=Qt

    def setUp(self):
        self.pane=self.SourcePane()
        self.pane.set_source(SOURCE, "move.3d")
        self.pane._debounce.stop()
        self.model=SimpleNamespace(
            vertices={11: SimpleNamespace(xyz=(100,20,30)),
                      22: SimpleNamespace(xyz=(-100,20,30))},
            n3_label_offsets={"left":11,"right":22})
        self.assertTrue(self.pane.goto_model_vertex(self.model,11))
        self.sent=[]
        self.pane.compileRequested.connect(
            lambda revision,text:self.sent.append((revision,text)))

    def tearDown(self):
        self.pane._debounce.stop()
        self.pane.close()
        self.pane.deleteLater()
        if hasattr(self,"view"):
            self.view.close()
            self.view.deleteLater()
        from PySide6.QtCore import QCoreApplication
        QCoreApplication.sendPostedEvents(None,self.QEvent.Type.DeferredDelete)
        self.app.processEvents()

    def test_drag_updates_source_and_symmetry_in_single_undo(self):
        self.pane.symmetry_enabled.setChecked(True)
        plan = self.pane.move_compiled_vertex(
            self.model, 11, (160,23,45))
        self.assertTrue(plan.changed)
        self.assertIn("left: [<160,23,45>, T=<10,11>]",self.sent[-1][1])
        self.assertIn("right: [<-160,23,45>, T=<12,13>]",self.sent[-1][1])
        self.pane.editor.undo()
        self.assertEqual(self.pane.editor.toPlainText(),SOURCE)

    def test_drag_refuses_mismatched_selection_and_pending_text(self):
        with self.assertRaisesRegex(ValueError, "Selected source vertex"):
            self.pane.move_compiled_vertex(
                self.model,22,(-160,23,45))
        self.pane.editor.insertPlainText(" ")  # pending edit
        with self.assertRaisesRegex(ValueError, "pending"):
            self.pane.move_compiled_vertex(
                self.model,11,(110,20,30))

    def test_viewport_gizmo_is_opt_in_and_emits_one_raw_xyz_commit(self):
        from vertex_move import hit_move_handle
        self.view=self.GLViewport()
        self.view.resize(800,600)
        self.view._mesh=SimpleNamespace(
            center=(0,0,0), scale=1000)
        self.view._model=self.model
        self.view.set_source_inspection("vertex",11)
        self.assertFalse(self.view.move_vertex_enabled)
        self.assertEqual(self.view._move_handles(),{})
        self.view.set_vertex_move_enabled(True)
        self.assertEqual(self.view.vertex_move_overlay.objectName(),
                         "cadVertexMoveGizmo")
        handles=self.view._move_handles()
        self.assertIn("X",handles)
        handle=handles["X"]
        base=(handle.center[0]+handle.direction[0]*45,
              handle.center[1]+handle.direction[1]*45)
        self.assertEqual(hit_move_handle(handles,*base),"X")
        press=self.QPoint(round(base[0]),round(base[1]))
        old_camera=(self.view.azimuth,self.view.elevation,
                    tuple(self.view.target))
        emitted=[]
        self.view.vertexMoveRequested.connect(
            lambda offset,xyz:emitted.append((offset,xyz)))
        self.QTest.mousePress(self.view,self.Qt.MouseButton.LeftButton,
                              pos=press)
        self.assertEqual(self.view._move_active_axis,"X")
        end=(base[0]+handle.direction[0]*50,
             base[1]+handle.direction[1]*50)
        pos=self.QPointF(*end)
        moving=self.QMouseEvent(
            self.QEvent.Type.MouseMove,pos,pos,
            self.Qt.MouseButton.NoButton,
            self.Qt.MouseButton.LeftButton,
            self.Qt.KeyboardModifier.NoModifier)
        self.app.sendEvent(self.view,moving)
        self.assertIsNotNone(self.view._move_preview_xyz)
        self.QTest.mouseRelease(
            self.view,self.Qt.MouseButton.LeftButton,
            pos=self.QPoint(round(end[0]),round(end[1])))
        self.assertEqual(len(emitted),1)
        self.assertEqual(emitted[0][0],11)
        self.assertNotEqual(emitted[0][1][0],100)
        self.assertEqual(emitted[0][1][1:],(20,30))
        self.assertEqual(self.model.vertices[11].xyz,(100,20,30))
        self.assertEqual(old_camera,(self.view.azimuth,
                         self.view.elevation,tuple(self.view.target)))
        self.assertIsNone(self.view._move_press)

    def test_escape_cancels_drag_without_emitting(self):
        self.view=self.GLViewport()
        self.view.resize(800,600)
        self.view._mesh=SimpleNamespace(
            center=(0,0,0),scale=1000)
        self.view._model=self.model
        self.view.set_source_inspection("vertex",11)
        self.view.set_vertex_move_enabled(True)
        h=self.view._move_handles()["X"]
        xy=(h.center[0]+h.direction[0]*50,
            h.center[1]+h.direction[1]*50)
        self.QTest.mousePress(
            self.view,self.Qt.MouseButton.LeftButton,
            pos=self.QPoint(round(xy[0]),round(xy[1])))
        self.assertIsNotNone(self.view._move_press)
        emits=[]
        self.view.vertexMoveRequested.connect(
            lambda *args: emits.append(args))
        self.QTest.keyClick(self.view,self.Qt.Key.Key_Escape)
        self.assertIsNone(self.view._move_press)
        self.QTest.mouseRelease(
            self.view,self.Qt.MouseButton.LeftButton,
            pos=self.QPoint(round(xy[0]),round(xy[1])))
        self.assertFalse(emits)


if __name__ == "__main__":
    unittest.main()
