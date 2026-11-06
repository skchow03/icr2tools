"""CPU-only regressions for Papyrus track section HI/MED/LO selection.

Uses synthetic track tables rather than distributing proprietary track data.
"""
import unittest

from gpu_viewer.mesh import make_mesh
from gpu_viewer.scene import build_scene, ordered_scene_indices
from gpu_viewer.track_lod import (
    detect_track_section_lods, selected_track_section_lists,
    selected_track_section_window_lists, track_section_dlongs,
)
from n3_compile import compile_n3_text
from three_do import Model


TRACK_SOURCE = """3D VERSION 3.0
a: [<0, 0, 0>];
b: [<10000, 0, 0>];
c: [<0, 10000, 0>];
hi0: POLY <40> {a,b,c};
hi1: POLY <41> {a,b,c};
hi2: POLY <42> {a,b,c};
hi3: POLY <43> {a,b,c};
med0: POLY <50> {a,b,c};
med1: POLY <51> {a,b,c};
lo0: POLY <60> {a,b,c};
sec0_l0: LIST {
    hi0, hi1, hi2, hi3,
    med0, med1, lo0,
    DATA {0, 0, 0, 0}
};
hash: DATA {0, 1, 2, 3};
index: LIST {hash, sec0_l0};
"""


class TrackSectionLODTests(unittest.TestCase):
    def setUp(self):
        self.model, _ = compile_n3_text(
            TRACK_SOURCE, "putnam_synthetic.3d", associate_planes=False)
        self.sections = detect_track_section_lods(self.model)

    def test_indexed_table_detected_for_text_and_binary(self):
        self.assertEqual(len(self.sections), 1)
        section, slots = next(iter(self.sections.items()))
        self.assertEqual(self.model.records[section], 11)
        self.assertEqual(len(slots), 7)
        binary = Model("putnam_synthetic.3do", raw_data=self.model.raw,
                       associate_planes=False)
        self.assertEqual(detect_track_section_lods(binary), self.sections)

    def test_one_exclusive_tier_per_section(self):
        self.assertEqual(len(self.model.polygons), 7)
        all_polys, _, _ = self.model.switched_polygons(
            None, (0, 0, 10000), "off")
        self.assertEqual(len(all_polys), 7)  # historical unfiltered view
        for mode, count in (("hi", 4), ("med", 2), ("lo", 1)):
            with self.subTest(mode=mode):
                overrides = selected_track_section_lists(self.sections, mode)
                polygons, _, _ = self.model.switched_polygons(
                    None, (0, 0, 10000), "off", list_overrides=overrides)
                self.assertEqual(len(polygons), count)
                expected_names = {
                    "hi": ("hi0", "hi1", "hi2", "hi3"),
                    "med": ("med0", "med1"),
                    "lo": ("lo0", ),
                }[mode]
                self.assertEqual(
                    set(polygons),
                    {self.model.n3_label_offsets[name] for name in expected_names})
        # Selection must not change compiled bytes or the loaded mesh.
        self.assertEqual(len(self.model.polygons), 7)

    def test_scene_draw_indices_switch_without_remeshing(self):
        scene = build_scene(self.model)
        self.assertEqual(scene.track_section_lods, self.sections)
        mesh = make_mesh(scene.geometry)
        for mode, count in (("hi", 4), ("med", 2), ("lo", 1)):
            with self.subTest(mode=mode):
                indices, visible, stats = ordered_scene_indices(
                    scene, mesh, (0, 0, 10000),
                    track_detail=mode)
                self.assertEqual(stats["mesh_polygons"], count)
                self.assertEqual(len(visible), count)
                self.assertEqual(len(indices), count * 3)
                # The All Polygons diagnostic uses the same track mask.
                all_indices, all_visible, _ = ordered_scene_indices(
                    scene, mesh, (0, 0, 10000), None,
                    track_detail=mode, bsp_mode="off")
                self.assertEqual(len(all_visible), count)
                self.assertEqual(len(all_indices), count * 3)

    def test_nil_slots_do_not_fall_back_to_another_tier(self):
        sparse = TRACK_SOURCE.replace(
            "hi0, hi1, hi2, hi3,\n    med0, med1, lo0",
            "hi0, nil, nil, nil,\n    med0, nil, lo0")
        model, _ = compile_n3_text(
            sparse, "sparse.3d", associate_planes=False)
        sections = detect_track_section_lods(model)
        self.assertEqual(len(sections), 1)
        for mode in ("hi", "med", "lo"):
            polygons, _, _ = model.switched_polygons(
                None, (0, 0, 0), "off",
                list_overrides=selected_track_section_lists(sections, mode))
            self.assertEqual(len(polygons), 1)

    def test_nontrack_and_incomplete_tables_not_classified(self):
        plain = TRACK_SOURCE.replace(
            "index: LIST {hash, sec0_l0};",
            "index: LIST {hi0, sec0_l0};")
        model, _ = compile_n3_text(
            plain, "nontrack.3d", associate_planes=False)
        self.assertFalse(detect_track_section_lods(model))
        invalid = TRACK_SOURCE.replace(
            "DATA {0, 0, 0, 0}\n};",
            "hi0\n};")
        model, _ = compile_n3_text(
            invalid, "invalid_table.3d", associate_planes=False)
        self.assertFalse(detect_track_section_lods(model))

    def test_invalid_tier_is_rejected(self):
        with self.assertRaises(ValueError):
            selected_track_section_lists(self.sections, "all")


