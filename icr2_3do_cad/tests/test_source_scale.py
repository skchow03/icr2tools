"""Exact, validated uniform N3 model geometry scaling with no UV/source loss."""
from __future__ import annotations

import struct
import unittest

from source_scale import scale_multiplier, scale_n3_source
from n3_compile import compile_n3_text


SOURCE = """3D VERSION 3.0;
% [<900,900,900>] in comments is not geometry.
a: [<0,0,0>, T=<0,0>];
b: [<100,0,0>, T=<127,0>];
c: [<0,100,0>, T=<0,127>];
panel: POLY [T] <42> {a,b,c};
front: MATERIAL MIP="road", GROUP=3, panel;
root: BSPF (a,b,c), NIL, front, NIL;
"""


def vertex_xyz(model, name):
    return model.vertices[model.n3_label_offsets[name]].xyz


class N3ModelScaleTests(unittest.TestCase):
    def test_multiply_and_divide_compiled_geometry_without_uv_or_mip_changes(self):
        base, _ = compile_n3_text(SOURCE, "base.3d", associate_planes=False)
        for factor, divide, scale in (
                ("2", False, 2),
                ("4", True, 0.25),
                ("0.5", False, 0.5)):
            with self.subTest(factor=factor, divide=divide):
                result = scale_n3_source(SOURCE, factor, divide=divide)
                scaled, _ = compile_n3_text(
                    result.source, "scaled.3d", associate_planes=False)
                self.assertEqual(vertex_xyz(scaled, "b"),
                                 (round(100 * scale), 0, 0))
                self.assertEqual(vertex_xyz(scaled, "c"),
                                 (0, round(100 * scale), 0))
                self.assertEqual(vertex_xyz(scaled, "a"), (0, 0, 0))
                self.assertEqual(
                    scaled.vertices[scaled.n3_label_offsets["b"]].uv,
                    base.vertices[base.n3_label_offsets["b"]].uv)
                self.assertIn("T=<127,0>", result.source)
                self.assertIn("POLY [T] <42>", result.source)
                self.assertIn('MIP="road"', result.source)
                self.assertIn("BSPF (a,b,c)", result.source)
                self.assertIn("% [<900,900,900>]", result.source)
                self.assertEqual(result.points, 3)
                self.assertEqual(result.multiplier,
                                 scale_multiplier(factor, divide=divide))

    def test_inline_plane_vertices_and_color_vertices(self):
        text = (
            "3D VERSION 3.0;\n"
            "a: [<10, 20, 30>, c=<44>];\n"
            "b: [<0, 100, 0>];\n"
            "c: [<100, 0, 0>];\n"
            "p: POLY <44> {a,b,c};\n"
            "root: FACE ([<10,20,30>], [<0,100,0>], [<100,0,0>]), p;\n"
        )
        result = scale_n3_source(text, 3)
        self.assertIn("a: [<30, 60, 90>, c=<44>]", result.source)
        self.assertIn("FACE ([<30,60,90>], [<0,300,0>], [<300,0,0>])",
                      result.source)
        self.assertEqual(result.points, 6)
        compiled, _ = compile_n3_text(
            result.source, "inline.3d", associate_planes=False)
        self.assertEqual(vertex_xyz(compiled, "a"), (30, 60, 90))

    def test_dynamic_translations_sprite_size_and_switch_distances(self):
        source = (
            "3D VERSION 3.0;\n"
            "a: [<0,0,0>];\n"
            "b: [<100,0,0>];\n"
            "c: [<0,100,0>];\n"
            "p: POLY <42> {a,b,c};\n"
            's: SRB a, 64, "pole";\n'
            'd: DYNAMIC 10, -20, 30, 0, 0, 180, 1, EXTERN "car";\n'
            "l: SWITCH DISTANCE (a) > {(100 ? p), (0 ? NIL)};\n"
            "root: LIST {s,d,l};\n"
        )
        result = scale_n3_source(source, "2")
        self.assertIn('SRB a, 128, "pole"', result.source)
        self.assertIn('DYNAMIC 20, -40, 60, 0, 0, 180, 1', result.source)
        self.assertIn("(200 ? p), (0 ? NIL)", result.source)
        self.assertEqual(result.sprite_sizes, 1)
        self.assertEqual(result.dynamic_values, 3)
        self.assertEqual(result.lod_distances, 1)
        compiled, _ = compile_n3_text(
            result.source, "mixed.3d", associate_planes=False)
        self.assertEqual(vertex_xyz(compiled, "b"), (200, 0, 0))
        self.assertEqual(compiled.switches[compiled.n3_label_offsets["l"]].branches[0][0], 200)
        dynamic = compiled.dynamics[compiled.n3_label_offsets["d"]]
        self.assertEqual(dynamic.xyz, (20, -40, 60))

    def test_raw_five_word_plane_offset_is_scaled_not_normal(self):
        source = (
            "3D VERSION 3.0;\n"
            "a: [<0,0,0>];\n"
            "b: [<100,0,0>];\n"
            "c: [<0,100,0>];\n"
            "p: POLY <42> {a,b,c};\n"
            "root: BSPF (0, 0, 1, 0, -500), NIL, p, NIL;\n"
        )
        result = scale_n3_source(source, "3")
        self.assertIn("BSPF (0, 0, 1, 0, -1500)", result.source)
        self.assertEqual(result.raw_planes, 1)
        model, _ = compile_n3_text(
            result.source, "raw.3d", associate_planes=False)
        equation = model.planes[model.root_offset].equation
        self.assertEqual(equation[:3], (0, 0, 1))
        self.assertEqual(equation[3], -1500 * (2 ** 32))

    def test_preserves_fractional_coordinate_scale_when_fractions_disappear(self):
        fractional = (
            "3D VERSION 3.0;\n"
            "a: [<0.5,0,0>];\n"
            "b: [<0,0.5,0>];\n"
            "c: [<0,0,0.5>];\n"
            "root: LIST {POLY <44> {a,b,c}};\n"
        )
        # Source is interpreted as 6000 raw units per authored coordinate,
        # so multiplying by two must yield 6000 rather than 1 raw unit.
        result = scale_n3_source(fractional, "2")
        self.assertTrue(result.inserted_scale_hint)
        self.assertIn("% ICR2_COORD_SCALE: 6000", result.source)
        self.assertIn("[<1,0,0>]", result.source)
        model, _ = compile_n3_text(
            result.source, "fractional.3d", associate_planes=False)
        self.assertEqual(vertex_xyz(model, "a"), (6000, 0, 0))

        # A preexisting explicit coordinate-scale hint is never duplicated.
        already = fractional.replace(
            "3D VERSION 3.0;\n",
            "3D VERSION 3.0;\n% ICR2_COORD_SCALE: 6000\n")
        changed = scale_n3_source(already, "2")
        self.assertFalse(changed.inserted_scale_hint)
        self.assertEqual(changed.source.count("ICR2_COORD_SCALE"), 1)

    def test_discard_half_unit_quantization_and_keep_generated_raw_units(self):
        src = (
            "3D VERSION 3.0;\n"
            "p: [<5,7,9>];\n"
            "root: LIST {POLY <44> {p,p,p}};\n"
        )
        changed = scale_n3_source(src, "2", divide=True)
        self.assertIn("[<2,4,4>]", changed.source)
        self.assertNotIn("ICR2_COORD_SCALE", changed.source)
        self.assertEqual(changed.points, 1)

    def test_ignore_fake_geometry_in_comments_and_strings(self):
        src = (
            "3D VERSION 3.0;\n"
            "% comment [<4,5,6>] DYNAMIC 1,2,3,0,EXTERN \"not\";\n"
            "p: [<20,30,40>]; % leave fake [<1,2,3>] alone\n"
            "root: LIST {POLY <44> {p,p,p}};\n"
        )
        changed = scale_n3_source(src, "2")
        self.assertIn("p: [<40,60,80>]; % leave fake [<1,2,3>] alone",
                      changed.source)
        self.assertIn("% comment [<4,5,6>] DYNAMIC 1,2,3", changed.source)
        self.assertEqual(changed.points, 1)
        self.assertEqual(changed.dynamic_values, 0)

    def test_range_checks_and_invalid_or_noop_factor_do_not_return_edits(self):
        for factor in ("0", "-2", "nan", "inf", "oops", "1e13", "1"):
            with self.subTest(factor=factor):
                with self.assertRaises(ValueError):
                    scale_n3_source(SOURCE, factor)
        with self.assertRaisesRegex(ValueError, "signed 32-bit"):
            scale_n3_source(
                SOURCE.replace("<100,0,0>", "<2100000000,0,0>"), "2")
        with self.assertRaisesRegex(ValueError, "become zero"):
            scale_n3_source(
                "3D VERSION 3.0;\n"
                "p: [<1,1,1>];\n"
                's: SRB p, 1, "pole";\n'
                "root: LIST {s};\n", "0.1")

    def test_crlf_preserved_by_transformation_and_scale_hint(self):
        source = (
            "3D VERSION 3.0;\r\n"
            "a: [<0.5, 0, 0>];\r\n"
            "root: LIST {POLY <42> {a,a,a}};\r\n"
        )
        result = scale_n3_source(source, "2")
        self.assertIn("\r\n% ICR2_COORD_SCALE: 6000\r\n", result.source)
        self.assertNotIn("\n% ICR2_COORD_SCALE: 6000\n", result.source)
        self.assertTrue(result.source.endswith("\r\n"))


if __name__ == "__main__":
    unittest.main()
