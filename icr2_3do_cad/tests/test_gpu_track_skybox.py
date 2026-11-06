"""Track skybox discovery, transforms and read-only background preparation.

Synthetic N3 sky geometry exercises behavior without bundling a commercial
HORIZ.3DO or its MIP assets.
"""
import tempfile
import unittest
from pathlib import Path

import numpy as np

from gpu_viewer.skybox import (
    SKY_EYE, find_track_skybox, load_track_skybox,
    load_preferred_track_skybox, skybox_view_matrix,
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

    def test_horiz_n3_fallback_compiles_without_binary(self):
        track = self.folder / "track.3d"
        track.touch()
        source = self.folder / "HoRiZ.3D"
        source.write_text(SKY_SOURCE, encoding="utf-8")
        self.assertEqual(find_track_skybox(track), source)
        sky, warning = load_preferred_track_skybox(track, self.palette)
        self.assertIsNone(warning)
        self.assertEqual(sky.path, source)
        self.assertEqual(sky.mesh.polygon_count, 6)
        self.assertEqual(sky.indices.size, sky.mesh.triangle_count * 3)
        self.assertEqual(source.read_text(), SKY_SOURCE)

    def test_corrupt_horiz_3do_uses_valid_horiz_3d(self):
        track = self.folder / "track.3do"
        track.touch()
        invalid = self.folder / "HORIZ.3DO"
        invalid.write_bytes(b"broken")
        alternative = self.folder / "horiz.3d"
        alternative.write_text(SKY_SOURCE, encoding="utf-8")
        self.assertEqual(find_track_skybox(track), alternative)
        sky, warning = load_preferred_track_skybox(track, self.palette)
        self.assertEqual(sky.path, alternative)
        self.assertIn("HORIZ.3DO", warning)
        self.assertEqual(invalid.read_bytes(), b"broken")

    def test_valid_binary_precedes_n3_across_search_folders(self):
        track = self.folder / "track.3do"
        track.touch()
        source = self.folder / "horiz.3d"
        source.write_text(SKY_SOURCE, encoding="utf-8")
        objects = self.folder / "objects"
        objects.mkdir()
        binary = objects / "HORIZ.3DO"
        binary.write_bytes(self.model.raw)
        self.assertEqual(find_track_skybox(track), binary)
        sky, warning = load_preferred_track_skybox(track, self.palette)
        self.assertIsNone(warning)
        self.assertEqual(sky.path, binary)

    def test_nonrenderable_binary_falls_back_to_renderable_n3(self):
        track = self.folder / "track.3do"
        track.touch()
        binary = self.folder / "horiz.3do"
        source_empty = """3D VERSION 3.0;
root: DYNAMIC 0,0,0,0,0,0,1, EXTERN "missing";
"""
        empty, _ = compile_n3_text(
            source_empty, binary, associate_planes=False)
        binary.write_bytes(empty.raw)
        alternative = self.folder / "horiz.3d"
        alternative.write_text(SKY_SOURCE, encoding="utf-8")
        sky, warning = load_preferred_track_skybox(track, self.palette)
        self.assertEqual(sky.path, alternative)
        self.assertIn("no renderable skybox polygons", warning)

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
            (0, 0, -4900))
        self.assertEqual(path.read_bytes(), before)

    def test_sky_follows_rotation_but_ignores_camera_translation(self):
        sky = load_track_skybox(
            self._write_model(), self.palette)
        # CPU-only: no import of PySide6 or the OpenGL viewer is required.
        a = np.identity(4)
        a[:3, :3] = ((0, -1, 0), (1, 0, 0), (0, 0, 1))
        b = a.copy()
        b[:3, 3] = (12, -18, 4)  # main camera position should be ignored
        c = np.identity(4)
        c[:3, :3] = ((1, 0, 0), (0, 0, -1), (0, 1, 0))
        sky_a = skybox_view_matrix(a, sky.mesh)
        sky_b = skybox_view_matrix(b, sky.mesh)
        sky_c = skybox_view_matrix(c, sky.mesh)
        np.testing.assert_allclose(sky_a, sky_b)
        self.assertFalse(np.allclose(sky_a, sky_c))
        # View origin corresponds exactly to (0,0,100) in raw sky geometry.
        eye = (np.asarray(SKY_EYE) - np.asarray(sky.mesh.center)) / sky.mesh.scale
        np.testing.assert_allclose(sky_a @ np.r_[eye, 1.0], [0, 0, 0, 1])

    def test_user_sky_eye_offset_is_independent_of_track_camera(self):
        sky = load_track_skybox(self._write_model(), self.palette)
        view = np.identity(4)
        view[:3, 3] = (123.0, -567.0, 89.0)
        initial = skybox_view_matrix(view, sky.mesh)
        moved_eye = (250.0, -125.0, 2500.0)
        changed = skybox_view_matrix(view, sky.mesh, eye=moved_eye)
        self.assertFalse(np.allclose(initial, changed))
        expected_eye = (np.asarray(moved_eye) - sky.mesh.center) / sky.mesh.scale
        np.testing.assert_allclose(changed @ np.r_[expected_eye, 1.0],
                                   (0., 0., 0., 1.))
        other_main_view = view.copy()
        other_main_view[:3, 3] = (-900., 200., 400.)
        np.testing.assert_allclose(changed, skybox_view_matrix(
            other_main_view, sky.mesh, eye=moved_eye))
        self.assertEqual(tuple(SKY_EYE), (0.0, 0.0, 100.0))
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
