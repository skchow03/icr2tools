"""Stock-car group-16 POLY[T] contract and backward compatibility."""
import unittest

from icr2_3do_ai.stage2 import validate_source
from three_do import FormatError


BODY = """3D VERSION 3.0;
% ICR2_COORD_SCALE: 1
% HINT
a: [<0, 0, 0>, T=<0, 0>];
b: [<3000, 0, 0>, T=<24, 0>];
c: [<0, 3000, 0>, T=<0, 24>];
root: POLY [T] <159> {a, b, c};
"""


class CarshapeGroupTests(unittest.TestCase):
    def group_for(self, hint):
        source=BODY.replace("% HINT",hint)
        model,summary=validate_source(source)
        self.assertFalse(summary["parser_warnings"])
        self.assertEqual(len(model.polygons),1)
        self.assertEqual(next(iter(model.polygons.values())).kind,2)
        self.assertEqual(model.mip_names,[])
        return next(iter(model.polygons.values())).group

    def test_legacy_poly_t_group_defaults_to_zero(self):
        self.assertEqual(self.group_for("% ordinary texture"),0)

    def test_stock_car_opt_in_group_sixteen(self):
        self.assertEqual(self.group_for("% ICR2_CAR_TEXTURE_GROUP: 16"),16)

    def test_group_hint_out_of_range_rejected(self):
        with self.assertRaisesRegex(FormatError,"outside 0..255"):
            self.group_for("% ICR2_CAR_TEXTURE_GROUP: 256")

    def test_duplicate_group_hint_rejected(self):
        with self.assertRaisesRegex(FormatError,"Only one"):
            self.group_for("% ICR2_CAR_TEXTURE_GROUP: 16\n% ICR2_CAR_TEXTURE_GROUP: 16")


if __name__=="__main__":
    unittest.main()