# The binary shape below reproduces the *structural* track compiler output
# observed in PUTNAM.3DO without bundling user-provided track geometry.
BINARY_TRACK_SOURCE = """3D VERSION 3.0
a: [<0,0,0>];
b: [<10000,0,0>];
c: [<0,10000,0>];
h0: POLY <40> {a,b,c};
h1: POLY <41> {a,b,c};
h2: POLY <42> {a,b,c};
h3: POLY <43> {a,b,c};
m0: POLY <50> {a,b,c};
m1: POLY <51> {a,b,c};
l0: POLY <60> {a,b,c};
h4: POLY <45> {a,b,c};
m2: POLY <52> {a,b,c};
l1: POLY <61> {a,b,c};
wrap0: LIST {h4, h4, h4, h4, m2, m2, l1};
wrap1: LIST {h4, h4, h4, h4, m2, m2, l1};
sec0_l0: LIST {h0, nil, nil, nil, m0, nil, l0};
sec1_l0: LIST {h1, h2, h3, h4, m1, m2, l1};
expanded: LIST {wrap0, sec0_l0, sec1_l0, wrap1};
index: LIST {expanded, sec0_l0, sec0_l0, sec1_l0, sec1_l0};
"""


class BinaryTrackSectionLODTests(unittest.TestCase):
    def setUp(self):
        self.model, _ = compile_n3_text(
            BINARY_TRACK_SOURCE, "binary_track.3do", associate_planes=False)
        self.sections = detect_track_section_lods(self.model)

    def test_compiled_binary_index_is_identified(self):
        # wrap0 and wrap1 share one seven-slot layout, which the new
        # detector keeps once alongside the two hash-indexed sections.
        self.assertEqual(len(self.sections), 3)
        self.assertTrue(all(len(slots) == 7 for slots in self.sections.values()))
        root = self.model.children[self.model.root_offset]
        self.assertEqual(len(root), 5)
        self.assertEqual(self.model.records[root[0]], 11)
        self.assertEqual(len(self.model.children[root[0]]), 4)
        # The binary record tree survives opening from bytes, not N3 labels.
        model = Model("binary_track.3do", raw_data=self.model.raw,
                      associate_planes=False)
        self.assertEqual(detect_track_section_lods(model), self.sections)

    def test_root_prelude_is_removed_and_only_selected_tier_is_drawn(self):
        # The expanded prelude must not draw all tiers before selection.
        # wrap0 contributes a distinct seven-slot signature, but its three
        # polygon references already exist under the other two sections.
        unfiltered, _, _ = self.model.switched_polygons(
            0, (0,0,10000), "off")
        self.assertGreaterEqual(len(unfiltered), 10)
        scene = build_scene(self.model)
        mesh = make_mesh(scene.geometry)
        # sec0 has 1 HI + 1 MED + 1 LO; sec1 has 4 HI + 2 MED + 1 LO.
        expected = {"hi": 5, "med": 3, "lo": 2}
        for mode, count in expected.items():
            with self.subTest(mode=mode):
                overlays = selected_track_section_lists(
                    self.sections, mode, model=self.model)
                self.assertEqual(overlays[self.model.root_offset],
                                 tuple(self.sections))
                polys, _, _ = self.model.switched_polygons(
                    0, (0,0,10000), "off", list_overrides=overlays)
                self.assertEqual(len(polys), count)
                indices, visible, stats = ordered_scene_indices(
                    scene, mesh, (0,0,10000),
                    track_detail=mode, bsp_mode="off")
                self.assertEqual(len(visible), count)
                self.assertEqual(stats["mesh_polygons"], count)
                self.assertEqual(indices.size, count * 3)

    def test_nonzero_flavor_zero_pointer_is_nil(self):
        # Papyrus' original compiler emits a valid, nonzero pointer to a
        # 4-byte zero-flavor NIL record, unlike the standalone N3 compiler.
        import struct
        raw = bytearray(self.model.raw)
        # Use an existing NIL slot rather than breaking an alias signature:
        # the expanded list contains a duplicate of wrap0's seven pointers.
        section = next(off for off, slots in self.sections.items()
                       if self.model.records.get(slots[1]) in (0, None))
        new_nil = len(self.model.body)
        raw.extend(b"\x00" * 4)
        struct.pack_into("<i", raw, 0, len(self.model.body) + 4)
        struct.pack_into("<i", raw,
                         self.model.body_start + section + 8 + 4 * 1, new_nil)
        binary = Model("binary_nil.3do", raw_data=raw,
                       associate_planes=False)
        sections = detect_track_section_lods(binary)
        self.assertEqual(len(sections), 3)
        self.assertEqual(binary.records[sections[section][1]], 0)
        override = selected_track_section_lists(
            sections, "hi", model=binary)
        self.assertNotIn(new_nil, override[section])

    def test_reject_unrelated_seven_pointer_lists(self):
        # A generic model containing seven children is not a track.
        malformed = BINARY_TRACK_SOURCE.replace(
            "index: LIST {expanded, sec0_l0, sec0_l0, sec1_l0, sec1_l0}",
            "index: LIST {expanded, sec0_l0, sec1_l0}")
        model, _ = compile_n3_text(malformed, "generic.3do",
                                   associate_planes=False)
        self.assertFalse(detect_track_section_lods(model))



