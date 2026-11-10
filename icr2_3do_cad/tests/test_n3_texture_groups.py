"""Stock ICR2 car texture groups and driver-wrapper N3 round trips."""
import struct
import tempfile
import unittest
from pathlib import Path

from car_appearance import read_car_appearance
from n3_compile import compile_n3_text
from text_3d import export_compilable_text, export_text, import_text
from three_do import FormatError


CAR = """3D VERSION 3.0;
a: [<0,0,0>, T=<0,0>];
b: [<100,0,0>, T=<32,0>];
c: [<0,100,0>, T=<0,32>];
bonnet: POLY [T] <42> {a,b,c} GROUP=16;
root: MATERIAL MIP="ind95", GROUP=113, bonnet;
"""

WRAPPER = """3D VERSION 3.0;
paint: RECOLOR (16:49, 17:51), EXTERN "indycar";
root: MATERIAL MIP="ind95", GROUP=113, paint;
"""


class StockCarTextureGroupTests(unittest.TestCase):
    def test_texture_group_and_material_group_are_independent(self):
        model, _ = compile_n3_text(CAR, "indycar.3d", associate_planes=False)
        polygon = next(iter(model.polygons.values()))
        self.assertEqual(polygon.group, 16)
        self.assertEqual(polygon.color, 42)
        self.assertEqual(struct.unpack_from("<i", model.body, model.root_offset + 8)[0], 113)
        source = export_compilable_text(model)
        self.assertIn("GROUP=16", source)
        self.assertIn('MIP="ind95", GROUP=113', source)
        again, _ = compile_n3_text(source, "car_again.3d", associate_planes=False)
        self.assertEqual(next(iter(again.polygons.values())).group, 16)
        self.assertEqual(struct.unpack_from("<i", again.body, again.root_offset + 8)[0], 113)

    def test_editing_group_in_annotated_source_only_changes_group_field(self):
        model, _ = compile_n3_text(CAR, "indycar.3d", associate_planes=False)
        text = export_text(model)
        self.assertIn("GROUP=16", text)
        edited, _ = import_text(model, text.replace("GROUP=16", "GROUP=7", 1))
        offset = next(iter(model.polygons))
        self.assertEqual(edited.polygons[offset].group, 7)
        self.assertEqual(edited.polygons[offset].color, 42)
        self.assertEqual(struct.unpack_from("<i", edited.body, edited.root_offset + 8)[0], 113)
        self.assertEqual(model.polygons[offset].group, 16)
        # Before this change annotated sources omitted groups; importing an
        # old source must not clear a nonzero group during a color-only edit.
        old_source = text.replace(" GROUP=16", "", 1)
        retained, _ = import_text(model, old_source)
        self.assertEqual(retained.raw, model.raw)

    def test_legacy_textured_polygon_defaults_to_zero(self):
        source = CAR.replace(" GROUP=16", "")
        model, _ = compile_n3_text(source, "legacy.3d", associate_planes=False)
        self.assertEqual(next(iter(model.polygons.values())).group, 0)

    def test_invalid_texture_group_fails(self):
        for source in (
            CAR.replace("GROUP=16", "GROUP=2147483648"),
            CAR.replace("POLY [T] <42>", "POLY <42>"),
        ):
            with self.subTest(source=source):
                with self.assertRaises(FormatError):
                    compile_n3_text(source, "invalid.3d", associate_planes=False)

    def test_stock_driver_wrapper_recolor_tail_round_trip(self):
        model, _ = compile_n3_text(WRAPPER, "ind95.3d", associate_planes=False)
        self.assertEqual(model.external_names, ["indycar"])
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "ind95.3do"
            path.write_bytes(model.raw)
            appearance = read_car_appearance(path)
            self.assertEqual(appearance.geometry_name, "indycar")
            self.assertEqual(appearance.texture_name, "ind95")
            self.assertEqual(appearance.mapping, {16: 49, 17: 51})
            self.assertEqual(appearance.source_color, 113)

            exported = export_compilable_text(model)
            self.assertIn('EXTERN "indycar"', exported)
            rebuilt, _ = compile_n3_text(exported, "ind95_rebuild.3d", associate_planes=False)
            path.write_bytes(rebuilt.raw)
            self.assertEqual(read_car_appearance(path).geometry_name, "indycar")
            self.assertEqual(read_car_appearance(path).mapping, {16: 49, 17: 51})

    def test_material_group_is_not_inferred_from_polygon(self):
        model, _ = compile_n3_text(CAR.replace("GROUP=113", "GROUP=0"),
                                   "indycar.3d", associate_planes=False)
        source = export_compilable_text(model)
        self.assertIn('MATERIAL MIP="ind95", GROUP=0,', source)
        self.assertIn('GROUP=16;', source)


if __name__ == "__main__":
    unittest.main()
