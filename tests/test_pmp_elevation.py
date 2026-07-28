from __future__ import annotations

import math

import pytest

from texture_tools.pmp import (
    calculate_pmp_feet_per_pixel,
    calculate_pmp_ground_adjustment,
    parse_pmp_header,
)


def test_parse_pmp_header_uses_signed_origins_and_half_open_bounds() -> None:
    data = bytes((40, 25, 246, 20, 0, 0, 0, 0, 0, 0, 0, 0))

    assert parse_pmp_header(data) == {
        "bbox_width": 40,
        "bbox_height": 25,
        "bbox_left": 10,
        "bbox_top": -20,
        "bbox_right": 50,
        "bbox_bottom": 5,
    }


def test_parse_pmp_header_treats_zero_dimension_as_256_with_runs() -> None:
    data = bytes((0, 0, 0, 0, 4, 0, 0, 0, 0, 0, 0, 0)) + bytes(4)
    header = parse_pmp_header(data)
    assert (header["bbox_width"], header["bbox_height"]) == (256, 256)


def test_ground_adjustment_uses_half_diagonal_scale_and_can_be_negative() -> None:
    scale = calculate_pmp_feet_per_pixel(30, 40, 10.0)
    assert scale == pytest.approx(0.4)
    assert calculate_pmp_ground_adjustment(30, 40, 60, 10.0) == pytest.approx(
        -28 * 0.4
    )


@pytest.mark.parametrize("width,height", [(0, 10), (10, 0), (-1, 10)])
def test_feet_per_pixel_rejects_nonpositive_dimensions(width: int, height: int) -> None:
    with pytest.raises(ValueError, match="dimensions must be positive"):
        calculate_pmp_feet_per_pixel(width, height, math.pi)
