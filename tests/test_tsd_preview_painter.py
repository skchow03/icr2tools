import math
from dataclasses import dataclass

import pytest

from sg_viewer.services.preview_painter import _point_on_section, _sample_tsd_detail_line
from sg_viewer.services.tsd_io import TrackSurfaceDetailLine


@dataclass(frozen=True)
class _Section:
    start: tuple[float, float]
    end: tuple[float, float]
    start_dlong: float
    length: float
    center: tuple[float, float] | None
    start_heading: tuple[float, float] | None


def _make_section(**overrides) -> _Section:
    base = dict(
        start=(0.0, 0.0),
        end=(10.0, 0.0),
        start_dlong=0.0,
        length=5000.0,
        center=None,
        start_heading=(1.0, 0.0),
    )
    base.update(overrides)
    return _Section(**base)


def test_tsd_detail_straight_uses_dlat_as_line_offset() -> None:
    section = _make_section()
    line = TrackSurfaceDetailLine(1, 500, 0, 500, 5000, 500)

    points = _sample_tsd_detail_line(line, [section])

    assert points[0] == (0.0, 1.0)
    assert points[-1] == (10.0, 1.0)


def test_tsd_detail_sampling_uses_one_foot_steps() -> None:
    section = _make_section()
    line = TrackSurfaceDetailLine(1, 500, 0, 0, 1500, 0)

    points = _sample_tsd_detail_line(line, [section])

    assert len(points) == 4


def test_point_on_section_curve_follows_arc_with_dlat_offset() -> None:
    curve = _make_section(
        start=(10.0, 0.0),
        end=(0.0, 10.0),
        length=(math.pi / 2.0) * 10.0 * 500.0,
        center=(0.0, 0.0),
        start_heading=(0.0, 1.0),
    )

    midpoint = _point_on_section(curve, fraction=0.5, dlat=1.0)

    expected = (9.0 / math.sqrt(2), 9.0 / math.sqrt(2))
    assert midpoint == pytest.approx(expected)
