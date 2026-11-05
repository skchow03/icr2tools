"""User-adjustable GPU viewer and .3D source colors.

All colors are opaque #RRGGBB. Keep editor syntax, selection highlights,
filtered rows and viewport accents on one shared, persistent palette.
"""
from __future__ import annotations

import re

COLOR_GROUPS = (
    ("Source editor", (
        ("source_background", "Editor background"),
        ("source_text", "Normal text"),
        ("source_comment", "Comments (%)"),
        ("source_string", "Strings / filenames"),
        ("source_keyword", "N3 keywords"),
        ("source_label", "Pointer labels"),
        ("source_selection_background", "Text selection background"),
        ("source_selection_text", "Text selection foreground"),
        ("source_visible_background", "Selected POLY: drawn"),
        ("source_hidden_background", "Selected POLY: not drawn"),
        ("source_error_background", "Error line"),
        ("source_highlight_text", "POLY / error line text"),
    )),
    ("GPU viewport", (
        ("viewport_background", "Background (clear color)"),
        ("viewport_wire", "Wireframe lines"),
        ("viewport_selected_wire", "Selected POLY outline"),
        ("viewport_vertex_dot", "Selected vertex dot"),
        ("viewport_vertex_outline", "Vertex dot border"),
    )),
)

DARK_COLORS = {
    "source_background": "#141B27",
    "source_text": "#E9EEF7",
    "source_comment": "#A4D3B0",
    "source_string": "#FFD09E",
    "source_keyword": "#A4CDFF",
    "source_label": "#FFE2A4",
    "source_selection_background": "#31547D",
    "source_selection_text": "#FFFFFF",
    "source_visible_background": "#193E35",
    "source_hidden_background": "#52333B",
    "source_error_background": "#602C3C",
    "source_highlight_text": "#F7FAFF",
    "viewport_background": "#111724",
    "viewport_wire": "#D6E3F2",
    "viewport_selected_wire": "#FFC24D",
    "viewport_vertex_dot": "#FFED41",
    "viewport_vertex_outline": "#0C1420",
}

LIGHT_COLORS = {
    "source_background": "#FFFFFF",
    "source_text": "#18212F",
    "source_comment": "#285D41",
    "source_string": "#8A4100",
    "source_keyword": "#064D98",
    "source_label": "#745000",
    "source_selection_background": "#B9D8FF",
    "source_selection_text": "#0F1B2A",
    "source_visible_background": "#D7F5E2",
    "source_hidden_background": "#FFE3DD",
    "source_error_background": "#FFD6E2",
    "source_highlight_text": "#17221D",
    "viewport_background": "#EEF3F9",
    "viewport_wire": "#263D57",
    "viewport_selected_wire": "#A15E00",
    "viewport_vertex_dot": "#FFDC37",
    "viewport_vertex_outline": "#1A2C3C",
}

_HEX = re.compile(r"#[0-9a-fA-F]{6}\Z")


def validated_colors(values, defaults=DARK_COLORS):
    """Ignore unknown roles and invalid persisted hex strings."""
    result = dict(defaults)
    for name in DARK_COLORS:
        value = values.get(name)
        if isinstance(value, str) and _HEX.fullmatch(value):
            result[name] = value.upper()
    return result


def load_colors(settings):
    return validated_colors({
        name: settings.value("appearance/" + name)
        for name in DARK_COLORS
    })


def save_colors(settings, colors):
    for name, color in validated_colors(colors).items():
        settings.setValue("appearance/" + name, color)
    settings.sync()


def swatch_text_color(color):
    """Give color-picker swatches readable foreground labels."""
    rgb = [int(color[i:i + 2], 16) / 255.0 for i in (1, 3, 5)]
    linear = [c / 12.92 if c <= 0.04045 else
              ((c + 0.055) / 1.055) ** 2.4 for c in rgb]
    luminance = sum(a * b for a, b in zip(linear, (0.2126, 0.7152, 0.0722)))
    return "#111827" if luminance > 0.179 else "#FFFFFF"
