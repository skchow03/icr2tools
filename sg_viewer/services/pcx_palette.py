from __future__ import annotations

from pathlib import Path


def read_pcx_256_palette(path: Path) -> list[tuple[int, int, int]]:
    data = path.read_bytes()
    if len(data) < 769 or data[-769] != 0x0C:
        raise ValueError("Invalid or missing 256-color PCX palette marker")
    raw_palette = data[-768:]
    return [
        (int(raw_palette[i]), int(raw_palette[i + 1]), int(raw_palette[i + 2]))
        for i in range(0, 768, 3)
    ]
