"""Safe N3 declaration rename and pointer-reference tracking regressions."""
import unittest

from n3_compile import compile_n3_text
from gpu_viewer.source_rename import (
    edited_declaration_label, declaration_label, reference_spans,
)


SOURCE = """3D VERSION 3.0;
% old_front should not change in this comment
old_front: [<0,0,0>];
right: [<100,0,0>];
top: [<0,100,0>];
nose: POLY <44> {old_front,right,top};
other: POLY <55> {old_front,top,right};
root: SWITCH DISTANCE (old_front) > {(1000 ? nose), (0 ? other)};
"""


def rename_references(text, old, new):
    spans = reference_spans(text, old, new)
    for start, end in reversed(spans):
        text = text[:start] + new + text[end:]
    return text, spans


class N3SymbolRenameTests(unittest.TestCase):
    def test_rename_vertex_pointer_references_compiles(self):
        updated = SOURCE.replace("old_front:", "lead:")
        renamed, spans = rename_references(updated, "old_front", "lead")
        self.assertEqual(len(spans), 3)
        self.assertIn("% old_front should not change", renamed)
        self.assertIn("nose: POLY <44> {lead,right,top};", renamed)
        self.assertIn("other: POLY <55> {lead,top,right};", renamed)
        self.assertIn("SWITCH DISTANCE (lead)", renamed)
        model, _ = compile_n3_text(renamed, "rename.3d",
                                   associate_planes=False)
        self.assertIn("lead", model.n3_label_offsets)

    def test_rename_poly_references_in_list_face_and_res(self):
        before = """3D VERSION 3.0;
a: [<0,0,0>];
b: [<100,0,0>];
c: [<0,100,0>];
body: POLY <44> {a,b,c};
face: FACE (a,b,c), body;
root: LIST {face, body};
"""
        after = before.replace("body:", "panel:")
        renamed, spans = rename_references(after, "body", "panel")
        self.assertEqual(len(spans), 2)
        self.assertIn("face: FACE (a,b,c), panel;", renamed)
        self.assertIn("root: LIST {face, panel};", renamed)
        compile_n3_text(renamed, "panel.3d", associate_planes=False)

    def test_exact_token_not_comments_strings_or_substrings(self):
        source = """3D VERSION 3.0;
front: POLY <44> {a,b,c};
reference: LIST {old, old_more, something_old, old};
texture: MATERIAL MIP="old", GROUP=3, old;
% old in a comment, including: old
"""
        text, spans = rename_references(source, "old", "front")
        self.assertEqual(len(spans), 3)
        self.assertIn("old_more", text)
        self.assertIn("something_old", text)
        self.assertIn('MIP="old"', text)
        self.assertIn("% old in a comment", text)
        self.assertIn("LIST {front, old_more, something_old, front}", text)

    def test_identifier_tokens_do_not_change_named_fields(self):
        source = """3D VERSION 3.0;
newcolor: [<1,2,3>, c=44];
vertex: POLY <1> {c, a, b};
"""
        text, spans = rename_references(source, "c", "newcolor")
        self.assertEqual(len(spans), 1)
        self.assertIn("c=44", text)
        self.assertIn("POLY <1> {newcolor, a, b}", text)

    def test_refuse_collision_ambiguous_old_and_reserved_names(self):
        source = """3D VERSION 3.0;
old: NIL;
new: NIL;
root: LIST {old};
"""
        self.assertEqual(reference_spans(source, "old", "new"), [])
        self.assertEqual(reference_spans(source, "NIL", "other"), [])
        self.assertEqual(reference_spans(source, "old", "LIST"), [])
        self.assertEqual(reference_spans(source, "old", "invalid name"), [])

    def test_identify_only_a_changed_declaration_label(self):
        original = SOURCE
        changed = original.replace("old_front:", "lead:")
        self.assertEqual(edited_declaration_label(original, changed, 2),
                         "old_front")
        self.assertEqual(declaration_label(changed, 2), "lead")
        missing = original.replace("old_front:", ":")
        self.assertEqual(edited_declaration_label(original, missing, 2),
                         "old_front")
        self.assertIsNone(declaration_label(missing, 2))
        self.assertIsNone(edited_declaration_label(
            original, original.replace("old_front,right", "lead,right"), 5))
        self.assertIsNone(edited_declaration_label(
            original, original.replace("% old_front", "% lead"), 1))
        self.assertIsNone(edited_declaration_label(
            original, original.replace("POLY <44>", "POLY <55>"), 5))


if __name__ == "__main__":
    unittest.main()
