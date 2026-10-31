"""v0.3 polygon-plane editing regression checks against real Papyrus files."""
import struct
import tempfile
import unittest
from pathlib import Path
from three_do import Model, FormatError, plane_distance, polygon_triplet_refs

HERE=Path(__file__).parent/'fixtures'


class PolygonPlaneTests(unittest.TestCase):
    def example(self):
        m=Model(HERE/'roadcar.3do')
        # A surface with a unique local FACE ancestor.
        poly=7896;plane=9124
        assert m.planes[plane].anchor==poly
        return m,poly,plane

    def test_polygon_ancestor_relationships(self):
        m,po,pl=self.example()
        self.assertIn(pl,m.planes_for_polygon(po))
        self.assertIn('local',m.plane_relationship(po,pl))
        self.assertEqual(len(m.polygons[po].unique_refs),4)
        self.assertIsNotNone(polygon_triplet_refs(m.polygons[po],m.vertices))
        with self.assertRaises(ValueError):
            m.set_plane_edit(pl,999999,'auto')

    def test_automatic_recalculation_without_vertex_change(self):
        m,po,pl=self.example()
        m.set_plane_edit(pl,po,'auto')
        self.assertTrue(m.dirty)
        data,report=m.build_modified_bytes()
        self.assertEqual(report.explicit_planes,1)
        self.assertEqual(len(data),len(m.raw))
        self.assertEqual(len(m.plane_edits),1)
        # Either plane coefficients are already identical or they are rebuilt
        # from unchanged polygon. Both must reopen and remain planar.
        with tempfile.TemporaryDirectory() as td:
            output=Path(td)/'auto.3do';output.write_bytes(data)
            reloaded=Model(output)
            self.assertEqual(len(reloaded.polygons),len(m.polygons))
            self.assertEqual(len(reloaded.planes),len(m.planes))
            eq=reloaded.planes[pl].equation
            self.assertLessEqual(max(plane_distance(eq,reloaded.vertices[r].xyz)
                             for r in reloaded.polygons[po].unique_refs),1)

    def test_reverse_original_plane_only_changes_plane_record(self):
        m,po,pl=self.example()
        old=m.planes[pl].equation
        m.flip_plane(pl,po)
        eq=m.effective_plane(pl)
        self.assertEqual(eq,tuple(-v for v in old))
        data,report=m.build_modified_bytes()
        self.assertEqual(report.explicit_planes,1)
        differences={i for i,(a,b) in enumerate(zip(m.raw,data)) if a!=b}
        start=m.body_start+pl+4
        self.assertTrue(differences)
        self.assertTrue(differences<=set(range(start,start+20)))
        m.flip_plane(pl,po)
        self.assertFalse(m.dirty)
        self.assertEqual(m.build_modified_bytes()[0],m.raw)

    def test_manual_three_vertices_and_order_reversal(self):
        m,po,pl=self.example()
        refs=polygon_triplet_refs(m.polygons[po],m.vertices)
        m.set_plane_edit(pl,po,'manual',refs)
        first=m.effective_plane(pl)
        m.set_plane_edit(pl,po,'manual',(refs[0],refs[2],refs[1]))
        second=m.effective_plane(pl)
        self.assertEqual(first,tuple(-v for v in second))
        for r in m.polygons[po].unique_refs:
            self.assertLessEqual(plane_distance(second,m.vertices[r].xyz),1)
        with self.assertRaises(ValueError):
            m.set_plane_edit(pl,po,'manual',(refs[0],refs[0],refs[1]))
        with self.assertRaises(ValueError):
            m.set_plane_edit(pl,po,'manual',(refs[0],refs[1],-1))

    def test_explicit_override_after_vertex_move(self):
        m,po,pl=self.example()
        refs=polygon_triplet_refs(m.polygons[po],m.vertices)
        # Move the entire polygon along X so it remains planar.
        for ref in m.polygons[po].unique_refs:
            xyz=m.vertices[ref].xyz
            m.set_vertex(ref,(xyz[0]+200,xyz[1],xyz[2]))
        m.set_plane_edit(pl,po,'manual',refs)
        expected=m.effective_plane(pl)
        data,report=m.build_modified_bytes()
        stored=struct.unpack_from('<3iq',data,m.body_start+pl+4)
        self.assertEqual(stored,expected)
        self.assertEqual(report.explicit_planes,1)
        self.assertTrue(report.updated_vertices)

    def test_nonplanar_manual_allowed_saved_and_reported(self):
        m,po,pl=self.example()
        refs=m.polygons[po].unique_refs
        tri=polygon_triplet_refs(m.polygons[po],m.vertices)
        # Displace a fourth vertex perpendicular to the original plane so
        # three selected vertices still define a valid but noncoplanar plane.
        moved=next(r for r in refs if r not in tri)
        xyz=list(m.vertices[moved].xyz)
        axis=max(range(3),key=lambda i:abs(m.planes[pl].equation[i]))
        xyz[axis]+=5000
        m.set_vertex(moved,xyz)
        m.set_plane_edit(pl,po,'manual',tri)
        eq=m.effective_plane(pl)
        deviation,relative=m.polygon_plane_deviation(po,eq)
        self.assertGreater(deviation,1.0)
        self.assertGreater(relative,0.0)
        data,report=m.build_modified_bytes()
        self.assertEqual(report.explicit_planes,1)
        self.assertTrue(any('noncoplanar' in w for w in report.warnings))
        self.assertEqual(struct.unpack_from('<3iq',data,m.body_start+pl+4),eq)
        with tempfile.TemporaryDirectory() as td:
            target=Path(td)/'nonplanar.3do'
            target.write_bytes(data)
            check=Model(target)
            self.assertEqual(check.planes[pl].equation,eq)
            self.assertEqual(len(check.polygons),len(m.polygons))
            self.assertEqual(len(check.vertices),len(m.vertices))

    def test_nonplanar_explicit_auto_allowed_but_implicit_remains_conservative(self):
        m,po,pl=self.example()
        ref=m.polygons[po].unique_refs[0]
        xyz=list(m.vertices[ref].xyz)
        axis=max(range(3),key=lambda i:abs(m.planes[pl].equation[i]))
        xyz[axis]+=3000
        m.set_vertex(ref,xyz)
        # Without explicit selection, a nonplanar surface must not cause
        # the safe automatic writer to replace the plane.
        unselected,report=m.build_modified_bytes()
        self.assertEqual(struct.unpack_from('<3iq',unselected,m.body_start+pl+4),m.planes[pl].equation)
        self.assertTrue(report.warnings)
        m.set_plane_edit(pl,po,'auto')
        explicit,report=m.build_modified_bytes()
        self.assertEqual(report.explicit_planes,1)
        self.assertTrue(any('noncoplanar' in w for w in report.warnings))

    def test_all_sample_files_noop_is_identical(self):
        for path in HERE.glob('*.3do'):
            with self.subTest(file=path.name):
                model=Model(path)
                self.assertEqual(model.build_modified_bytes()[0],path.read_bytes())

if __name__=='__main__':
    unittest.main()
