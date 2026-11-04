"""Track skybox discovery, transforms and read-only background preparation.

Synthetic N3 sky geometry exercises behavior without bundling a commercial
HORIZ.3DO or its MIP assets.
"""
import tempfile
import unittest
from pathlib import Path

import numpy as np

from gpu_viewer.skybox import (
    SKY_EYE, find_track_skybox, load_track_skybox, skybox_view_matrix,
)
from gpu_viewer.scene import build_scene
from n3_compile import compile_n3_text


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


class TrackSkyboxTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.folder = Path(self.tmp.name)
        self.palette = np.zeros((256, 3), dtype=np.float32)
        self.palette[40:46] = 1.0
        self.model, _ = compile_n3_text(
            SKY_SOURCE, self.folder / "sky.3d", associate_planes=False)

    def test_case_insensitive_track_folder_and_object_folder_search(self):
        track = self.folder / "putnam.3d"
        track.touch()
        self.assertIsNone(find_track_skybox(track))
        sky = self.folder / "HORIZ.3DO"
        sky.write_bytes(self.model.raw)
        self.assertEqual(find_track_skybox(track), sky)
        sky.unlink()
        objects = self.folder / "assets"
        objects.mkdir()
        nested = objects / "hOrIz.3Do"
        nested.write_bytes(self.model.raw)
        self.assertEqual(find_track_skybox(track, objects), nested)
        self.assertIsNone(find_track_skybox(self.folder / "other" / "track.3do"))

    def test_background_mesh_is_independent_and_preserves_binary(self):
        path = self.folder / "horiz.3do"
        path.write_bytes(self.model.raw)
        before = path.read_bytes()
        sky = load_track_skybox(path, self.palette)
        self.assertEqual(sky.path, path)
        self.assertEqual(sky.mesh.polygon_count, 6)
        self.assertEqual(sky.indices.size, sky.mesh.triangle_count * 3)
        self.assertEqual(sky.mesh.center, (0.0, 0.0, 5000.0))
        self.assertEqual(sky.mesh.scale, 50000.0)
        np.testing.assert_allclose(
            np.asarray(SKY_EYE) - np.asarray(sky.mesh.center),
            (0, 0, -4000))
        self.assertEqual(path.read_bytes(), before)

    def test_sky_follows_rotation_but_ignores_camera_translation(self):
        from gpu_viewer.main import camera_view
        sky = load_track_skybox(
            self._write_model(), self.palette)
        a, _, _ = camera_view(0.4, 0.3, 4.0, np.array((0, 0, 0)))
        b, _, _ = camera_view(0.4, 0.3, 32.0, np.array((10, -8, 2)))
        c, _, _ = camera_view(0.8, -0.2, 4.0, np.array((0, 0, 0)))
        sky_a = skybox_view_matrix(a, sky.mesh)
        sky_b = skybox_view_matrix(b, sky.mesh)
        sky_c = skybox_view_matrix(c, sky.mesh)
        np.testing.assert_allclose(sky_a, sky_b)
        self.assertFalse(np.allclose(sky_a, sky_c))
        # View origin corresponds exactly to (0,0,1000) in raw sky geometry.
        eye = (np.asarray(SKY_EYE) - np.asarray(sky.mesh.center)) / sky.mesh.scale
        np.testing.assert_allclose(sky_a @ np.r_[eye, 1.0], [0, 0, 0, 1])

    def test_track_scene_remains_unchanged_after_background_preparation(self):
        from gpu_viewer.mesh import make_mesh
        source = """3D VERSION 3.0;
a: [<0,0,0>];
b: [<300,0,0>];
c: [<0,300,0>];
p: POLY <55> {a,b,c};
root: LIST {p};
"""
        track, _ = compile_n3_text(source, self.folder / "track.3d",
                                   associate_planes=False)
        scene = build_scene(track)
        before = make_mesh(scene.geometry)
        sky = load_track_skybox(self._write_model(), self.palette)
        scene.skybox = sky
        after = make_mesh(scene.geometry)
        self.assertFalse(scene.track_section_lods)
        np.testing.assert_array_equal(before.vertices, after.vertices)
        self.assertEqual(before.center, after.center)
        self.assertEqual(before.scale, after.scale)
        self.assertEqual(scene.root.raw, track.raw)

    def _write_model(self):
        path = self.folder / "horiz.3do"
        path.write_bytes(self.model.raw)
        return path


if __name__ == "__main__":
    unittest.main()
