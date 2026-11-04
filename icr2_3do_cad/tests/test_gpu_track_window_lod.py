"""Camera-relative track section LOD tests (source N3 and compiled 3DO).

These cases synthesize exact Papyrus index/DATA structures without
redistributing track binaries or depending on the GUI/OpenGL.
"""
import unittest

from gpu_viewer.mesh import make_mesh
from gpu_viewer.scene import build_scene, ordered_scene_indices
from gpu_viewer.track_lod import (
    DEFAULT_WINDOW_COUNTS, detect_track_section_lods,
    selected_track_section_window_lists, track_section_dlongs,
)
from n3_compile import compile_n3_text
from three_do import Model


def make_source_track(count=40):
    source = [
        "3D VERSION 3.0;",
        "a: [<0,0,0>];",
        "b: [<10000,0,0>];",
        "c: [<0,10000,0>];",
    ]
    for i in range(count):
        for name, color in (("hi", 40), ("med", 50), ("lo", 60)):
            source.append(
                f"p{i}_{name}: POLY <{color}> {{a,b,c}};")
    for i in range(count):
        d = i * 100000
        source.append(
            f"sec{i}: LIST {{p{i}_hi, nil, nil, nil, "
            f"p{i}_med, nil, p{i}_lo, "
            f"DATA {{{d}, {d+25000}, {d+50000}, {d+75000}}}}};")
    source += [
        "hash: DATA {0,1,2,3};",
        "index: LIST {hash, " + ", ".join(f"sec{i}" for i in range(count)) + "};",
    ]
    return "\n".join(source)


BINARY_METADATA_SOURCE = """3D VERSION 3.0;
a: [<0,0,0>];
b: [<10000,0,0>];
c: [<0,10000,0>];
h0: POLY <40> {a,b,c};
m0: POLY <50> {a,b,c};
l0: POLY <60> {a,b,c};
h1: POLY <41> {a,b,c};
m1: POLY <51> {a,b,c};
l1: POLY <61> {a,b,c};
h2: POLY <42> {a,b,c};
m2: POLY <52> {a,b,c};
l2: POLY <62> {a,b,c};
h3: POLY <43> {a,b,c};
m3: POLY <53> {a,b,c};
l3: POLY <63> {a,b,c};
alias_meta3: DATA {300000, 325000, 350000, 375000};
alias3: LIST {h3, nil, nil, nil, m3, nil, l3};
data0: DATA {0, 25000, 50000, 75000};
sec0: LIST {h0, nil, nil, nil, m0, nil, l0};
data1: DATA {100000, 125000, 150000, 175000};
sec1: LIST {h1, nil, nil, nil, m1, nil, l1};
data2: DATA {200000, 225000, 250000, 275000};
sec2: LIST {h2, nil, nil, nil, m2, nil, l2};
data3: DATA {300000, 325000, 350000, 375000};
sec3: LIST {h3, nil, nil, nil, m3, nil, l3};
alias_meta0: DATA {0, 25000, 50000, 75000};
alias0: LIST {h0, nil, nil, nil, m0, nil, l0};
expanded: LIST {alias3, sec0, sec1, sec2, sec3, alias0};
index: LIST {expanded, sec0, sec0, sec1, sec2, sec2};
"""


