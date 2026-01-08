"""AI line overlays for track preview."""
from __future__ import annotations

from typing import Callable, Iterable, Sequence

from PyQt5 import QtCore, QtGui

from track_viewer.rendering.primitives.mapping import Point2D, Transform, map_point

MPH_TO_FEET_PER_SECOND = 5280 / 3600
# One DLONG corresponds to 1/500 inch, or 1/6000 feet.
DLONG_TO_FEET = 1 / 6000
DEFAULT_DECIMATION_PIXELS = 6.0


def _decimation_distance(transform: Transform) -> float:
    scale, _ = transform
    return max(1.0, DEFAULT_DECIMATION_PIXELS / max(scale, 0.01))


def _decimate_mapped_points(
    points: Sequence[QtCore.QPointF], min_distance: float
) -> tuple[list[QtCore.QPointF], list[int]]:
    if len(points) < 2:
        return list(points), list(range(len(points)))
    min_distance_sq = min_distance * min_distance
    decimated = [points[0]]
    indices = [0]
    last = points[0]
    for index, point in enumerate(points[1:], start=1):
        dx = point.x() - last.x()
        dy = point.y() - last.y()
        if dx * dx + dy * dy >= min_distance_sq:
            decimated.append(point)
            indices.append(index)
            last = point
    if indices[-1] != len(points) - 1:
        decimated.append(points[-1])
        indices.append(len(points) - 1)
    return decimated, indices


def _segment_visible(
    start: QtCore.QPointF, end: QtCore.QPointF, viewport: QtCore.QRectF
) -> bool:
    min_x = min(start.x(), end.x())
    max_x = max(start.x(), end.x())
    min_y = min(start.y(), end.y())
    max_y = max(start.y(), end.y())
    segment_rect = QtCore.QRectF(min_x, min_y, max_x - min_x, max_y - min_y)
    return segment_rect.intersects(viewport)


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
    antialias: bool = True,
) -> None:
    painter.setRenderHint(QtGui.QPainter.Antialiasing, antialias)
    window_size = max(1, acceleration_window)
    pen_width = max(1, line_width)
    viewport = QtCore.QRectF(painter.viewport())
    decimation_distance = _decimation_distance(transform)
    for name in sorted(set(visible_lp_files)):
        points = get_points(name)
        if not points:
            continue
        mapped = [map_point(px, py, transform, viewport_height) for px, py in points]
        mapped, kept_indices = _decimate_mapped_points(mapped, decimation_distance)
        if len(mapped) < 2:
            continue

        if gradient != "none" and get_records is not None:
            records = get_records(name)
            speeds = [getattr(record, "speed_mph", None) for record in records]
            if len(mapped) >= 2 and len(speeds) >= 2:
                try:
                    min_speed = min(speed for speed in speeds if speed is not None)
                    max_speed = max(speed for speed in speeds if speed is not None)
                except ValueError:
                    min_speed = max_speed = None

                if gradient == "speed":
                    segment_speeds = [
                        speeds[index] if index < len(speeds) else None
                        for index in kept_indices[:-1]
                    ]

                    def _speed_to_color(speed_value: float | None) -> QtGui.QColor:
                        if (
                            speed_value is None
                            or min_speed is None
                            or max_speed is None
                            or max_speed == min_speed
                        ):
                            return QtGui.QColor(lp_color(name))
                        ratio = (speed_value - min_speed) / (max_speed - min_speed)
                        ratio = max(0.0, min(1.0, ratio))
                        red = int(round(255 * (1 - ratio)))
                        green = int(round(255 * ratio))
                        return QtGui.QColor(red, green, 0)

                    for start, end, speed in zip(
                        mapped[:-1], mapped[1:], segment_speeds
                    ):
                        if not _segment_visible(start, end, viewport):
                            continue
                        pen = QtGui.QPen(_speed_to_color(speed), pen_width)
                        painter.setPen(pen)
                        painter.drawLine(QtCore.QLineF(start, end))
                    continue

                if gradient == "acceleration":
                    raw_accelerations: list[float | None] = []
                    for record_a, record_b in zip(records[:-1], records[1:]):
                        raw_accelerations.append(
                            compute_segment_acceleration(record_a, record_b)
                        )
                    segment_accelerations = [
                        raw_accelerations[index]
                        if index < len(raw_accelerations)
                        else None
                        for index in kept_indices[:-1]
                    ]

                    accelerations: list[float | None] = []
                    recent: list[float] = []
                    for accel in segment_accelerations:
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
                            return QtGui.QColor(lp_color(name))
                        if accel_value >= 0:
                            if max_accel is None or max_accel == 0:
                                return QtGui.QColor(lp_color(name))
                            ratio = max(0.0, min(1.0, accel_value / max_accel))
                            red = int(round(255 * (1 - ratio)))
                            return QtGui.QColor(red, 255, 0)
                        if max_decel is None or max_decel == 0:
                            return QtGui.QColor(lp_color(name))
                        ratio = max(0.0, min(1.0, abs(accel_value) / abs(max_decel)))
                        green = int(round(255 * (1 - ratio)))
                        return QtGui.QColor(255, green, 0)

                    for start, end, accel in zip(mapped[:-1], mapped[1:], accelerations):
                        if not _segment_visible(start, end, viewport):
                            continue
                        pen = QtGui.QPen(_accel_to_color(accel), pen_width)
                        painter.setPen(pen)
                        painter.drawLine(QtCore.QLineF(start, end))
                    continue

        color = QtGui.QColor(lp_color(name))
        painter.setPen(QtGui.QPen(color, pen_width))
        for start, end in zip(mapped[:-1], mapped[1:]):
            if not _segment_visible(start, end, viewport):
                continue
            painter.drawLine(QtCore.QLineF(start, end))


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
