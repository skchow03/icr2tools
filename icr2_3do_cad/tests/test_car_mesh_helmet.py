"""Split-car mesh helmets inherit driver body MIP and polygon RECOLOR.

Stock PMP/PMP2 helmets remain sprite-only, with their separate sprite recolor
path and no inherited body MIP. Never write referenced model or texture assets.
"""
from pathlib import Path
import shutil
import struct
import tempfile
import unittest

from scene import load_car_or_model, build_scene
from textures import build_atlas
from three_do import Model
from test_car_dynamic_livery import make_indycar, make_part, make_wrapper

FIX = Path(__file__).resolve().parents[1] / "fixtures"


class CarMeshHelmetTests(unittest.TestCase):
    def prepare(self, folder, *, helmet_material=None):
        make_part(folder / "helmet.3do", material=helmet_material)
        make_part(folder / "sfront.3do", material="wheel1")
        base = folder / "indycar.3do"
        make_indycar(base)
        # Synthetic base has a flpod and a sfront placement. Replace the
        # first 8-character external filename with the helmet resource.
        data = base.read_bytes()
        self.assertEqual(data.count(b"flpod\0\0\0"), 1)
        base.write_bytes(data.replace(b"flpod\0\0\0", b"helmet\0\0", 1))
        # The driver's MIP also includes a helmet region at V > 255.
        # Encode real UV values into its three textured mesh vertices.
        helmet = folder / "helmet.3do"
        raw = bytearray(helmet.read_bytes())
        for vertex, uv in enumerate(((2, 308), (98, 320), (30, 327))):
            struct.pack_into("<HH", raw, 20 + vertex * 20 + 16, *uv)
        helmet.write_bytes(raw)
        make_wrapper(folder / "ind95.3do")
        return folder / "ind95.3do"

    def child_faces(self, scene, name):
        return [(i, old, new, scene.geometry.polygons[new])
                for (i, old), new in scene.polygon_lookup.items()
                if scene.instances[i].model.path.stem.casefold() == name]

    def test_helmet_mesh_receives_driver_livery_and_recolor(self):
        with tempfile.TemporaryDirectory() as temp:
            folder = Path(temp)
            wrapper = self.prepare(folder)
            original = {p.name: p.read_bytes() for p in folder.iterdir()}
            _, scene, appearance = load_car_or_model(wrapper)
            self.assertEqual(appearance.texture_name, "ind95")
            helmets = [x for x in scene.instances
                       if x.model.path.stem.casefold() == "helmet"]
            self.assertEqual(len(helmets), 1)
            helmet = helmets[0]
            self.assertTrue(helmet.car_body)
            self.assertEqual(helmet.recolor_layers, (appearance.mapping,))
            self.assertEqual(helmet.texture_override, "ind95")
            self.assertEqual(helmet.texture_source, wrapper)
            helmet_faces = self.child_faces(scene, "helmet")
            self.assertEqual(len(helmet_faces), 2)
            for i, old, new, out in helmet_faces:
                raw = scene.instances[i].model.polygons[old]
                self.assertEqual(out.color, appearance.map_color(raw.color))
                if raw.kind == 2:
                    self.assertEqual(scene.geometry.polygon_materials[new], "ind95")
                    self.assertEqual(scene.geometry.polygon_sources[new], wrapper)
                    self.assertIn(new, scene.geometry.body_polygons)
            # Preserve the extended-MIP UVs: this helmet is not a PMP and
            # the driver bitmap can be taller than 256 pixels.
            self.assertTrue(any(v.uv is not None and v.uv[1] > 255
                                for v in scene.geometry.vertices.values()))
            self.assertEqual({p.name: p.read_bytes() for p in folder.iterdir()},
                             original)

    def test_helmet_mesh_manual_body_override_covers_helmet_not_wheel(self):
        with tempfile.TemporaryDirectory() as temp:
            folder = Path(temp)
            wrapper = self.prepare(folder)
            for name in ("ind95", "wheel1", "alternate"):
                shutil.copyfile(FIX / "ind96.mip", folder / (name + ".mip"))
            _, scene, _ = load_car_or_model(wrapper)
            regular = build_atlas(scene.geometry, wrapper)
            other = build_atlas(scene.geometry, wrapper,
                                body_mip=folder / "alternate.mip")
            self.assertEqual(set(regular.loaded_names),
                             {"ind95.mip", "wheel1.mip"})
            self.assertEqual(set(other.loaded_names),
                             {"alternate.mip", "wheel1.mip"})
            helmet_poly = next(
                new for i, old, new, face in self.child_faces(scene, "helmet")
                if face.kind == 2)
            self.assertIn(helmet_poly, regular.polygon_rects)
            self.assertIn(helmet_poly, other.polygon_rects)
            wheels = self.child_faces(scene, "sfront")
            for i, old, new, face in wheels:
                raw = scene.instances[i].model.polygons[old]
                self.assertEqual(face.color, raw.color)
                self.assertNotIn(new, scene.geometry.body_polygons)
                if raw.kind == 2:
                    self.assertEqual(scene.geometry.polygon_materials[new],
                                     "wheel1")

    def test_helmet_local_material_wins_over_driver_body_mip(self):
        with tempfile.TemporaryDirectory() as temp:
            folder = Path(temp)
            wrapper = self.prepare(folder, helmet_material="helmmip")
            _, scene, appearance = load_car_or_model(wrapper)
            for i, old, new, out in self.child_faces(scene, "helmet"):
                raw = scene.instances[i].model.polygons[old]
                self.assertEqual(out.color, appearance.map_color(raw.color))
                if raw.kind == 2:
                    self.assertEqual(scene.geometry.polygon_materials[new],
                                     "helmmip")
                    self.assertEqual(scene.geometry.polygon_sources[new],
                                     folder / "helmet.3do")
                    self.assertNotIn(new, scene.geometry.body_polygons)

    def test_default_sprite_helmet_still_has_no_body_mip(self):
        base = Model(FIX / "indycar.3do", associate_planes=False)
        from car_appearance import read_car_appearance
        app = read_car_appearance(FIX / "cit74.3do")
        scene = build_scene(base, objects_folder=FIX, appearance=app)
        helmet = next(x for x in scene.instances
                      if x.model.path.stem.casefold() == "helmet")
        self.assertFalse(helmet.model.polygons)
        self.assertFalse(helmet.car_body)
        self.assertIsNone(helmet.texture_override)
        self.assertFalse(helmet.recolor_layers)
        self.assertEqual(helmet.sprite_recolor_layers, (app.mapping,))

    def test_helmet_mesh_material_inheritance_without_wrapper(self):
        with tempfile.TemporaryDirectory() as temp:
            folder = Path(temp)
            self.prepare(folder)
            _, scene, app = load_car_or_model(folder / "indycar.3do")
            self.assertIsNone(app)
            helmet = next(x for x in scene.instances
                          if x.model.path.stem.casefold() == "helmet")
            self.assertTrue(helmet.car_body)
            textured = [new for _, _, new, face in self.child_faces(scene, "helmet")
                        if face.kind == 2]
            self.assertEqual(len(textured), 1)
            self.assertIn(textured[0], scene.geometry.body_polygons)


if __name__ == "__main__":
    unittest.main()
