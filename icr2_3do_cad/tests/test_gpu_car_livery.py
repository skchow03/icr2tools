"""CPU-only regression tests for individual-car RECOLOR/MATERIAL/livery files."""
import struct
import shutil
import tempfile
import unittest
from pathlib import Path

import numpy as np

from gpu_viewer.car import TAG_RECOLOR, recolor_table, recolor_index
from gpu_viewer.scene import build_scene
from gpu_viewer.mesh import make_mesh
from gpu_viewer.textures import build_atlas
from three_do import Model


ROOT = Path(__file__).resolve().parents[1]


def write_car_wrapper(path, mappings, *, mip_name='race74', model_name='roadcar'):
    """Create a real standalone car 3DO: unreferenced RECOLOR + MATERIAL -> -1.

    The RECOLOR node is before the root MATERIAL and not reachable via
    the root traversal, like real stock individual car files.
    """
    pairs = [v for a, b in mappings for v in (a, b)]
    body = bytearray(struct.pack('<2i', TAG_RECOLOR, len(mappings)))
    body.extend(struct.pack('<' + 'i'*len(pairs), *pairs))
    body.extend(struct.pack('<i', -1))
    root = len(body)
    body.extend(struct.pack('<4i', -(1<<31)+4, 0, 0, -1))
    data = (struct.pack('<5i', len(body), root, 1, 0, 1) +
            mip_name.encode('ascii').ljust(8,b'\x00') +
            model_name.encode('ascii').ljust(8,b'\x00') + body)
    path.write_bytes(data)


class CarRecolorTests(unittest.TestCase):
    def test_wrapper_recolor_parsed_without_root_graph_reference(self):
        with tempfile.TemporaryDirectory() as tmp:
            folder = Path(tmp)
            wrapper = folder/'race74.3do'
            write_car_wrapper(wrapper, [(1, 160), (2, 152), (44, 73)])
            model = Model(wrapper, associate_planes=False)
            self.assertEqual(model.mip_names, ['race74'])
            self.assertEqual(model.external_names, ['roadcar'])
            self.assertEqual(len(model.polygons), 0)
            self.assertEqual(recolor_table(model), {1:160,2:152,44:73})
            self.assertEqual(recolor_index(44, (recolor_table(model),)), 73)
            self.assertEqual(recolor_index(99, (recolor_table(model),)), 99)
            self.assertEqual(model.raw,wrapper.read_bytes())

    def test_wrapper_loads_shared_geometry_and_applies_only_polygon_recolor(self):
        with tempfile.TemporaryDirectory() as tmp:
            folder = Path(tmp)
            wrapper = folder/'race74.3do'
            shape = folder/'ROADCAR.3DO'
            shutil.copyfile(ROOT/'fixtures'/'roadcar.3do', shape)
            car_model = Model(shape, associate_planes=False)
            base_colors = {p.color for p in car_model.polygons.values()}
            selected = min(base_colors)
            destination = (selected+99)%256
            write_car_wrapper(wrapper, [(selected, destination)])
            raw = wrapper.read_bytes()
            root = Model(wrapper, associate_planes=False)
            scene = build_scene(root)
            self.assertEqual(root.raw,raw)
            self.assertEqual(scene.recolor_pairs,1)
            self.assertEqual(len(scene.instances),2)
            self.assertGreater(len(scene.geometry.polygons),0)
            self.assertTrue(all(
                p.color == (destination if car_model.polygons[off].color == selected
                            else car_model.polygons[off].color)
                for (inst,off),polyref in scene.polygon_lookup.items()
                if inst == 1
                for p in [scene.geometry.polygons[polyref]]
            ))
            mapped=set(scene.geometry.polygon_materials.values())
            self.assertIn('race74',mapped)
            matching = [key for key,name in scene.geometry.polygon_materials.items()
                        if name == 'race74']
            self.assertTrue(matching)
            self.assertEqual(scene.geometry.polygon_sources[matching[0]],wrapper)

    def test_named_livery_mip_override_and_rebuild_detection(self):
        with tempfile.TemporaryDirectory() as tmp:
            folder = Path(tmp)
            wrapper = folder/'race74.3do'
            shape = folder/'roadcar.3do'
            shutil.copyfile(ROOT/'fixtures'/'roadcar.3do', shape)
            write_car_wrapper(wrapper, [(44,73)])
            original_mip=folder/'race74.mip'
            alternate=folder/'alternate.mip'
            shutil.copyfile(ROOT/'fixtures'/'ind96.mip', original_mip)
            shutil.copyfile(original_mip, alternate)
            # Change only one indexed pixel inside alternate; preserve header.
            raw=bytearray(alternate.read_bytes())
            offset = 4+struct.unpack_from('<i',raw,32)[0]
            raw[offset] = (raw[offset]+51)%256
            alternate.write_bytes(raw)
            scene=build_scene(Model(wrapper,associate_planes=False))
            atlas_a=build_atlas(scene.geometry,wrapper)
            atlas_b=build_atlas(scene.geometry,wrapper,
                                mip_overrides={'RaCe74':alternate})
            self.assertEqual(atlas_a.polygon_rects, atlas_b.polygon_rects)
            self.assertFalse(np.array_equal(atlas_a.pixels,atlas_b.pixels))
            self.assertEqual(atlas_a.loaded_names, ('race74.mip',))
            self.assertEqual(atlas_b.loaded_names, ('alternate.mip',))
            mesh_a=make_mesh(scene.geometry,atlas=atlas_a)
            mesh_b=make_mesh(scene.geometry,atlas=atlas_b)
            np.testing.assert_array_equal(mesh_a.vertices,mesh_b.vertices)

    def test_optional_external_carshape_override(self):
        with tempfile.TemporaryDirectory() as tmp:
            folder=Path(tmp)
            wrapper=folder/'race74.3do'
            write_car_wrapper(wrapper,[(44,73)],model_name='missing')
            shape=folder/'newshape.3do'
            shutil.copyfile(ROOT/'fixtures'/'roadcar.3do',shape)
            root=Model(wrapper,associate_planes=False)
            missing=build_scene(root)
            self.assertEqual(missing.loaded_instances,0)
            found=build_scene(root,object_overrides={'MISSING':shape})
            self.assertEqual(found.loaded_instances,1)
            self.assertGreater(len(found.geometry.polygons),0)

    def test_invalid_recolor_is_not_applied(self):
        with tempfile.TemporaryDirectory() as tmp:
            p=Path(tmp)/'bad.3do'
            write_car_wrapper(p,[(44,73),(44,100)])
            root=Model(p,associate_planes=False)
            self.assertEqual(recolor_table(root),{})


if __name__=='__main__':
    unittest.main()
