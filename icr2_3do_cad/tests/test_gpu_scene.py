"""CPU-only GPU scene regressions: orthographic BSP, DYNAMIC, RES/LOD.

No Qt/OpenGL or proprietary RENO asset required.
"""
import math
import shutil
import struct
import tempfile
import unittest
from pathlib import Path

import numpy as np

from dynamic_scene import placement_transform
from gpu_viewer.mesh import make_mesh
from gpu_viewer.scene import build_scene, ordered_scene_indices
from n3_compile import compile_n3_text
from three_do import Model


ROOT = Path(__file__).resolve().parents[1]


def make_child(path):
    """A tiny DYNAMIC child with ordinary polygon geometry."""
    body = bytearray()
    verts = []
    for xyz in ((0,0,0),(20000,0,0),(0,20000,0)):
        verts.append(len(body))
        body.extend(struct.pack('<4i',0,*xyz))
    poly = len(body)
    body.extend(struct.pack('<3i',-(1<<31)+1,44,2))
    for off in verts:
        body.extend(struct.pack('<i',off))
    node = len(body)
    body.extend(struct.pack('<3i',-(1<<31)+11,1,poly))
    path.write_bytes(struct.pack('<5i',len(body),node,0,0,0) + body)


class OrthographicBSPTests(unittest.TestCase):
    def test_parallel_ray_side_is_independent_of_finite_camera_distance(self):
        src = """3D VERSION 3.0;
nil: NIL;
a: [<0,0,0>]; b: [<100,0,0>]; c: [<0,100,0>];
p: POLY <44> {a,b,c};
root: FACE (a,b,c), p;
"""
        model, _ = compile_n3_text(src, 'ortho_test.3d',
                                   associate_planes=False)
        p = next(iter(model.polygons))
        a, _, _ = model.switched_polygons(
            0, (0,0,1000), 'original', view_direction=(0,0,1))
        b, _, _ = model.switched_polygons(
            0, (0,0,-1000), 'original', view_direction=(0,0,1))
        self.assertEqual(a,b)
        self.assertEqual(a,[p])
        different, _, _ = model.switched_polygons(
            0, (0,0,-1000), 'original')
        self.assertNotEqual(different,a)

    def test_perspective_switched_polygons_remains_unchanged(self):
        model = Model(ROOT/'fixtures'/'roadcar.3do', associate_planes=False)
        for eye in ((-36000,-80000,7000),(-36000,80000,7000)):
            expected,_,_ = model.switched_polygons(0,eye,'original')
            new,_,_ = model.switched_polygons(
                0,eye,'original',view_direction=None)
            self.assertEqual(new,expected)

    def test_auto_res_uses_each_own_anchor(self):
        model = Model(ROOT/'fixtures'/'roadcar.3do', associate_planes=False)
        self.assertTrue(model.switches)
        for eye in ((0,0,0),(300000,200000,100000)):
            _,_,choices = model.switched_polygons('auto',eye,'original')
            self.assertTrue(choices)
            for switch, threshold, ptr in choices:
                obj=model.switches[switch]
                distance=math.dist(eye,model.vertices[obj.anchor].xyz)
                self.assertEqual(obj.choose(distance),(threshold,ptr))
        _,_,all_lods = model.switched_polygons(None,(0,0,0),'original')
        self.assertEqual(all_lods, [])

    def test_invalid_direction_and_auto_distance_fail_explicitly(self):
        m=Model(ROOT/'fixtures'/'roadcar.3do',associate_planes=False)
        for value in ((),(0,0,0),(math.inf,0,0)):
            with self.assertRaises(ValueError):
                m.switched_polygons(0,(0,0,0),'original',
                                    view_direction=value)
        with self.assertRaises(ValueError):
            m.switched_polygons(float('nan'),(0,0,0),'original')


class GPUSceneTests(unittest.TestCase):
    def _setup_scene(self, path):
        for name in ('SFRONT.3DO','SREAR.3DO','HELMET.3DO'):
            make_child(path.parent/name)
        model=Model(path,associate_planes=False)
        before=model.raw
        scene=build_scene(model)
        self.assertEqual(before,model.raw)
        return model,scene

    def test_dynamic_instances_built_distinctly_and_transformed(self):
        with tempfile.TemporaryDirectory() as temp:
            path=Path(temp)/'roadcar.3do'
            shutil.copyfile(ROOT/'fixtures'/'roadcar.3do',path)
            model,scene=self._setup_scene(path)
            self.assertEqual(scene.loaded_instances,5)
            self.assertEqual(scene.warnings,())
            self.assertGreater(len(scene.geometry.polygons),len(model.polygons))
            self.assertEqual(len(set(scene.polygon_lookup.values())),
                             len(scene.polygon_lookup))
            # The same SFRONT model appears more than once but each placement
            # has unique translated/rotated vertex coordinates.
            first=scene.links[(0,'dynamic',5268)]
            rotated=scene.links[(0,'dynamic',5300)]
            self.assertIs(scene.instances[first].model,scene.instances[rotated].model)
            v=next(iter(scene.instances[rotated].model.vertices.values()))
            expected=placement_transform(model.dynamics[5300]).apply(v.xyz)
            localid=next(iter(scene.instances[rotated].model.vertices))
            localref=scene.polygon_lookup[(rotated,next(iter(
                scene.instances[rotated].model.polygons)))]
            p=scene.geometry.polygons[localref]
            found=[scene.geometry.vertices[ref].xyz for ref in p.unique_refs]
            self.assertIn(expected,found)

    def test_nested_painter_order_includes_dynamic_at_insertion_site(self):
        with tempfile.TemporaryDirectory() as temp:
            path=Path(temp)/'roadcar.3do'
            shutil.copyfile(ROOT/'fixtures'/'roadcar.3do',path)
            model,scene=self._setup_scene(path)
            mesh=make_mesh(scene.geometry)
            eye=(-36000,-80000,7000)
            indices,root,info=ordered_scene_indices(scene,mesh,eye,0)
            self.assertEqual(indices.dtype,np.uint32)
            self.assertEqual(info['instances_visited'],6)
            self.assertGreater(info['mesh_polygons'],0)
            self.assertGreater(info['triangles'],0)
            self.assertTrue((indices<len(mesh.vertices)).all())
            self.assertTrue(any(ref in root for ref in model.polygons))
            self.assertGreater(info['mesh_polygons'],len(root))
            indices2,_,info2=ordered_scene_indices(
                scene,mesh,eye,'auto',view_direction=(0,-1,0))
            self.assertGreater(len(indices2),0)
            self.assertEqual(info2['instances_visited'],6)

    def test_missing_objects_leave_root_geometry_intact(self):
        with tempfile.TemporaryDirectory() as temp:
            path=Path(temp)/'roadcar.3do'
            shutil.copyfile(ROOT/'fixtures'/'roadcar.3do',path)
            model=Model(path,associate_planes=False)
            scene=build_scene(model)
            self.assertEqual(scene.loaded_instances,0)
            self.assertTrue(scene.warnings)
            mesh=make_mesh(scene.geometry)
            indices,selected,_=ordered_scene_indices(
                scene,mesh,(-36000,-80000,7000),0)
            self.assertGreater(indices.size,0)
            self.assertTrue(selected)


if __name__ == '__main__':
    unittest.main()
