"""Rendering helpers for the 2-color track map preview."""

from __future__ import annotations

from dataclasses import dataclass
import math

from PyQt5 import QtCore, QtGui


@dataclass(frozen=True)
class TrackMapLayout:
    mapped: list[QtCore.QPointF]
    scale: float
    min_x: float
    max_y: float


def build_trk_map_image(
    centerline: list[tuple[float, float]],
    width: int = 183,
    height: int = 86,
    margin: int = 6,
    scale: float | None = None,
    angle_deg: float = 0.0,
) -> QtGui.QImage:
    """Build the 2-color track map preview image."""
    track_pen_width = 3
    layout_margin = margin + math.ceil(track_pen_width / 2)
    if scale is None:
        scale = compute_fit_scale(
            centerline, width, height, layout_margin, angle_deg
        )
    layout = _layout_with_transform(
        centerline, width, height, layout_margin, scale, angle_deg
    )

    image = QtGui.QImage(width, height, QtGui.QImage.Format_ARGB32)
    image.fill(QtCore.Qt.black)

    if not layout.mapped:
        return image

    painter = QtGui.QPainter(image)
    painter.setRenderHint(QtGui.QPainter.Antialiasing, False)
    painter.setRenderHint(QtGui.QPainter.TextAntialiasing, False)
    track_pen = QtGui.QPen(QtCore.Qt.white, track_pen_width)
    track_pen.setCapStyle(QtCore.Qt.SquareCap)
    track_pen.setJoinStyle(QtCore.Qt.MiterJoin)
    painter.setPen(track_pen)
    painter.setBrush(QtCore.Qt.NoBrush)

    path = QtGui.QPainterPath()
    path.moveTo(layout.mapped[0])
    for point in layout.mapped[1:]:
        path.lineTo(point)
    painter.drawPath(path)

    start_finish = _draw_start_finish_marker(painter, layout.mapped)
    _draw_north_marker(
        painter,
        layout.mapped,
        start_finish,
        width,
        height,
        layout_margin,
        angle_deg,
    )

    painter.end()
    return image


def compute_fit_scale(
    centerline: list[tuple[float, float]],
    width: int,
    height: int,
    margin: int,
    angle_deg: float = 0.0,
) -> float:
    points = [QtCore.QPointF(x, y) for x, y in centerline]
    if not points:
        return 1.0

    center = _centroid(points)
    rotated = _rotate_points(points, center, math.radians(angle_deg))
    min_x, max_x, min_y, max_y = _bounds(rotated)
    span_x = max(max_x - min_x, 1e-6)
    span_y = max(max_y - min_y, 1e-6)
    return min(
        (width - 2 * margin) / span_x,
        (height - 2 * margin) / span_y,
    )


def _layout_with_transform(
    centerline: list[tuple[float, float]],
    width: int,
    height: int,
    margin: int,
    scale: float,
    angle_deg: float,
) -> TrackMapLayout:
    points = [QtCore.QPointF(x, y) for x, y in centerline]
    if not points:
        return TrackMapLayout([], scale, 0.0, 0.0)

    center = _centroid(points)
    rotated = _rotate_points(points, center, math.radians(angle_deg))
    min_x, max_x, min_y, max_y = _bounds(rotated)
    mapped = _map_points(rotated, min_x, max_y, scale, margin)
    return TrackMapLayout(mapped, scale, min_x, max_y)


def _centroid(points: list[QtCore.QPointF]) -> QtCore.QPointF:
    sum_x = sum(point.x() for point in points)
    sum_y = sum(point.y() for point in points)
    count = max(len(points), 1)
    return QtCore.QPointF(sum_x / count, sum_y / count)


def _rotate_points(
    points: list[QtCore.QPointF], center: QtCore.QPointF, angle: float
) -> list[QtCore.QPointF]:
    cos_a = math.cos(angle)
    sin_a = math.sin(angle)
    rotated = []
    for point in points:
        dx = point.x() - center.x()
        dy = point.y() - center.y()
        x = dx * cos_a - dy * sin_a + center.x()
        y = dx * sin_a + dy * cos_a + center.y()
        rotated.append(QtCore.QPointF(x, y))
    return rotated


def _bounds(points: list[QtCore.QPointF]) -> tuple[float, float, float, float]:
    xs = [point.x() for point in points]
    ys = [point.y() for point in points]
    return min(xs), max(xs), min(ys), max(ys)


def _map_points(
    points: list[QtCore.QPointF],
    min_x: float,
    max_y: float,
    scale: float,
    margin: int,
) -> list[QtCore.QPointF]:
    mapped = []
    for point in points:
        x = margin + (point.x() - min_x) * scale
        y = margin + (max_y - point.y()) * scale
        mapped.append(QtCore.QPointF(x, y))
    return mapped


