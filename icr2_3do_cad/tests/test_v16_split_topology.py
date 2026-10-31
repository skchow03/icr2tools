"""v1.6 structural tests; uses actual ICR2 car geometry records."""
import unittest
import tempfile
import struct
from pathlib import Path
from three_do import Model, FormatError, plane_distance
from topology_split import _parent_slots

ROOT=Path(__file__).resolve().parents[1]

class PolygonSplitTests(unittest.TestCase):
    def setUp(self):
        self.m=Model(ROOT/'fixtures'/'roadcar.3do')

    def test_existing_triangulation_does_not_touch_source(self):
        old=self.m.raw
        a=self.m.polygons[8548]
        edited,report=self.m.split_polygon(8548,0,3)
        self.assertEqual(self.m.raw,old)
        self.assertEqual(len(edited.polygons),len(self.m.polygons)+1)
        self.assertTrue(edited.dirty)
        self.assertNotIn(8548,edited.polygons)
        self.assertEqual(edited.children[report.replacement_list],list(report.new_polygons))
        self.assertEqual(len(report.new_vertices),2)
        self.assertTrue(all(edited.vertices[x].uv is not None for x in report.new_vertices))
        # Geometry and texture at the split segment ends are averages.
        for idx,edge in enumerate((0,3)):
            original_a=self.m.vertices[a.refs[edge]]
            original_b=self.m.vertices[a.refs[(edge+1)%len(a.refs)]]
            v=edited.vertices[report.new_vertices[idx]]
            self.assertEqual(v.xyz,tuple(round((x+y)/2) for x,y in zip(original_a.xyz,original_b.xyz)))
            self.assertEqual(v.uv,tuple(round((x+y)/2) for x,y in zip(original_a.uv,original_b.uv)))
        # The two replacement faces inherit both material group and color.
        for off in report.new_polygons:
            q=edited.polygons[off]
            self.assertEqual(q.kind,a.kind)
            self.assertEqual(q.color,a.color)
            self.assertEqual(q.group,a.group)

    def test_preserves_binary_except_header_and_real_parent_slots(self):
        original=self.m.raw
        edited,report=self.m.split_polygon(8548,0,3)
        same_size=edited.raw[:len(original)]
        changed={i for i,(a,b) in enumerate(zip(original,same_size)) if a!=b}
        allowed=set(range(4))
        replaced={8548,*(old for old,_ in report.updated_neighbors)}
        for parent in self.m.records:
            for slot,pointer in _parent_slots(self.m,parent):
                if pointer in replaced:
                    allowed.update(range(self.m.body_start+slot,self.m.body_start+slot+4))
        self.assertTrue(changed<=allowed,f'Unintended mutation: {sorted(changed-allowed)[:10]}')
        # Header body-size updated to actual new tail bytes.
        self.assertEqual(struct.unpack_from('<i',edited.raw)[0],len(edited.body))

    def test_original_bsp_equations_and_lod_tree_unchanged(self):
        edited,r=self.m.split_polygon(5696,0,1)
        self.assertEqual({k:v.equation for k,v in edited.planes.items()},
                         {k:v.equation for k,v in self.m.planes.items()})
        self.assertEqual(edited.switches,self.m.switches)
        camera=(2_000_000,2_000_000,2_000_000)
        before,_,_=self.m.switched_polygons(0,camera,'off')
        after,_,_=edited.switched_polygons(0,camera,'off')
        old_to_new=dict(r.updated_neighbors)
        expected=(set(before)-{5696}-set(old_to_new)) | set(r.new_polygons) | set(old_to_new.values())
        self.assertEqual(set(after),expected)

    def test_neighbors_repoint_and_share_vertex(self):
        # Pair 7832 and 7864 share edge (1020,1040).
        p=self.m.polygons[7832]
        edges=[i for i in range(len(p.refs)) if {p.refs[i],p.refs[(i+1)%len(p.refs)]}=={1020,1040}]
        self.assertEqual(len(edges),1)
        new,r=self.m.split_polygon(7832,edges[0],(edges[0]+2)%len(p.refs))
        replacements=dict(r.updated_neighbors)
        self.assertIn(7864,replacements)
        self.assertNotIn(7864,new.polygons)
        np=new.polygons[replacements[7864]]
        self.assertTrue(any(ref in r.new_vertices for ref in np.refs))
        self.assertEqual(len(new.polygons),len(self.m.polygons)+1)

    def test_split_again_then_vertex_change_then_round_trip(self):
        once,r1=self.m.split_polygon(8548,0,3)
        twice,r2=once.split_polygon(r1.new_polygons[0],0,2)
        self.assertEqual(len(twice.topology_history),2)
        chosen=r2.new_vertices[0]
        v=twice.vertices[chosen]
        twice.set_vertex(chosen,(v.xyz[0]+10,*v.xyz[1:]))
        out,report=twice.build_modified_bytes()
        self.assertEqual(report.split_operations,2)
        self.assertEqual(report.added_polygons,4)
        with tempfile.TemporaryDirectory() as d:
            saved=Path(d)/'changed.3do'
            saved.write_bytes(out)
            check=Model(saved)
        self.assertIn(r2.new_polygons[1],check.polygons)
        self.assertEqual(check.vertices[chosen].xyz,twice.vertices[chosen].xyz)

    def test_input_validation(self):
        for a,b,fa,fb in [(0,0,.5,.5),(-1,2,.5,.5),(0,3,0,.5),(0,3,.5,1)]:
            with self.subTest(args=(a,b,fa,fb)),self.assertRaises(FormatError):
                self.m.split_polygon(8548,a,b,fa,fb)
        with self.assertRaises(FormatError):
            self.m.split_polygon(999999,0,2)

    def test_untextured_polygon(self):
        edited,result=self.m.split_polygon(5780,0,2)
        self.assertTrue(all(edited.vertices[r].uv is None for r in result.new_vertices[:2]))
        self.assertTrue(all(edited.polygons[r].kind==1 for r in result.new_polygons))

    def test_all_supplied_models(self):
        for name in ['indycar.3do','roadcar.3do','irl.3do','panoz.3do']:
            with self.subTest(name=name):
                m=Model(ROOT/'fixtures'/name)
                poly=next(p for p in m.polygons.values() if p.kind in (1,2) and len(p.refs)>=4
                         and len(p.unique_refs)==len(p.refs))
                new,r=m.split_polygon(poly.offset,0,2)
                self.assertIn(r.replacement_list,new.records)
                self.assertEqual(new.build_modified_bytes()[0],new.raw)

if __name__=='__main__':unittest.main()
