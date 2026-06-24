from __future__ import annotations

from pathlib import Path

import pytest
from PIL import Image

from sunny_optimizer.chop_horizon import chop_horizon


PANEL_COLORS = [
    (255, 0, 0, 255),
    (0, 255, 0, 255),
    (0, 0, 255, 255),
    (255, 255, 0, 255),
    (255, 0, 255, 255),
    (0, 255, 255, 255),
    (128, 128, 128, 255),
    (255, 128, 0, 255),
]


def _panel_image(path: Path) -> None:
    img = Image.new("RGBA", (2048, 64), (0, 0, 0, 0))
    for index, color in enumerate(PANEL_COLORS):
        panel = Image.new("RGBA", (256, 64), color)
        img.paste(panel, (index * 256, 0))
    img.save(path)


def test_chop_horizon_creates_two_sheets(tmp_path: Path) -> None:
    src = tmp_path / "horizon.png"
    Image.new("RGBA", (2048, 64), (255, 0, 0, 255)).save(src)

    out1, out2 = chop_horizon(src, tmp_path)

    assert out1.exists()
    assert out2.exists()
    assert Image.open(out1).size == (256, 256)
    assert Image.open(out2).size == (256, 256)


def test_chop_horizon_can_start_with_selected_panel(tmp_path: Path) -> None:
    src = tmp_path / "horizon.png"
    _panel_image(src)

    out1, out2 = chop_horizon(src, tmp_path, start_panel=3)

    sheet1 = Image.open(out1)
    sheet2 = Image.open(out2)
    expected = PANEL_COLORS[2:] + PANEL_COLORS[:2]
    actual = [sheet1.getpixel((0, row * 64)) for row in range(4)] + [
        sheet2.getpixel((0, row * 64)) for row in range(4)
    ]
    assert actual == expected


@pytest.mark.parametrize("start_panel", [0, 9])
def test_chop_horizon_rejects_invalid_start_panel(tmp_path: Path, start_panel: int) -> None:
    src = tmp_path / "horizon.png"
    _panel_image(src)

    with pytest.raises(ValueError, match="Start panel must be between 1 and 8"):
        chop_horizon(src, tmp_path, start_panel=start_panel)
