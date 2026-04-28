from __future__ import annotations

from pathlib import Path

from PIL import Image

from texture_tools.pmp import png_to_pmp
from texture_tools.pmp_to_png import convert_pmp_to_png


def test_pmp_to_png_round_trip_with_palette(tmp_path: Path) -> None:
    src_png = tmp_path / "source.png"
    pmp_path = tmp_path / "sprite.pmp"
    out_png = tmp_path / "sprite.png"
    palette_path = tmp_path / "SUNNY.PCX"

    source = Image.new("RGBA", (2, 1))
    source.putdata([(255, 0, 0, 255), (0, 255, 0, 255)])
    source.save(src_png)

    palette = Image.new("P", (1, 1))
    pal = [0] * (256 * 3)
    pal[3:6] = [255, 0, 0]
    pal[6:9] = [0, 255, 0]
    palette.putpalette(pal)
    palette.save(palette_path)

    png_to_pmp(src_png, pmp_path, size_field=0, palette_path=palette_path)
    convert_pmp_to_png(str(pmp_path), str(out_png), str(palette_path), crop=False)

    converted = Image.open(out_png).convert("RGBA")
    assert converted.size == (2, 1)
    assert list(converted.getdata()) == [(255, 0, 0, 255), (0, 255, 0, 255)]

