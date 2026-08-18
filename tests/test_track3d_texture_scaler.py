from pathlib import Path

import pytest

from sg_viewer.io.track3d_texture_scaler import (
    scale_track3d_texture_coordinates,
    scale_track3d_texture_file,
)

TRACK3D = """HEADER\n
MATERIAL GROUP = 1, MIP = "GRASS",\n
  POLY [T] grass.c {\n
    [< 1, 2, 3 >, t= <346,20>],\n
    [< 4, 5, 6 >, t= <-3, 5>]\n
  },\n
MATERIAL GROUP = 0, MIP = "ASPHALT",\n
  POLY [T] asphalt.c {\n
    [< 1, 2, 3 >, t= <466, 210>]\n
  }\n
MATERIAL GROUP = 2, MIP = "grass.mip",\n
  POLY [T] more_grass.c {\n
    [< 1, 2, 3 >, T = < 7 , 9 >]\n
  }\n
"""


def test_scales_only_matching_materials_and_counts_them() -> None:
    result = scale_track3d_texture_coordinates(TRACK3D, "grass", 2)

    assert result.materials_altered == 2
    assert "t= <692,40>" in result.text
    assert "t= <-6, 10>" in result.text
    assert "t= <466, 210>" in result.text
    assert "T = < 14 , 18 >" in result.text


def test_fractional_factor_rounds_down_including_negative_values() -> None:
    result = scale_track3d_texture_coordinates(TRACK3D, "GRASS.MIP", 0.5)

    assert "t= <173,10>" in result.text
    assert "t= <-2, 2>" in result.text


@pytest.mark.parametrize(
    ("scale_u", "scale_v", "expected"),
    [(True, False, "t= <692,20>"), (False, True, "t= <346,40>")],
)
def test_can_scale_one_coordinate_axis_only(
    scale_u: bool, scale_v: bool, expected: str
) -> None:
    result = scale_track3d_texture_coordinates(
        TRACK3D, "grass", 2, scale_u=scale_u, scale_v=scale_v
    )

    assert expected in result.text


def test_supports_independent_u_and_v_factors() -> None:
    result = scale_track3d_texture_coordinates(
        TRACK3D, "grass", u_factor=3, v_factor=0.5
    )

    assert "t= <1038,10>" in result.text
    assert "t= <-9, 2>" in result.text


def test_rejects_when_no_coordinate_axis_is_selected() -> None:
    with pytest.raises(ValueError, match="At least one"):
        scale_track3d_texture_coordinates(
            TRACK3D, "grass", 2, scale_u=False, scale_v=False
        )


def test_no_matching_material_leaves_text_unchanged() -> None:
    result = scale_track3d_texture_coordinates(TRACK3D, "sand", 2)

    assert result.materials_altered == 0
    assert result.text == TRACK3D


@pytest.mark.parametrize("factor", [0, -1, float("inf"), float("nan")])
def test_rejects_invalid_factor(factor: float) -> None:
    with pytest.raises(ValueError):
        scale_track3d_texture_coordinates(TRACK3D, "grass", factor)


def test_file_operation_updates_in_place(tmp_path: Path) -> None:
    path = tmp_path / "track.3d"
    path.write_bytes(TRACK3D.encode("latin-1"))

    result = scale_track3d_texture_file(path, "asphalt", 3)

    assert result.materials_altered == 1
    assert "t= <1398, 630>" in path.read_text(encoding="latin-1")
