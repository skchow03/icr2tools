"""Multiple MIP MATERIAL scopes must match the innermost N3 wrapper.

This is the original 3-MIP arrangement reported for the GPU viewer:
root page03 -> LIST of four unwrapped sides, four nested page03b
sides, and a skyindex top. Exercise the compiled binary parser, scene
flattening and the GPU atlas association (no OpenGL context required).
"""
from __future__ import annotations

from collections import Counter
from pathlib import Path
import shutil
import tempfile
import unittest

from n3_compile import compile_n3_text
from scene import build_scene
from textures import build_atlas

ROOT = Path(__file__).resolve().parents[1]

SAMPLE = """3D VERSION 3.0;
_4: [<20000, -50000, 0>];
_24: [<50000, -20000, 0>];
_44: [<50000, 20000, 0>];
_64: [<20000, 50000, 0>];
_84: [<-20000, 50000, 0>];
_104: [<-50000, 20000, 0>];
_124: [<-50000, -20000, 0>];
_144: [<-20000, -50000, 0>];
_356: [<50000, -20000, 10000>, T=<74, 6>];
_376: [<50000, 20000, 10000>, T=<4, 76>];
_396: [<20000, 50000, 10000>, T=<4, 182>];
_416: [<-20000, 50000, 10000>, T=<74, 252>];
_468: [<-50000, 20000, 10000>, T=<180, 252>];
_488: [<-50000, -20000, 10000>, T=<250, 182>];
_508: [<-20000, -50000, 10000>, T=<250, 76>];
_528: [<20000, -50000, 10000>, T=<180, 6>];
_548: [<20000, -50000, 10000>, T=<0, 0>];
_568: [<-20000, -50000, 10000>, T=<255, 0>];
_588: [<-20000, -50000, 0>, T=<255, 63>];
_608: [<20000, -50000, 0>, T=<0, 63>];
_628: [<-20000, -50000, 10000>, T=<0, 64>];
_648: [<-50000, -20000, 10000>, T=<255, 64>];
_668: [<-50000, -20000, 0>, T=<255, 127>];
_688: [<-20000, -50000, 0>, T=<0, 127>];
_708: [<-50000, -20000, 10000>, T=<0, 192>];
_728: [<-50000, 20000, 10000>, T=<255, 192>];
_748: [<-50000, 20000, 0>, T=<255, 255>];
_768: [<-50000, -20000, 0>, T=<0, 255>];
_788: [<-50000, 20000, 10000>, T=<0, 192>];
_808: [<-20000, 50000, 10000>, T=<255, 192>];
_828: [<-20000, 50000, 0>, T=<255, 255>];
_848: [<-50000, 20000, 0>, T=<0, 255>];
_868: [<-20000, 50000, 10000>, T=<0, 0>];
_888: [<20000, 50000, 10000>, T=<255, 0>];
_908: [<20000, 50000, 0>, T=<255, 63>];
_928: [<-20000, 50000, 0>, T=<0, 63>];
_948: [<20000, 50000, 10000>, T=<0, 64>];
_968: [<50000, 20000, 10000>, T=<255, 64>];
_988: [<50000, 20000, 0>, T=<255, 127>];
_1008: [<20000, 50000, 0>, T=<0, 127>];
_1028: [<50000, 20000, 10000>, T=<0, 192>];
_1048: [<50000, -20000, 10000>, T=<255, 192>];
_1068: [<50000, -20000, 0>, T=<255, 255>];
_1088: [<50000, 20000, 0>, T=<0, 255>];
_1108: [<50000, -20000, 10000>, T=<0, 192>];
_1128: [<20000, -50000, 10000>, T=<255, 192>];
_1148: [<20000, -50000, 0>, T=<255, 255>];
_1168: [<50000, -20000, 0>, T=<0, 255>];
_1252: POLY <208> {_4, _24, _44, _64, _84, _104, _124, _144};
_1296: POLY [T] <227> {_356, _376, _396, _416, _468, _488, _508, _528};
_1344: MATERIAL MIP="skyindex", GROUP=3, _1296;
_1360: POLY [T] <219> {_548, _568, _588, _608};
_1392: POLY [T] <219> {_628, _648, _668, _688};
_1424: POLY [T] <219> {_708, _728, _748, _768};
_1456: POLY [T] <219> {_788, _808, _828, _848};
_1488: POLY [T] <219> {_868, _888, _908, _928};
_1520: MATERIAL MIP="page03b", GROUP=3, _1488;
_1536: POLY [T] <219> {_948, _968, _988, _1008};
_1568: MATERIAL MIP="page03b", GROUP=3, _1536;
_1584: POLY [T] <219> {_1028, _1048, _1068, _1088};
_1616: MATERIAL MIP="page03b", GROUP=3, _1584;
_1632: POLY [T] <219> {_1108, _1128, _1148, _1168};
_1664: MATERIAL MIP="page03b", GROUP=3, _1632;
_1680: LIST {_1360, _1392, _1424, _1456, _1520, _1568, _1616, _1664};
_1720: LIST {_1252, _1344, _1680};
root: MATERIAL MIP="page03", GROUP=3, _1720;
"""


