"""Papyrus N3 FACE/BSP planes must be defined with three points, not raw coefficients."""
from pathlib import Path
import re
import unittest

from n3_compile import compile_n3_text
from n3_plane_points import get_points_on_plane, oriented_plane_matches, plane_expression
from text_3d import export_text, import_text
from three_do import FormatError, Model

FIXTURES=Path(__file__).resolve().parents[1]/"fixtures"


class N3PlaneExpressionTests(unittest.TestCase):
    def test_exact_integer_points_respect_orientation(self):
        for equation in ((0,0,1,-37),(0,0,-1,37),
                         (3,5,7,-11),(-1,0,0,100),
                         (7,-3,19,-1234)):
            with self.subTest(eq=equation):
                points=get_points_on_plane(equation)
                self.assertEqual(len(set(points)),3)
                self.assertTrue(oriented_plane_matches(equation,points))
                self.assertTrue(all(-2147483648<=v<=2147483647
                                    for p in points for v in p))

    def test_impossible_exact_integer_plane_rejected(self):
        for eq in ((2,4,6,-3),(0,0,0,0)):
            with self.subTest(eq=eq):
                with self.assertRaises(FormatError):
                    get_points_on_plane(eq)

    def test_named_vertex_pointers_preferred_when_matching(self):
        src="""3D VERSION 3.0;
nil: NIL;
a: [<0,0,37>];
b: [<100,0,37>];
c: [<0,100,37>];
p: POLY <40> {a,b,c};
root: BSPF (a,b,c), nil,p,nil;
"""
        model,_=compile_n3_text(src,"matching.3d")
        off=next(o for o,p in model.planes.items() if p.kind==7)
        expr=plane_expression(model,off)
        self.assertTrue(re.fullmatch(r"\(_\d+, _\d+, _\d+\)",expr),expr)
        source=export_text(model)
        self.assertIn("BSPF (_",source)
        self.assertNotRegex(source,r"BSPF\s*\(\s*-?\d+\s*,")
        rebuilt,_=compile_n3_text(source,"rebuilt.3d")
        self.assertEqual(len(rebuilt.planes),1)

    def test_missing_vertices_use_three_inline_coordinates(self):
        src="""3D VERSION 3.0;
nil: NIL;
a: [<0,0,0>];
b: [<100,0,0>];
c: [<0,100,0>];
p: POLY <40> {a,b,c};
root: BSPF ([<0,0,37>],[<100,0,37>],[<0,100,37>]), nil,p,nil;
"""
        model,_=compile_n3_text(src,"far_plane.3d")
        off=next(iter(model.planes))
        expr=plane_expression(model,off)
        self.assertEqual(expr.count("[<"),3,expr)
        self.assertIn("], [<",expr)
        source=export_text(model)
        self.assertIn("BSPF ([<",source)
        self.assertNotRegex(source,r"BSPF\s*\(\s*-?\d+\s*,")
        rebuilt,_=compile_n3_text(source,"rebuilt.3d")
        self.assertEqual(rebuilt.planes[next(iter(rebuilt.planes))].equation,
                         model.planes[off].equation)

    def test_binary_fixtures_emit_no_five_coefficient_plane(self):
        for name in ("roadcar.3do","indycar.3do","cars.3do"):
            path=FIXTURES/name
            if not path.exists():continue
            with self.subTest(name=name):
                model=Model(path)
                src=export_text(model)
                self.assertNotRegex(src,r"\b(?:FACE2?|BSPF|BSPA|BSP2|BSPN)\s+"
                                        r"\(\s*-?\d+\s*,\s*-?\d+\s*,\s*-?\d+\s*,")
                rebuilt,doc=import_text(model,src)
                self.assertEqual(rebuilt.raw,model.raw)

    def test_original_pointer_aliases_survive_noop_source_export(self):
        src="""3D VERSION 3.0;
nil: NIL;
a: [<0,0,0>]; b: [<100,0,0>]; c: [<0,100,0>];
p: POLY <44> {a,b,c};
root: FACE (a,b,c), p;
"""
        # Existing standalone converter accepts one declaration per line.
        src=src.replace("; b:", ";\nb:").replace("; c:", ";\nc:")
        m,_=compile_n3_text(src,"face.3d")
        output=export_text(m)
        self.assertNotIn("FACE (0, 0, ",output)
        self.assertIn("FACE (_",output)


if __name__=="__main__":
    unittest.main()
