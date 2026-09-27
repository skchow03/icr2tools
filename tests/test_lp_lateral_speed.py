"""Regression tests for the LP Coriolis / lateral-velocity calculation."""
from types import SimpleNamespace

import pytest

from track_viewer.ai.lateral_speed import calculate_lp_lateral_speeds


def _record(dlong: float, dlat: float, speed: float = 100.0):
    return SimpleNamespace(dlong=dlong, dlat=dlat, speed_mph=speed)


def test_lateral_speed_is_forward_speed_times_lateral_slope() -> None:
    records = [_record(0, 0), _record(6000, 6000, 80.0)]

    result = calculate_lp_lateral_speeds(records)

    assert result == pytest.approx([
        (6000 / 6000) * 100.0 * (5280 / 9),
        (6000 / 6000) * 80.0 * (5280 / 9),
    ])


def test_constant_dlat_has_zero_lateral_velocity() -> None:
    records = [
        _record(0, 12000),
        _record(6000, 12000),
        _record(12000, 12000),
        _record(18000, 12000),
    ]

    assert calculate_lp_lateral_speeds(
        records, track_length=18000
    ) == pytest.approx([0.0] * 4)


def test_periodic_start_finish_uses_neighbor_across_seam() -> None:
    # Last record closes the path. The previous neighbor for record zero
    # is at track length minus 6000, not the terminal duplicate.
    records = [
        _record(0, 0),
        _record(6000, 12000),
        _record(12000, -12000),
        _record(18000, 0),
    ]
    result = calculate_lp_lateral_speeds(records, track_length=18000)
    factor = 100.0 * 5280 / 9

    assert result == pytest.approx([
        2 * factor,
        -1 * factor,
        -1 * factor,
        2 * factor,
    ])


def test_terminal_duplicate_uses_own_forward_speed() -> None:
    records = [
        _record(0, 0, 100),
        _record(6000, 12000, 100),
        _record(12000, -12000, 100),
        _record(18000, 0, 75),
    ]
    result = calculate_lp_lateral_speeds(records, track_length=18000)

    assert result[-1] == pytest.approx(result[0] * 0.75)


def test_unsorted_stations_raise_instead_of_writing_invalid_values() -> None:
    with pytest.raises(ValueError, match="strictly increasing"):
        calculate_lp_lateral_speeds([
            _record(0, 0), _record(6000, 1000), _record(6000, 2000)
        ])


def test_inconsistent_track_length_raises() -> None:
    records = [_record(0, 0), _record(1000, 10), _record(3000, 20)]

    with pytest.raises(ValueError, match="incompatible with track length"):
        calculate_lp_lateral_speeds(records, track_length=2000)
