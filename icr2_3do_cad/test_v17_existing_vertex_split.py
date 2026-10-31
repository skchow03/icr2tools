"""Regression tests for splitting an existing N-gon along existing vertex refs."""
from pathlib import Path
from tempfile import TemporaryDirectory
import struct
import unittest

from three_do import Model, FormatError
from topology_split import _parent_slots, _diagonal_is_inside

ROOT=Path(__file__).parent


class ExistingVertexSplitTests(unittest.TestCase):
    def setUp(self):
        self.source=Model(ROOT/'fixtures'/'roadcar.3do')

    def test_textured_ngon_split_preserves_uv_and_all_vertices(self):
        original=self.source.polygons[8548]
        after,result=self.source.split_polygon_at_vertices(8548,0,3)
        self.assertEqual(result.new_vertices,())
        self.assertEqual(result.updated_neighbors,())
        self.assertEqual(set(after.vertices),set(self.source.vertices))
        self.assertEqual(len(after.polygons),len(self.source.polygons)+1)
        self.assertNotIn(8548,after.polygons)
        self.assertEqual(after.children[result.replacement_list],list(result.new_polygons))
        expected=(original.refs[:4],original.refs[3:]+original.refs[:1])
        for off,refs in zip(result.new_polygons,expected):
            poly=after.polygons[off]
            self.assertEqual(poly.refs,refs)
            self.assertEqual((poly.kind,poly.color,poly.group),
                             (original.kind,original.color,original.group))
            for ref in refs:
                self.assertEqual(after.vertices[ref].uv,self.source.vertices[ref].uv)

    def test_cut_uses_existing_new_neighbor_vertex(self):
        # First split inserts a boundary point in its adjacent polygon.
        p=self.source.polygons[7832]
        j=next(i for i in range(len(p.refs))
               if {p.refs[i],p.refs[(i+1)%len(p.refs)]}=={1020,1040})
        first,r1=self.source.split_polygon(7832,j,(j+2)%len(p.refs))
        neighbor=dict(r1.updated_neighbors)[7864]
        poly=first.polygons[neighbor]
        inserted=next(i for i,ref in enumerate(poly.refs) if ref in r1.new_vertices)
        other=(inserted+2)%len(poly.refs)
        if (inserted-other)%len(poly.refs) in (1,len(poly.refs)-1):
            other=(inserted+3)%len(poly.refs)
        count=len(first.vertices)
        second,r2=first.split_polygon_at_vertices(neighbor,inserted,other)
        self.assertEqual(len(second.vertices),count)
        self.assertEqual(len(r2.new_vertices),0)
        self.assertEqual(sum(poly.refs.count(r1.new_vertices[0]) for poly in
                             (second.polygons[k] for k in r2.new_polygons)),2)
        self.assertEqual(len(second.topology_history),2)
        output,report=second.build_modified_bytes()
        self.assertEqual(report.split_operations,2)
        self.assertEqual(report.added_vertices,len(r1.new_vertices))
        with TemporaryDirectory() as path:
            file=Path(path)/'twice.3do'
            file.write_bytes(output)
            reopened=Model(file)
            self.assertTrue(all(k in reopened.polygons for k in r2.new_polygons))

    def test_binary_preservation_except_header_and_actual_parent_slots(self):
        edited,r=self.source.split_polygon_at_vertices(8548,0,3)
        old=self.source.raw
        changed={i for i,(a,b) in enumerate(zip(old,edited.raw)) if a!=b}
        allowed=set(range(4))
        for parent in self.source.records:
            for location,pointer in _parent_slots(self.source,parent):
                if pointer==8548:
                    allowed.update(range(self.source.body_start+location,self.source.body_start+location+4))
        self.assertTrue(changed <= allowed)
        self.assertEqual(struct.unpack_from('<i',edited.raw,0)[0],len(edited.body))
        self.assertEqual(self.source.raw,old)
        self.assertEqual(self.source.planes.keys(),edited.planes.keys())
        self.assertEqual({k:v.equation for k,v in self.source.planes.items()},
                         {k:v.equation for k,v in edited.planes.items()})
        self.assertEqual(self.source.switches,edited.switches)

    def test_keep_previous_coordinate_edits_and_save(self):
        m=self.source
        ref=m.polygons[8548].refs[0]
        vertex=m.vertices[ref]
        moved=(vertex.xyz[0]+20,*vertex.xyz[1:])
        m.set_vertex(ref,moved)
        updated,r=m.split_polygon_at_vertices(8548,0,3)
        self.assertEqual(updated.vertices[ref].xyz,moved)
        self.assertIn(r.new_polygons[0],updated.polygons)
        data,report=updated.build_modified_bytes()
        self.assertEqual(report.added_vertices,0)
        with TemporaryDirectory() as folder:
            saved=Path(folder)/'test.3do';saved.write_bytes(data)
            self.assertEqual(Model(saved).vertices[ref].xyz,moved)

    def test_invalid_selection_and_triangle(self):
        for a,b in [(0,0),(0,1),(0,5),(0,6),(-1,2),(0,100)]:
            with self.subTest(a=a,b=b),self.assertRaises(FormatError):
                self.source.split_polygon_at_vertices(8548,a,b)
        with self.assertRaises(FormatError):
            self.source.split_polygon_at_vertices(5696,0,2)
        with self.assertRaises(FormatError):
            self.source.split_polygon_at_vertices(999999,0,2)

    def test_reject_diagonal_outside_concave_polygon(self):
        # Planar L shaped polygon, the 1 -> 4 diagonal goes through empty area
        p=[(0,0),(8,0),(8,2),(2,2),(2,8),(0,8)]
        self.assertFalse(_diagonal_is_inside(p,1,4))
        self.assertTrue(_diagonal_is_inside(p,0,3))

    def test_repeated_split_and_original_snapshot(self):
        first,r1=self.source.split_polygon_at_vertices(8548,0,3)
        face=first.polygons[r1.new_polygons[0]]
        second,r2=first.split_polygon_at_vertices(face.offset,0,2)
        self.assertEqual(len(second.topology_history),2)
        self.assertEqual(len(second.vertices),len(self.source.vertices))
        self.assertTrue(all(x in second.polygons for x in r2.new_polygons))
        self.assertIn(8548,self.source.polygons)

    def test_other_stock_models(self):
        for name in ('indycar.3do','roadcar.3do','irl.3do','panoz.3do'):
            with self.subTest(name=name):
                m=Model(ROOT/'fixtures'/name)
                candidate=next(p for p in m.polygons.values()
                               if len(p.refs)>=4 and len(p.refs)==len(p.unique_refs)
                               and p.kind in (1,2))
                new,r=m.split_polygon_at_vertices(candidate.offset,0,2)
                self.assertEqual(len(new.vertices),len(m.vertices))
                self.assertEqual(new.build_modified_bytes()[0],new.raw)


if __name__=='__main__':unittest.main()
