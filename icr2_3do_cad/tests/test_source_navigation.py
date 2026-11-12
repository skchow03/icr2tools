"""N3 reference navigation: unique declarations and safe token hit testing."""
import unittest

from source_navigation import declaration_lines, referenced_pointer_at
from source_rename import qt_utf16_offset


SOURCE = """3D VERSION 3.0;
front-left: [<0,0,0>];
front_right: [<100,0,0>];
triangle: POLY <49> {front-left, front_right, front-left};
branch: LIST {
    triangle,
    front_right
};
finish: MATERIAL ("triangle.mip", branch); % triangle in comment
root: LIST {finish};
"""


class PointerNavigationDataTests(unittest.TestCase):
    def setUp(self):
        self.lines = SOURCE.splitlines()
        self.declarations = declaration_lines(SOURCE)

    def pointer(self, line_number, text):
        line = self.lines[line_number]
        return referenced_pointer_at(
            line, qt_utf16_offset(line, line.index(text) + 1),
            self.declarations)

    def test_every_n3_declaration_kind_is_indexed(self):
        self.assertEqual(self.declarations["front-left"], 1)
        self.assertEqual(self.declarations["triangle"], 3)
        self.assertEqual(self.declarations["branch"], 4)
        self.assertEqual(self.declarations["finish"], 8)
        self.assertEqual(self.declarations["root"], 9)

    def test_follow_polygon_and_multiline_list_references(self):
        self.assertEqual(self.pointer(3, "front-left"), "front-left")
        self.assertEqual(self.pointer(5, "triangle"), "triangle")
        self.assertEqual(self.pointer(6, "front_right"), "front_right")
        self.assertEqual(self.pointer(9, "finish"), "finish")

    def test_never_link_declaration_name_keyword_comment_or_filename(self):
        self.assertIsNone(self.pointer(1, "front-left"))
        self.assertIsNone(self.pointer(3, "POLY"))
        line = self.lines[8]
        self.assertEqual(self.pointer(8, "branch"), "branch")
        filename = line.index("triangle.mip") + 1
        self.assertIsNone(referenced_pointer_at(
            line, qt_utf16_offset(line, filename), self.declarations))
        comment = line.index("% triangle") + 3
        self.assertIsNone(referenced_pointer_at(
            line, qt_utf16_offset(line, comment), self.declarations))
        self.assertIsNone(referenced_pointer_at(
            "root: LIST {triangle_extra};", 15, self.declarations))
        self.assertIsNone(referenced_pointer_at(
            "root: LIST {triang};", 13, self.declarations))

    def test_unicode_before_identifier_does_not_shift_qt_hit(self):
        line = 'paint: MATERIAL ("🟡.mip", triangle);'
        offset = qt_utf16_offset(line, line.index("triangle") + 3)
        self.assertEqual(
            referenced_pointer_at(line, offset, self.declarations), "triangle")

    def test_duplicate_declarations_remain_unresolved(self):
        source = "root: LIST {a};\na: LIST {root};\na: LIST {root};\n"
        declarations = declaration_lines(source)
        self.assertNotIn("a", declarations)
        self.assertEqual(referenced_pointer_at(
            "root: LIST {a};", 12, declarations), None)
        self.assertEqual(declarations["root"], 0)


if __name__ == "__main__":
    unittest.main()
