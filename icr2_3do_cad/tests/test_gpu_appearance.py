"""Appearance palette normalization, contrast, persistence and swatch tests."""
import tempfile
import unittest
from pathlib import Path

from gpu_viewer.appearance import (
    COLOR_GROUPS, DARK_COLORS, LIGHT_COLORS, load_colors, save_colors,
    swatch_text_color, validated_colors,
)


class FakeSettings:
    def __init__(self):
        self.saved = {}
        self.synced = False

    def value(self, key):
        return self.saved.get(key)

    def setValue(self, key, value):
        self.saved[key] = value

    def sync(self):
        self.synced = True


def contrast(a, b):
    def luminance(value):
        parts = [int(value[i:i+2], 16) / 255.0 for i in (1, 3, 5)]
        linear = [c/12.92 if c <= 0.04045 else
                  ((c+0.055)/1.055)**2.4 for c in parts]
        return sum(x*y for x, y in zip(linear, (.2126, .7152, .0722)))
    x, y = sorted((luminance(a), luminance(b)))
    return (y+.05)/(x+.05)


class AppearanceTests(unittest.TestCase):
    def test_roles_and_presets_are_complete(self):
        roles = [name for _, group in COLOR_GROUPS for name, _ in group]
        self.assertEqual(len(roles), len(set(roles)))
        self.assertEqual(set(roles), set(DARK_COLORS))
        self.assertEqual(set(DARK_COLORS), set(LIGHT_COLORS))

    def test_preset_has_readable_normal_syntax_and_selected_lines(self):
        for theme in (DARK_COLORS, LIGHT_COLORS):
            for kind in ("source_text", "source_comment", "source_string",
                         "source_keyword", "source_label"):
                with self.subTest(theme=theme["source_background"], kind=kind):
                    self.assertGreaterEqual(contrast(
                        theme[kind], theme["source_background"]), 4.5)
            for key in ("source_visible_background", "source_hidden_background",
                        "source_error_background"):
                self.assertGreaterEqual(contrast(
                    theme["source_highlight_text"], theme[key]), 4.5)
            self.assertGreaterEqual(contrast(
                theme["source_selection_text"],
                theme["source_selection_background"]), 4.5)

    def test_invalid_colors_are_ignored_and_persistent_overrides_roundtrip(self):
        settings = FakeSettings()
        colors = dict(DARK_COLORS, source_background="#abcdef",
                      viewport_wire="#010203")
        colors["unknown"] = "#123456"
        save_colors(settings, colors)
        self.assertTrue(settings.synced)
        self.assertEqual(settings.saved["appearance/source_background"], "#ABCDEF")
        self.assertEqual(settings.saved["appearance/viewport_wire"], "#010203")
        self.assertNotIn("appearance/unknown", settings.saved)
        self.assertEqual(load_colors(settings)["source_background"], "#ABCDEF")
        settings.setValue("appearance/source_keyword", "malformed")
        self.assertEqual(load_colors(settings)["source_keyword"],
                         DARK_COLORS["source_keyword"])
        self.assertEqual(validated_colors({"source_label": "#1234"})[
            "source_label"], DARK_COLORS["source_label"])

    def test_color_button_text_contrasts_with_swatch(self):
        for color in ("#000000", "#FFFFFF", "#193E35", "#D7F5E2"):
            self.assertGreaterEqual(
                contrast(color, swatch_text_color(color)), 4.5)


if __name__ == "__main__":
    unittest.main()
