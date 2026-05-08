from pathlib import Path

from texture_tools.main import _collect_folder_image_inputs


def test_collect_folder_inputs_prefers_png_over_bmp(tmp_path: Path) -> None:
    (tmp_path / "same.png").write_bytes(b"png")
    (tmp_path / "same.bmp").write_bytes(b"bmp")
    (tmp_path / "only_bmp.bmp").write_bytes(b"bmp")
    (tmp_path / "other.txt").write_text("x")

    selected = _collect_folder_image_inputs(tmp_path)
    names = sorted(p.name for p in selected)

    assert names == ["only_bmp.bmp", "same.png"]
