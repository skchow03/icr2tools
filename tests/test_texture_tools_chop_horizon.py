from __future__ import annotations

from pathlib import Path

from PIL import Image

from sunny_optimizer.chop_horizon import chop_horizon


def test_chop_horizon_creates_two_sheets(tmp_path: Path) -> None:
    src = tmp_path / "horizon.png"
    Image.new("RGBA", (2048, 64), (255, 0, 0, 255)).save(src)

    out1, out2 = chop_horizon(src, tmp_path)

    assert out1.exists()
    assert out2.exists()
    assert Image.open(out1).size == (256, 256)
    assert Image.open(out2).size == (256, 256)
