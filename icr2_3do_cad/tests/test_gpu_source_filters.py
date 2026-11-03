"""Pure N3 source category indexing: complete, editable text stays unmodified."""
import unittest

from gpu_viewer.source_filters import (
    CATEGORIES, classify_statement, index_source_entries,
)


TEXT = """3D VERSION 3.0;
% global comment describing POLY and SWITCH
origin: [<0,0,0>]; % inline comment should stay with vertex
right: [<100,0,0>];
top: [<0,100,0>];

body: POLY <44>
  {origin, right,
   top};
objects: LIST {body};
plane: BSPN (origin,right,top), {body};
flip: FACE2 (origin,right,top), body, objects;
lod: SWITCH DISTANCE (origin) > {
  (1000 ? objects),
  (0 ? body)};
paint: MATERIAL MIP="poly;%.mip", GROUP=1, body;
extra: DYNAMIC 0,0,0,0, EXTERN "wheel";
line: LINE <12> {origin,right};
colors: RECOLOR {1,2};
billboard: SRB origin, 100, "sprite.pmp";
data: DATA {1,2};
% last comment
"""


class SourceFilterTests(unittest.TestCase):
    def test_every_requested_statement_category_and_multiline_groups(self):
        entries = index_source_entries(TEXT)
        self.assertEqual(set(e.category for e in entries), set(CATEGORIES))
        by_category = {cat: [e for e in entries if e.category == cat]
                       for cat in CATEGORIES}
        self.assertEqual(len(by_category["Comments (%)"]), 2)
        self.assertEqual(len(by_category["Vertices"]), 3)
        self.assertEqual(len(by_category["POLY"]), 1)
        self.assertEqual(len(by_category["LIST"]), 1)
        self.assertEqual(len(by_category["BSP"]), 1)
        self.assertEqual(len(by_category["FACE"]), 1)
        self.assertEqual(len(by_category["SWITCH"]), 1)
        self.assertEqual(len(by_category["MATERIAL"]), 1)
        self.assertEqual(len(by_category["DYNAMIC"]), 1)
        self.assertEqual(len(by_category["LINE"]), 1)
        self.assertEqual(len(by_category["RECOLOR"]), 1)
        self.assertEqual(len(by_category["Sprites"]), 1)
        self.assertEqual(len(by_category["Other"]), 2)
        polygon = by_category["POLY"][0]
        self.assertEqual((polygon.first_line, polygon.last_line), (6, 8))
        self.assertIn("(3 lines)", polygon.preview)
        switch = by_category["SWITCH"][0]
        self.assertEqual((switch.first_line, switch.last_line), (12, 14))
        self.assertTrue(by_category["MATERIAL"][0].preview.startswith("paint:"))

    def test_comment_and_quote_aware_semicolons(self):
        source = """a: MATERIAL MIP="foo;%.mip",
  GROUP=1, b; % trailing;
% POLY <1> {a,b,c};
p: POLY <2> {a,b,c}; % comment
"""
        entries = index_source_entries(source)
        self.assertEqual([(e.category, e.first_line, e.last_line)
                          for e in entries], [
                              ("MATERIAL", 0, 1),
                              ("Comments (%)", 2, 2),
                              ("POLY", 3, 3)])
        self.assertEqual(classify_statement("% LIST {x};"), "Comments (%)")
        self.assertEqual(classify_statement("body: POLY [T] <40> {a,b,c};"),
                         "POLY")
        self.assertEqual(classify_statement("p: [<0,0,0>, T=<1,1>];"),
                         "Vertices")

    def test_incomplete_declaration_does_not_swallow_next_declaration(self):
        source = """first: POLY <44>
  {a, b,
second: LIST {first};
% trailing
"""
        entries = index_source_entries(source)
        self.assertEqual([(e.category, e.first_line, e.last_line)
                          for e in entries], [
                              ("POLY", 0, 1),
                              ("LIST", 2, 2),
                              ("Comments (%)", 3, 3)])

    def test_does_not_modify_source_or_offset(self):
        original = "a: [<1,2,3>];\r\n% text\r\np: POLY <44> {a,a,a};\r\n"
        entries = index_source_entries(original)
        self.assertEqual(entries[0].first_line, 0)
        self.assertEqual(entries[1].first_line, 1)
        self.assertEqual(entries[2].first_line, 2)
        self.assertEqual(original.splitlines()[2],
                         "p: POLY <44> {a,a,a};")
        self.assertEqual(index_source_entries(" \n\n"), ())


if __name__ == "__main__":
    unittest.main()
