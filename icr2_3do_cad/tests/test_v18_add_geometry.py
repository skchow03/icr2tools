"""Add-geometry binary regression tests (real car fixtures)."""
import unittest
import struct
from pathlib import Path
from three_do import Model,FormatError
from geometry_add import list_insert_targets,create_model_polygon
from raw_disassembly import disassemble

ROOT=Path(__file__).resolve().parents[1]


class GeometryCreationTests(unittest.TestCase):
    def setUp(self):
        self.m=Model(ROOT/'fixtures'/'roadcar.3do')
        self.anchor=8484
        self.target=list_insert_targets(self.m,self.anchor)[0]
        a,b=self.m.polygons[self.anchor].refs[:2]
        self.a,self.b=a,b
        p=self.m.vertices[a].xyz;q=self.m.vertices[b].xyz
        self.apex=((p[0]+q[0])//2,(p[1]+q[1])//2,max(p[2],q[2])+5000)

    def make(self,**kw):
        return create_model_polygon(self.m,self.anchor,*self.target,[self.a,self.b,self.apex],**kw)

    def test_append_preserves_old_bytes_except_one_pointer_and_header(self):
        after,result=self.make()
        assert len(after.polygons)==len(self.m.polygons)+2
        assert len(after.vertices)==len(self.m.vertices)+1
        self.assertEqual(len(after.planes),len(self.m.planes)+1)
        self.assertEqual(after.records[result.face_offset],6)
        self.assertEqual(after.records[result.replacement_list],11)
        self.assertEqual(after.children[result.replacement_list],
            self.m.children[result.source_list][:self.target[1]+1]+[result.face_offset]+
            self.m.children[result.source_list][self.target[1]+1:])
        self.assertEqual(after.body[result.source_list:result.source_list+8],
                         self.m.body[result.source_list:result.source_list+8])
        expected=bytearray(self.m.raw)
        slot=self.m.body_start+result.patched_slot
        struct.pack_into('<i',expected,slot,result.replacement_list)
        struct.pack_into('<i',expected,0,len(after.body))
        self.assertEqual(after.raw[:len(self.m.raw)],bytes(expected))
        self.assertEqual(result.new_vertices,len(result.new_vertices) and (result.new_vertices[0],))

    def test_new_vertices_and_side_winding(self):
        new,result=self.make()
        front,back=result.new_polygons
        self.assertEqual(new.polygons[front].refs,tuple([self.a,self.b,result.new_vertices[0]]))
        self.assertEqual(new.polygons[back].refs,tuple(reversed(new.polygons[front].refs)))
        self.assertEqual(new.vertices[result.new_vertices[0]].xyz,self.apex)
        eq=new.planes[result.face_offset].equation
        self.assertTrue(any(eq[:3]))
        for ref in new.polygons[front].refs:
            self.assertEqual(sum(a*b for a,b in zip(eq[:3],new.vertices[ref].xyz))+eq[3],0)

    def test_single_sided_and_existing_only(self):
        # Uses 3 established corners (if not collinear).
        p=self.m.polygons[self.anchor]
        three=p.refs[:3]
        result_model,r=create_model_polygon(self.m,self.anchor,*self.target,three,
                                             two_sided=False,after=False)
        self.assertEqual(len(r.new_polygons),1)
        self.assertEqual(r.new_vertices,())
        self.assertEqual(result_model.records[r.face_offset],5)
        self.assertEqual(result_model.children[r.replacement_list][self.target[1]],r.face_offset)

    def test_save_roundtrip(self):
        new,result=self.make()
        raw,report=new.build_modified_bytes()
        reopened=Model(new.path,raw_data=raw)
        self.assertEqual(reopened.polygons[result.new_polygons[0]].refs,
                         new.polygons[result.new_polygons[0]].refs)
        self.assertEqual(raw,new.raw)
        self.assertIn('fixed LIST paint order',report.describe())
        self.assertNotIn('New split polygons share',report.describe())

    def test_invalid_references_and_collinear(self):
        for verts in ([self.a,self.a,self.b], [self.a,self.b,(0,0,0,0,0)],
                      [999999,self.a,self.b], [self.a,self.b]):
            with self.subTest(verts=verts),self.assertRaises((FormatError,ValueError)):
                create_model_polygon(self.m,self.anchor,*self.target,verts)

    def test_tampered_insertion_occurrence_rejected(self):
        with self.assertRaises(FormatError):
            create_model_polygon(self.m,self.anchor,self.target[0],self.target[1],
                                 self.target[2],123456,[self.a,self.b,self.apex])

    def test_append_to_all_supplied_base_cars(self):
        for name in ('indycar.3do','irl.3do','panoz.3do'):
            with self.subTest(name=name):
                model=Model(ROOT/'fixtures'/name)
                anchor=next(p for p in model.polygons if list_insert_targets(model,p))
                refs=model.polygons[anchor].refs
                corners=list(dict.fromkeys(refs))
                from three_do import cross,sub
                triplet=None
                for i in range(1,len(corners)-1):
                    pp=[model.vertices[off].xyz for off in (corners[0],corners[i],corners[i+1])]
                    if cross(sub(pp[1],pp[0]),sub(pp[2],pp[0]))!=(0,0,0):
                        triplet=(corners[0],corners[i],corners[i+1]);break
                if not triplet:continue
                out,r=create_model_polygon(model,anchor,*list_insert_targets(model,anchor)[0],triplet)
                self.assertEqual(len(out.polygons),len(model.polygons)+2)

    def test_disassembly_includes_new_records(self):
        new,r=self.make()
        text=disassemble(new)
        self.assertIn(f'@{r.face_offset}',text)
        self.assertIn(f'@{r.replacement_list}',text)
        self.assertIn('back→front=',text)
        self.assertIn('READ ONLY',text)


if __name__=='__main__':unittest.main()