class CameraSectionWindowTests(unittest.TestCase):
    def setUp(self):
        self.model, _ = compile_n3_text(
            make_source_track(), "window.3d", associate_planes=False)
        self.sections = detect_track_section_lods(self.model)
        self.dlongs = track_section_dlongs(self.model, self.sections)
        self.scene = build_scene(self.model)
        self.mesh = make_mesh(self.scene.geometry)

    def _window(self, dlong, counts=DEFAULT_WINDOW_COUNTS):
        return selected_track_section_window_lists(
            self.sections, self.dlongs, model=self.model,
            camera_dlong=dlong, track_length=4000000, counts=counts)

    def test_source_metadata_is_four_hi_starts(self):
        self.assertEqual(len(self.sections), 40)
        self.assertEqual(len(self.dlongs), 40)
        self.assertEqual(
            self.dlongs[self.model.n3_label_offsets["sec2"]],
            (200000, 225000, 250000, 275000))
        self.assertEqual(self.scene.track_section_dlongs, self.dlongs)

    def test_window_has_current_plus_eight_five_three_on_each_side(self):
        overrides = self._window(2050000)
        root = overrides[self.model.root_offset]
        self.assertEqual(len(root), 33)
        selected = set(root)
        for offset in self.sections:
            i = next(k for k in range(40)
                     if self.model.n3_label_offsets[f"sec{k}"] == offset)
            distance = min((i - 20) % 40, (20 - i) % 40)
            if distance == 0 or distance <= 8:
                tier = "hi"
            elif distance <= 13:
                tier = "med"
            elif distance <= 16:
                tier = "lo"
            else:
                self.assertNotIn(offset, selected)
                continue
            self.assertIn(offset, selected)
            expected = self.model.n3_label_offsets[f"p{i}_{tier}"]
            self.assertEqual(overrides[offset], (expected,))

    def test_traversal_only_builds_selected_33_polygons_without_mesh_rebuild(self):
        for dlong in (2050000, 3999999, 0):
            with self.subTest(dlong=dlong):
                indices, visible, info = ordered_scene_indices(
                    self.scene, self.mesh, (0, 0, 0),
                    track_window=(dlong, 4000000, (8, 5, 3)),
                    bsp_mode="off")
                self.assertEqual(info["mesh_polygons"], 33)
                self.assertEqual(len(visible), 33)
                self.assertEqual(indices.size, 99)
                self.assertEqual(self.mesh.polygon_count, 120)

    def test_wraparound_boundaries_and_adjustable_counts(self):
        root = self._window(0, (2, 1, 1))[self.model.root_offset]
        expected = {0, 1, 2, 3, 4, 36, 37, 38, 39}
        actual = {i for i in range(40)
                  if self.model.n3_label_offsets[f"sec{i}"] in root}
        self.assertEqual(actual, expected)
        self.assertEqual(len(self._window(99999, (0,0,0))[
            self.model.root_offset]), 1)
        self.assertIn(self.model.n3_label_offsets["sec1"],
                      self._window(100000, (0,0,0))[
                          self.model.root_offset])
        self.assertEqual(len(self._window(0, (100, 0, 0))[
            self.model.root_offset]), 40)

    def test_zero_counts_and_invalid_inputs(self):
        self.assertEqual(len(self._window(2000000, (0,0,0))[
            self.model.root_offset]), 1)
        with self.assertRaises(ValueError):
            self._window(0, (-1, 2, 3))
        with self.assertRaises(ValueError):
            self._window(0, (3, 4))
        with self.assertRaises(ValueError):
            selected_track_section_window_lists(
                self.sections, {}, model=self.model,
                camera_dlong=0, track_length=4000000)
        with self.assertRaises(ValueError):
            selected_track_section_window_lists(
                self.sections, self.dlongs, model=self.model,
                camera_dlong=0, track_length=0)


class OriginalBinaryDataTests(unittest.TestCase):
    def setUp(self):
        compiler, _ = compile_n3_text(
            BINARY_METADATA_SOURCE, "binary_data.3d",
            associate_planes=False)
        self.model = Model(
            "binary_data.3do", raw_data=compiler.raw,
            associate_planes=False)
        self.sections = detect_track_section_lods(self.model)

    def test_binary_data_is_unlinked_but_20_bytes_before_lists(self):
        self.assertEqual(len(self.sections), 4)
        result = track_section_dlongs(self.model, self.sections)
        self.assertEqual(len(result), 4)
        self.assertEqual(sorted(values[0] for values in result.values()),
                         [0, 100000, 200000, 300000])
        # The original 3DO parser intentionally never visits these
        # unlinked DATA records, so none appears in model.records.
        self.assertFalse(any(
            self.model.records.get(off - 20) == 17
            for off in self.sections))
        # Alias3 comes first in the expanded index, yet it retains DLONG
        # metadata and must be counted only once with the canonical section.
        self.assertEqual(len(set(result.values())), 4)

    def test_compiled_window_selects_disjoint_tiers(self):
        scene = build_scene(self.model)
        self.assertEqual(len(scene.track_section_dlongs), 4)
        mesh = make_mesh(scene.geometry)
        offsets = selected_track_section_window_lists(
            self.sections, scene.track_section_dlongs, model=self.model,
            camera_dlong=250000, track_length=400000, counts=(1, 0, 0))
        self.assertEqual(len(offsets[self.model.root_offset]), 3)
        indices, visible, info = ordered_scene_indices(
            scene, mesh, (0,0,0),
            track_window=(250000, 400000, (1, 0, 0)), bsp_mode="off")
        self.assertEqual(info["mesh_polygons"], 3)
        self.assertEqual(len(visible), 3)
        self.assertEqual(indices.size, 9)

    def test_missing_binary_data_safely_disables_window_mode(self):
        compiler, _ = compile_n3_text(
            BINARY_METADATA_SOURCE.replace(
                "data1: DATA {100000, 125000, 150000, 175000};",
                "data1: NIL;"),
            "binary_missing_data.3d", associate_planes=False)
        binary = Model("missing.3do", raw_data=compiler.raw,
                       associate_planes=False)
        sections = detect_track_section_lods(binary)
        self.assertEqual(len(sections), 4)
        self.assertEqual(track_section_dlongs(binary, sections), {})


if __name__ == "__main__":
    unittest.main()
