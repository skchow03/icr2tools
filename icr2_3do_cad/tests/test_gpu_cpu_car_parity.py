"""Regression: CPU-style individual-car appearance and body-only livery targeting.

A genuine Papyrus individual-car file has MATERIAL->RECOLOR(0), NOT a
MATERIAL->external geometry child. This was masked by the earlier synthetic
GPU test, which mistakenly put -1 in the MATERIAL child pointer.
"""
from pathlib import Path
import shutil
import struct
import tempfile
import unittest

import numpy as np

from car_appearance import read_car_appearance
from gpu_viewer.scene import load_car_or_model
from gpu_viewer.textures import build_atlas
from gpu_viewer.mesh import make_mesh
from three_do import Model

ROOT = Path(__file__).resolve().parents[1]


def make_real_car_wrapper(path, *, geometry='roadcar', livery='car74',
                          recolors=((44, 151),)):
    body = bytearray()
    body.extend(struct.pack('<2i', -(1 << 31) + 14, len(recolors)))
    for source, dest in recolors:
        body.extend(struct.pack('<2i', source, dest))
    if len(body) % 4:
        raise ValueError('Misaligned RECOLOR table')
    root = len(body)
    # Child 0 is the REAL RECOLOR pointer, not an external -1 pointer.
    body.extend(struct.pack('<4i', -(1 << 31) + 4, 0, 0, 0))
    names = livery.encode().ljust(8, b'\0') + geometry.encode().ljust(8, b'\0')
    path.write_bytes(struct.pack('<5i', len(body), root, 1, 0, 1)
                     + names + body)


def make_wheel_child(path):
    """Synthetic wheel with an independent wheel1 MATERIAL and POLY[T]."""
    body = bytearray()
    refs = []
    for xyz in ((0,0,0), (16000,0,0), (0,16000,0)):
        refs.append(len(body))
        body.extend(struct.pack('<4iHH', 0, *xyz, 0, 0))
    poly = len(body)
    body.extend(struct.pack('<4i3i', -(1<<31)+2, 0, 110, 2, *refs))
    root = len(body)
    body.extend(struct.pack('<4i', -(1<<31)+4, 0, 0, poly))
    path.write_bytes(struct.pack('<5i', len(body), root, 1, 0, 0)
                     + b'wheel1\\0\\0' + body)


