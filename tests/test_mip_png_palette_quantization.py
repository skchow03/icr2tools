from pathlib import Path

from PIL import Image

from icr2_core.mip.mips import img_to_mip, load_palette, mip_to_img


def test_img_to_mip_quantizes_base_level_with_provided_palette(tmp_path: Path) -> None:
    src = Image.new("RGB", (4, 4), color=(250, 10, 10))

    palette_path = tmp_path / "SUNNY.PCX"
    pal_img = Image.new("P", (1, 1))
    pal = [0] * (256 * 3)
    # index 7 = bright red (closest match to source)
    pal[7 * 3 : 7 * 3 + 3] = [255, 0, 0]
    # index 8 = bright green (farther)
    pal[8 * 3 : 8 * 3 + 3] = [0, 255, 0]
    pal_img.putpalette(pal)
    pal_img.save(palette_path)

    out_path = tmp_path / "out.mip"
    img_to_mip(src, str(out_path), str(palette_path), mode="track")

    decoded = mip_to_img(str(out_path), load_palette(str(palette_path)))[0]
    indexes = list(decoded.getdata())

    assert set(indexes) == {7}