class NestedMaterialMipTests(unittest.TestCase):
    def test_user_three_mip_model_assigns_nearest_material(self):
        with tempfile.TemporaryDirectory() as temp:
            folder = Path(temp)
            model, _ = compile_n3_text(
                SAMPLE, folder / 'three_mips.3d', associate_planes=False)
            self.assertEqual(len(model.polygons), 10)
            self.assertEqual(Counter(model.polygon_materials.values()),
                             Counter({'skyindex': 1, 'page03': 4, 'page03b': 4}))
            self.assertEqual(
                len([p for p in model.polygons.values() if p.kind == 2]), 9)
            # Skyindex is the only polygon with color 227.
            textured_top = next(off for off, p in model.polygons.items()
                                if p.kind == 2 and p.color == 227)
            self.assertEqual(model.polygon_materials[textured_top], 'skyindex')
            scene = build_scene(model)
            self.assertEqual(Counter(scene.geometry.polygon_materials.values()),
                             Counter({'skyindex': 1, 'page03': 4, 'page03b': 4}))

            # Use known-good MIP bytes under all three source names, testing
            # resolution + distinct rectangles regardless of palette pixels.
            for name in ('skyindex', 'page03', 'page03b'):
                shutil.copyfile(ROOT / 'fixtures' / 'ind96.mip',
                                folder / (name + '.mip'))
            atlas = build_atlas(scene.geometry, folder / 'three_mips.3d')
            self.assertEqual(set(atlas.loaded_names),
                             {'skyindex.mip', 'page03.mip', 'page03b.mip'})
            self.assertEqual(atlas.missing_names, ())
            self.assertEqual(atlas.errors, ())
            self.assertEqual(len(atlas.polygon_rects), 9)
            regions = {}
            for (instance, old), scene_poly in scene.polygon_lookup.items():
                if old not in model.polygon_materials:
                    continue
                material = model.polygon_materials[old]
                regions.setdefault(material, set()).add(
                    atlas.polygon_rects[scene_poly])
            self.assertEqual({name: len(rects) for name, rects in regions.items()},
                             {'skyindex': 1, 'page03': 1, 'page03b': 1})
            self.assertEqual(len(set.union(*regions.values())), 3)

    def test_group_only_material_does_not_hide_parent_named_mip(self):
        source = """3D VERSION 3.0;
v1: [<0, 0, 0>, T=<0, 0>];
v2: [<100, 0, 0>, T=<255, 0>];
v3: [<0, 100, 0>, T=<0, 255>];
p: POLY [T] <7> {v1, v2, v3};
group: MATERIAL GROUP=30, p;
root: MATERIAL MIP="outside", GROUP=3, group;
"""
        with tempfile.TemporaryDirectory() as temp:
            model, _ = compile_n3_text(
                source, Path(temp) / 'group.3d', associate_planes=False)
            self.assertEqual(list(model.polygon_materials.values()), ['outside'])


if __name__ == '__main__':
    unittest.main()
