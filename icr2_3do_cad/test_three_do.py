"""Regression tests against the uploaded 3DO fixtures."""
import tempfile
import unittest
import sys
from pathlib import Path

from three_do import Model, INT32_HI, FormatError

FIXTURES=Path(__file__).parent/'fixtures'

class TestRealFiles(unittest.TestCase):
    def test_noop_is_binary_identical(self):
        for name in ('roadcar','indycar','irl','panoz','cit74','cars'):
            with self.subTest(name=name):
                model=Model(FIXTURES/f'{name}.3do')
                data,report=model.build_modified_bytes()
                self.assertEqual(data, model.raw)
                self.assertEqual(report.updated_planes,0)

    def test_roadcar_counts(self):
        m=Model(FIXTURES/'roadcar.3do')
        self.assertEqual((len(m.vertices),len(m.polygons),len(m.planes)),(325,124,124))
        self.assertEqual(len(m.raw),15880)

    def test_plane_updates_keep_structure_and_file_size(self):
        m=Model(FIXTURES/'indycar.3do')
        v=m.vertices[84]; initial=v.xyz
        m.set_vertex(84,(initial[0],initial[1],initial[2]+100))
        data,report=m.build_modified_bytes()
        self.assertGreater(report.updated_planes,0)
        self.assertEqual(len(data),len(m.raw))
        # All modifications must be confined to the edited vertex coordinates
        # and the plane equations explicitly identified by this parser.
        differences={i for i,(a,b) in enumerate(zip(data,m.raw)) if a!=b}
        vertex_span=set(range(m.body_start+84+4,m.body_start+84+16))
        plane_span=set()
        for p in m.planes.values():
            plane_span.update(range(m.body_start+p.offset+4,m.body_start+p.offset+24))
        self.assertTrue(differences<=vertex_span|plane_span)
        with tempfile.TemporaryDirectory() as d:
            out=Path(d)/'edited.3do';out.write_bytes(data)
            rebuilt=Model(out)
            self.assertEqual(len(rebuilt.polygons),len(m.polygons))
            self.assertEqual(len(rebuilt.vertices),len(m.vertices))
            self.assertEqual(rebuilt.vertices[84].xyz,v.xyz)

    def test_bad_coordinates_refused(self):
        m=Model(FIXTURES/'roadcar.3do')
        one=next(iter(m.vertices))
        with self.assertRaises(ValueError):
            m.set_vertex(one,(INT32_HI+1,0,0))

    def test_unmodified_untouched(self):
        m=Model(FIXTURES/'roadcar.3do')
        r=next(iter(m.vertices))
        m.set_vertex(r,m.vertices[r].xyz)
        data,rep=m.build_modified_bytes()
        self.assertEqual(data,m.raw)
        self.assertEqual(rep.updated_vertices,0)

if __name__=='__main__':
    unittest.main(verbosity=2)