# These synthetic compiled tracks reproduce the structural difference seen
# in St. Petersburg 2024 and Washington D.C.: the expanded index contains
# extra 7-slot LOD sections that never occur in the root hash table.
# As with real tracks, aliases have separate LIST offsets but identical slots.
IRREGULAR_BINARY_SOURCE = """3D VERSION 3.0
a: [<0,0,0>];
b: [<10000,0,0>];
c: [<0,10000,0>];
h0: POLY <40> {a,b,c};
m0: POLY <41> {a,b,c};
l0: POLY <42> {a,b,c};
h1: POLY <43> {a,b,c};
m1: POLY <44> {a,b,c};
l1: POLY <45> {a,b,c};
ha: POLY <46> {a,b,c};
ma: POLY <47> {a,b,c};
la: POLY <48> {a,b,c};
hb: POLY <49> {a,b,c};
mb: POLY <50> {a,b,c};
lb: POLY <51> {a,b,c};
clone0: LIST {h0, nil, nil, nil, m0, nil, l0};
sec0: LIST {h0, nil, nil, nil, m0, nil, l0};
extra_a: LIST {ha, nil, nil, nil, ma, nil, la};
sec1: LIST {h1, nil, nil, nil, m1, nil, l1};
extra_b: LIST {hb, nil, nil, nil, mb, nil, lb};
clone1: LIST {h1, nil, nil, nil, m1, nil, l1};
expanded: LIST {clone0, sec0, extra_a, sec1, extra_b, clone1};
index: LIST {expanded, sec0, sec0, sec1, sec1, sec1};
"""


