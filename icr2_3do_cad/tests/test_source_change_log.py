"""Pure tests for the bounded, source-offset-accurate automatic edit log."""
import unittest

from source_change_log import (
    MAX_DETAILS_PER_OPERATION, format_rename_event,
)


class SourceChangeLogTests(unittest.TestCase):
    def test_summary_and_reference_lines(self):
        source = (
            "head: LIST {a};\n"
            "% do not rewrite a\n"
            "a: [<0,0,0>];\n"
            "poly: POLY <44> {a,a,a};\n"
            "root: LIST {poly};\n")
        target = "a"
        first = source.index("{a};") + 1
        second = source.index("{a,a,a};") + 1
        spans = [(second + 4, second + 5), (first, first + 1),
                 (second, second + 1), (second + 2, second + 3)]
        lines = format_rename_event(
            source, "a", "front", spans,
            action="Auto-rename references", declaration_line=2)
        self.assertEqual(
            lines[0], "Auto-rename references: a → front "
            "(declaration line 3; 4 references updated)")
        self.assertEqual(lines[1], "  line 1: a → front")
        self.assertEqual(lines[2:], ["  line 4: a → front"] * 3)

    def test_zero_references_and_truncation(self):
        lines = format_rename_event(
            "a: [<0,0,0>];", "a", "b", [],
            action="F2 pointer rename", declaration_line=0)
        self.assertEqual(len(lines), 1)
        self.assertIn("0 references updated", lines[0])
        source = "a\n" * (MAX_DETAILS_PER_OPERATION + 8)
        spans = [(2 * i, 2 * i + 1)
                 for i in range(MAX_DETAILS_PER_OPERATION + 8)]
        lines = format_rename_event(
            source, "a", "b", spans, action="Auto-rename references",
            declaration_line=0)
        self.assertEqual(len(lines), MAX_DETAILS_PER_OPERATION + 2)
        self.assertIn("8 additional references", lines[-1])

    def test_unicode_before_references_preserves_line_numbers(self):
        source = "% 📌 comment\nlabel: POLY {old};\nother: LIST {old};"
        offsets = [source.index("{old}") + 1, source.rindex("{old}") + 1]
        lines = format_rename_event(
            source, "old", "new", [(pos, pos + 3) for pos in offsets],
            action="Auto-rename references", declaration_line=1)
        self.assertIn("line 2", lines[1])
        self.assertIn("line 3", lines[2])


if __name__ == "__main__":
    unittest.main()
