"""Real OpenGL color regression: selected white POLYs must remain obvious."""
import os
import sys
import unittest

import numpy as np

from appearance import DARK_COLORS
from mesh import make_mesh
from scene import build_scene
from textures import build_atlas
from n3_compile import compile_n3_text


HAS_DISPLAY = bool(os.environ.get("DISPLAY") or
                   os.environ.get("WAYLAND_DISPLAY") or
                   sys.platform in ("win32", "darwin"))

SOURCE = """3D VERSION 3.0;
a: [<-1000,-1000,0>];
b: [<1000,-1000,0>];
c: [<1000,1000,0>];
d: [<-1000,1000,0>];
panel: POLY <44> {a,b,c,d};
root: LIST {panel};
"""


def center_pixel(view):
    from PySide6.QtGui import QImage
    view.update()
    view.repaint()
    image = view.grabFramebuffer().convertToFormat(
        QImage.Format.Format_RGBA8888)
    if image.isNull():
        raise AssertionError("No GPU framebuffer")
    pixels = np.frombuffer(image.bits(), dtype=np.uint8,
                           count=image.sizeInBytes())
    data = pixels.reshape(image.height(), image.bytesPerLine())[
        :, :image.width() * 4].reshape(image.height(), image.width(), 4)
    return np.asarray(data[image.height() // 2,
                           image.width() // 2, :3], dtype=np.int16).copy()


@unittest.skipUnless(HAS_DISPLAY, "Requires real Qt/OpenGL desktop or Xvfb")
class PolygonHighlightGLTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        try:
            from PySide6.QtGui import QSurfaceFormat
            from PySide6.QtWidgets import QApplication
            from icr2_3do_cad import GLViewport
        except (ImportError, SystemExit) as error:
            raise unittest.SkipTest(str(error))
        format = QSurfaceFormat()
        format.setVersion(3, 3)
        format.setProfile(QSurfaceFormat.OpenGLContextProfile.CoreProfile)
        format.setDepthBufferSize(24)
        QSurfaceFormat.setDefaultFormat(format)
        cls.app = QApplication.instance() or QApplication([])
        cls.Viewport = GLViewport

    def setUp(self):
        self.model, _ = compile_n3_text(
            SOURCE, "poly_highlight.3d", associate_planes=False)
        self.raw = self.model.raw
        self.scene = build_scene(self.model)
        self.polygon = self.model.n3_label_offsets["panel"]
        self.palette = np.zeros((256, 3), dtype=np.uint8)
        self.palette[44] = (255, 255, 255)
        self.atlas = build_atlas(self.scene.geometry, "poly_highlight.3d")
        mesh = make_mesh(
            self.scene.geometry,
            self.palette.astype(np.float32) / 255., self.atlas)
        self.view = self.Viewport()
        self.view.resize(640, 480)
        self.view.show()
        self.app.processEvents()
        self.assertTrue(self.view.context().isValid())
        self.view.set_mesh(mesh, self.model, self.atlas,
                           self.palette, self.scene)
        self.view.set_view("Top")
        self.view.half_height = 0.75
        self.view.set_render_mode("all")

    def tearDown(self):
        self.view.shutdown_gl()
        self.view.close()
        self.app.processEvents()

    def test_white_poly_is_contrasting_blue_not_clipped_to_white(self):
        white = center_pixel(self.view)
        self.assertTrue(np.all(white >= 245), white)
        self.view.set_source_inspection("polygon", self.polygon)
        selected = center_pixel(self.view)
        self.assertGreater(int(selected[2]), int(selected[0]) + 70)
        self.assertLess(int(selected[0]), 140)
        self.assertGreater(int(np.abs(white-selected).max()), 70)
        self.assertEqual(self.model.raw, self.raw)

    def test_tint_is_customizable_without_reuploading_geometry(self):
        self.view.set_source_inspection("polygon", self.polygon)
        mesh_before = self.view._mesh
        colors = dict(DARK_COLORS, viewport_poly_tint_light="#E00070")
        self.view.set_appearance_colors(colors)
        colored = center_pixel(self.view)
        self.assertGreater(int(colored[0]), int(colored[1]) + 70)
        self.assertIs(self.view._mesh, mesh_before)
        self.palette[44] = (20, 20, 20)
        self.view.set_palette(self.palette)
        self.view.set_appearance_colors(dict(
            DARK_COLORS, viewport_poly_tint_dark="#00FF00"))
        dark_selected = center_pixel(self.view)
        self.assertGreater(int(dark_selected[1]),
                           int(dark_selected[0]) + 70)
        self.assertEqual(self.model.raw, self.raw)


if __name__ == "__main__":
    unittest.main()
