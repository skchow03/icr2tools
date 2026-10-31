"""Regression checks for v0.2 UV edits, LOD filtering and plane previews."""
import tempfile
import unittest
from pathlib import Path
from three_do import Model, FormatError

FILES=Path(__file__).resolve().parents[1]/'fixtures'


class PreviewUvTests(unittest.TestCase):
    def test_uv_roundtrip_is_binary_local(self):
        m=Model(FILES/'roadcar.3do')
        vertex=next(v for v in m.vertices.values() if v.textured)
        before=vertex.uv
        m.set_uv(vertex.offset,((before[0]+3)%65536,(before[1]+2)%65536))
        data,report=m.build_modified_bytes()
        self.assertEqual(report.updated_uv,1)
        self.assertEqual(report.updated_vertices,0)
        changed={i for i,(x,y) in enumerate(zip(m.raw,data)) if x!=y}
        start=m.body_start+vertex.offset+16
        self.assertTrue(changed)
        self.assertTrue(changed<=set(range(start,start+4)))
        with tempfile.TemporaryDirectory() as directory:
            path=Path(directory)/'uv.3do';path.write_bytes(data)
            loaded=Model(path)
            self.assertEqual(loaded.vertices[vertex.offset].uv,vertex.uv)
        m.reset()
        self.assertFalse(m.dirty)
        self.assertEqual(m.build_modified_bytes()[0],m.raw)

    def test_uv_restrictions(self):
        m=Model(FILES/'roadcar.3do')
        t=next(v for v in m.vertices.values() if v.textured)
        n=next(v for v in m.vertices.values() if not v.textured)
        for invalid in [(-1,0),(0,65536),(4,),('x',1)]:
            with self.assertRaises((TypeError,ValueError)):
                m.set_uv(t.offset,invalid)
        with self.assertRaises(ValueError):
            m.set_uv(n.offset,(3,6))

    def test_switch_branches(self):
        m=Model(FILES/'roadcar.3do')
        self.assertEqual(len(m.switches),1)
        sw=next(iter(m.switches.values()))
        thresholds=[t for t,p in sw.branches]
        self.assertEqual(thresholds,[955092,334618,225321,0])
        for d,index in [(955093,0),(955092,0),(900000,1),(334618,1),
                        (225321,2),(100000,3),(0,3)]:
            self.assertEqual(sw.choose(d)[1],sw.branches[index][1])
        camera=(1000000,1000000,1000000)
        all_polys,_,_=m.switched_polygons(None,camera,'off')
        self.assertEqual(len(all_polys),len(m.polygons))
        stage_counts=[]
        for d in (1200000,500000,250000,0):
            polys,_,selected=m.switched_polygons(d,camera,'off')
            self.assertEqual(len(selected),1)
            stage_counts.append(len(polys))
            self.assertLessEqual(len(polys),len(all_polys))
        self.assertEqual(stage_counts,[21,42,67,100])

    def test_bsp_modes_and_edited_planes(self):
        m=Model(FILES/'indycar.3do')
        camera=(0,1000000,1000000)
        for mode in ('off','original','rebuilt'):
            polys,stat,lods=m.switched_polygons(0,camera,mode)
            self.assertLessEqual(stat['tested_planes'],len(m.planes))
            self.assertTrue(set(polys)<=set(m.polygons))
            self.assertEqual(len(polys),len(set(polys)))
        xyz=m.vertices[84].xyz
        m.set_vertex(84,(xyz[0],xyz[1],xyz[2]+100))
        data,report=m.build_modified_bytes()
        self.assertGreater(report.updated_planes,0)
        self.assertEqual(len(data),len(m.raw))
        m.switched_polygons(0,camera,'rebuilt')

    def test_all_fixtures_unchanged(self):
        for f in FILES.glob('*.3do'):
            with self.subTest(f=f.name):
                model=Model(f)
                self.assertEqual(model.build_modified_bytes()[0],f.read_bytes())
                for mode in ('off','original','rebuilt'):
                    model.switched_polygons(0,(0,1000000,0),mode)


if __name__=='__main__':
    unittest.main(verbosity=2)
