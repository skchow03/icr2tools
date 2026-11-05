"""Regression for the ICR2 bldg1.3do zero-body-offset vertex ambiguity.

This self-contained synthetic 3DO exercises the exact pointer layout of
bldg1.3do without distributing any proprietary game asset:
body offset 0 is a textured vertex; separate LIST child slot 0 means NIL.
"""
from __future__ import annotations

import struct
import unittest

from n3_compile import compile_n3_text
from text_3d import export_compilable_text, export_text, import_text
from three_do import FormatError, Model


def fixture_zero_vertex_binary():
    body = bytearray()

    def record(tag, *fields):
        address = len(body)
        body.extend(struct.pack("<I" + "i" * len(fields),
                                0x80000000 | tag, *fields))
        return address

    def vertex(x, y, z, u, v):
        address = len(body)
        body.extend(struct.pack("<4i2H", 0, x, y, z, u, v))
        return address

    first = vertex(0, 0, 27, 127, 120)
    middle = vertex(10, 0, 27, 127, 200)
    last = vertex(0, 10, 27, 127, 0)
    assert (first, middle, last) == (0, 20, 40)

    # Both kinds of POLY reference the real vertex at offset zero.
    # A repeated first vertex is the conventional closed-polygon slot.
    textured = record(2, 4, 42, 3, first, middle, last, first)
    plain = record(1, 46, 3, middle, first, last, middle)
    material = record(4, 0, 4, textured)
    # This zero IS an absent child, not a vertex.
    root = record(11, 3, material, 0, plain)

    header = struct.pack("<5i", len(body), root, 1, 0, 0)
    return header + b"bldg1a\x00" + bytes(body)


class ZeroVertexExportTests(unittest.TestCase):
    def setUp(self):
        self.binary = fixture_zero_vertex_binary()
        self.model = Model(
            "synthetic_zero_vertex.3do",
            raw_data=self.binary, associate_planes=False)
        self.assertIn(0, self.model.vertices)
        self.assertEqual(len(self.model.polygons), 2)
        self.assertEqual(self.model.root_offset, max(self.model.records))

    def test_compilable_export_distinguishes_poly_vertex_zero_from_nil(self):
        source = export_compilable_text(self.model)
        self.assertIn("_0: [<0, 0, 27>, T=<127, 120>];", source)
        self.assertRegex(
            source, r"POLY \[T\] <42> \{_0, _20, _40, _0\}")
        self.assertRegex(
            source, r"POLY <46> \{_20, _0, _40, _20\}")
        self.assertRegex(source, r"root: LIST \{_\\d+, NIL, _\\d+\}")
        self.assertNotIn("POLY [T] <42> {NIL", source)
        self.assertEqual(self.model.raw, self.binary)

    def test_binary_to_source_to_binary_keeps_actual_zero_vertex(self):
        source = export_compilable_text(self.model)
        compiled, _ = compile_n3_text(
            source, "roundtrip.3d", associate_planes=False)
        # The standalone compiler reserves four bytes for null pointers.
        # It relocates authored '_0' to a positive offset, preserving shape.
        self.assertGreater(compiled.n3_label_offsets["_0"], 0)
        self.assertEqual(
            compiled.vertices[compiled.n3_label_offsets["_0"]].xyz,
            self.model.vertices[0].xyz)
        self.assertEqual(len(compiled.polygons), len(self.model.polygons))
        self.assertEqual(
            sorted(tuple(self.model.vertices[r].xyz for r in p.refs)
                   for p in self.model.polygons.values()),
            sorted(tuple(compiled.vertices[r].xyz for r in p.refs)
                   for p in compiled.polygons.values()))
        # Parsed scene children omit NIL; inspect the original raw LIST slot.
        self.assertEqual(struct.unpack_from(
            "<i", compiled.body, compiled.root_offset + 12)[0], 0)
        self.assertEqual(self.model.raw, self.binary)

    def test_annotated_export_and_safe_in_place_import(self):
        annotated = export_text(self.model)
        self.assertIn("% ICR2_OFFSET: 0", annotated)
        self.assertIn("_0: [<0, 0, 27>, T=<127, 120>];", annotated)
        self.assertRegex(
            annotated, r"POLY \[T\] <42> \{_0, _20, _40, _0\}")
        self.assertIn("NIL", annotated)  # LIST child, not a vertex.
        modified, _ = import_text(self.model, annotated)
        self.assertEqual(modified.raw, self.binary)

    def test_reject_nil_in_polygon_even_when_vertex_zero_exists(self):
        source = export_compilable_text(self.model)
        invalid = source.replace(
            "POLY [T] <42> {_0, _20", "POLY [T] <42> {NIL, _20")
        self.assertNotEqual(invalid, source)
        with self.assertRaisesRegex(FormatError, "polygon must reference"):
            compile_n3_text(invalid, "invalid.3d", associate_planes=False)
        # The original binary has no null polygon vertex in any record.
        self.assertTrue(all(
            ref in self.model.vertices
            for poly in self.model.polygons.values()
            for ref in poly.refs))


if __name__ == "__main__":
    unittest.main()
