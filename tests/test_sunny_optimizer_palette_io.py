from pathlib import Path

import numpy as np

from sunny_optimizer.palette import save_palette


def test_save_palette_writes_320x200_white_image_data(tmp_path: Path) -> None:
    palette = np.zeros((256, 3), dtype=np.uint8)
    out_path = tmp_path / "sunny.pcx"

    save_palette(out_path, palette)

    data = out_path.read_bytes()

    x_max = data[8] | (data[9] << 8)
    y_max = data[10] | (data[11] << 8)
    bytes_per_line = data[66] | (data[67] << 8)

    assert x_max == 319
    assert y_max == 199
    assert bytes_per_line == 320

    image_data = data[128:-769]
    assert len(image_data) == 2400
    expected_scanline = bytes([0xFF, 0xFF]) * 5 + bytes([0xC5, 0xFF])
    assert image_data == expected_scanline * 200
