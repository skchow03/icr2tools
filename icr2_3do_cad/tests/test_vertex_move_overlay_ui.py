"""Raster regression for mouse-transparent vertex drag overlay with edge preview."""
import os
import sys
import unittest
from types import SimpleNamespace

import numpy as np

HAS_DISPLAY = bool(os.environ.get("DISPLAY") or os.environ.get("WAYLAND_DISPLAY")
                   or sys.platform in ("win32", "darwin"))


@unittest.skipUnless(HAS_DISPLAY, "Qt desktop or Xvfb required")
class VertexMoveOverlayUITests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        try:
            from PySide6.QtWidgets import QApplication, QWidget
            from PySide6.QtCore import Qt
            from PySide6.QtGui import QImage
            from vertex_move import move_handles
            from vertex_move_overlay import VertexMoveOverlay
        except (ImportError, SystemExit) as e:
            raise unittest.SkipTest(str(e))
        cls.app = QApplication.instance() or QApplication([])
        cls.QWidget=QWidget
        cls.Qt=Qt
        cls.QImage=QImage
        cls.move_handles=staticmethod(move_handles)
        cls.VertexMoveOverlay=VertexMoveOverlay

    def test_gizmo_rasterizes_axes_coordinates_and_connected_edges(self):
        import numpy as np
        class StubViewport(self.QWidget):
            def __init__(self):
                super().__init__()
                self._mesh=SimpleNamespace(center=(0,0,0),scale=1000)
                self._move_original_xyz=(0,0,0)
                self._move_preview_xyz=(100,0,0)
                self._move_neighbors=((20,(0,200,0)),)
                self._move_active_axis="X"
                self._move_hover_axis=None
            def _projection_and_view(self):
                return np.diag((1.0,1.0,-0.2,1.0)),np.eye(4)
            def _move_handles(self,*,preview=False):
                from vertex_move import move_handles
                return move_handles(
                    self._move_preview_xyz if preview else
                    self._move_original_xyz,
                    self._mesh.center,self._mesh.scale,
                    np.diag((1.0,1.0,-0.2,1.0)),
                    self.width(),self.height())
        root=StubViewport()
        root.resize(640,480)
        overlay=self.VertexMoveOverlay(root)
        overlay.setGeometry(root.rect())
        root.show()
        overlay.show()
        self.app.processEvents()
        try:
            self.assertTrue(overlay.testAttribute(
                self.Qt.WidgetAttribute.WA_TransparentForMouseEvents))
            self.assertTrue(overlay.testAttribute(
                self.Qt.WidgetAttribute.WA_TranslucentBackground))
            image=overlay.grab().toImage().convertToFormat(
                self.QImage.Format.Format_RGBA8888)
            pixels=np.frombuffer(
                image.bits(), dtype=np.uint8, count=image.sizeInBytes())
            rgba=pixels.reshape(image.height(),image.bytesPerLine())[
                :, :image.width()*4].reshape(image.height(),image.width(),4)
            self.assertGreater(np.count_nonzero(rgba[...,3]),150)
            # Moved vertex, X arrow and connected edge are actually painted.
            self.assertGreater(np.count_nonzero(
                rgba[225:255,335:425,3]),60)
            before=image.copy()
            root._move_preview_xyz=(150,0,0)
            overlay.update()
            self.app.processEvents()
            after=overlay.grab().toImage().convertToFormat(
                self.QImage.Format.Format_RGBA8888)
            self.assertNotEqual(before,after)
        finally:
            root.close()
            from PySide6.QtCore import QCoreApplication, QEvent
            root.deleteLater()
            QCoreApplication.sendPostedEvents(None,QEvent.Type.DeferredDelete)
            self.app.processEvents()


if __name__=="__main__":
    unittest.main()
