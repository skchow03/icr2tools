"""AI line overlay rendering helpers.

This module is part of the rendering layer. It builds in-memory draw caches
and issues QPainter draw calls without mutating model state or performing IO.
Inputs are world-space coordinates that are mapped into screen space.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Callable, Iterable, Sequence

from PyQt5 import QtCore, QtGui

from track_viewer.common.preview_constants import LP_COLORS, LP_FILE_NAMES
from track_viewer.model.track_preview_model import TrackPreviewModel
from track_viewer.model.view_state import TrackPreviewViewState
from track_viewer.rendering.base.transform import surface_transform
from track_viewer.rendering.primitives.mapping import Point2D, Transform, map_point

MPH_TO_FEET_PER_SECOND = 5280 / 3600
# One DLONG corresponds to 1/500 inch, or 1/6000 feet.
DLONG_TO_FEET = 1 / 6000


@dataclass(frozen=True)
class AiLineCache:
    """Cached polyline and per-segment colors for an AI line."""
    polygon: QtGui.QPolygonF
    segment_colors: list[QtGui.QColor] | None
    base_color: QtGui.QColor


def compute_segment_acceleration(
    record_a: object, record_b: object, *, track_length: float | None = None
) -> float | None:
    """Estimate acceleration between two LP records in ft/s^2.

    The calculation uses the change in speed between consecutive AI line
    segments and converts the DLONG spacing into feet. Time is derived from
    the segment length and average speed to express the result in ft/s^2.
    """

    dlong_a = getattr(record_a, "dlong", None)
    dlong_b = getattr(record_b, "dlong", None)
    speed_a_mph = getattr(record_a, "speed_mph", None)
    speed_b_mph = getattr(record_b, "speed_mph", None)
    if None in {dlong_a, dlong_b, speed_a_mph, speed_b_mph}:
        return None

    delta_dlong = float(dlong_b) - float(dlong_a)
    if track_length is not None and delta_dlong < 0:
        delta_dlong += float(track_length)
    if delta_dlong <= 0:
        return None

    distance_feet = delta_dlong * DLONG_TO_FEET
    speed_a = float(speed_a_mph) * MPH_TO_FEET_PER_SECOND
    speed_b = float(speed_b_mph) * MPH_TO_FEET_PER_SECOND
    average_speed = (speed_a + speed_b) / 2
    if average_speed <= 0:
        return None

    time_seconds = distance_feet / average_speed
    if time_seconds <= 0:
        return None

    delta_speed = speed_b - speed_a
    return delta_speed / time_seconds


def _build_gradient_segment_colors(
    records: Sequence[object],
    base_color: QtGui.QColor,
    *,
    gradient: str,
    acceleration_window: int,
) -> list[QtGui.QColor] | None:
    """Return per-segment colors based on speed or acceleration gradients."""
    if gradient == "none" or len(records) < 2:
        return None

    if gradient == "speed":
        speeds = [getattr(record, "speed_mph", None) for record in records]
        try:
            min_speed = min(speed for speed in speeds if speed is not None)
            max_speed = max(speed for speed in speeds if speed is not None)
        except ValueError:
            min_speed = max_speed = None

        def _speed_to_color(speed_value: float | None) -> QtGui.QColor:
            if (
                speed_value is None
                or min_speed is None
                or max_speed is None
                or max_speed == min_speed
            ):
                return base_color
            ratio = (speed_value - min_speed) / (max_speed - min_speed)
            ratio = max(0.0, min(1.0, ratio))
            red = int(round(255 * (1 - ratio)))
            green = int(round(255 * ratio))
            return QtGui.QColor(red, green, 0)

        return [_speed_to_color(speed) for speed in speeds[:-1]]

    if gradient == "acceleration":
        raw_accelerations: list[float | None] = []
        for record_a, record_b in zip(records[:-1], records[1:]):
            raw_accelerations.append(compute_segment_acceleration(record_a, record_b))

        accelerations: list[float | None] = []
        recent: list[float] = []
        window_size = max(1, acceleration_window)
        for accel in raw_accelerations:
            if accel is not None:
                recent.append(accel)
            if len(recent) > window_size:
                recent.pop(0)
            if recent:
                accelerations.append(sum(recent) / len(recent))
            else:
                accelerations.append(None)

        max_accel = max(
            (a for a in accelerations if a is not None and a > 0),
            default=None,
        )
        max_decel = min(
            (a for a in accelerations if a is not None and a < 0),
            default=None,
        )

        def _accel_to_color(accel_value: float | None) -> QtGui.QColor:
            if accel_value is None:
                return base_color
            if accel_value >= 0:
                if max_accel is None or max_accel == 0:
                    return base_color
                ratio = max(0.0, min(1.0, accel_value / max_accel))
                red = int(round(255 * (1 - ratio)))
                return QtGui.QColor(red, 255, 0)
            if max_decel is None or max_decel == 0:
                return base_color
            ratio = max(0.0, min(1.0, abs(accel_value) / abs(max_decel)))
            green = int(round(255 * (1 - ratio)))
            return QtGui.QColor(255, green, 0)

        return [_accel_to_color(accel) for accel in accelerations]

    return None


def build_ai_line_cache(
    records: Sequence[object],
    *,
    color: str,
    gradient: str = "none",
    acceleration_window: int = 3,
) -> AiLineCache | None:
    """Create a cached polyline and optional per-segment colors."""
    if not records:
        return None
    polygon = QtGui.QPolygonF(
        [QtCore.QPointF(record.x, record.y) for record in records]
    )
    base_color = QtGui.QColor(color)
    segment_colors = _build_gradient_segment_colors(
        records,
        base_color,
        gradient=gradient,
        acceleration_window=acceleration_window,
    )
    return AiLineCache(
        polygon=polygon,
        segment_colors=segment_colors,
        base_color=base_color,
    )


def draw_ai_lines(
    painter: QtGui.QPainter,
    visible_lp_files: Iterable[str],
    get_points: Callable[[str], Sequence[Point2D]],
    transform: Transform,
    viewport_height: int,
    lp_color: Callable[[str], str],
    *,
    gradient: str = "none",
    get_records: Callable[[str], Sequence[object]] | None = None,
    line_width: int = 2,
    acceleration_window: int = 3,
) -> None:
    """Draw AI lines in world space, mapped into screen coordinates."""
    painter.setRenderHint(QtGui.QPainter.Antialiasing, True)
    window_size = max(1, acceleration_window)
    pen_width = max(1, line_width)
    for name in sorted(set(visible_lp_files)):
        points = get_points(name)
        if not points:
            continue
        mapped = [map_point(px, py, transform, viewport_height) for px, py in points]
        if gradient != "none" and get_records is not None:
            records = get_records(name)
            segment_colors = _build_gradient_segment_colors(
                records,
                QtGui.QColor(lp_color(name)),
                gradient=gradient,
                acceleration_window=window_size,
            )
            if segment_colors and len(mapped) >= 2:
                for start, end, color in zip(mapped[:-1], mapped[1:], segment_colors):
                    pen = QtGui.QPen(color, pen_width)
                    painter.setPen(pen)
                    painter.drawLine(QtCore.QLineF(start, end))
                continue

        color = QtGui.QColor(lp_color(name))
        painter.setPen(QtGui.QPen(color, pen_width))
        painter.drawPolyline(QtGui.QPolygonF(mapped))


def draw_lp_segment(
    painter: QtGui.QPainter,
    start: Point2D,
    end: Point2D,
    transform: Transform,
    viewport_height: int,
    *,
    color: QtGui.QColor | str = "#ffeb3b",
    width: int = 4,
) -> None:
    """Draw a highlighted LP segment between two world points."""
    painter.save()
    painter.setRenderHint(QtGui.QPainter.Antialiasing, True)
    pen = QtGui.QPen(QtGui.QColor(color), width)
    pen.setCapStyle(QtCore.Qt.RoundCap)
    painter.setPen(pen)
    painter.drawLine(
        QtCore.QLineF(
            map_point(start[0], start[1], transform, viewport_height),
            map_point(end[0], end[1], transform, viewport_height),
        )
    )
    painter.restore()


class AiLineOverlay:
    """Render AI line overlays with cached polylines."""

    def __init__(self) -> None:
        self._ai_line_cache: dict[str, AiLineCache] = {}
        self._ai_line_cache_key: tuple[
            object | None, int, str, int, int, tuple[tuple[str, str], ...]
        ] | None = None
        self._replay_line_cache = QtGui.QPolygonF()
        self._replay_cache_key: tuple[object | None, int] | None = None

    def invalidate_cache(self) -> None:
        self._ai_line_cache = {}
        self._ai_line_cache_key = None
        self._replay_line_cache = QtGui.QPolygonF()
        self._replay_cache_key = None

    def draw(
        self,
        painter: QtGui.QPainter,
        model: TrackPreviewModel,
        state: TrackPreviewViewState,
        transform: Transform,
        viewport_height: int,
    ) -> None:
        self._draw_ai_lines(painter, model, state, transform, viewport_height)
        self._draw_replay_line(painter, model, state, transform, viewport_height)

    def _draw_ai_lines(
        self,
        painter: QtGui.QPainter,
        model: TrackPreviewModel,
        state: TrackPreviewViewState,
        transform: Transform,
        viewport_height: int,
    ) -> None:
        if not model.visible_lp_files:
            return
        self._ensure_ai_line_cache(model, state)
        pen_width = max(1, state.ai_line_width)
        painter.save()
        painter.setRenderHint(QtGui.QPainter.Antialiasing, True)
        painter.setTransform(surface_transform(transform, viewport_height))
        for name in sorted(set(model.visible_lp_files)):
            cache = self._ai_line_cache.get(name)
            if cache is None or cache.polygon.isEmpty():
                continue
            if cache.segment_colors:
                points = cache.polygon
                for index, color in enumerate(cache.segment_colors):
                    pen = QtGui.QPen(color, pen_width)
                    pen.setCosmetic(True)
                    painter.setPen(pen)
                    painter.drawLine(QtCore.QLineF(points[index], points[index + 1]))
                continue
            pen = QtGui.QPen(cache.base_color, pen_width)
            pen.setCosmetic(True)
            painter.setPen(pen)
            painter.drawPolyline(cache.polygon)
        painter.restore()

    def _draw_replay_line(
        self,
        painter: QtGui.QPainter,
        model: TrackPreviewModel,
        state: TrackPreviewViewState,
        transform: Transform,
        viewport_height: int,
    ) -> None:
        if not state.show_replay_line or not model.replay_lap_points:
            return
        self._ensure_replay_cache(model)
        if self._replay_line_cache.isEmpty():
            return
        painter.save()
        painter.setRenderHint(QtGui.QPainter.Antialiasing, True)
        pen = QtGui.QPen(QtGui.QColor("#00ffff"), 2)
        pen.setCosmetic(True)
        painter.setPen(pen)
        painter.setBrush(QtCore.Qt.NoBrush)
        painter.setTransform(surface_transform(transform, viewport_height))
        painter.drawPolyline(self._replay_line_cache)
        painter.restore()

    def _ensure_ai_line_cache(
        self, model: TrackPreviewModel, state: TrackPreviewViewState
    ) -> None:
        key = (
            model.track_path,
            model.ai_line_cache_generation,
            state.ai_color_mode,
            state.ai_acceleration_window,
            state.ai_line_width,
            tuple(sorted(state.lp_colors.items())),
        )
        if key == self._ai_line_cache_key:
            return
        self._ai_line_cache = {}
        for lp_name in sorted(set(model.visible_lp_files)):
            records = model.ai_line_records(lp_name)
            cache = build_ai_line_cache(
                records,
                color=self._lp_color(state, lp_name),
                gradient=state.ai_color_mode,
                acceleration_window=state.ai_acceleration_window,
            )
            if cache is not None:
                self._ai_line_cache[lp_name] = cache
        self._ai_line_cache_key = key

    def _ensure_replay_cache(self, model: TrackPreviewModel) -> None:
        key = (model.track_path, model.replay_line_generation)
        if key == self._replay_cache_key:
            return
        self._replay_line_cache = QtGui.QPolygonF(
            [QtCore.QPointF(point.x, point.y) for point in model.replay_lap_points]
        )
        self._replay_cache_key = key

    @staticmethod
    def _lp_color(state: TrackPreviewViewState, name: str) -> str:
        override = state.lp_colors.get(name)
        if override:
            return override
        try:
            index = LP_FILE_NAMES.index(name)
        except ValueError:
            return "#e53935"
        return LP_COLORS[index % len(LP_COLORS)]
