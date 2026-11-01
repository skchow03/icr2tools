"""Regression: fractional standalone N3 coordinates must not collapse BSP planes.

Reproduces the failure pattern in cone.3d without publishing the author's
entire original scenery source. Papyrus integers are kept unscaled; fractional
feet default to the documented legacy 3d23do /s=6000 scale.
"""
import unittest
from decimal import Decimal

from n3_compile import compile_n3_text, Compiler
from three_do import FormatError


CONE_FRAGMENT="""3D VERSION 3.0;
nil: NIL;
a0: [<-0.4375, 0.4375, 0>];
b0: [<-0.4375, -0.4375, 0>];
c0: [<0.4375, -0.4375, 0>];
a1: [<-0.4375, 0.4375, 0.083>];
b1: [<-0.4375, -0.4375, 0.083>];
c1: [<0.4375, -0.4375, 0.083>];
e: [<-0.3125, 0.3125, 0.083>];
f: [<-0.3125, -0.3125, 0.083>];
j: [<-0.0520833333333333, 0.0520833333333333, 1.41666666666667>];
k: [<-0.0520833333333333, -0.0520833333333333, 1.41666666666667>];
base_l: POLY <46> {a1,a0,b0,b1};
cone_ls: POLY <56> {j,e,f,k};
o0: BSPF (a1,a0,b0), nil,base_l,nil;
root: BSPF (j,e,f), nil,cone_ls,o0;
"""


class N3FractionalCoordinateTests(unittest.TestCase):
    def test_fractional_cone_bsp_is_not_collinear(self):
        compiled, doc=compile_n3_text(CONE_FRAGMENT,"cone.3d")
        self.assertEqual(compiled.n3_coordinate_scale,Decimal(6000))
        self.assertEqual(len(compiled.polygons),2)
        self.assertEqual(len(compiled.planes),2)
        coordinates={v.xyz for v in compiled.vertices.values()}
        self.assertIn((-2625,2625,498),coordinates)
        self.assertIn((-2625,2625,0),coordinates)
        self.assertIn((-2625,-2625,0),coordinates)
        self.assertIn((-312,-312,8500),coordinates)
        self.assertEqual(len({x[2] for x in coordinates if x[2]>0}),2)
        self.assertTrue(all(plane.equation[:3]!=(0,0,0)
                            for plane in compiled.planes.values()))
        self.assertIn("a1",doc.original_text)

    def test_edit_then_export_uses_canonical_scale_without_double_scaling(self):
        from text_3d import export_standalone_text
        original=CONE_FRAGMENT.replace("3D VERSION 3.0;",
                     "3D VERSION 3.0;\n% ICR2_COORD_SCALE: 6000")
        model,doc=compile_n3_text(original,"cone.3d")
        original_raw=model.raw
        offset=next(i for i,v in model.vertices.items()
                    if v.xyz==(-2625,2625,498))
        model.set_vertex(offset,(-2610,2625,498))
        exported=export_standalone_text(model,doc,original_raw)
        self.assertIn("% ICR2_COORD_SCALE: 1",exported)
        self.assertNotIn("% ICR2_COORD_SCALE: 6000",exported)
        reparsed,_=compile_n3_text(exported,"roundtrip.3d")
        self.assertEqual(reparsed.n3_coordinate_scale,Decimal(1))
        self.assertIn((-2610,2625,498),
                      {v.xyz for v in reparsed.vertices.values()})
        self.assertIn("a1:",exported)

    def test_integer_papyrus_units_remain_unscaled(self):
        source="""3D VERSION 3.0;
nil: NIL;
a: [<0,0,0>]; 
b: [<1000,0,0>];
c: [<0,1000,0>];
poly: POLY <20> {a,b,c};
root: FACE (a,b,c), poly;
"""
        model,_=compile_n3_text(source,"native.3d")
        self.assertEqual(model.n3_coordinate_scale,Decimal(1))
        self.assertIn((1000,0,0),{v.xyz for v in model.vertices.values()})

    def test_explicit_scale_for_metric_and_other_authoring_units(self):
        source=CONE_FRAGMENT.replace("3D VERSION 3.0;",
                                     "3D VERSION 3.0;\n% ICR2_COORD_SCALE: 19685",1)
        model,_=compile_n3_text(source,"metric.3d")
        self.assertEqual(model.n3_coordinate_scale,Decimal(19685))
        self.assertIn((-8612,8612,0),{v.xyz for v in model.vertices.values()})

    def test_explicit_scale_one_keeps_fractional_values_but_explains_failure(self):
        source=CONE_FRAGMENT.replace("3D VERSION 3.0;",
                                     "3D VERSION 3.0;\n% ICR2_COORD_SCALE: 1",1)
        with self.assertRaisesRegex(FormatError,"collinear"):
            compile_n3_text(source,"invalid_scale.3d")

    def test_invalid_scale_directive_rejected(self):
        for scale in ("0","-1","not-a-number","100000000"):
            source=CONE_FRAGMENT.replace("3D VERSION 3.0;",
                       "3D VERSION 3.0;\n% ICR2_COORD_SCALE: "+scale,1)
            with self.subTest(scale=scale):
                with self.assertRaises(FormatError):
                    compile_n3_text(source,"bad.3d")

    def test_fractional_dynamic_positions_share_model_scale(self):
        source=CONE_FRAGMENT.replace("root: BSPF (j,e,f), nil,cone_ls,o0;",
            'wheel: DYNAMIC 0.5, 0, 1.25, 0, 0, 0, 1, EXTERN "wheel";\n'
            'root: LIST {o0,wheel};')
        model,_=compile_n3_text(source,"dynamic.3d")
        self.assertEqual(len(model.dynamics),1)
        d=next(iter(model.dynamics.values()))
        self.assertEqual(d.xyz,(3000,0,7500))


if __name__=="__main__":
    unittest.main()
