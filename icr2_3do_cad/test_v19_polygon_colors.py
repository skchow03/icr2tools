"""Color edits for existing, split, and newly appended 3DO polygons."""
import struct
import unittest
from pathlib import Path
from three_do import Model
from geometry_add import create_model_polygon, list_insert_targets
from raw_disassembly import disassemble
from icr2_3do_cad import write_validated_3do
from tempfile import TemporaryDirectory

FIX=Path(__file__).resolve().parent/'fixtures'

class PolygonColorTests(unittest.TestCase):
    def test_existing_poly_untextured_writes_only_correct_color_dword(self):
        m=Model(FIX/'roadcar.3do')
        target=next(i for i,p in m.polygons.items() if p.kind==1)
        old=m.polygons[target].color
        new=140 if old!=140 else 141
        m.set_polygon_color(target,new)
        self.assertTrue(m.dirty)
        raw,report=m.build_modified_bytes()
        self.assertEqual(report.updated_polygon_colors,1)
        allowed=set(range(m.body_start+target+4,m.body_start+target+8))
        self.assertTrue({i for i,(a,b) in enumerate(zip(raw,m.raw)) if a!=b} <= allowed)
        out=Model(m.path,raw_data=raw)
        self.assertEqual(out.polygons[target].color,new)
        self.assertEqual(len(raw),len(m.raw))

    def test_textured_poly_color_not_group(self):
        m=Model(FIX/'roadcar.3do')
        target=next(i for i,p in m.polygons.items() if p.kind==2)
        group=m.polygons[target].group
        m.set_polygon_color(target,150)
        raw,_=m.build_modified_bytes()
        self.assertEqual(struct.unpack_from('<i',raw,m.body_start+target+8)[0],150)
        self.assertEqual(struct.unpack_from('<i',raw,m.body_start+target+4)[0],group)
        self.assertEqual(Model(m.path,raw_data=raw).polygons[target].group,group)

    def test_roundtrip_new_two_sided_fin_and_pair(self):
        m=Model(FIX/'roadcar.3do')
        a=8484
        r=m.polygons[a].refs
        x=m.vertices[r[0]].xyz;y=m.vertices[r[1]].xyz
        apex=((x[0]+y[0])//2,(x[1]+y[1])//2,max(x[2],y[2])+5000)
        new,res=create_model_polygon(m,a,*list_insert_targets(m,a)[0],[r[0],r[1],apex],color=40)
        front,back=res.new_polygons
        self.assertEqual(new.face2_pair(front),back)
        self.assertEqual(new.face2_pair(back),front)
        for poly in (front,back):new.set_polygon_color(poly,141)
        raw,report=new.build_modified_bytes()
        self.assertEqual(report.updated_polygon_colors,2)
        out=Model(new.path,raw_data=raw)
        self.assertEqual([out.polygons[i].color for i in (front,back)],[141,141])
        self.assertEqual(out.planes[res.face_offset].equation,new.planes[res.face_offset].equation)
        self.assertIn(f'@{front}',disassemble(out))
        with TemporaryDirectory() as temp:
            dest=Path(temp)/'painted.3do'
            saved=write_validated_3do(dest,raw,expected_vertices=len(new.vertices),expected_polygons=len(new.polygons))
            self.assertEqual(saved.polygons[front].color,141)
            self.assertEqual(saved.polygons[back].color,141)

    def test_reset_and_invalid_colors(self):
        m=Model(FIX/'indycar.3do')
        target=next(iter(m.polygons))
        old=m.polygons[target].color
        for value in (-1,256,100000):
            with self.assertRaises(ValueError):m.set_polygon_color(target,value)
        m.set_polygon_color(target,200)
        m.reset()
        self.assertEqual(m.polygons[target].color,old)
        self.assertFalse(m.dirty)
        self.assertEqual(m.build_modified_bytes()[0],m.raw)

    def test_roundtrip_after_other_geometry_edits(self):
        m=Model(FIX/'roadcar.3do')
        offset=8484
        m.set_polygon_color(offset,143)
        m2,result=m.split_polygon_at_vertices(offset,0,3)
        # Underlying append-and-repoint stream includes any color patch before the split;
        # the old polygon becomes unreachable, so use a new active polygon for the later edit.
        target=result.new_polygons[0]
        m2.set_polygon_color(target,154)
        raw,_=m2.build_modified_bytes()
        out=Model(m2.path,raw_data=raw)
        self.assertEqual(out.polygons[target].color,154)
        self.assertEqual(len(out.polygons),len(m2.polygons))

if __name__=='__main__':unittest.main()
