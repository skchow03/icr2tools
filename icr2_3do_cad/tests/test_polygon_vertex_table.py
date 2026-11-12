"""Selected-POLY table: authored coordinates, UV spans, shared vertices and safety."""
import unittest
from decimal import Decimal

from n3_compile import compile_n3_text
from polygon_vertex_table import (
    polygon_vertex_rows, plan_polygon_vertex_edit,
    source_vertex_declarations,
)

SOURCE = """3D VERSION 3.0;
nose: [<100, 20, 30>, T=<12,34>]; % keep this comment
outside: [<200, 20, 30>, T=<32,34>];
top: [
    <50, 60, 30>,
    T = <12, 90>
];
paint: POLY [T] <49> {nose,outside,top};
other: POLY [T] <50> {nose,top,outside};
root: LIST {paint,other};
"""


class SelectedPolygonVertexTableTests(unittest.TestCase):
    def setUp(self):
        self.model, _ = compile_n3_text(
            SOURCE, "poly_table.3d", associate_planes=False)
        self.polygon = self.model.n3_label_offsets["paint"]
        self.nose = self.model.n3_label_offsets["nose"]

    def test_vertex_order_and_authored_xyz_uv_are_preserved(self):
        rows = polygon_vertex_rows(self.model, self.polygon, SOURCE)
        self.assertEqual([r.label for r in rows],
                         ["nose", "outside", "top"])
        self.assertEqual(rows[0].values, ("100", "20", "30", "12", "34"))
        self.assertEqual(rows[2].values, ("50", "60", "30", "12", "90"))
        self.assertTrue(all(rows[0].editable))

    def test_numeric_field_changes_only_target_token(self):
        plan = plan_polygon_vertex_edit(
            SOURCE, self.model, self.polygon, self.nose, "x", "155")
        self.assertTrue(plan.changed)
        changed = SOURCE[:plan.start] + plan.after + SOURCE[plan.end:]
        self.assertEqual(
            changed, SOURCE.replace("nose: [<100,", "nose: [<155,"))
        self.assertIn("T=<12,34>]; % keep this comment", changed)
        self.assertEqual(plan.field, "X")
        rebuilt, _ = compile_n3_text(
            changed, "edited_poly.3d", associate_planes=False)
        self.assertEqual(
            rebuilt.vertices[rebuilt.n3_label_offsets["nose"]].xyz[0], 155)
        self.assertIn(
            rebuilt.n3_label_offsets["nose"],
            rebuilt.polygons[rebuilt.n3_label_offsets["other"]].unique_refs)

    def test_uv_changes_compiled_texture_without_moving_xyz(self):
        plan = plan_polygon_vertex_edit(
            SOURCE, self.model, self.polygon, self.nose, "v", "128")
        updated = SOURCE[:plan.start] + plan.after + SOURCE[plan.end:]
        self.assertIn("nose: [<100, 20, 30>, T=<12,128>];", updated)
        rebuilt, _ = compile_n3_text(
            updated, "newuv.3d", associate_planes=False)
        vertex = rebuilt.vertices[rebuilt.n3_label_offsets["nose"]]
        self.assertEqual(vertex.xyz, (100, 20, 30))
        self.assertEqual(vertex.uv, (12, 128))
        self.assertEqual(plan.field, "V")

    def test_scaled_xyz_table_uses_authored_not_raw_coordinates(self):
        source = """3D VERSION 3.0;
% ICR2_COORD_SCALE: 6000
a: [<0.5,0,0>, T=<0,1>];
b: [<1,0,0>, T=<0,2>];
c: [<0,1,0>, T=<0,3>];
p: POLY [T] <49> {a,b,c};
root: LIST {p};
"""
        model, _ = compile_n3_text(
            source, "scaled.3d", associate_planes=False)
        poly = model.n3_label_offsets["p"]
        a = model.n3_label_offsets["a"]
        self.assertEqual(polygon_vertex_rows(model, poly, source)[0].values[0],
                         "0.5")
        plan = plan_polygon_vertex_edit(source, model, poly, a, "x", "0.6")
        edited = source[:plan.start] + plan.after + source[plan.end:]
        rebuilt, _ = compile_n3_text(
            edited, "scaled2.3d", associate_planes=False)
        self.assertEqual(rebuilt.vertices[rebuilt.n3_label_offsets["a"]].xyz[0],
                         3600)

    def test_prevent_changing_implicit_scale_of_all_vertices(self):
        with self.assertRaisesRegex(ValueError, "implicit coordinate scale"):
            plan_polygon_vertex_edit(
                SOURCE, self.model, self.polygon, self.nose, "x", "100.5")

    def test_validation_noop_invalid_uv_and_stale_geometry(self):
        self.assertFalse(plan_polygon_vertex_edit(
            SOURCE, self.model, self.polygon, self.nose, "u", "12").changed)
        for text in ("-1", "65536", "2.5", "xyz", "NaN"):
            with self.subTest(text=text):
                with self.assertRaises(ValueError):
                    plan_polygon_vertex_edit(
                        SOURCE, self.model, self.polygon, self.nose,
                        "v", text)
        with self.assertRaisesRegex(ValueError, "no longer belongs"):
            plan_polygon_vertex_edit(
                SOURCE, self.model, self.polygon, -500, "u", "45")
        out_of_sync = SOURCE.replace("nose: [<100,", "nose: [<101,")
        with self.assertRaisesRegex(ValueError, "no longer match"):
            plan_polygon_vertex_edit(
                out_of_sync, self.model, self.polygon, self.nose, "x", "150")

    def test_anonymous_and_nontextured_cells_are_read_only(self):
        source = """3D VERSION 3.0;
a: [<0,0,0>];
b: [<100,0,0>];
p: POLY <42> {a,b,[<0,100,0>]};
root: LIST {p};
"""
        model, _ = compile_n3_text(
            source, "anonymous.3d", associate_planes=False)
        rows = polygon_vertex_rows(model, model.n3_label_offsets["p"], source)
        self.assertEqual(len(rows), 3)
        self.assertEqual(rows[0].editable, (True, True, True, False, False))
        self.assertFalse(any(rows[2].editable))
        self.assertIn("(inline)", rows[2].label)


if __name__ == "__main__":
    unittest.main()
