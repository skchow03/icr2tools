"""CPU-only tests for the optional read-only GPU viewport.

No Qt, ModernGL, display server, or proprietary RENO.3D asset is required.
"""
import ast
from pathlib import Path
from types import SimpleNamespace
import unittest

import numpy as np

from gpu_viewer.mesh import make_mesh, read_palette, triangulate
from n3_compile import compile_n3_text
from three_do import Model


CAD_ROOT = Path(__file__).resolve().parents[1]


def _area2(points):
    return sum(a[0]*b[1]-b[0]*a[1]
               for a,b in zip(points,points[1:]+points[:1]))


class TriangulationTests(unittest.TestCase):
    def test_convex_quad_yields_two_triangles(self):
        polygon=[(0,0,0),(4,0,0),(4,3,0),(0,3,0)]
        tris,fallback=triangulate(polygon)
        self.assertFalse(fallback)
        self.assertEqual(len(tris),2)
        self.assertEqual(set(i for tri in tris for i in tri),{0,1,2,3})

    def test_concave_polygon_preserves_surface_area(self):
        polygon=[(0,0,0),(4,0,0),(4,4,0),(2,1,0),(0,4,0)]
        tris,fallback=triangulate(polygon)
        self.assertFalse(fallback)
        self.assertEqual(len(tris),3)
        contour=[(x,y) for x,y,z in polygon]
        original=abs(_area2(contour))
        triangles=sum(abs(_area2([contour[i] for i in tri])) for tri in tris)
        self.assertAlmostEqual(original,triangles)

    def test_z_up_wall_faces_are_supported(self):
        vertical=[(0,3,0),(0,3,4),(0,0,4),(0,0,0)]
        tris,fallback=triangulate(vertical)
        self.assertEqual(len(tris),2)
        self.assertFalse(fallback)

    def test_degenerate_vertices_never_produce_triangles(self):
        for points in ([],[(0,0,0),(1,1,1)],
                       [(0,0,0),(1,1,1),(2,2,2)]):
            with self.subTest(points=points):
                self.assertEqual(triangulate(points)[0],[])


class ModelMeshTests(unittest.TestCase):
    def test_real_binary_fixture_mesh_is_gpu_ready(self):
        model=Model(CAD_ROOT/"fixtures"/"roadcar.3do",
                    associate_planes=False)
        mesh=make_mesh(model, read_palette(CAD_ROOT/"gamepal.pcx"))
        self.assertGreater(mesh.polygon_count,0)
        self.assertGreater(mesh.triangle_count,0)
        self.assertEqual(mesh.vertices.shape,(mesh.triangle_count*3,6))
        self.assertEqual(mesh.vertices.dtype,np.float32)
        self.assertTrue(mesh.vertices.flags.c_contiguous)
        self.assertTrue(np.isfinite(mesh.vertices).all())
        self.assertLessEqual(abs(mesh.vertices[:,:3]).max(),1.01)
        self.assertTrue(((mesh.vertices[:,3:]>=0) &
                         (mesh.vertices[:,3:]<=1)).all())
        self.assertEqual(mesh.size_bytes,mesh.vertices.nbytes)

    def test_flattened_model_does_not_mutate_binary_or_vertices(self):
        model=Model(CAD_ROOT/"fixtures"/"roadcar.3do",
                    associate_planes=False)
        before=model.raw
        refs={offset:v.xyz for offset,v in model.vertices.items()}
        _=make_mesh(model)
        self.assertEqual(model.raw,before)
        self.assertEqual(refs,
                         {offset:v.xyz for offset,v in model.vertices.items()})

    def test_skip_edit_anchors_keeps_geometry_and_compiler_bytes(self):
        source="""3D VERSION 3.0;
nil: NIL;
a: [<0,0,0>];
b: [<200,0,0>];
c: [<0,200,0>];
p: POLY <44> {a,b,c};
root: FACE (a,b,c), p;
"""
        edited,_=compile_n3_text(source,"gpu.3d")
        fast,_=compile_n3_text(source,"gpu.3d",associate_planes=False)
        self.assertEqual(fast.raw,edited.raw)
        self.assertEqual(fast.vertices,edited.vertices)
        self.assertEqual(set(fast.planes),set(edited.planes))
        self.assertEqual(fast.polygons,edited.polygons)

    def test_center_and_precision_with_large_track_coordinates(self):
        points=[(3_000_000,4_000_000,-100_000),
                (5_000_000,4_000_000,-100_000),
                (5_000_000,6_000_000,-100_000),
                (3_000_000,6_000_000,-100_000)]
        vertices={i:SimpleNamespace(xyz=p) for i,p in enumerate(points)}
        poly=SimpleNamespace(unique_refs=(0,1,2,3),color=44)
        model=SimpleNamespace(vertices=vertices,polygons={8:poly})
        mesh=make_mesh(model)
        self.assertEqual(mesh.center,(4_000_000.0,5_000_000.0,-100_000.0))
        self.assertEqual(mesh.scale,1_000_000.0)
        self.assertAlmostEqual(float(mesh.vertices[:,:3].max()),1.0)
        self.assertEqual(mesh.triangle_count,2)

    def test_qt_module_compiles_without_importing_optional_libraries(self):
        path=CAD_ROOT/"gpu_viewer"/"main.py"
        ast.parse(path.read_text(encoding="utf8"),filename=str(path))

    def test_empty_geometry_mesh_is_valid(self):
        model=SimpleNamespace(vertices={},polygons={})
        mesh=make_mesh(model)
        self.assertEqual(mesh.vertices.shape,(0,6))
        self.assertEqual(mesh.triangle_count,0)


if __name__=="__main__":
    unittest.main()
