"""Active N3 RES branches and their editable source dependencies."""
import unittest
from types import SimpleNamespace

from n3_compile import compile_n3_text
from gpu_viewer.active_source import (
    active_source_labels, entry_is_active, label_offsets,
    plane_vertex_dependencies,
)
from gpu_viewer.source_filters import index_source_entries


SOURCE = """3D VERSION 3.0;
a: [<0,0,0>];
b: [<100,0,0>];
c: [<0,100,0>];
d: [<0,0,100>];
e: [<0,100,100>];
near_poly: POLY <44> {a,b,c};
far_poly: POLY <55> {a,b,e};
near_face: FACE (a,b,d), near_poly;
far_list: LIST {far_poly};
far_material: MATERIAL GROUP=3, far_list;
lod: SWITCH DISTANCE (a) > {(1000 ? far_material), (0 ? near_face)};
root: LIST {lod};
"""


class ActiveSourceTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.model, _ = compile_n3_text(
            SOURCE, "active_filter.3d", associate_planes=False)
        cls.dependencies = plane_vertex_dependencies(SOURCE, cls.model)

    def labels(self, distance, camera=(0, 0, 0)):
        return active_source_labels(
            self.model, distance, camera, self.dependencies)

    def test_near_includes_only_active_branch_and_plane_vertices(self):
        names = self.labels(0)
        self.assertTrue({
            "root", "lod", "near_face", "near_poly",
            "a", "b", "c", "d",
        } <= names)
        self.assertFalse({"far_poly", "far_list", "far_material", "e"} & names)
        self.assertEqual(
            self.dependencies[self.model.n3_label_offsets["near_face"]],
            {self.model.n3_label_offsets[x] for x in ("a", "b", "d")})

    def test_far_includes_material_list_and_only_far_vertices(self):
        names = self.labels(1000)
        self.assertTrue({
            "root", "lod", "far_poly", "far_list", "far_material",
            "a", "b", "e",
        } <= names)
        self.assertFalse({"near_face", "near_poly", "c", "d"} & names)
        self.assertEqual(names, self.labels(2500))

    def test_auto_per_anchor_and_all_lod_branches(self):
        self.assertEqual(self.labels("auto"), self.labels(0))
        self.assertEqual(
            self.labels("auto", (2000, 0, 0)), self.labels(1000))
        names = self.labels(None)
        self.assertTrue({
            "far_poly", "near_poly", "a", "b", "c", "d", "e",
            "far_material", "near_face",
        } <= names)

    def test_exported_binary_generated_labels_resolve_by_offset(self):
        model = self.model
        name = model.n3_label_offsets["far_poly"]
        aliases = label_offsets(model)
        self.assertEqual(aliases[f"_{name}"], name)
        self.assertIn(f"_{name}", self.labels(1200))
        self.assertNotIn(f"_{name}", self.labels(0))

    def test_classification_matches_reachable_named_declarations(self):
        entries = index_source_entries(SOURCE)
        near = self.labels(0)
        far = self.labels(1000)
        near_labels = {e.preview.split(":", 1)[0].strip()
                       for e in entries if entry_is_active(e, near)}
        far_labels = {e.preview.split(":", 1)[0].strip()
                      for e in entries if entry_is_active(e, far)}
        self.assertIn("near_poly", near_labels)
        self.assertNotIn("near_poly", far_labels)
        self.assertNotIn("far_poly", near_labels)
        self.assertIn("far_poly", far_labels)
        self.assertFalse(any(entry_is_active(e, near)
                             for e in entries if e.category == "Comments (%)"))

    def test_nested_res_and_sprite_vertex_dependency(self):
        class Switch:
            def __init__(self, anchor, branches):
                self.anchor = anchor
                self.branches = branches

            def choose(self, distance):
                return next((t, p) for t, p in self.branches if distance >= t)

        model = SimpleNamespace(
            root_offset=1,
            records={1: 11, 2: 13, 3: 13, 4: 3, 5: 15, 6: 1, 7: 1},
            children={1: [2], 2: [3, 5], 3: [4, 6], 4: [], 5: [],
                      6: [], 7: []},
            switches={
                2: Switch(100, ((500, 5), (0, 3))),
                3: Switch(100, ((200, 6), (0, 4))),
            },
            polygons={
                6: SimpleNamespace(refs=(100, 102, 104)),
                7: SimpleNamespace(refs=(100, 102, 104)),
            },
            vertices={
                100: SimpleNamespace(xyz=(0, 0, 0)),
                102: SimpleNamespace(xyz=(0, 20, 0)),
                104: SimpleNamespace(xyz=(30, 0, 0)),
                106: SimpleNamespace(xyz=(99, 99, 99)),
            },
            pmp_sprites={4: SimpleNamespace(vertex_ref=106)},
            n3_label_offsets={
                "root": 1, "outer": 2, "inner": 3,
                "sprite": 4, "far_dynamic": 5, "far_poly": 6,
                "orphan": 7, "anchor": 100,
                "b": 102, "c": 104, "sprite_anchor": 106,
            },
        )
        near = active_source_labels(model, 0, (0, 0, 0))
        self.assertTrue({"root", "outer", "inner", "sprite", "sprite_anchor",
                         "anchor"} <= near)
        self.assertFalse({"far_dynamic", "far_poly", "orphan"} & near)
        middle = active_source_labels(model, 200, (0, 0, 0))
        self.assertTrue({"far_poly", "b", "c", "anchor"} <= middle)
        self.assertNotIn("sprite_anchor", middle)
        far = active_source_labels(model, 500, (0, 0, 0))
        self.assertIn("far_dynamic", far)
        self.assertNotIn("inner", far)

    def test_no_model_or_unreferenced_rows_are_excluded(self):
        self.assertEqual(active_source_labels(None, 0, (0, 0, 0)), set())
        self.assertFalse(entry_is_active(
            index_source_entries("% hello\n")[0], set()))


if __name__ == "__main__":
    unittest.main()
