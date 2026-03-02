from __future__ import annotations

from pathlib import Path

import numpy as np

try:
    from PyQt5 import QtGui
except ImportError:  # pragma: no cover
    from PySide6 import QtGui  # type: ignore


def load_sunny_palette(path: str | Path) -> np.ndarray:
    data = Path(path).read_bytes()
    if len(data) < 769 or data[-769] != 0x0C:
        raise ValueError("Invalid or missing 256-color PCX palette marker")
    raw = np.frombuffer(data[-768:], dtype=np.uint8).reshape(256, 3)
    return raw.copy()


def save_palette(path: str | Path, palette_array: np.ndarray) -> None:
    palette = np.asarray(palette_array, dtype=np.uint8)
    if palette.shape != (256, 3):
        raise ValueError("palette_array must be shape (256, 3)")
    out = bytearray(128)
    out[0] = 10
    out[1] = 5
    out[2] = 1
    out[3] = 8
    width = 320
    height = 200
    out[8] = (width - 1) & 0xFF
    out[9] = ((width - 1) >> 8) & 0xFF
    out[10] = (height - 1) & 0xFF
    out[11] = ((height - 1) >> 8) & 0xFF
    out[65] = 1
    out[66] = width & 0xFF
    out[67] = (width >> 8) & 0xFF
    out[68] = 1
    out[69] = 0
    pixels = width * height
    while pixels > 0:
        run = min(63, pixels)
        out.append(0xC0 | run)
        out.append(0xFF)
        pixels -= run
    out.append(0x0C)
    out.extend(palette.tobytes())
    Path(path).write_bytes(bytes(out))


def visualize_palette(
    palette_array: np.ndarray,
    tile_size: int = 16,
    selected_index: int | None = None,
) -> QtGui.QImage:
    palette = np.asarray(palette_array, dtype=np.uint8)
    if palette.shape != (256, 3):
        raise ValueError("palette_array must be shape (256, 3)")

    size = 16 * tile_size
    image = QtGui.QImage(size, size, QtGui.QImage.Format_RGB888)
    painter = QtGui.QPainter(image)
    for i, (r, g, b) in enumerate(palette):
        x = (i % 16) * tile_size
        y = (i // 16) * tile_size
        painter.fillRect(x, y, tile_size, tile_size, QtGui.QColor(int(r), int(g), int(b)))
        if 176 <= i <= 245:
            pen = QtGui.QPen(QtGui.QColor(255, 255, 255) if i < 244 else QtGui.QColor(0, 0, 0))
            pen.setWidth(1)
            painter.setPen(pen)
            painter.drawRect(x, y, tile_size - 1, tile_size - 1)
        if selected_index is not None and i == selected_index:
            pen = QtGui.QPen(QtGui.QColor(255, 64, 64))
            pen.setWidth(3)
            painter.setPen(pen)
            painter.drawRect(x + 1, y + 1, tile_size - 3, tile_size - 3)
    painter.end()
    return image
