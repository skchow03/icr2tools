"""Safe textual N3 vertex moves: scale, range, UV, comments and no-op."""
import unittest

from source_vertex_move import plan_vertex_move
from source_symmetry import apply_replacements


SOURCE = """3D VERSION 3.0;
left: [<100,20,30>, T=<12,34>]; % keep
right: [<-100,20,30>, T=<56,78>];
root: LIST {left,right};
"""


class VertexSourceMoveTests(unittest.TestCase):
    def test_only_xyz_tokens_change(self):
        p = plan_vertex_move(SOURCE, "left",
                             (100,20,30), (150,20,45))
        result = apply_replacements(SOURCE, p.edits)
        self.assertEqual(
            result,
            SOURCE.replace("<100,20,30>", "<150,20,45>"))
        self.assertIn("T=<12,34>]; % keep", result)
        self.assertIn("right: [<-100,20,30>", result)
        self.assertEqual(len(p.edits), 2)

    def test_explicit_fractional_scale(self):
        source = """3D VERSION 3.0;
% ICR2_COORD_SCALE: 6000
v: [<0.5, -0.25, 0.125>, T=<9,10>];
root: NIL;
"""
        p = plan_vertex_move(source, "v",
                             (3000,-1500,750), (3600,-1200,750))
        result = apply_replacements(source, p.edits)
        self.assertIn("v: [<0.6, -0.2, 0.125>, T=<9,10>]", result)

    def test_implicit_fractional_scale(self):
        source = """3D VERSION 3.0;
a: [<0.5,0,1>, T=<20,40>];
root: NIL;
"""
        p = plan_vertex_move(
            source, "a", (3000,0,6000), (4200,0,8400))
        result = apply_replacements(source, p.edits)
        self.assertIn("a: [<0.7,0,1.4>, T=<20,40>]", result)
        self.assertNotIn("ICR2_COORD_SCALE", result)

    def test_half_even_compiled_roundtrip_with_repeating_decimal(self):
        source = """3D VERSION 3.0;
% ICR2_COORD_SCALE: 3
a: [<1,2,3>];
root: NIL;
"""
        p = plan_vertex_move(source,"a",(3,6,9),(4,7,8))
        result = apply_replacements(source,p.edits)
        self.assertIn("a: [<1.333333333333,2.333333333333,2.666666666667>]",result)

    def test_missing_mismatch_noop_and_range(self):
        with self.assertRaisesRegex(ValueError, "No complete"):
            plan_vertex_move(SOURCE,"unknown",(1,2,3),(2,2,3))
        with self.assertRaisesRegex(ValueError, "no longer matches"):
            plan_vertex_move(SOURCE,"left",(999,20,30),(150,20,30))
        with self.assertRaisesRegex(ValueError, "32-bit"):
            plan_vertex_move(SOURCE,"left",(100,20,30),
                             (2_147_483_648,20,30))
        p = plan_vertex_move(SOURCE,"left",(100,20,30),(100,20,30))
        self.assertFalse(p.changed)
        self.assertEqual(p.edits,())

    def test_multiline_and_unicode_comments_preserved(self):
        source = ("""3D VERSION 3.0;
% 日本語
nose: [
    <100, 20, 30>,
    T=<500,600>
]; % leave UV alone
root: NIL;
""")
        p = plan_vertex_move(source,"nose",
                             (100,20,30),(150,25,31))
        result = apply_replacements(source,p.edits)
        self.assertIn("    <150, 25, 31>,",result)
        self.assertIn("    T=<500,600>",result)
        self.assertIn("% 日本語",result)


if __name__ == "__main__":
    unittest.main()