def _draw_start_finish_marker(
    painter: QtGui.QPainter, mapped: list[QtCore.QPointF]
) -> QtGui.QPolygonF | None:
    if len(mapped) < 2:
        return None
    start = mapped[0]
    next_point = mapped[1]
    direction = next_point - start
    length = math.hypot(direction.x(), direction.y())
    if length <= 0:
        return None
    direction /= length
    perpendicular = QtCore.QPointF(-direction.y(), direction.x())

    perpendicular_length = 8.0
    along_length = 10.0
    arrow_length = 7.0
    arrow_width = 6.0

    best_arrow = None
    best_clearance = None
    for sign in (1.0, -1.0):
        perp = perpendicular * sign
        kink = start + perp * perpendicular_length
        arrow_tip = kink + direction * along_length
        base_center = arrow_tip - direction * arrow_length
        left = base_center + perp * (arrow_width / 2)
        right = base_center - perp * (arrow_width / 2)
        arrow = QtGui.QPolygonF([arrow_tip, left, right])
        clearance = _polygon_clearance(arrow, mapped)
        if best_clearance is None or clearance > best_clearance:
            best_clearance = clearance
            best_arrow = (kink, arrow_tip, arrow)

    if best_arrow is None:
        return None

    kink, arrow_tip, arrow = best_arrow
    marker_pen = QtGui.QPen(QtCore.Qt.white, 2)
    marker_pen.setCapStyle(QtCore.Qt.SquareCap)
    marker_pen.setJoinStyle(QtCore.Qt.MiterJoin)
    painter.setPen(marker_pen)
    painter.setBrush(QtCore.Qt.NoBrush)
    painter.drawLine(start, kink)
    painter.drawLine(kink, arrow_tip)

    painter.setBrush(QtCore.Qt.white)
    painter.setPen(QtCore.Qt.NoPen)
    painter.drawPolygon(arrow)
    return arrow


def _draw_north_marker(
    painter: QtGui.QPainter,
    mapped: list[QtCore.QPointF],
    arrow_polygon: QtGui.QPolygonF | None,
    width: int,
    height: int,
    margin: int,
    angle_deg: float,
) -> None:
    font = QtGui.QFont()
    font.setPixelSize(8)
    painter.setFont(font)
    metrics = QtGui.QFontMetrics(font)
    text = "N"
    text_width = metrics.horizontalAdvance(text)
    text_height = metrics.height()
    arrow_height = 11
    arrow_width = max(8, text_width)
    gap = 2
    total_width = arrow_width
    total_height = arrow_height + gap + text_height

    candidates = []
    cols = 5
    rows = 3
    for row in range(rows):
        for col in range(cols):
            x = margin + col * (width - 2 * margin - total_width) / max(cols - 1, 1)
            y = margin + row * (height - 2 * margin - total_height) / max(
                rows - 1, 1
            )
            candidates.append(QtCore.QPointF(x, y))

    best = QtCore.QPointF(margin, margin)
    best_score = None
    for candidate in candidates:
        center = QtCore.QPointF(
            candidate.x() + total_width / 2, candidate.y() + total_height / 2
        )
        min_distance = _min_distance(center, mapped)
        arrow_distance = _polygon_distance(arrow_polygon, center)
        if arrow_distance is not None:
            min_distance = min(min_distance, arrow_distance)
        score = min_distance
        if best_score is None or score > best_score:
            best_score = score
            best = candidate

    arrow_tip = QtCore.QPointF(best.x() + total_width / 2, best.y())
    base_y = best.y() + arrow_height
    arrow_left = QtCore.QPointF(arrow_tip.x() - arrow_width / 2, base_y)
    arrow_right = QtCore.QPointF(arrow_tip.x() + arrow_width / 2, base_y)
    arrow = QtGui.QPolygonF([arrow_tip, arrow_left, arrow_right])

    transform = None
    if angle_deg % 360:
        center = QtCore.QPointF(
            best.x() + total_width / 2, best.y() + total_height / 2
        )
        transform = QtGui.QTransform()
        transform.translate(center.x(), center.y())
        transform.rotate(angle_deg)
        transform.translate(-center.x(), -center.y())
        arrow = transform.map(arrow)
        arrow_tip = transform.map(arrow_tip)
    painter.setBrush(QtCore.Qt.white)
    painter.setPen(QtCore.Qt.NoPen)
    painter.drawPolygon(arrow)

    painter.setPen(QtCore.Qt.white)
    text_x = best.x() + (total_width - text_width) / 2
    text_y = base_y + gap + metrics.ascent()
    painter.drawText(QtCore.QPointF(text_x, text_y), text)


def _polygon_clearance(
    polygon: QtGui.QPolygonF, points: list[QtCore.QPointF]
) -> float:
    center = _polygon_center(polygon)
    if center is None:
        return 0.0
    return _min_distance(center, points)


def _polygon_center(polygon: QtGui.QPolygonF) -> QtCore.QPointF | None:
    if polygon.isEmpty():
        return None
    sum_x = 0.0
    sum_y = 0.0
    for point in polygon:
        sum_x += point.x()
        sum_y += point.y()
    count = max(len(polygon), 1)
    return QtCore.QPointF(sum_x / count, sum_y / count)


def _polygon_distance(
    polygon: QtGui.QPolygonF | None, point: QtCore.QPointF
) -> float | None:
    if polygon is None:
        return None
    center = _polygon_center(polygon)
    if center is None:
        return None
    return (center - point).manhattanLength()


def _min_distance(point: QtCore.QPointF, points: list[QtCore.QPointF]) -> float:
    best = None
    for track_point in points:
        delta = track_point - point
        distance = delta.x() ** 2 + delta.y() ** 2
        if best is None or distance < best:
            best = distance
    return float(best or 0.0)
