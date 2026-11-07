"""Driver MIP/RECOLOR must reach external car bodywork, not wheels/helmet.

Synthetic binary fixtures model the split DYNAMIC flpod arrangement used by
modern ICR2 carsets. The child has textured faces but no MATERIAL of its own.
"""
from pathlib import Path
import shutil
import struct
import tempfile
import unittest

from scene import load_car_or_model
from textures import build_atlas

FIX = Path(__file__).resolve().parents[1] / "fixtures"
TAG = -(1 << 31)


def make_part(path, *, material=None):
    body = bytearray()
    refs = []
    for xyz in ((0, 0, 0), (1000, 0, 0), (0, 1000, 0)):
        refs.append(len(body))
        body.extend(struct.pack("<4iHH", 0, *xyz, 0, 0))
    textured = len(body)
    body.extend(struct.pack("<4i3i", TAG + 2, 0, 12, 2, *refs))
    solid = len(body)
    body.extend(struct.pack("<3i3i", TAG + 1, 30, 2, *refs))
    root = len(body)
    body.extend(struct.pack("<4i", TAG + 11, 2, textured, solid))
    if material:
        child = root
        root = len(body)
        body.extend(struct.pack("<4i", TAG + 4, 0, 0, child))
    names = material.encode().ljust(8, b"\0") if material else b""
    path.write_bytes(struct.pack("<5i", len(body), root,
                                 bool(material), 0, 0) + names + body)


def make_indycar(path):
    body = bytearray()
    refs = []
    for xyz in ((0, 0, 0), (1000, 0, 0), (0, 1000, 0)):
        refs.append(len(body))
        body.extend(struct.pack("<4iHH", 0, *xyz, 0, 0))
    tub = len(body)
    body.extend(struct.pack("<4i3i", TAG + 2, 0, 12, 2, *refs))
    placements = []
    for index in (1, 2):
        placements.append(len(body))
        body.extend(struct.pack("<8i", TAG + 15, 0, 0, 0,
                                0, 0, 0, -index))
    root = len(body)
    body.extend(struct.pack("<5i", TAG + 11, 3, tub, *placements))
    names = b"flpod\0\0\0" + b"sfront\0\0"
    path.write_bytes(struct.pack("<5i", len(body), root, 0, 0, 2)
                     + names + body)


def make_wrapper(path):
    body = bytearray(struct.pack("<2i", TAG + 14, 2))
    body.extend(struct.pack("<4i", 12, 77, 30, 55))
    root = len(body)
    body.extend(struct.pack("<4i", TAG + 4, 0, 0, 0))
    path.write_bytes(
        struct.pack("<5i", len(body), root, 1, 0, 1)
        + b"ind95\0\0\0" + b"indycar\0" + body)


class DynamicCarLiveryTests(unittest.TestCase):
    def prepare(self, folder, *, pod_material=None):
        make_part(folder / "flpod.3do", material=pod_material)
        make_part(folder / "sfront.3do", material="wheel1")
        make_indycar(folder / "indycar.3do")
        make_wrapper(folder / "ind95.3do")
        return folder / "ind95.3do"

    @staticmethod
    def parts(scene, basename):
        return [
            (inst, old, scene.geometry.polygons[new], new)
            for (inst, old), new in scene.polygon_lookup.items()
            if scene.instances[inst].model.path.stem.casefold() == basename
        ]

    def test_wrapper_reaches_unmaterialed_pod_but_not_wheel(self):
        with tempfile.TemporaryDirectory() as tmp:
            folder = Path(tmp)
            wrapper = self.prepare(folder)
            before = {p: p.read_bytes() for p in folder.iterdir()}
            _, scene, app = load_car_or_model(wrapper)
            self.assertEqual(app.texture_name, "ind95")
            self.assertEqual(len(scene.instances), 3, scene.warnings)
            pods = self.parts(scene, "flpod")
            wheels = self.parts(scene, "sfront")
            self.assertEqual(len(pods), 2)
            self.assertEqual(len(wheels), 2)

            for inst, old, painted, new in pods:
                raw = scene.instances[inst].model.polygons[old]
                self.assertEqual(painted.color, {12: 77, 30: 55}[raw.color])
                if raw.kind == 2:
                    self.assertEqual(scene.geometry.polygon_materials[new], "ind95")
                    self.assertEqual(scene.geometry.polygon_sources[new], wrapper)
                    self.assertIn(new, scene.geometry.body_polygons)

            for inst, old, painted, new in wheels:
                raw = scene.instances[inst].model.polygons[old]
                self.assertEqual(painted.color, raw.color)
                self.assertNotIn(new, scene.geometry.body_polygons)
                if raw.kind == 2:
                    self.assertEqual(scene.geometry.polygon_materials[new], "wheel1")
                    self.assertEqual(scene.geometry.polygon_sources[new],
                                     folder / "sfront.3do")
            self.assertEqual(before, {p: p.read_bytes() for p in folder.iterdir()})

    def test_manual_body_mip_also_covers_pod_and_keeps_wheel_texture(self):
        with tempfile.TemporaryDirectory() as tmp:
            folder = Path(tmp)
            wrapper = self.prepare(folder)
            for name in ("ind95", "wheel1", "alternate"):
                shutil.copyfile(FIX / "ind96.mip", folder / (name + ".mip"))
            _, scene, _ = load_car_or_model(wrapper)
            base = build_atlas(scene.geometry, wrapper)
            replacement = build_atlas(
                scene.geometry, wrapper, body_mip=folder / "alternate.mip")
            self.assertEqual(set(base.loaded_names), {"ind95.mip", "wheel1.mip"})
            self.assertEqual(set(replacement.loaded_names),
                             {"alternate.mip", "wheel1.mip"})
            self.assertEqual(set(base.polygon_rects),
                             set(replacement.polygon_rects))
            pod_texture = next(new for inst, old, _, new in self.parts(scene, "flpod")
                               if scene.instances[inst].model.polygons[old].kind == 2)
            self.assertIn(pod_texture, scene.geometry.body_polygons)

    def test_child_explicit_material_overrides_inherited_mip(self):
        with tempfile.TemporaryDirectory() as tmp:
            folder = Path(tmp)
            wrapper = self.prepare(folder, pod_material="podtex")
            _, scene, _ = load_car_or_model(wrapper)
            textured = [
                (inst, old, p, new) for inst, old, p, new
                in self.parts(scene, "flpod")
                if scene.instances[inst].model.polygons[old].kind == 2
            ]
            self.assertEqual(len(textured), 1)
            _, _, face, new = textured[0]
            self.assertEqual(face.color, 77)  # RECOLOR still applies
            self.assertEqual(scene.geometry.polygon_materials[new], "podtex")
            self.assertNotIn(new, scene.geometry.body_polygons)

    def test_body_mip_targets_pods_even_without_driver_wrapper(self):
        with tempfile.TemporaryDirectory() as tmp:
            folder = Path(tmp)
            self.prepare(folder)
            _, scene, app = load_car_or_model(folder / "indycar.3do")
            self.assertIsNone(app)
            pods = self.parts(scene, "flpod")
            wheels = self.parts(scene, "sfront")
            self.assertTrue(any(new in scene.geometry.body_polygons
                                for _, _, _, new in pods))
            self.assertTrue(all(new not in scene.geometry.body_polygons
                                for _, _, _, new in wheels))


if __name__ == "__main__":
    unittest.main()
