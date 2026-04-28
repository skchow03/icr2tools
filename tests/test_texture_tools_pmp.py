from __future__ import annotations

from pathlib import Path

from PIL import Image

from texture_tools.pmp import png_to_pmp


def test_png_to_pmp_writes_expected_header_and_runs(tmp_path: Path) -> None:
    image = Image.new("P", (4, 2))
    image.putdata([
        1,
        1,
        2,
        2,
        3,
        4,
        4,
        4,
    ])
    src = tmp_path / "sprite.png"
    dst = tmp_path / "sprite.pmp"
    image.save(src)

    png_to_pmp(src, dst, size_field=0x1234, palette_path=None)

    data = dst.read_bytes()
    assert data[:2] == bytes((4, 2))
    assert data[2:4] == bytes((0x34, 0x12))
    assert int.from_bytes(data[4:8], "little") == len(data) - 12
    assert data[8:12] == bytes((0x1E, 0x00, 0x00, 0x00))

    runs = data[12:]
    # Row 0: [1,1][2,2] and row 1: [3][4,4,4]
    assert runs == bytes(
        (
            0,
            0,
            2,
            1,
            0,
            2,
            4,
            2,
            1,
            0,
            1,
            3,
            1,
            1,
            4,
            4,
        )
    )


def test_png_to_pmp_rejects_large_images(tmp_path: Path) -> None:
    src = tmp_path / "too_wide.png"
    Image.new("P", (257, 1)).save(src)

    try:
        png_to_pmp(src, tmp_path / "out.pmp", size_field=0, palette_path=None)
    except ValueError as exc:
        assert "256x256" in str(exc)
    else:
        raise AssertionError("expected ValueError for oversized image")


def test_png_to_pmp_supports_256x256(tmp_path: Path) -> None:
    src = tmp_path / "max_size.png"
    dst = tmp_path / "max_size.pmp"
    Image.new("RGBA", (256, 256), color=(255, 0, 0, 255)).save(src)

    png_to_pmp(src, dst, size_field=0, palette_path=None)

    data = dst.read_bytes()
    assert data[0] == 0
    assert data[1] == 0


def test_png_to_pmp_skips_fully_transparent_pixels(tmp_path: Path) -> None:
    src = tmp_path / "alpha.png"
    dst = tmp_path / "alpha.pmp"
    image = Image.new("RGBA", (4, 1), color=(255, 0, 0, 255))
    pixels = image.load()
    pixels[1, 0] = (0, 255, 0, 0)
    image.save(src)

    png_to_pmp(src, dst, size_field=0, palette_path=None)

    runs = dst.read_bytes()[12:]
    assert len(runs) == 8
    assert runs[0:3] == bytes((0, 0, 1))
    assert runs[4:7] == bytes((0, 2, 4))


def test_png_to_pmp_writes_bbox_offsets_when_size_field_is_zero(tmp_path: Path) -> None:
    src = tmp_path / "offsets.png"
    dst = tmp_path / "offsets.pmp"
    image = Image.new("RGBA", (256, 256), color=(0, 0, 0, 0))
    pixels = image.load()
    pixels[10, 20] = (255, 0, 0, 255)
    pixels[12, 21] = (255, 0, 0, 255)
    image.save(src)

    png_to_pmp(src, dst, size_field=0, palette_path=None)

    data = dst.read_bytes()
    assert data[0] == 3  # bbox width
    assert data[1] == 2  # bbox height
    assert data[2] == 243  # 255 - rightmost_x (12)
    assert data[3] == 234  # 255 - bottommost_y (21)


def test_png_to_pmp_uses_given_palette(tmp_path: Path) -> None:
    src = tmp_path / "source.png"
    dst = tmp_path / "paletted.pmp"
    palette_path = tmp_path / "SUNNY.PCX"

    source = Image.new("RGBA", (1, 1), color=(255, 0, 0, 255))
    source.save(src)

    palette = Image.new("P", (1, 1))
    pal = [0] * (256 * 3)
    pal[3:6] = [255, 0, 0]
    palette.putpalette(pal)
    palette.save(palette_path)

    png_to_pmp(src, dst, size_field=0, palette_path=palette_path)

    runs = dst.read_bytes()[12:]
    assert runs == bytes((0, 0, 1, 1))
