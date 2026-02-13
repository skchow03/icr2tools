from __future__ import annotations

from PyQt5 import QtGui


def parse_hex_color(value: str) -> QtGui.QColor | None:
    text = value.strip()
    if not text:
        return None
    if not text.startswith("#"):
        text = f"#{text}"
    color = QtGui.QColor(text)
    if not color.isValid():
        return None
    return color

