"""F2 pointer rename plans: declaration-only edits and safe references."""
import unittest

from source_rename import plan_pointer_rename, qt_utf16_offset


SOURCE = """3D VERSION 3.0;
% front is a comment, not a pointer; 🚗
front: [<0,0,0>];
right: [<100,0,0>];
top: [<0,100,0>];
panel: POLY <44>
   {front, right, top};
face: FACE (front,right,top), panel;
root: LIST {face, panel};
material: MATERIAL MIP="panel", GROUP=3, root;
% MIP "panel" is not a pointer
"""


def apply_plan(source, edits):
    for start, end, replacement in edits:
        source = source[:start] + replacement + source[end:]
    return source


class F2PointerRenamePlanTests(unittest.TestCase):
    def test_change_only_poly_name_and_exact_references(self):
        old, edits = plan_pointer_rename(
            SOURCE, 5, "front_wing", update_references=True)
        self.assertEqual(old, "panel")
        self.assertEqual(len(edits), 3)  # label, FACE, LIST
        changed = apply_plan(SOURCE, edits)
        expected = SOURCE.replace("panel: POLY", "front_wing: POLY").replace(
            ", panel;", ", front_wing;").replace(
                "{face, panel};", "{face, front_wing};")
        self.assertEqual(changed, expected)
        self.assertIn('MIP="panel"', changed)
        self.assertIn('% MIP "panel"', changed)
        self.assertIn("   {front, right, top};", changed)

    def test_change_vertex_refs_in_poly_face_and_preserve_comments(self):
        old, edits = plan_pointer_rename(SOURCE, 2, "nose_vertex")
        self.assertEqual(old, "front")
        self.assertEqual(len(edits), 3)
        changed = apply_plan(SOURCE, edits)
        self.assertIn("nose_vertex: [<0,0,0>];", changed)
        self.assertIn("{nose_vertex, right, top};", changed)
        self.assertIn("FACE (nose_vertex,right,top)", changed)
        self.assertIn("% front is a comment", changed)
        self.assertIn("🚗", changed)

    def test_auto_rename_disabled_leaves_every_reference_intact(self):
        _, edits = plan_pointer_rename(
            SOURCE, 5, "body", update_references=False)
        self.assertEqual(len(edits), 1)
        changed = apply_plan(SOURCE, edits)
        self.assertEqual(
            changed, SOURCE.replace("panel: POLY", "body: POLY"))
        self.assertIn("FACE (front,right,top), panel;", changed)

    def test_refuse_collisions_invalid_reserved_and_ambiguous_names(self):
        for new in ("right", "bad name", "55invalid", "", "POLY", "mip",
                    "a:b", "middle.part"):
            with self.subTest(new=new), self.assertRaises(ValueError):
                plan_pointer_rename(SOURCE, 5, new)
        with self.assertRaises(ValueError):
            plan_pointer_rename(SOURCE + "panel: NIL;\n", 5, "wing")
        with self.assertRaises(ValueError):
            plan_pointer_rename(SOURCE, 1, "wing")
        with self.assertRaises(ValueError):
            plan_pointer_rename(SOURCE, 0, "wing")
        with self.assertRaises(ValueError):
            plan_pointer_rename(SOURCE, 100, "wing")

    def test_noop_is_empty_and_unchanged(self):
        old, edits = plan_pointer_rename(SOURCE, 5, "panel")
        self.assertEqual(old, "panel")
        self.assertEqual(edits, [])

    def test_original_offsets_are_descending_and_unicode_correct(self):
        _, edits = plan_pointer_rename(SOURCE, 2, "nose_vertex")
        self.assertEqual(
            [start for start, _, _ in edits],
            sorted((start for start, _, _ in edits), reverse=True))
        first_after_comment = SOURCE.index("front: [")
        self.assertEqual(
            qt_utf16_offset(SOURCE, first_after_comment),
            first_after_comment + 1)  # astral emoji consumes two UTF16 units
        self.assertEqual(
            apply_plan(SOURCE, edits).count("nose_vertex"), 3)
        self.assertEqual(SOURCE[:first_after_comment].count("🚗"), 1)

    def test_case_distinct_labels_and_underscore_offsets(self):
        source = "3D VERSION 3.0;\n_200: POLY <44> {_100,_101,_102};\nroot: LIST {_200};\n"
        _, edits = plan_pointer_rename(source, 1, "body_200")
        self.assertIn(
            "root: LIST {body_200};", apply_plan(source, edits))


if __name__ == "__main__":
    unittest.main()
