"""Tests for user-visible LP lap time formatting."""

import pytest

from track_viewer.ai.lap_time_format import format_lap_time


@pytest.mark.parametrize(
    ("seconds", "expected"),
    [
        (0, "0:00.000"),
        (9.2, "0:09.200"),
        (59.9996, "1:00.000"),
        (60.0, "1:00.000"),
        (78.027, "1:18.027"),
        (80.473, "1:20.473"),
        (125.09, "2:05.090"),
        (600.0, "10:00.000"),
    ],
)
def test_format_lap_time(seconds, expected):
    assert format_lap_time(seconds) == expected
