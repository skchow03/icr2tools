"""N3 go-to-declaration token lookup, without Qt or source compilation."""
import unittest

from gpu_viewer.source_navigation import declaration_lines, pointer_at_column


SOURCE = '''3D VERSION 3.0;
% A real name in a comment: root and nose
nose: [<0,0,0>];
right: [<100,0,0>];
tip: [<0,100,0>];
surface: POLY <44> {nose, right, tip};
plane: FACE (nose,right,tip), surface;
branch: BSPF (nose,right,tip), plane, NIL, surface;
res: SWITCH DISTANCE (nose) > {(1200 ? branch), (0 ? surface)};
external: DYNAMIC 0,0,0,0,0,0,1, EXTERN "nose";
texture: MATERIAL MIP="surface", GROUP=3, surface;
root: LIST {plane, res, external, texture};
'''


class PointerNavigationTests(unittest.TestCase):
    def setUp(self):
        self.definitions = declaration_lines(SOURCE)

    def hit(self, line, name, *, index=0):
        row = SOURCE.splitlines()[line]
        start = -1
        for _ in range(index + 1):
            start = row.index(name, start + 1)
        return pointer_at_column(row, start + 1, self.definitions)

    def test_any_n3_statement_can_jump_to_its_declarations(self):
        for line, token, expected in (
                (5, "nose", 2), (5, "right", 3), (5, "tip", 4),
                (6, "surface", 5), (7, "plane", 6),
                (8, "branch", 7), (8, "surface", 5),
                (10, "surface", 5), (11, "plane", 6),
                (11, "res", 8), (11, "external", 9),
                (11, "texture", 10)):
            with self.subTest(line=line, token=token):
                self.assertEqual(self.hit(line, token, index=1 if line == 10 else 0).target_line, expected)
        # The reference on a separate continuation row is still resolvable.
        self.assertEqual(pointer_at_column(
            "   {nose, right, tip};", 6, self.definitions).target_line, 2)

    def test_comments_quoted_resources_keywords_and_declaration_names_not_links(self):
        self.assertIsNone(self.hit(1, "root"))
        self.assertIsNone(self.hit(9, "nose"))
        self.assertIsNone(self.hit(10, "surface", index=0))
        self.assertIsNone(self.hit(5, "surface", index=0))  # declaration label
        self.assertIsNone(self.hit(11, "root", index=0))  # declaration label
        self.assertIsNone(self.hit(11, "LIST"))
        self.assertIsNone(self.hit(8, "DISTANCE"))
        self.assertIsNone(pointer_at_column(
            "MIP=surface, GROUP=3", 1, self.definitions))
        self.assertIsNone(pointer_at_column(
            "surface=44, surface;", 1, self.definitions))
        self.assertEqual(pointer_at_column(
            "surface=44, surface;", 14, self.definitions).target_line, 5)

    def test_click_requires_token_hit_and_f12_accepts_caret_after_token(self):
        row = "root: LIST {nose, right};"
        start = row.index("nose")
        end = start + len("nose")
        self.assertEqual(
            pointer_at_column(row, end, self.definitions).name, "nose")
        self.assertIsNone(pointer_at_column(
            row, end, self.definitions, include_end=False))
        self.assertEqual(
            pointer_at_column(row, start+1, self.definitions,
                              include_end=False).name, "nose")
        self.assertIsNone(pointer_at_column(row, len(row)+3, self.definitions))

    def test_duplicate_and_unknown_symbols_are_not_resolved(self):
        definitions = declaration_lines(
            SOURCE + "nose: NIL;\nnose: NIL;\n")
        self.assertNotIn("nose", definitions)
        self.assertIsNone(pointer_at_column(
            "root: LIST {nose};", 13, definitions))
        self.assertIsNone(pointer_at_column(
            "root: LIST {not_present};", 14, self.definitions))
        self.assertNotIn("fake", declaration_lines('% fake: NIL;\n'))

    def test_generated_body_offset_label_and_exact_case(self):
        src = "_104: POLY <1> {_4,_20,_48};\n_4: [<0,0,0>];\n"
        definitions = declaration_lines(src)
        self.assertEqual(pointer_at_column(
            "_104: POLY <1> {_4,_20,_48};", 16, definitions).target_line, 1)
        self.assertIsNone(pointer_at_column(
            "root: LIST {NOSE};", 13, self.definitions))


if __name__ == "__main__":
    unittest.main()
