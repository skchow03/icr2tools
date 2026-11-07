"""Regression coverage for safe, exact named N3 symmetry pairing."""
import unittest
from decimal import Decimal

from source_symmetry import (
    named_vertices, mirror_xyz, plan_mirrored_vertices,
    coordinate_replacements, apply_replacements,
)


BASE = """3D VERSION 3.0;
left: [<100,20,30>, T=<11,22>]; % leave texture coords
right: [<-100,20,30>, T=<77,88>];
mid: [<0,20,30>];
p: POLY <44> {left,right,mid};
root: LIST {p};
"""


class SourceSymmetryTests(unittest.TestCase):
    def changes(self, edited, **opts):
        proposals, issues = plan_mirrored_vertices(BASE, edited, **opts)
        selected = [(p, p.candidates[0].label) for p in proposals
                    if len(p.candidates) == 1]
        spans = coordinate_replacements(
            edited, selected, axis=opts["axis"],
            plane_at=opts.get("plane_at", 0))
        return apply_replacements(edited, spans), proposals, issues

    def test_matches_from_previous_coords_not_from_new_position(self):
        edited = BASE.replace("left: [<100,20,30>", "left: [<120,40,-5>")
        changed, proposals, issues = self.changes(edited, axis="X")
        self.assertEqual(len(proposals), 1)
        self.assertFalse(issues)
        self.assertEqual(proposals[0].candidates[0].label, "right")
        self.assertIn("right: [<-120,40,-5>, T=<77,88>]", changed)
        self.assertIn("left: [<120,40,-5>, T=<11,22>]", changed)
        self.assertIn("p: POLY <44> {left,right,mid}", changed)

    def test_axis_y_z_and_shifted_plane(self):
        source = "a: [<5,9,10>];\nb: [<5,-3,10>];\n"
        edited = source.replace("9,10", "15,23")
        p, issues = plan_mirrored_vertices(
            source, edited, axis="Y", plane_at=3)
        self.assertEqual(len(p), 1)
        self.assertFalse(issues)
        mirrored = apply_replacements(edited,
            coordinate_replacements(edited, [(p[0], "b")],
                                    axis="Y", plane_at=3))
        self.assertIn("b: [<5,-9,23>]", mirrored)
        source = "a: [<1,2,80>];\nb: [<1,2,-80>];\n"
        edited = source.replace("2,80", "9,150")
        p, issues = plan_mirrored_vertices(source, edited, axis="Z")
        mirrored = apply_replacements(edited,
            coordinate_replacements(edited, [(p[0], "b")], axis="Z"))
        self.assertIn("b: [<1,9,-150>]", mirrored)

    def test_conservative_tolerance_never_guesses(self):
        source = "a: [<100,20,30>];\nb: [<-99,20,30>];"
        edited = source.replace("100,20,30", "120,22,40")
        p, issues = plan_mirrored_vertices(source, edited, axis="X")
        self.assertFalse(p)
        self.assertIn("no mirrored vertex", issues[0].reason)
        p, issues = plan_mirrored_vertices(
            source, edited, axis="X", tolerance=1)
        self.assertEqual(p[0].candidates[0].label, "b")
        self.assertFalse(issues)

    def test_multiple_matches_are_returned_not_auto_picked(self):
        source = ("a: [<100,20,30>];\n"
                  "b: [<-100,20,30>, T=<1,2>];\n"
                  "c: [<-100,20,30>, T=<3,4>];\n")
        edited = source.replace("a: [<100,20,30>", "a: [<150,22,35>")
        p, issues = plan_mirrored_vertices(source, edited, axis="X")
        self.assertFalse(issues)
        self.assertEqual({v.label for v in p[0].candidates}, {"b", "c"})
        changes = coordinate_replacements(
            edited, [(p[0], "c")], axis="X")
        result = apply_replacements(edited, changes)
        self.assertIn("b: [<-100,20,30>, T=<1,2>]", result)
        self.assertIn("c: [<-150,22,35>, T=<3,4>]", result)
        with self.assertRaises(ValueError):
            coordinate_replacements(edited, [(p[0], "unlisted")], axis="X")

    def test_centerline_point_maintains_plane_and_warns_if_moved_off_it(self):
        changed = BASE.replace("mid: [<0,20,30>", "mid: [<0,44,33>")
        p, issues = plan_mirrored_vertices(BASE, changed, axis="X")
        self.assertEqual(p, [])
        self.assertFalse(issues)
        changed = BASE.replace("mid: [<0,20,30>", "mid: [<10,44,33>")
        p, issues = plan_mirrored_vertices(BASE, changed, axis="X")
        self.assertEqual(p, [])
        self.assertIn("off the mirror plane", issues[0].reason)

    def test_both_sides_edited_are_preserved_and_inconsistency_warned(self):
        altered = BASE.replace("left: [<100,20,30>", "left: [<150,20,30>")
        altered = altered.replace("right: [<-100,20,30>", "right: [<-150,20,30>")
        p, issues = plan_mirrored_vertices(BASE, altered, axis="X")
        self.assertFalse(p)
        self.assertFalse(issues)
        altered = altered.replace("right: [<-150,20,30>",
                                  "right: [<-135,20,30>")
        p, issues = plan_mirrored_vertices(BASE, altered, axis="X")
        self.assertFalse(p)
        self.assertTrue(any("manually" in i.reason for i in issues))

    def test_multiline_preserves_uv_line_and_comments_and_quoted_text(self):
        source = ("""a: [
  <100, 20, 30>,
  T=<45,67>
]; % the trailing comment stays
b: [<-100,20,30>, T=<12,34>];
other: MIP "a: [<100,20,30>];";
% ghost: [<-100,20,30>];
""")
        vertices = named_vertices(source)
        self.assertEqual(set(vertices), {"a", "b"})
        altered = source.replace("100, 20, 30", "125, 30, -30")
        p, issues = plan_mirrored_vertices(source, altered, axis="X")
        self.assertFalse(issues)
        replacement = apply_replacements(
            altered, coordinate_replacements(
                altered, [(p[0], "b")], axis="X"))
        self.assertIn("b: [<-125,30,-30>, T=<12,34>]", replacement)
        self.assertIn('  T=<45,67>', replacement)
        self.assertIn('% the trailing comment stays', replacement)
        self.assertIn('% ghost: [<-100,20,30>]', replacement)

    def test_decimal_precision_and_duplicate_name_rejection(self):
        a = "a: [<1.250,-2.5,3>];\nb: [<-1.25,-2.5,3>];"
        edited = a.replace("1.250,-2.5,3", "2.75,-1.125,3.5")
        p, _ = plan_mirrored_vertices(a, edited, axis="X")
        result = apply_replacements(
            edited, coordinate_replacements(edited, [(p[0], "b")],
                                            axis="X"))
        self.assertIn("b: [<-2.75,-1.125,3.5>]", result)
        self.assertEqual(mirror_xyz(
            (Decimal("1.25"), Decimal(2), Decimal(3)), "X"),
            (Decimal("-1.25"), Decimal(2), Decimal(3)))
        with self.assertRaises(ValueError):
            named_vertices("a: [<1,2,3>];\na: [<-1,2,3>];")
        with self.assertRaises(ValueError):
            plan_mirrored_vertices(a, edited, axis="Z", tolerance=-1)


if __name__ == "__main__":
    unittest.main()
