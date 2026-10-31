"""Regression tests for external DYNAMIC geometry and read-only placement edits."""
import math
import struct
import tempfile
import unittest
from pathlib import Path
from three_do import Model
from dynamic_scene import (ExternalResolver, gather_faces, placement_transform,
                           papyrus_to_degrees, degrees_to_papyrus)

BASE=Path(__file__).resolve().parents[1]
TAG_POLY=-(1<<31)+1
TAG_LIST=-(1<<31)+11

def make_test_wheel(path):
    """Valid small external 3DO. This is TEST geometry, not a stock wheel."""
    body=bytearray()
    vertices=[]
    for k in range(8):
        theta=2*math.pi*k/8
        off=len(body)
        vertices.append(off)
        body.extend(struct.pack('<4i',0,round(6800*math.cos(theta)),0,round(6800*math.sin(theta))))
    face_offset=len(body)
    body.extend(struct.pack('<3i',TAG_POLY,110,7))
    for off in vertices:body.extend(struct.pack('<i',off))
    root=len(body)
    body.extend(struct.pack('<3i',TAG_LIST,1,face_offset))
    path.write_bytes(struct.pack('<5i',len(body),root,0,0,0)+body)

class DynamicParserTests(unittest.TestCase):
    def test_stock_placement_offsets_and_external_names(self):
        for name in ('roadcar.3do','indycar.3do'):
            m=Model(BASE/'fixtures'/name)
            self.assertEqual(len(m.dynamics),5)
            self.assertEqual([m.dynamics[o].name for o in (5268,5300,5332,5364)],
                             ['sfront','sfront','srear','srear'])
            self.assertEqual(m.dynamics[5300].angles,(-(1<<31),0,0))
            self.assertEqual(m.build_modified_bytes()[0],m.raw)

    def test_parent_only_changes_and_undoable_values(self):
        with tempfile.TemporaryDirectory() as tmp:
            source=Path(tmp)/'roadcar.3do'
            source.write_bytes((BASE/'fixtures'/'roadcar.3do').read_bytes())
            m=Model(source)
            before=m.raw
            m.set_dynamic(5268,(33284,17497,-1253),(degrees_to_papyrus(15),0,0))
            self.assertTrue(m.dirty)
            data,report=m.build_modified_bytes()
            self.assertEqual(report.updated_dynamics,1)
            allowed=set(range(m.body_start+5268+4,m.body_start+5268+28))
            self.assertTrue(any(data[i]!=before[i] for i in allowed))
            self.assertTrue(all(a==b for i,(a,b) in enumerate(zip(data,before)) if i not in allowed))
            edited=Path(tmp)/'edited.3do';edited.write_bytes(data)
            reread=Model(edited)
            self.assertEqual(reread.dynamics[5268].xyz,(33284,17497,-1253))
            self.assertEqual(reread.dynamics[5268].angles[0],degrees_to_papyrus(15))
            m.reset()
            self.assertEqual(m.build_modified_bytes()[0],before)

    def test_external_geometry_at_parent_traversal_site(self):
        with tempfile.TemporaryDirectory() as tmp:
            d=Path(tmp)
            parent=d/'roadcar.3do'
            parent.write_bytes((BASE/'fixtures'/'roadcar.3do').read_bytes())
            make_test_wheel(d/'SFRONT.3DO')
            make_test_wheel(d/'SREAR.3DO')
            make_test_wheel(d/'helmet.3do')
            before=(d/'SFRONT.3DO').read_bytes()
            m=Model(parent)
            resolver=ExternalResolver()
            faces,errors=gather_faces(m,0,(0,-200000,100000),'original',resolver)
            self.assertFalse(errors)
            child=[f for f in faces if f.placement is not None]
            self.assertTrue(child)
            self.assertEqual({f.placement for f in child},set(m.dynamics))
            self.assertTrue(any(f.placement is None for f in faces))
            one=next(f for f in child if f.placement==5300)
            self.assertAlmostEqual(one.transform.apply((1,2,3))[1],-17499.0,places=3)
            m.set_dynamic(5300,(-29426,-15000,-2253),(-2147483648,0,0))
            m.write(d/'changed.3do')
            self.assertEqual((d/'SFRONT.3DO').read_bytes(),before)

    def test_unresolved_components_safe(self):
        with tempfile.TemporaryDirectory() as tmp:
            parent=Path(tmp)/'roadcar.3do'
            parent.write_bytes((BASE/'fixtures'/'roadcar.3do').read_bytes())
            m=Model(parent)
            faces,failures=gather_faces(m,0,(0,0,100000),'original',ExternalResolver())
            self.assertEqual(len(failures),5)
            self.assertTrue(any(f.placement is None for f in faces))
            self.assertTrue(all(f.placement is None for f in faces))

    def test_angles_and_rotation(self):
        self.assertEqual(degrees_to_papyrus(180),-(1<<31))
        self.assertEqual(degrees_to_papyrus(-180),-(1<<31))
        self.assertEqual(papyrus_to_degrees(-(1<<31)),-180)
        m=Model(BASE/'fixtures'/'roadcar.3do')
        t=placement_transform(m.dynamics[5300])
        self.assertEqual(tuple(round(x) for x in t.apply((100,0,0))),
                         (32184,-17497,-2253))
        self.assertEqual(tuple(round(x) for x in t.inverse_point((32184,-17497,-2253))),
                         (100,0,0))

if __name__=='__main__':
    unittest.main()
