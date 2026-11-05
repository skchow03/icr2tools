"""Real GPU framebuffer check for distinct BSP arrow/vertex marker colors."""
import os
import sys
import unittest

import numpy as np
from gpu_viewer.appearance import DARK_COLORS
from gpu_viewer.mesh import make_mesh
from gpu_viewer.scene import build_scene
from gpu_viewer.textures import build_atlas
from n3_compile import compile_n3_text

DISPLAY = bool(os.environ.get("DISPLAY") or os.environ.get("WAYLAND_DISPLAY")
               or sys.platform in ("win32", "darwin"))

SOURCE = """3D VERSION 3.0;
a: [<-100000,-100000,0>];
b: [<100000,-100000,0>];
c: [<100000,100000,0>];
d: [<-100000,100000,0>];
panel: POLY <44> {a,b,c,d};
root: LIST {panel};
"""
POINTS = ((-80000, -80000, 0), (80000, -80000, 0),
          (-80000, 80000, 0))


def framebuffer(view):
    from PySide6.QtGui import QImage
    view.update()
    view.repaint()
    image = view.grabFramebuffer().convertToFormat(
        QImage.Format.Format_RGBA8888)
    if image.isNull():
        raise AssertionError("OpenGL framebuffer not available")
    pix = np.frombuffer(image.bits(), dtype=np.uint8,
                        count=image.sizeInBytes())
    return pix.reshape(image.height(), image.bytesPerLine())[
        :, :image.width()*4].reshape(image.height(), image.width(), 4).copy()


@unittest.skipUnless(DISPLAY, "Requires desktop or Xvfb OpenGL")
class BSPOverlayGLTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        try:
            from PySide6.QtGui import QSurfaceFormat
            from PySide6.QtWidgets import QApplication
            from gpu_viewer.main import GLViewport
        except (ImportError, SystemExit) as exc:
            raise unittest.SkipTest(str(exc))
        fmt = QSurfaceFormat()
        fmt.setVersion(3, 3)
        fmt.setProfile(QSurfaceFormat.OpenGLContextProfile.CoreProfile)
        fmt.setDepthBufferSize(24)
        QSurfaceFormat.setDefaultFormat(fmt)
        cls.app = QApplication.instance() or QApplication([])
        cls.Viewport = GLViewport

    def setUp(self):
        self.model, _ = compile_n3_text(
            SOURCE, "bsp_overlay.3d", associate_planes=False)
        self.original_bytes = self.model.raw
        scene = build_scene(self.model)
        palette = np.zeros((256, 3), dtype=np.uint8)
        palette[44] = (35, 35, 35)
        atlas = build_atlas(scene.geometry, "bsp_overlay.3d")
        mesh = make_mesh(scene.geometry, palette.astype(np.float32)/255., atlas)
        self.view = self.Viewport()
        self.view.resize(640, 480)
        self.view.show()
        self.app.processEvents()
        self.assertTrue(self.view.context().isValid())
        self.view.set_mesh(mesh, self.model, atlas, palette, scene)
        self.view.set_view("Top")
        self.view.half_height = 0.9

    def tearDown(self):
        self.view.shutdown_gl()
        self.view.close()
        self.app.processEvents()

    @staticmethod
    def cyan_pixels(image):
        r, g, b = (image[:, :, k].astype(np.int16) for k in (0, 1, 2))
        return int(((r < 100) & (g > 125) & (b > 150)).sum())

    def test_cyan_plane_winding_overlay_vs_yellow_single_vertex(self):
        for mode in ("all", "wire"):
            with self.subTest(mode=mode):
                self.view.set_render_mode(mode)
                self.view.set_source_inspection()
                baseline = framebuffer(self.view)
                self.view.set_source_inspection("bsp", plane_points=POINTS)
                selected = framebuffer(self.view)
                self.assertGreater(
                    self.cyan_pixels(selected) -
                    self.cyan_pixels(baseline), 160)
                self.view.set_source_inspection(
                    "vertex", self.model.n3_label_offsets["a"])
                single = framebuffer(self.view)
                self.assertLess(self.cyan_pixels(single), 15)
                self.assertEqual(self.model.raw, self.original_bytes)

    def test_custom_plane_colors_do_not_modify_geometry(self):
        before = self.view._mesh
        self.view.set_appearance_colors(dict(
            DARK_COLORS, viewport_bsp_vertex="#FF3355",
            viewport_bsp_arrow="#FF3355"))
        self.view.set_source_inspection("bsp", plane_points=POINTS)
        pix = framebuffer(self.view)
        r, g, b = (pix[:, :, k].astype(np.int16) for k in (0, 1, 2))
        pink = ((r > 175) & (g < 130) & (b > 45))
        self.assertGreater(int(pink.sum()), 160)
        self.assertIs(self.view._mesh, before)
        self.assertEqual(self.model.raw, self.original_bytes)


if __name__ == "__main__":
    unittest.main()
