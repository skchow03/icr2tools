"""BSP2 endplate regression for stock roadcar/irl/panoz geometry.

Body offsets 7076/7108 and 7136/7168 are coincident textured/plain
polygons and must not be rendered simultaneously in BSP mode.
"""
import unittest
from pathlib import Path
from three_do import Model

BASE=Path(__file__).resolve().parents[1]/'fixtures'

class WingBsp2Tests(unittest.TestCase):
    def test_innermost_bsp2_child_slots_and_matching_polygons(self):
        m=Model(BASE/'roadcar.3do')
        for tex,plain,outer in ((7136,7168,9960),(7076,7108,10000)):
            self.assertEqual(m.polygons[tex].kind,2)
            self.assertEqual(m.polygons[plain].kind,1)
            self.assertEqual([m.vertices[v].xyz for v in m.polygons[tex].unique_refs],
                             [m.vertices[v].xyz for v in m.polygons[plain].unique_refs])
            self.assertEqual(m.children[outer][-2:], [tex,plain])
            self.assertEqual(m.records[outer],9)

    def test_endplates_view_dependent_without_coincident_overdraw(self):
        for name in ('roadcar','irl','panoz'):
            with self.subTest(name=name):
                m=Model(BASE/(name+'.3do'))
                for lod in (0,250000,400000):
                    for mode in ('original','rebuilt'):
                        for y,expected in ((-80000,{7108,7136}),
                                           (0,{7108,7168}),
                                           (80000,{7076,7168})):
                            with self.subTest(lod=lod,mode=mode,y=y):
                                offsets,stats,_=m.switched_polygons(lod,(-36000,y,7000),mode)
                                shown=set(offsets)&{7076,7108,7136,7168}
                                self.assertEqual(shown,expected)
                                if y<0:
                                    self.assertLess(offsets.index(7108),offsets.index(7136))
                                if y>0:
                                    self.assertLess(offsets.index(7168),offsets.index(7076))

    def test_wing_center_painted_between_far_and_near_endplates(self):
        m=Model(BASE/'roadcar.3do')
        for lod,middle in ((0,6888),(250000,11544),(400000,11544)):
            for y,far,near in ((-80000,7108,7136),(80000,7168,7076)):
                with self.subTest(lod=lod,y=y):
                    painted,_,_=m.switched_polygons(lod,(-36000,y,7000),'original')
                    self.assertLess(painted.index(far),painted.index(middle))
                    self.assertLess(painted.index(middle),painted.index(near))

    def test_no_bsp_mode_still_allows_inspection_of_every_polygon(self):
        m=Model(BASE/'roadcar.3do')
        offsets,_,_=m.switched_polygons(0,(-36000,-80000,7000),'off')
        self.assertTrue({7076,7108,7136,7168}.issubset(offsets))

    def test_zero_edit_save_remains_identical(self):
        m=Model(BASE/'roadcar.3do')
        self.assertEqual(m.build_modified_bytes()[0],m.raw)

if __name__=='__main__':
    unittest.main()