class IrregularBinaryTrackTests(unittest.TestCase):
    def setUp(self):
        compiled, _ = compile_n3_text(
            IRREGULAR_BINARY_SOURCE, "irregular.3d", associate_planes=False)
        # Actual track files are .3do; round-trip the generated bytes through
        # the same binary Model reader used by the GPU viewer.
        self.binary = Model("irregular.3do", raw_data=compiled.raw,
                            associate_planes=False)
        self.sections = detect_track_section_lods(self.binary)

    def test_indexed_and_nonindexed_sections_are_recognized_once(self):
        self.assertEqual(len(self.sections), 4)
        labels = self.binary.n3_label_offsets if hasattr(
            self.binary, "n3_label_offsets") else {}
        self.assertEqual(len(labels), 0)
        root_entries = self.binary.children[self.binary.root_offset]
        self.assertEqual(len(root_entries), 6)
        expanded = self.binary.children[root_entries[0]]
        self.assertEqual(len(expanded), 6)
        # The two aliases have exactly the same LOD pointers as their
        # respective indexed sections; one representative is enough.
        self.assertEqual(len(self.sections), len(set(self.sections.values())))

    def test_extra_unique_geometry_is_retained_in_all_detail_modes(self):
        scene = build_scene(self.binary)
        self.assertEqual(scene.track_section_lods, self.sections)
        mesh = make_mesh(scene.geometry)
        self.assertEqual(mesh.polygon_count, 12)
        for mode in ("hi", "med", "lo"):
            with self.subTest(mode=mode):
                overrides = selected_track_section_lists(
                    self.sections, mode, model=self.binary)
                self.assertEqual(overrides[self.binary.root_offset],
                                 tuple(self.sections))
                polygons, _, _ = self.binary.switched_polygons(
                    None, (0, 0, 10000), "off", list_overrides=overrides)
                self.assertEqual(len(polygons), 4)
                indices, visible, info = ordered_scene_indices(
                    scene, mesh, (0, 0, 10000),
                    track_detail=mode, bsp_mode="off")
                self.assertEqual(len(visible), 4)
                self.assertEqual(info["mesh_polygons"], 4)
                self.assertEqual(indices.size, 12)

    def test_misordered_expanded_sections_are_not_misclassified(self):
        bad = IRREGULAR_BINARY_SOURCE.replace(
            "expanded: LIST {clone0, sec0, extra_a, sec1, extra_b, clone1}",
            "expanded: LIST {clone0, sec1, extra_a, sec0, extra_b, clone1}")
        model, _ = compile_n3_text(
            bad, "misordered.3d", associate_planes=False)
        self.assertFalse(detect_track_section_lods(model))

    def test_invalid_extra_section_is_not_silently_skipped(self):
        bad = IRREGULAR_BINARY_SOURCE.replace(
            "extra_b: LIST {hb, nil, nil, nil, mb, nil, lb}",
            "extra_b: LIST {hb, nil, nil, mb, nil, lb}")
        model, _ = compile_n3_text(
            bad, "bad_extra.3d", associate_planes=False)
        self.assertFalse(detect_track_section_lods(model))



