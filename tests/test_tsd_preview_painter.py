import math
from dataclasses import dataclass

import pytest

from sg_viewer.services.preview_painter import (
    _point_on_section,
    _sample_tsd_detail_line,
    _tsd_width_to_pixels,
    split_wrapped_segment,
)
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
    line = TrackSurfaceDetailLine(1, 500, 0, 1, 5000, 1)

    points = _sample_tsd_detail_line(line, [section], pixels_per_world_unit=1.0)

    assert points[0] == (0.0, 1.0)
    assert points[-1] == (10.0, 1.0)


def test_tsd_detail_sampling_uses_one_foot_steps() -> None:
    section = _make_section()
    line = TrackSurfaceDetailLine(1, 500, 0, 0, 18000, 0)

    points = _sample_tsd_detail_line(line, [section], pixels_per_world_unit=1.0)

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


def test_tsd_width_uses_world_500ths_scale() -> None:
    # TSD widths are already in 500ths world units and should not be rescaled by inch/foot conversion.
    assert _tsd_width_to_pixels(500, pixels_per_world_unit=2.0) == pytest.approx(1000.0)


def test_tsd_width_has_minimum_visible_pixel() -> None:
    assert _tsd_width_to_pixels(1, pixels_per_world_unit=0.1) == pytest.approx(1.0)


def test_tsd_detail_wraps_once_when_end_is_before_start() -> None:
    section = _make_section(length=10000.0)
    line = TrackSurfaceDetailLine(1, 500, 9000, 0, 1000, 0)

    points = _sample_tsd_detail_line(line, [section], pixels_per_world_unit=1.0)

    assert points[0] == (9.0, 0.0)
    assert points[-1] == (1.0, 0.0)
    assert len(points) == 3


def test_tsd_detail_zero_span_does_not_draw_full_loop() -> None:
    section = _make_section(length=10000.0)
    line = TrackSurfaceDetailLine(1, 500, 2500, 0, 2500, 0)

    points = _sample_tsd_detail_line(line, [section], pixels_per_world_unit=1.0)

    assert points == []


def test_split_wrapped_segment_splits_closed_loop_crossing() -> None:
    segments = split_wrapped_segment(
        x1=9800.0,
        y1=10.0,
        x2=200.0,
        y2=20.0,
        track_length=10000.0,
        is_closed_loop=True,
    )

    assert segments == (
        (9800.0, 10.0, 10000.0, 10.0),
        (0.0, 20.0, 200.0, 20.0),
    )


def test_tsd_segment_bbox_cached_across_paints(monkeypatch, qapp) -> None:
    from PyQt5 import QtGui

    from sg_viewer.services import preview_painter

    preview_painter._GLOBAL_TSD_GEOMETRY_CACHE.clear()
    line = TrackSurfaceDetailLine(1, 500, 0, 0, 5000, 0)
    section = _make_section()
    sections = [section]
    estimate_calls = 0

    def _fake_estimate(**_kwargs):
        nonlocal estimate_calls
        estimate_calls += 1
        return (0.0, 0.0, 10.0, 10.0)

    monkeypatch.setattr(preview_painter, "_estimate_tsd_segment_world_bbox", _fake_estimate)
    monkeypatch.setattr(
        preview_painter,
        "_sample_tsd_detail_segment",
        lambda **_kwargs: [(0.0, 0.0), (1.0, 1.0)],
    )

    for _ in range(2):
        image = QtGui.QImage(80, 80, QtGui.QImage.Format_ARGB32)
        image.fill(0)
        painter = QtGui.QPainter(image)
        preview_painter._draw_tsd_lines(
            painter,
            (line,),
            (),
            sections,
            (1.0, (0.0, 0.0)),
            widget_height=80,
            section_geometry_version=7,
            tsd_lines_version=11,
        )
        painter.end()

    assert estimate_calls == 1


def test_tsd_segment_bbox_culling_still_skips_sampling(monkeypatch, qapp) -> None:
    from PyQt5 import QtGui

    from sg_viewer.services import preview_painter

    preview_painter._GLOBAL_TSD_GEOMETRY_CACHE.clear()
    line = TrackSurfaceDetailLine(1, 500, 0, 0, 5000, 0)
    section = _make_section()
    sections = [section]
    estimate_calls = 0
    sample_calls = 0

    def _fake_estimate(**_kwargs):
        nonlocal estimate_calls
        estimate_calls += 1
        return (1000.0, 1000.0, 1010.0, 1010.0)

    def _count_sample(**_kwargs):
        nonlocal sample_calls
        sample_calls += 1
        return [(0.0, 0.0), (1.0, 1.0)]

    monkeypatch.setattr(preview_painter, "_estimate_tsd_segment_world_bbox", _fake_estimate)
    monkeypatch.setattr(preview_painter, "_sample_tsd_detail_segment", _count_sample)

    for _ in range(2):
        image = QtGui.QImage(80, 80, QtGui.QImage.Format_ARGB32)
        image.fill(0)
        painter = QtGui.QPainter(image)
        preview_painter._draw_tsd_lines(
            painter,
            (line,),
            (),
            sections,
            (1.0, (0.0, 0.0)),
            widget_height=80,
            section_geometry_version=7,
            tsd_lines_version=11,
        )
        painter.end()

    assert estimate_calls == 1
    assert sample_calls == 0
