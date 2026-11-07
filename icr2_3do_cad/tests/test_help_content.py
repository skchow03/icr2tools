"""Non-GUI tests for the offline HTML manual's native-help topic index."""
import tempfile
import unittest
from pathlib import Path

from help_content import plain_text, read_manual


MANUAL = Path(__file__).resolve().parents[1] / "USER_MANUAL.html"


class NativeHelpContentTests(unittest.TestCase):
    def test_manual_has_searchable_named_topics_and_index(self):
        topics, entries = read_manual(MANUAL)
        ids = {topic.topic_id for topic in topics}
        self.assertGreaterEqual(len(topics), 15)
        self.assertEqual(len(ids), len(topics))
        for name in ("welcome", "quickstart", "files", "editing", "tracing",
                     "textures", "tracks", "shortcuts", "index"):
            self.assertIn(name, ids)
        self.assertTrue(all(topic.title and topic.text for topic in topics))
        self.assertGreaterEqual(len(entries), 25)
        self.assertTrue(all(target in ids for _letter, _term, target in entries))
        self.assertIn("Back", plain_text("<b>Back</b>"))

    def test_manual_is_content_only_without_faux_browser_or_network_assets(self):
        source = MANUAL.read_text(encoding="utf-8")
        self.assertNotIn('class="window"', source)
        self.assertNotIn('class="titlebar"', source)
        self.assertNotIn("javascript:", source.lower())
        self.assertNotIn("<script", source.lower())
        self.assertNotIn("http://", source.lower())
        self.assertNotIn("https://", source.lower())
        self.assertIn('<nav id="contents"', source)

    def test_missing_and_malformed_help_are_clear(self):
        with tempfile.TemporaryDirectory() as temporary:
            file = Path(temporary) / "bad.html"
            with self.assertRaises(FileNotFoundError):
                read_manual(file)
            file.write_text("<html><body>No topics</body></html>", encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "no recognizable"):
                read_manual(file)
            file.write_text(
                '<section id="welcome"><h1>Hello</h1></section>'
                '<section id="welcome"><h1>Hello</h1></section>',
                encoding="utf-8",
            )
            with self.assertRaisesRegex(ValueError, "Duplicate"):
                read_manual(file)


if __name__ == "__main__":
    unittest.main()
