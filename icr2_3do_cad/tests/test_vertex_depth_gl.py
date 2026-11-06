"""Actual OpenGL occlusion test for frontmost root-model vertex labels."""
import os
import sys
import unittest

import numpy as np

from mesh import make_mesh
from scene import build_scene
from textures import build_atlas
from n3_compile import compile_n3_text

DISPLAY = bool(os.environ.get("DISPLAY") or os.environ.get("WAYLAND_DISPLAY")
               or sys.platform in ("win32", "darwin"))

SOURCE = """3D VERSION 3.0;
back_a: [<-30000,-30000,0>];
back_b: [<30000,-30000,0>];
back_c: [<30000,30000,0>];
back_d: [<-30000,30000,0>];
front_a: [<-100000,-100000,50000>];
front_b: [<100000,-100000,50000>];
front_c: [<100000,100000,50000>];
front_d: [<-100000,100000,50000>];
back_face: POLY <42> {back_a,back_b,back_c,back_d};
front_face: POLY <43> {front_a,front_b,front_c,front_d};
root: LIST {back_face,front_face};
"""


def image(view):
    from PySide6.QtGui import QImage
    view.update()
    view.repaint()
    pixels = view.grabFramebuffer().convertToFormat(
        QImage.Format.Format_RGBA8888)
    return np.frombuffer(
        pixels.bits(), dtype=np.uint8, count=pixels.sizeInBytes()).copy()


@unittest.skipUnless(DISPLAY, "Requires desktop or Xvfb GL")
class GPUDepthVertexLabelGLTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        try:
            from PySide6.QtGui import QSurfaceFormat
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
        cls.GLViewport = GLViewport

    def setUp(self):
        self.model, _ = compile_n3_text(
            SOURCE, "depth_label.3d", associate_planes=False)
        self.original_raw = self.model.raw
        scene = build_scene(self.model)
        palette = np.zeros((256, 3), dtype=np.uint8)
        palette[42] = (120, 60, 90)
        palette[43] = (180, 150, 100)
        atlas = build_atlas(scene.geometry, "depth_label.3d")
        mesh = make_mesh(scene.geometry, palette.astype(np.float32) / 255, atlas)
        self.view = self.GLViewport()
        self.view.resize(640, 480)
        self.view.show()
        self.app.processEvents()
        self.assertTrue(self.view.context().isValid())
        self.view.set_mesh(mesh, self.model, atlas, palette, scene)
        self.view.set_view("Top")
        self.view.half_height = 1.5  # Keep outer/front square corners inside the frustum

    def tearDown(self):
        self.view.shutdown_gl()
        self.view.close()
        self.app.processEvents()

    def test_backside_points_hidden_in_painter_depth_all_and_wire(self):
        back = {self.model.n3_label_offsets[f"back_{letter}"]
                for letter in "abcd"}
        front = {self.model.n3_label_offsets[f"front_{letter}"]
                 for letter in "abcd"}
        for render_mode in ("painter", "depth", "all", "wire"):
            with self.subTest(render_mode=render_mode):
                self.view.set_render_mode(render_mode)
                self.view.set_all_vertex_labels(False)
                baseline = image(self.view)
                self.view.set_vertex_label_mode("visible")
                self.view.set_all_vertex_labels(True)
                after = image(self.view)
                shown = {row[0] for row in self.view._depth_visible_vertex_labels}
                self.assertIsNone(
                    self.view._vertex_depth_error,
                    f"Depth readback failed: {self.view._vertex_depth_error}")
                self.assertFalse(back & shown, f"Occluded rear vertices shown: {shown}")
                self.assertTrue(front & shown, f"No front vertices shown: {shown}")
                self.assertTrue(np.array_equal(baseline, after),
                                "Depth pass unexpectedly changed visible pixels")
                self.assertEqual(self.model.raw, self.original_raw)

    def test_toggle_off_and_all_mode_do_not_compute_depth(self):
        self.view.set_all_vertex_labels(True)
        self.view.set_vertex_label_mode("visible")
        image(self.view)
        self.assertIsInstance(self.view._depth_visible_vertex_labels, list)
        self.view.set_vertex_label_mode("all")
        image(self.view)
        self.assertEqual(self.view._depth_visible_vertex_labels, [])
        self.view.set_all_vertex_labels(False)
        image(self.view)
        self.assertEqual(self.view._depth_visible_vertex_labels, [])


if __name__ == "__main__":
    unittest.main()
