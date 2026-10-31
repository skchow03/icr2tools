"""v0.6 FACE2 side-selection regression tests against supplied car files."""
import unittest
from pathlib import Path
from three_do import Model

FIXTURES = Path(__file__).parent/'fixtures'

class Face2Tests(unittest.TestCase):
    FRONT=(0,300000,50000)
    BACK=(0,-300000,50000)

    def test_5540_sidedness_follows_face2_in_near_mid_and_high_lod(self):
        m=Model(FIXTURES/'roadcar.3do')
        for lod in (0,250000,350000):
            with self.subTest(lod=lod):
                front,_,_=m.switched_polygons(lod,self.FRONT,'original')
                back,_,_=m.switched_polygons(lod,self.BACK,'original')
                self.assertIn(5540,front)
                self.assertNotIn(5540,back)
                # No BSP intentionally leaves the polygon visible from both sides.
                off_front,_,_=m.switched_polygons(lod,self.FRONT,'off')
                off_back,_,_=m.switched_polygons(lod,self.BACK,'off')
                self.assertIn(5540,off_front)
                self.assertIn(5540,off_back)

    def test_face2_children_are_view_dependent(self):
        m=Model(FIXTURES/'roadcar.3do')
        # Isolate FACE2 @10580; binary +24 is front list containing 5540,
        # binary +28 is a different back-side list.
        m.root_offset=10580
        front,_,_=m.switched_polygons(None,self.FRONT,'original')
        back,_,_=m.switched_polygons(None,self.BACK,'original')
        self.assertIn(5540,front)
        self.assertNotIn(5540,back)
        self.assertNotEqual(front,back)

    def test_flipping_face2_swaps_visibility_in_rebuilt_preview(self):
        m=Model(FIXTURES/'roadcar.3do')
        m.root_offset=10580
        before=m.switched_polygons(None,self.FRONT,'original')[0]
        m.flip_plane(10580,5540)
        rebuilt=m.switched_polygons(None,self.FRONT,'rebuilt')[0]
        original=m.switched_polygons(None,self.FRONT,'original')[0]
        self.assertIn(5540,before)
        self.assertNotIn(5540,rebuilt)
        self.assertEqual(original,before)
        self.assertNotEqual(set(rebuilt),set(before))

    def test_5540_other_car_variants(self):
        for name in ('indycar','panoz','irl'):
            with self.subTest(name=name):
                m=Model(FIXTURES/(name+'.3do'))
                self.assertIn(5540,m.polygons)
                front=m.switched_polygons(0,self.FRONT,'original')[0]
                back=m.switched_polygons(0,self.BACK,'original')[0]
                self.assertIn(5540,front)
                self.assertNotIn(5540,back)

if __name__=='__main__': unittest.main()