class StockSuperobjTrackTests(unittest.TestCase):
    """Stock Papyrus tracks wrap the indexed LIST and scenery in SUPEROBJ."""

    def test_wrapped_binary_index_detected_and_preserves_sceneries(self):
        # The synthetic binary-style index has repeated hash pointers and
        # seven-slot section tables just like original compiled Vancouver.
        source = (BINARY_TRACK_SOURCE
                  + 'suite: DYNAMIC 0, 0, 0, 873, 900, 0, 1, EXTERN "pitsuite";\n'
                  + 'stock_root: SUPEROBJ index, {suite};\n')
        compiled, _ = compile_n3_text(
            source, 'stock_vancouver_like.3d', associate_planes=False)
        model = Model('stock_vancouver_like.3do',
                      raw_data=compiled.raw, associate_planes=False)
        root = model.root_offset
        self.assertEqual(model.records[root], 16)
        index = model.children[root][0]
        self.assertEqual(model.records[index], 11)
        self.assertEqual(model.records[model.children[root][1]], 15)
        sections = detect_track_section_lods(model)
        self.assertEqual(len(sections), 3)
        scene = build_scene(model)
        self.assertEqual(scene.track_section_lods, sections)
        for tier, count in (('hi', 5), ('med', 3), ('lo', 2)):
            with self.subTest(tier=tier):
                overrides = selected_track_section_lists(
                    sections, tier, model=model)
                self.assertIn(index, overrides)
                self.assertNotIn(root, overrides)
                events = []
                polys, _, _ = model.switched_polygons(
                    0, (0, 0, 10000), 'off',
                    list_overrides=overrides, events=events)
                self.assertEqual(len(polys), count)
                self.assertEqual(
                    len([event for event in events if event[0] == 'dynamic']),
                    1)  # Root SUPEROBJ scenery still traversed
                mesh = make_mesh(scene.geometry)
                indices, visible, stats = ordered_scene_indices(
                    scene, mesh, (0, 0, 10000),
                    track_detail=tier, bsp_mode='off')
                self.assertEqual(stats['mesh_polygons'], count)
                self.assertEqual(len(visible), count)
                self.assertEqual(len(indices), 3 * count)

    def test_wrapped_source_index_metadata_and_camera_window(self):
        source = (TRACK_SOURCE
                  + 'suite: DYNAMIC 0, 0, 0, 873, 900, 0, 1, EXTERN "pitsuite";\n'
                  + 'stock_root: SUPEROBJ index, {suite};\n')
        model, _ = compile_n3_text(source, 'stock_wrapped_source.3d',
                                   associate_planes=False)
        index = model.children[model.root_offset][0]
        sections = detect_track_section_lods(model)
        self.assertEqual(len(sections), 1)
        dlongs = track_section_dlongs(model, sections)
        self.assertEqual(set(dlongs), set(sections))
        self.assertEqual(next(iter(dlongs.values())), (0, 0, 0, 0))
        overrides = selected_track_section_window_lists(
            sections, dlongs, model=model, camera_dlong=20,
            track_length=100, counts=(0, 0, 0))
        self.assertEqual(overrides[index], tuple(sections))
        self.assertNotIn(model.root_offset, overrides)
        events = []
        model.switched_polygons(
            0, (0, 0, 10000), 'off',
            list_overrides=overrides, events=events)
        self.assertEqual(
            len([event for event in events if event[0] == 'dynamic']), 1)

    def test_unrelated_superobj_is_not_misclassified(self):
        source = (BINARY_TRACK_SOURCE
                  + 'unrelated: LIST {h0};\n'
                  + 'suite: DYNAMIC 0, 0, 0, 0, 0, 0, 1, EXTERN "pitsuite";\n'
                  + 'stock_root: SUPEROBJ unrelated, {suite};\n')
        model, _ = compile_n3_text(source, 'generic_superobj.3d',
                                   associate_planes=False)
        self.assertFalse(detect_track_section_lods(model))



if __name__ == "__main__":
    unittest.main()