class GPUCarWrapperParityTests(unittest.TestCase):
    def test_true_material_recolor_wrapper_loads_its_base_3do(self):
        with tempfile.TemporaryDirectory() as d:
            folder = Path(d)
            wrapper = folder / 'car74.3do'
            make_real_car_wrapper(wrapper)
            base = folder / 'ROADCAR.3DO'
            shutil.copyfile(ROOT / 'fixtures' / 'roadcar.3do', base)
            raw = wrapper.read_bytes()
            cpu = read_car_appearance(wrapper)
            self.assertEqual(cpu.geometry_name, 'roadcar')
            self.assertEqual(cpu.texture_name, 'car74')
            self.assertEqual(cpu.mapping, {44:151})
            self.assertEqual(Model(wrapper, associate_planes=False).polygons, {})
            model, scene, appearance = load_car_or_model(wrapper)
            self.assertEqual(model.path, base)
            self.assertEqual(appearance, cpu)
            self.assertEqual(scene.recolor_pairs, 1)
            self.assertGreater(len(scene.geometry.body_polygons), 0)
            self.assertGreater(len(scene.geometry.polygons), 0)
            self.assertEqual(wrapper.read_bytes(), raw)
            for offset, p in model.polygons.items():
                generated = scene.geometry.polygons[scene.polygon_lookup[0, offset]]
                self.assertEqual(generated.color, cpu.map_color(p.color))
                if p.kind == 2:
                    poly_id = scene.polygon_lookup[0, offset]
                    self.assertEqual(scene.geometry.polygon_materials[poly_id], 'car74')
                    self.assertEqual(scene.geometry.polygon_sources[poly_id], wrapper)

    def test_recolor_and_livery_do_not_leak_onto_wheels(self):
        with tempfile.TemporaryDirectory() as d:
            folder = Path(d)
            wrapper = folder / 'car74.3do'
            make_real_car_wrapper(wrapper, recolors=((44, 199), (110, 201)))
            base = folder / 'roadcar.3do'
            shutil.copyfile(ROOT / 'fixtures' / 'roadcar.3do', base)
            for nm in ('sfront', 'srear', 'helmet'):
                make_wheel_child(folder / (nm+'.3do'))
            model, scene, app = load_car_or_model(wrapper)
            self.assertGreater(scene.loaded_instances, 0)
            for (inst,off),poly_id in scene.polygon_lookup.items():
                orig = scene.instances[inst].model.polygons[off].color
                expected = app.map_color(orig) if inst == 0 else orig
                self.assertEqual(scene.geometry.polygons[poly_id].color, expected)
            # Texture override targeted at body faces MUST not touch
            # children's atlas assignments even with identical MIP pixels.
            livery = folder / 'car74.mip'
            wheels = folder / 'wheel1.mip'
            shutil.copyfile(ROOT/'fixtures'/'ind96.mip', livery)
            shutil.copyfile(ROOT/'fixtures'/'ind96.mip', wheels)
            alt = folder / 'newbody.mip'
            shutil.copyfile(livery, alt)
            # Explicit body assignment changes root-face atlas labels only.
            base_atlas = build_atlas(scene.geometry, wrapper)
            swapped = build_atlas(scene.geometry, wrapper, body_mip=alt)
            self.assertTrue(base_atlas.polygon_rects)
            for poly_id in base_atlas.polygon_rects:
                if poly_id not in scene.geometry.body_polygons:
                    self.assertIn(poly_id, swapped.polygon_rects)
            self.assertEqual(scene.geometry.polygon_materials[
                next(iter(scene.geometry.body_polygons))], 'car74')
            self.assertIn('newbody.mip', swapped.loaded_names)
            np.testing.assert_array_equal(
                make_mesh(scene.geometry, atlas=base_atlas).vertices[:, :9],
                make_mesh(scene.geometry, atlas=swapped).vertices[:, :9])

    def test_manual_carshape_override_and_actionable_missing_diagnostics(self):
        with tempfile.TemporaryDirectory() as d:
            folder = Path(d)
            wrapper = folder / 'missingcar.3do'
            make_real_car_wrapper(wrapper, geometry='indycar', livery='cit74')
            model, scene, app = load_car_or_model(wrapper)
            self.assertEqual(model.path, wrapper)
            self.assertEqual(scene.loaded_instances, 0)
            self.assertIn('Assign carshape', ' '.join(scene.warnings))
            base = folder / 'alternate.3do'
            shutil.copyfile(ROOT/'fixtures'/'roadcar.3do', base)
            model, scene, app = load_car_or_model(
                wrapper, object_overrides={'INDYCAR': base})
            self.assertEqual(model.path, base)
            self.assertGreater(len(scene.geometry.polygons), 0)
            self.assertEqual(app.geometry_name, 'indycar')

    def test_plain_geometry_offers_body_mip_but_keeps_dynamic_child_material(self):
        model = Model(ROOT/'fixtures'/'roadcar.3do', associate_planes=False)
        _,scene,app = load_car_or_model(model.path, existing_model=model)
        self.assertIsNone(app)
        self.assertGreater(len(scene.geometry.body_polygons), 0)
        with tempfile.TemporaryDirectory() as d:
            body = Path(d)/'body.mip'
            shutil.copyfile(ROOT/'fixtures'/'ind96.mip', body)
            atlas = build_atlas(scene.geometry, model.path, body_mip=body)
            # Some fixture wheel materials are present and resolve their
            # own MIPs; only insist all root car faces use the new body MIP.
            self.assertTrue(
                set(scene.geometry.body_polygons).issubset(atlas.polygon_rects))
            self.assertEqual(atlas.loaded_names, ('body.mip',))


if __name__ == '__main__':
    unittest.main()
