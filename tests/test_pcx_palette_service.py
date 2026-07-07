import pytest

from sg_viewer.services.pcx_palette import read_pcx_256_palette


def test_read_pcx_256_palette_reads_trailing_palette(tmp_path) -> None:
    palette = bytes([value % 256 for value in range(768)])
    path = tmp_path / "SUNNY.PCX"
    path.write_bytes(b"header" + bytes([0x0C]) + palette)

    colors = read_pcx_256_palette(path)

    assert len(colors) == 256
    assert colors[0] == (0, 1, 2)
    assert colors[-1] == (253, 254, 255)


def test_read_pcx_256_palette_rejects_missing_marker(tmp_path) -> None:
    path = tmp_path / "bad.pcx"
    path.write_bytes(b"header" + bytes(769))

    with pytest.raises(ValueError, match="palette marker"):
        read_pcx_256_palette(path)
