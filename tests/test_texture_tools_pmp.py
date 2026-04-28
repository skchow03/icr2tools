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

    png_to_pmp(src, dst, size_field=0x1234)

    data = dst.read_bytes()
    assert data[:2] == bytes((2, 4))
    assert data[2:4] == bytes((0x34, 0x12))
    assert int.from_bytes(data[4:8], "little") == len(data) - 12
    assert data[8:12] == bytes((0x1E, 0x00, 0x00, 0x00))

    runs = data[12:]
    # Row 0: [1,1][2,2] and row 1: [3][4,4,4]
    assert runs == bytes(
        (
            0,
            0,
            1,
            1,
            0,
            2,
            3,
            2,
            1,
            0,
            0,
            3,
            1,
            1,
            3,
            4,
        )
    )


def test_png_to_pmp_rejects_large_images(tmp_path: Path) -> None:
    src = tmp_path / "too_wide.png"
    Image.new("P", (256, 1)).save(src)

    try:
        png_to_pmp(src, tmp_path / "out.pmp", size_field=0)
    except ValueError as exc:
        assert "255x255" in str(exc)
    else:
        raise AssertionError("expected ValueError for oversized image")
