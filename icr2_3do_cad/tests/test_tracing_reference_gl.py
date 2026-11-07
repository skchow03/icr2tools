"""OpenGL framebuffer test: photo sits behind geometry in all render modes."""
import os
import sys
import unittest
from dataclasses import replace
from pathlib import Path

import numpy as np

from mesh import make_mesh
from n3_compile import compile_n3_text
from scene import build_scene
from textures import build_atlas
from tracing_reference import initial_reference

HAS_DISPLAY = bool(os.environ.get("DISPLAY") or os.environ.get("WAYLAND_DISPLAY")
                   or sys.platform in ("win32", "darwin"))

SOURCE = """3D VERSION 3.0;
a: [<-1000,0,-1000>];
b: [<1000,0,-1000>];
c: [<0,0,1000>];
panel: POLY <44> {a,b,c};
root: LIST {panel};
"""


def framebuffer(view):
    from PySide6.QtGui import QImage
    view.update()
    view.repaint()
    qimage = view.grabFramebuffer().convertToFormat(
        QImage.Format.Format_RGBA8888)
    if qimage.isNull():
        raise AssertionError("OpenGL framebuffer is not available")
    return np.frombuffer(
        qimage.bits(), dtype=np.uint8, count=qimage.sizeInBytes()).reshape(
            qimage.height(), qimage.bytesPerLine())[:, :qimage.width()*4].reshape(
                qimage.height(), qimage.width(), 4).copy()


@unittest.skipUnless(HAS_DISPLAY, "Requires Qt OpenGL / Xvfb")
class TracingReferenceGLTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        try:
            from PySide6.QtGui import QSurfaceFormat, QImage, QColor
            from PySide6.QtWidgets import QApplication
            from icr2_3do_cad import GLViewport
        except (ImportError, SystemExit) as exc:
            raise unittest.SkipTest(str(exc))
        fmt = QSurfaceFormat()
        fmt.setVersion(3, 3)
        fmt.setProfile(QSurfaceFormat.OpenGLContextProfile.CoreProfile)
        fmt.setDepthBufferSize(24)
        QSurfaceFormat.setDefaultFormat(fmt)
        cls.app = QApplication.instance() or QApplication([])
        cls.Viewport = GLViewport
        cls.QImage = QImage
        cls.QColor = QColor

    def setUp(self):
        self.model, _ = compile_n3_text(
            SOURCE, "reference_test.3d", associate_planes=False)
        self.original = self.model.raw
        self.scene = build_scene(self.model)
        palette = np.zeros((256, 3), dtype=np.uint8)
        palette[44] = (50, 85, 130)
        atlas = build_atlas(self.scene.geometry, "reference_test.3d")
        mesh = make_mesh(
            self.scene.geometry, palette.astype(np.float32)/255, atlas)
        self.mesh = mesh
        self.view = self.Viewport()
        self.view.resize(640, 480)
        self.view.show()
        self.app.processEvents()
        self.assertTrue(self.view.context().isValid())
        self.view.set_mesh(mesh, self.model, atlas, palette, self.scene)
        self.view.set_view("Front")
        self.view.perspective = False
        self.view.half_height = 1.6
        self.photo = self.QImage(
            80, 80, self.QImage.Format.Format_RGBA8888)
        self.photo.fill(self.QColor(230, 35, 45))
        self.ref = replace(initial_reference(
            Path("reference.png"), 80, 80, mesh, plane="Front"),
            units_per_pixel=mesh.scale * 4 / 80, opacity=1.0)

    def tearDown(self):
        self.view.shutdown_gl()
        self.view.close()
        self.app.processEvents()

    @staticmethod
    def red_count(image):
        rgb = image[:, :, :3].astype(np.int16)
        return int(((rgb[:, :, 0] > 170) &
                    (rgb[:, :, 0] > rgb[:, :, 1] + 85) &
                    (rgb[:, :, 0] > rgb[:, :, 2] + 85)).sum())

    def test_image_is_background_and_geometry_remains_visible(self):
        self.view.set_render_mode("all")
        no_ref = framebuffer(self.view)
        before_model = self.view._model
        before_mesh = self.view._mesh
        before_pick = self.view.pick_nearest_polygon(320, 240)
        self.view.set_tracing_reference(self.ref, self.photo)
        after = framebuffer(self.view)
        self.assertIsNone(self.view.tracing_error)
        self.assertGreater(
            self.red_count(after)-self.red_count(no_ref), 1000)
        # The opaque central polygon is drawn AFTER the photo and must
        # not be covered by red pixels.
        self.assertTrue(np.allclose(
            after[240, 320, :3], no_ref[240, 320, :3], atol=3))
        self.assertIs(self.view._model, before_model)
        self.assertIs(self.view._mesh, before_mesh)
        self.assertEqual(
            self.view.pick_nearest_polygon(320, 240), before_pick)
        self.assertEqual(self.model.raw, self.original)

    def test_image_visible_in_painter_and_wireframe_and_toggle(self):
        for mode in ("painter", "wire", "depth"):
            with self.subTest(mode=mode):
                self.view.set_render_mode(mode)
                before = framebuffer(self.view)
                self.view.set_tracing_reference(self.ref, self.photo)
                visible = framebuffer(self.view)
                self.assertIsNone(self.view.tracing_error)
                self.assertGreater(
                    self.red_count(visible)-self.red_count(before), 1000)
                self.view.set_tracing_reference(
                    replace(self.ref, visible=False))
                hidden = framebuffer(self.view)
                self.assertLess(
                    abs(self.red_count(hidden)-self.red_count(before)), 40)
                self.view.set_tracing_reference(None)
        self.assertEqual(self.model.raw, self.original)


if __name__ == "__main__":
    unittest.main()
