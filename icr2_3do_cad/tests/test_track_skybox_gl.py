"""Real OpenGL background pass: HORIZ sky stays behind the track.

Uses synthetic models and a palette only; no game assets are committed.
"""
import os
import sys
import tempfile
import unittest
from pathlib import Path

import numpy as np

from n3_compile import compile_n3_text
from scene import build_scene
from mesh import make_mesh
from textures import build_atlas
from skybox import load_track_skybox

HAS_DISPLAY = bool(os.environ.get("DISPLAY") or
                   os.environ.get("WAYLAND_DISPLAY") or
                   sys.platform in ("win32", "darwin"))

TRACK_SOURCE = """3D VERSION 3.0;
a: [<-5000,-5000,0>];
b: [<5000,-5000,0>];
c: [<0,5000,0>];
p: POLY <60> {a,b,c};
root: LIST {p};
"""
SKY_SOURCE = """3D VERSION 3.0;
a: [<-50000,-50000,0>];
b: [<50000,-50000,0>];
c: [<50000,50000,0>];
d: [<-50000,50000,0>];
e: [<-50000,-50000,10000>];
f: [<50000,-50000,10000>];
g: [<50000,50000,10000>];
h: [<-50000,50000,10000>];
wall0: POLY <40> {a,b,f,e};
wall1: POLY <41> {b,c,g,f};
wall2: POLY <42> {c,d,h,g};
wall3: POLY <43> {d,a,e,h};
roof: POLY <44> {e,f,g,h};
floor: POLY <45> {d,c,b,a};
root: LIST {floor, roof, wall0, wall1, wall2, wall3};
"""


@unittest.skipUnless(HAS_DISPLAY, "Requires Qt/OpenGL desktop or Xvfb")
class TrackSkyboxGLTests(unittest.TestCase):
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
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.view = self.GLViewport()
        self.view.resize(640, 480)
        self.view.show()
        self.app.processEvents()
        self.assertTrue(self.view.context().isValid())

    def tearDown(self):
        self.view.shutdown_gl()
        self.view.close()
        self.app.processEvents()

    def screenshot(self):
        from PySide6.QtGui import QImage
        self.app.processEvents()
        image = self.view.grabFramebuffer()
        self.assertFalse(image.isNull())
        image = image.convertToFormat(QImage.Format.Format_RGBA8888)
        data = np.frombuffer(
            image.bits(), dtype=np.uint8, count=image.sizeInBytes())
        return data.reshape(image.height(), image.bytesPerLine())[
            :, :image.width() * 4].reshape(image.height(), image.width(), 4).copy()

    def test_skybox_default_on_toggle_off_and_track_stays_in_foreground(self):
        folder = Path(self.temp.name)
        track, _ = compile_n3_text(
            TRACK_SOURCE, folder/"putnam.3d", associate_planes=False)
        sky_model, _ = compile_n3_text(
            SKY_SOURCE, folder/"sky.3d", associate_planes=False)
        sky_file = folder / "horiz.3do"
        sky_file.write_bytes(sky_model.raw)
        palette = np.zeros((256, 3), dtype=np.uint8)
        palette[40:46] = (
            (0, 0, 150), (0, 80, 150), (0, 120, 180),
            (0, 160, 180), (0, 190, 220), (20, 100, 200))
        palette[60] = (255, 255, 0)
        scene = build_scene(track)
        sky = load_track_skybox(
            sky_file, palette.astype(np.float32)/255.0)
        scene.skybox = sky
        atlas = build_atlas(scene.geometry, folder/"putnam.3d")
        mesh = make_mesh(
            scene.geometry, palette.astype(np.float32)/255.0, atlas)
        self.view.set_mesh(mesh, track, atlas, palette, scene)
        self.view.set_view("Top")
        sky_on = self.screenshot()
        self.assertTrue(self.view.sky_enabled)
        self.assertIsNotNone(self.view._sky_vao)
        self.assertEqual(self.view._sky_index_count, sky.indices.size)
        self.view.sky_enabled = False
        self.view.update()
        sky_off = self.screenshot()
        changed = np.any(sky_on[..., :3] != sky_off[..., :3], axis=2)
        self.assertGreater(int(changed.sum()), 1000)
        # The sky cannot cover the track: it is drawn first without depth
        # and the track remains the final visible foreground at the center.
        midpoint = (sky_on.shape[0]//2, sky_on.shape[1]//2)
        np.testing.assert_array_equal(sky_on[midpoint][:3],
                                      sky_off[midpoint][:3])
        self.view.sky_enabled = True
        self.view.update()
        np.testing.assert_array_equal(self.screenshot(), sky_on)

    def test_background_ignores_camera_translation(self):
        # The skybox view transform is derived from rotation and fixed sky
        # coordinates; the main track camera can orbit/pan independently.
        from icr2_3do_cad import camera_view
        from skybox import skybox_view_matrix
        sky_model, _ = compile_n3_text(
            SKY_SOURCE, Path(self.temp.name)/"test.3d",
            associate_planes=False)
        from mesh import make_mesh
        mesh = make_mesh(build_scene(sky_model).geometry)
        a = camera_view(.3, .25, 5, np.array((0, 0, 0)))[0]
        b = camera_view(.3, .25, 50, np.array((99, -11, 0)))[0]
        np.testing.assert_allclose(
            skybox_view_matrix(a, mesh), skybox_view_matrix(b, mesh))


if __name__ == "__main__":
    unittest.main()
