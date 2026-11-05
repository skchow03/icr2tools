"""Coverage and behavior of contextual help for the editable N3 subset."""
import unittest

from gpu_viewer.source_help import (
    COMMAND_HELP, help_for_lines, help_for_statement,
)


EXAMPLES = {
    "VERSION": "3D VERSION 3.0;",
    "DECLARATION": "unfamiliar:",
    "VERTEX": "v: [<1,2,3>, T=<127,50>];",
    "POLY": "face: POLY <42> {a,b,c};",
    "POLY_T": "tex: POLY [T] <42> {a,b,c};",
    "LINE": "edge: LINE <1> {a,b};",
    "NIL": "nil: NIL;",
    "LIST": "group: LIST {a,b,NIL};",
    "FACE": "f: FACE (a,b,c), object;",
    "FACE2": "f: FACE2 (a,b,c), object, NIL;",
    "BSPF": "b: BSPF (a,b,c), NIL, object, NIL;",
    "BSPA": "b: BSPA (a,b,c), NIL, object, NIL;",
    "BSP2": "b: BSP2 (a,b,c), NIL, object, NIL, NIL;",
    "BSPN": "b: BSPN (a,b,c), object, NIL;",
    "MATERIAL": 'm: MATERIAL MIP="road", GROUP=4, tex;',
    "SWITCH": "lod: SWITCH DISTANCE (ref) > {(100 ? near), (0 ? far)};",
    "DYNAMIC": 'd: DYNAMIC 0,0,0,0,0,0,1,EXTERN "car";',
    "EXTERN": 'obj: EXTERN "car";',
    "SUPEROBJ": "s: SUPEROBJ a, {b,c};",
    "SRB": 's: SRB ref,100,"sprite";',
    "PMP2": 's: PMP2 ref,100,"sprite";',
    "RECOLOR": "r: RECOLOR (1:2, 3:4);",
    "DYNO": "d: DYNO {1,2,3,4};",
    "DATA": "d: DATA {1,2,3,4};",
    "COMMENT": "% a comment",
    "SCALE": "% ICR2_COORD_SCALE: 6000",
    "OFFSET": "% ICR2_OFFSET: 192",
    "ROOT_HINT": "% ICR2_ROOT: 192",
}


