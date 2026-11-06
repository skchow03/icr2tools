"""Regression tests for the GPU viewer's source-preserving split workflow.

These test the source adapter without importing Qt/OpenGL; the GUI uses the
same binary topology operations and live N3 compiler.
"""
from pathlib import Path
import sys
import unittest

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from n3_compile import compile_n3_text
from three_do import FormatError
from gpu_viewer.polygon_split import split_n3_polygon


SQUARE = """3D VERSION 3.0;
% Preserve this annotated source comment.
a: [<0, 0, 0>];
b: [<100, 0, 0>];
c: [<100, 100, 0>];
d: [<0, 100, 0>];
face: POLY <42> {a, b, c, d}; % Keep the selected face note
root: LIST {face};
"""

NEIGHBORS = """3D VERSION 3.0;
a: [<0, 0, 0>];
b: [<100, 0, 0>];
c: [<100, 100, 0>];
d: [<0, 100, 0>];
e: [<200, 0, 0>];
f: [<200, 100, 0>];
left: POLY <42> {a, b, c, d};
right: POLY <51> {b, e, f, c};
root: LIST {left, right};
"""

TEXTURED = """3D VERSION 3.0;
a: [<0, 0, 0>, T=<0, 0>];
b: [<100, 0, 0>, T=<200, 0>];
c: [<100, 100, 0>, T=<200, 200>];
d: [<0, 100, 0>, T=<0, 200>];
piece: MATERIAL MIP="TEST", GROUP=3, POLY [T] <32> {a, b, c, d};
root: LIST {piece};
"""


class GPUPolygonSplitTests(unittest.TestCase):
    def compile(self, text):
        return compile_n3_text(text, ROOT / "fixtures" / "test.3d",
                               associate_planes=False)[0]

    def test_existing_vertex_diagonal_preserves_original_source(self):
        original = self.compile(SQUARE)
        result = split_n3_polygon(
            original, SQUARE, original.n3_label_offsets["face"],
            mode="vertices", index_a=0, index_b=2)
        self.assertEqual(result.new_vertices, 0)
        self.assertEqual(result.updated_neighbors, 0)
        self.assertIn("% Preserve this annotated source comment.", result.source)
        self.assertIn("% Keep the selected face note", result.source)
        self.assertIn("face: LIST {", result.source)
        rebuilt = self.compile(result.source)
        for label in (result.first_polygon_label, result.second_polygon_label):
            polygon = rebuilt.polygons[rebuilt.n3_label_offsets[label]]
            self.assertEqual(polygon.color, 42)
            self.assertEqual(len(set(polygon.refs)), 3)
        self.assertEqual(len(rebuilt.polygons), 2)
        self.assertEqual(len(original.polygons), 1)

    def test_output_reuses_existing_authored_vertex_pointer_names(self):
        # UI names must correspond to the actual N3 pointers written by
        # either splitting mode, not numeric compiled body offsets.
        renamed = (SQUARE.replace("a: [", "front_left: [")
                   .replace("b: [", "front_right: [")
                   .replace("c: [", "rear_right: [")
                   .replace("d: [", "rear_left: [")
                   .replace("{a, b, c, d}",
                            "{front_left, front_right, rear_right, rear_left}"))
        model = self.compile(renamed)
        for mode in ("vertices", "edges"):
            with self.subTest(mode=mode):
                result = split_n3_polygon(
                    model, renamed, model.n3_label_offsets["face"],
                    mode=mode, index_a=0, index_b=2)
                self.assertIn("front_left", result.source)
                self.assertIn("front_right", result.source)
                self.assertIn("rear_right", result.source)
                self.assertIn("rear_left", result.source)
                self.assertNotIn("POLY <42> {@", result.source)
                checked = self.compile(result.source)
                self.assertEqual(len(checked.polygons), 2)

    def test_edge_split_repairs_shared_neighbor_and_preserves_labels(self):
        original = self.compile(NEIGHBORS)
        result = split_n3_polygon(
            original, NEIGHBORS, original.n3_label_offsets["left"],
            mode="edges", index_a=1, index_b=3,
            fraction_a=0.5, fraction_b=0.5)
        self.assertEqual(result.new_vertices, 2)
        self.assertEqual(result.updated_neighbors, 1)
        self.assertIn("right: POLY <51>", result.source)
        rebuilt = self.compile(result.source)
        right = rebuilt.polygons[rebuilt.n3_label_offsets["right"]]
        positions = [rebuilt.vertices[offset].xyz for offset in right.refs]
        self.assertIn((100, 50, 0), positions)
        self.assertEqual(len(set(right.refs)), 5)
        self.assertEqual(len(rebuilt.polygons), 3)

    def test_inline_material_wrapper_is_preserved(self):
        original = self.compile(TEXTURED)
        # Click picking resolves the wrapper to its one compiled child POLY.
        material = original.n3_label_offsets["piece"]
        polygon_offset = original.children[material][0]
        result = split_n3_polygon(
            original, TEXTURED, polygon_offset,
            mode="edges", index_a=0, index_b=2)
        self.assertIn('piece: MATERIAL MIP="TEST", GROUP=3, LIST {',
                      result.source)
        rebuilt = self.compile(result.source)
        self.assertEqual(len(rebuilt.polygons), 2)
        for label in (result.first_polygon_label, result.second_polygon_label):
            polygon = rebuilt.polygons[rebuilt.n3_label_offsets[label]]
            self.assertEqual(polygon.kind, 2)
            for offset in polygon.refs:
                self.assertIsNotNone(rebuilt.vertices[offset].uv)

    def test_scaled_source_points_round_trip_to_exact_raw_coordinates(self):
        text = ("% ICR2_COORD_SCALE: 6000\n" +
                SQUARE.replace("100", "1"))
        original = self.compile(text)
        result = split_n3_polygon(
            original, text, original.n3_label_offsets["face"],
            index_a=0, index_b=2,
            fraction_a=0.333, fraction_b=0.5)
        rebuilt = self.compile(result.source)
        locations = {v.xyz for v in rebuilt.vertices.values()}
        self.assertIn((1998, 0, 0), locations)
        self.assertIn((3000, 6000, 0), locations)

    def test_invalid_split_does_not_modify_model(self):
        original = self.compile(SQUARE)
        raw_before = original.raw
        with self.assertRaises((FormatError, ValueError)):
            split_n3_polygon(
                original, SQUARE, original.n3_label_offsets["face"],
                index_a=0, index_b=0)
        self.assertEqual(original.raw, raw_before)

    def test_unlabeled_inline_list_polygon_is_rejected(self):
        source = SQUARE.replace("face: POLY <42> {a, b, c, d}; % Keep the selected face note\n",
                                "").replace(
            "root: LIST {face};", "root: LIST {POLY <42> {a, b, c, d}};")
        model = self.compile(source)
        offset = next(iter(model.polygons))
        with self.assertRaisesRegex(FormatError, "no individually editable"):
            split_n3_polygon(model, source, offset, index_a=0, index_b=2)


if __name__ == "__main__":
    unittest.main()
