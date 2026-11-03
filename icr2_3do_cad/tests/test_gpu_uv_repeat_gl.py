"""Real OpenGL regression for per-MIP UV tiling, N3 source and binary 3DO.

A synthetic four-color texture atlas exercises multiple complete tiles.
No proprietary track or texture assets are included.
"""
import os
import sys
import unittest

import numpy as np

from n3_compile import compile_n3_text
from three_do import Model
from gpu_viewer.mesh import make_mesh
from gpu_viewer.scene import build_scene
from gpu_viewer.textures import TextureAtlas


HAS_DISPLAY = bool(os.environ.get("DISPLAY") or
                   os.environ.get("WAYLAND_DISPLAY") or
                   sys.platform in ("win32", "darwin"))

TILED_SOURCE = """3D VERSION 3.0;
a: [<-1000,-1000,0>, t=<0,0>];
b: [<1000,-1000,0>, t=<12,0>];
c: [<1000,1000,0>, t=<12,12>];
d: [<-1000,1000,0>, t=<0,12>];
quad: POLY [T] <44> {a,b,c,d};
root: MATERIAL GROUP=3, MIP="tile", quad;
"""


@unittest.skipUnless(HAS_DISPLAY, "Requires Qt/OpenGL desktop or Xvfb")
class RepeatedMIPRenderingTests(unittest.TestCase):
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
        self.view = self.Viewport()
        self.view.resize(640, 480)
        self.view.show()
        self.app.processEvents()
        self.assertTrue(self.view.context().isValid())

    def tearDown(self):
        self.view.shutdown_gl()
        self.view.close()
        self.app.processEvents()

    def _frame(self):
        from PySide6.QtGui import QImage
        self.app.processEvents()
        image = self.view.grabFramebuffer()
        self.assertFalse(image.isNull())
        image = image.convertToFormat(QImage.Format.Format_RGBA8888)
        pixels = np.frombuffer(
            image.bits(), dtype=np.uint8, count=image.sizeInBytes())
        return pixels.reshape(image.height(), image.bytesPerLine())[
            :, :image.width() * 4].reshape(image.height(), image.width(), 4).copy()

    def _install(self, *, binary):
        model, _ = compile_n3_text(
            TILED_SOURCE, "tile.3d", associate_planes=False)
        if binary:
            model = Model("tile.3do", raw_data=model.raw,
                          associate_planes=False)
        before = model.raw
        scene = build_scene(model)
        polygon_id = next(iter(scene.geometry.polygons))
        # Four independently colored quadrants in a single 4x4 image.
        pixels = np.array([
            [1, 1, 2, 2],
            [1, 1, 2, 2],
            [3, 3, 4, 4],
            [3, 3, 4, 4],
        ], dtype=np.uint8)
        atlas = TextureAtlas(
            pixels, {polygon_id: (0, 0, 4, 4)},
            loaded_names=("tile.mip",), textured_polygons=1)
        palette = np.zeros((256, 3), dtype=np.uint8)
        palette[1] = (255, 0, 0)
        palette[2] = (0, 255, 0)
        palette[3] = (0, 0, 255)
        palette[4] = (255, 255, 0)
        mesh = make_mesh(scene.geometry,
                         palette.astype(np.float32)/255.0, atlas)
        self.assertEqual(mesh.triangle_count, 2)
        self.assertGreater(float(mesh.vertices[:, 7:9].max()), 4.0)
        self.view.set_mesh(mesh, model, atlas, palette, scene)
        self.view.set_view("Top")
        self.app.processEvents()
        self.assertTrue(self.view.texture_repeat)
        self.assertEqual(model.raw, before)
        return mesh

    def test_out_of_range_uvs_tile_for_3d_and_3do(self):
        for binary in (False, True):
            with self.subTest(binary=binary):
                mesh = self._install(binary=binary)
                repeat = self._frame()
                self.view.texture_repeat = False
                self.view.update()
                clamp = self._frame()
                changed = np.any(repeat[..., :3] != clamp[..., :3], axis=2)
                self.assertGreater(int(changed.sum()), 500)
                # Clamp is an alternate preview only: no UVs/VBO are rebuilt.
                self.assertIs(self.view._mesh, mesh)
                self.view.texture_repeat = True
                self.view.update()
                np.testing.assert_array_equal(self._frame(), repeat)


if __name__ == "__main__":
    unittest.main()