class N3SourceHelpTests(unittest.TestCase):
    def test_complete_compiler_commands_have_syntax_and_purpose(self):
        self.assertEqual(set(COMMAND_HELP), set(EXAMPLES))
        for key, example in EXAMPLES.items():
            with self.subTest(command=key):
                help_item = help_for_statement(example)
                self.assertIs(help_item, COMMAND_HELP[key])
                self.assertTrue(help_item.syntax)
                self.assertTrue(help_item.description)
                self.assertTrue(help_item.detail)
                self.assertIn("Syntax:", help_item.tooltip())
                self.assertIn(help_item.description, help_item.compact())

    def test_html_tooltips_are_constrained_and_escape_n3_syntax(self):
        material = help_for_statement(
            'm: MATERIAL MIP="building", GROUP=4, child;')
        formatted = material.tooltip_html(note="Original line 27 | MATERIAL")
        self.assertIn('<table width="370"', formatted)
        self.assertIn('<td width="370">', formatted)
        self.assertIn('Original line 27', formatted)
        self.assertIn('&quot;texture&quot;', formatted)
        self.assertIn('wrap', formatted.lower())
        polygon = help_for_statement("p: POLY <46> {a,b,c};")
        escaped = polygon.tooltip_html()
        self.assertIn('&lt;color&gt;', escaped)
        self.assertNotIn('<color>', escaped)
        self.assertIn('1', polygon.tooltip())
        self.assertNotIn('Original line', polygon.tooltip_html())

    def test_face_and_bsp_sidedness_explanations(self):
        # These descriptions intentionally document the CAD viewport's
        # side-dependent traversal rather than promising pixel visibility.
        behavior = {
            "FACE": ("one-sided", "from the back"),
            "FACE2": ("two-sided", "same child in both slots"),
            "BSPF": ("middle child", "front-only"),
            "BSPA": ("all three", "from either side"),
            "BSP2": ("front/back faces", "child4"),
            "BSPN": ("both children", "from both sides"),
        }
        for cmd, phrases in behavior.items():
            with self.subTest(command=cmd):
                tooltip = COMMAND_HELP[cmd].tooltip().lower()
                for phrase in phrases:
                    self.assertIn(phrase.lower(), tooltip)
                self.assertIn("v1, v2, v3", COMMAND_HELP[cmd].syntax)
                self.assertIn("Syntax:", COMMAND_HELP[cmd].tooltip())

    def test_solid_and_textured_polygon_tips_include_both_directions(self):
        solid = help_for_statement("wall: POLY <42> {a,b,c};")
        textured = help_for_statement("wall: POLY [T] <42> {a,b,c};")
        self.assertIn("add [T]", solid.tooltip())
        self.assertIn("POLY [T] <42> {a,b,c}", solid.tooltip())
        self.assertIn("T=<U,V>", solid.tooltip())
        self.assertIn('MATERIAL MIP="name"', solid.tooltip())
        self.assertIn("remove [T]", textured.tooltip())
        self.assertIn("POLY <42> {a,b,c}", textured.tooltip())
        self.assertIn("can remain", textured.tooltip())
        self.assertIn("MIP MATERIAL", textured.tooltip())
        self.assertIn("add [T]", solid.compact())
        self.assertIn("remove [T]", textured.compact())
        self.assertIn("MATERIAL", solid.tooltip_html())
        self.assertIn("MATERIAL", textured.tooltip_html())

    def test_documented_face_bsp_traversal_matches_compiler_and_model(self):
        """Guard exact N3 child ordering used in user-facing explanations."""
        from n3_compile import compile_n3_text

        declarations = (
            "3D VERSION 3.0;\n"
            "p0: [<0,0,0>];\n"
            "p1: [<100,0,0>];\n"
            "p2: [<0,100,0>];\n"
            "A: POLY <40> {p0,p1,p2};\n"
            "B: POLY <41> {p0,p1,p2};\n"
            "C: POLY <42> {p0,p1,p2};\n"
            "D: POLY <43> {p0,p1,p2};\n"
        )
        cases = {
            "FACE": ("A", ["A"], []),
            "FACE2": ("A, B", ["A"], ["B"]),
            "BSPF": ("A, B, C", ["C", "B", "A"], ["A", "C"]),
            "BSPA": ("A, B, C", ["C", "B", "A"], ["A", "B", "C"]),
            "BSP2": ("A, B, C, D", ["A", "D", "C"], ["B", "D", "A"]),
            "BSPN": ("A, B", ["B", "A"], ["A", "B"]),
        }
        for kind, (children, expected_front, expected_back) in cases.items():
            with self.subTest(kind=kind):
                source = (
                    declarations + f"root: {kind} (p0,p1,p2), {children};\n")
                model, _ = compile_n3_text(
                    source, f"{kind.lower()}_help.3d",
                    associate_planes=False)
                reverse = {off: name for name, off
                           in model.n3_label_offsets.items()
                           if name in ("A", "B", "C", "D")}
                for z, expected in ((100, expected_front),
                                    (-100, expected_back)):
                    drawn, _stats, _lod = model.switched_polygons(
                        None, (10, 10, z), bsp_mode="original")
                    self.assertEqual(
                        [reverse[off] for off in drawn], expected)

    def test_solid_textured_conversion_examples_compile(self):
        from n3_compile import compile_n3_text

        base = (
            "3D VERSION 3.0;\n"
            "a: [<0,0,0>, T=<0,0>];\n"
            "b: [<100,0,0>, T=<127,0>];\n"
            "c: [<0,100,0>, T=<0,127>];\n"
        )
        for kind, command, root_expr, expected_flavor in (
                ("solid", "POLY", "face", 1),
                ("textured", "POLY [T]",
                 'MATERIAL MIP="wall", GROUP=3, face', 2)):
            source = (base + f"face: {command} <42> {{a,b,c}};\n"
                      + f"root: {root_expr};\n")
            with self.subTest(kind=kind):
                model, _ = compile_n3_text(
                    source, f"{kind}_help.3d", associate_planes=False)
                polygon = model.polygons[model.n3_label_offsets["face"]]
                self.assertEqual(polygon.kind, expected_flavor)

    def test_multiline_continuations_and_incomplete_commands(self):
        src = [
            "3D VERSION 3.0;",
            "a: [<0,0,0>];",
            "plane: BSPF (a,",
            "    b,",
            "    c), NIL, poly, NIL;",
            "next: POLY [T] <42> {",
            "    a,b,c",
            "};",
            "lod: SWITCH DISTANCE (a) > {",
            "   (200 ? x),",
            "   (0 ? y)",
            "};",
            "some: MATERIAL MIP=",
        ]
        for line in (2,3,4):
            self.assertIs(help_for_lines(src, line), COMMAND_HELP["BSPF"])
        for line in (5,6,7):
            self.assertIs(help_for_lines(src, line), COMMAND_HELP["POLY_T"])
        for line in (8,9,10,11):
            self.assertIs(help_for_lines(src, line), COMMAND_HELP["SWITCH"])
        self.assertIs(help_for_lines(src, 12), COMMAND_HELP["MATERIAL"])

    def test_no_help_leak_from_previous_statement(self):
        lines = [
            "a: POLY <44> {a,b,c};",
            "",
            "% comment about something else",
            "random text",
            "another: BSPN (p,q,r), NIL, NIL;",
            "not a declaration",
        ]
        self.assertIs(help_for_lines(lines,0), COMMAND_HELP["POLY"])
        self.assertIsNone(help_for_lines(lines,1))
        self.assertIs(help_for_lines(lines,2), COMMAND_HELP["COMMENT"])
        self.assertIsNone(help_for_lines(lines,3))
        self.assertIs(help_for_lines(lines,4), COMMAND_HELP["BSPN"])
        self.assertIsNone(help_for_lines(lines,5))
        self.assertIsNone(help_for_lines(lines,-1))
        self.assertIsNone(help_for_lines(lines,100))

    def test_comment_and_quote_handling(self):
        self.assertIs(help_for_statement(
            '% ICR2_COORD_SCALE: 1'), COMMAND_HELP["SCALE"])
        self.assertIs(help_for_statement(
            'mat: MATERIAL MIP="contains%percent", GROUP=4, child; % note'),
            COMMAND_HELP["MATERIAL"])
        lines = ["m: MATERIAL MIP=\"name%pcx\"", "    GROUP=4, p;"]
        self.assertIs(help_for_lines(lines,1), COMMAND_HELP["MATERIAL"])

    def test_in_progress_typing_and_unknown_commands(self):
        for example, expected in [
            ("p:", "DECLARATION"),
            ("p: POLY", "POLY"),
            ("p: POLY [T]", "POLY_T"),
            ("p: BSP", None),
            ("p: BSPF (", "BSPF"),
            ("s: SWITCH", "SWITCH"),
            ("p: [<1,", "VERTEX"),
            ("p: FOO {a};", None),
            ("p: MATERIAL MIP=", "MATERIAL"),
        ]:
            with self.subTest(example=example):
                tip = help_for_statement(example)
                self.assertEqual(tip.name if tip else None,
                                 COMMAND_HELP[expected].name if expected else None)


if __name__ == "__main__":
    unittest.main()
