"""Real GL framebuffer regression: coplanar TSD lines over asphalt.

Synthetic geometry & palette, no copyrighted game textures. Runs in Xvfb.
"""
import os
import sys
import tempfile
import time
import unittest
from pathlib import Path

import numpy as np

from mesh import make_mesh
from scene import build_scene
from textures import build_atlas
from n3_compile import compile_n3_text

HAS_DISPLAY = bool(os.environ.get("DISPLAY") or
                   os.environ.get("WAYLAND_DISPLAY") or
                   sys.platform in ("win32", "darwin"))


SOURCE = """3D VERSION 3.0;
a: [<-100000,-100000,0>];
b: [<100000,-100000,0>];
c: [<100000,100000,0>];
d: [<-100000,100000,0>];
e: [<-22000,-60000,0>];
f: [<22000,-60000,0>];
g: [<22000,60000,0>];
h: [<-22000,60000,0>];
asphalt: POLY <20> {a,b,c,d};
tsd: POLY <30> {e,f,g,h};
tsd_line: LINE <30> {e,g};
detail_list: LIST {tsd, tsd_line};
high: LIST {asphalt, detail_list};
section: LIST {high, nil, nil, nil, nil, nil, nil,
               DATA {0,25000,50000,75000}};
hash: DATA {0};
root: LIST {hash, section};
"""


def framebuffer(view):
    from PySide6.QtGui import QImage
    view.update()
    view.repaint()
    image = view.grabFramebuffer()
    if image.isNull():
        raise AssertionError("OpenGL framebuffer unavailable")
    image = image.convertToFormat(QImage.Format.Format_RGBA8888)
    pixels = np.frombuffer(
        image.bits(), dtype=np.uint8, count=image.sizeInBytes())
    return pixels.reshape(image.height(), image.bytesPerLine())[
        :, :image.width() * 4].reshape(
        image.height(), image.width(), 4).copy()


@unittest.skipUnless(HAS_DISPLAY, "Requires Xvfb or desktop OpenGL")
class TSDDepthGLTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        try:
            from PySide6.QtGui import QSurfaceFormat
            from PySide6.QtWidgets import QApplication
            from icr2_3do_cad import GLViewport, Window
        except (ImportError, SystemExit) as exc:
            raise unittest.SkipTest(str(exc))
        fmt = QSurfaceFormat()
        fmt.setVersion(3, 3)
        fmt.setProfile(QSurfaceFormat.OpenGLContextProfile.CoreProfile)
        fmt.setDepthBufferSize(24)
        QSurfaceFormat.setDefaultFormat(fmt)
        cls.app = QApplication.instance() or QApplication([])
        cls.GLViewport = GLViewport
        cls.Window = Window

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.model_path = Path(self.temp.name) / "course.3d"
        self.model_path.write_text(SOURCE, encoding="utf8")
        self.model, _ = compile_n3_text(
            SOURCE, self.model_path, associate_planes=False)
        self.scene = build_scene(self.model)
        self.assertEqual(len(self.scene.track_surface_details), 1)
        palette = np.zeros((256, 3), dtype=np.uint8)
        palette[20] = (40, 40, 40)
        palette[30] = (250, 250, 250)
        self.palette = palette
        atlas = build_atlas(self.scene.geometry, self.model_path)
        mesh = make_mesh(
            self.scene.geometry, palette.astype(np.float32) / 255.0, atlas)
        self.view = self.GLViewport()
        self.view.resize(640, 480)
        self.view.show()
        self.app.processEvents()
        self.assertTrue(self.view.context().isValid())
        self.view.set_mesh(mesh, self.model, atlas, palette, self.scene)
        self.view.set_view("Top")
        self.view.half_height = 0.75
        self.view.set_render_mode("depth")

    def tearDown(self):
        self.view.shutdown_gl()
        self.view.close()
        self.app.processEvents()

    def test_coplanar_marking_is_depth_biased_above_base_polygon(self):
        with_tsd = framebuffer(self.view)
        self.assertEqual(self.view.render_mode, "depth")
        self.assertGreater(self.view._surface_index_count, 0)
        self.assertEqual(self.view._visibility_info["surface_detail_polygons"], 1)
        y, x = with_tsd.shape[0] // 2, with_tsd.shape[1] // 2
        # Center is inside both asphalt and TSD, whose Z values are exactly
        # identical. The second depth-biased pass must win the depth test.
        self.assertGreater(int(with_tsd[y, x, 0]), 225)
        self.assertGreater(int(with_tsd[y, x, 1]), 225)

        details = self.scene.track_surface_details
        self.scene.track_surface_details = frozenset()
        self.view.invalidate_visibility()
        without_tsd = framebuffer(self.view)
        self.assertEqual(self.view._surface_index_count, 0)
        self.assertLess(int(without_tsd[y, x, 0]), 100)
        changed = np.any(with_tsd[:, :, :3] != without_tsd[:, :, :3], axis=2)
        self.assertGreater(int(changed.sum()), 500)
        self.scene.track_surface_details = details
        self.view.invalidate_visibility()
        np.testing.assert_array_equal(framebuffer(self.view), with_tsd)

    def test_painter_and_depth_modes_preserve_polygon_selection(self):
        depth_img = framebuffer(self.view)
        base_index_count = self.view._index_count
        self.view.set_render_mode("painter")
        painted = framebuffer(self.view)
        self.assertEqual(self.view._surface_index_count, 0)
        self.assertEqual(self.view._index_count, base_index_count)
        self.assertGreater(int(painted[
            painted.shape[0]//2, painted.shape[1]//2, 0]), 225)
        self.view.set_render_mode("depth")
        self.assertTrue(np.array_equal(framebuffer(self.view), depth_img))

    def test_new_track_defaults_to_bsp_depth_but_manual_change_persists(self):
        # Test real Window -> LoadWorker -> _loaded integration, rather than
        # just changing the viewport's mode in isolation.
        window = self.Window()
        window.show()
        self.app.processEvents()
        try:
            window.load(self.model_path)
            deadline = time.monotonic() + 15.0
            while window.viewer._model is None and time.monotonic() < deadline:
                self.app.processEvents()
                time.sleep(0.01)
            self.assertIsNotNone(window.viewer._model)
            self.assertEqual(window.mode_combo.currentData(), "depth")
            self.assertEqual(window.viewer.render_mode, "depth")
            window.mode_combo.setCurrentIndex(window.mode_combo.findData("painter"))
            self.assertEqual(window.viewer.render_mode, "painter")
            window.load(self.model_path, reuse_model=True)
            deadline = time.monotonic() + 15.0
            while (window.worker is not None and window.worker.isRunning()
                   and time.monotonic() < deadline):
                self.app.processEvents()
                time.sleep(0.01)
            self.app.processEvents()
            self.assertEqual(window.mode_combo.currentData(), "painter")
        finally:
            window.close()
            self.app.processEvents()


if __name__ == "__main__":
    unittest.main()
