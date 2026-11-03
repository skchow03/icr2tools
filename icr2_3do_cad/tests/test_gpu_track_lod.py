"""CPU-only regressions for Papyrus track section HI/MED/LO selection.

Uses synthetic track tables rather than distributing proprietary track data.
"""
import unittest

from gpu_viewer.mesh import make_mesh
from gpu_viewer.scene import build_scene, ordered_scene_indices
from gpu_viewer.track_lod import (
    detect_track_section_lods, selected_track_section_lists,
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


if __name__ == "__main__":
    unittest.main()
