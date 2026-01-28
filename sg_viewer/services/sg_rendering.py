from __future__ import annotations

from configparser import ConfigParser
from pathlib import Path
from typing import Iterable, Tuple

from PyQt5 import QtCore, QtGui
from PyQt5.QtCore import Qt
from PyQt5.QtGui import QColor, QPen

Point = Tuple[float, float]
Transform = tuple[float, tuple[float, float]]

_DEFAULT_WALL_COLOR = QColor(255, 255, 255)
_DEFAULT_ARMCO_COLOR = QColor(0, 255, 255)

SOLID_PEN_STYLE = Qt.SolidLine
FENCE_PEN_STYLE = Qt.DashLine

_DEFAULT_SURFACE_COLORS = {
    0: QtGui.QColor(40, 140, 40),
    1: QtGui.QColor(120, 170, 80),
    2: QtGui.QColor(140, 100, 60),
    3: QtGui.QColor(200, 190, 120),
    4: QtGui.QColor(170, 170, 170),
    5: QtGui.QColor(80, 80, 80),
    6: QtGui.QColor(220, 40, 40),
    7: QtGui.QColor(200, 200, 220),
    8: QtGui.QColor(180, 180, 180),
}

DEFAULT_SURFACE_COLOR = QtGui.QColor(128, 128, 128)


def _parse_ini_color(value: str) -> QtGui.QColor | None:
    cleaned = value.strip()
    if not cleaned:
        return None
    if cleaned.startswith("#"):
        parsed = QtGui.QColor(cleaned)
        return parsed if parsed.isValid() else None
    parts = [part.strip() for part in cleaned.split(",")]
    if len(parts) != 3:
        return None
    try:
        r, g, b = (int(part) for part in parts)
    except ValueError:
        return None
    for channel in (r, g, b):
        if channel < 0 or channel > 255:
            return None
    return QtGui.QColor(r, g, b)


def _load_fsection_colors() -> tuple[dict[int, QtGui.QColor], QtGui.QColor, QtGui.QColor]:
    surfaces = {key: QtGui.QColor(color) for key, color in _DEFAULT_SURFACE_COLORS.items()}
    wall_color = QtGui.QColor(_DEFAULT_WALL_COLOR)
    armco_color = QtGui.QColor(_DEFAULT_ARMCO_COLOR)
    config_path = Path(__file__).resolve().parents[1] / "rendering" / "fsection_colors.ini"
    if not config_path.exists():
        return surfaces, wall_color, armco_color

    parser = ConfigParser()
    parser.read(config_path)
    if parser.has_section("surface"):
        for key, value in parser.items("surface"):
            try:
                surface_id = int(key)
            except ValueError:
                continue
            color = _parse_ini_color(value)
            if color is not None:
                surfaces[surface_id] = color
    if parser.has_section("boundary"):
        for key, value in parser.items("boundary"):
            try:
                boundary_id = int(key)
            except ValueError:
                continue
            color = _parse_ini_color(value)
            if color is None:
                continue
            if boundary_id == 7:
                wall_color = color
            elif boundary_id == 8:
                armco_color = color
    return surfaces, wall_color, armco_color


SURFACE_COLORS, WALL_COLOR, ARMCO_COLOR = _load_fsection_colors()


def make_boundary_pen(color: QColor, is_fence: bool, width: float) -> QPen:
    pen = QPen(color)
    pen.setWidthF(width)
    pen.setStyle(FENCE_PEN_STYLE if is_fence else SOLID_PEN_STYLE)
    pen.setCapStyle(Qt.FlatCap)
    pen.setJoinStyle(Qt.MiterJoin)
    pen.setCosmetic(True)
    return pen


def draw_status_message(painter: QtGui.QPainter, rect: QtCore.QRect, message: str) -> None:
    if not message:
        return

    painter.save()
    painter.setRenderHint(QtGui.QPainter.Antialiasing, True)

    padding = QtCore.QMargins(10, 8, 10, 8)
    metrics = painter.fontMetrics()
    offset = QtCore.QPoint(12, 12)
    available_width = max(
        0,
        rect.width() - offset.x() * 2 - padding.left() - padding.right(),
    )
    text_rect = metrics.boundingRect(
        0,
        0,
        available_width,
        0,
        QtCore.Qt.TextWordWrap,
        message,
    )
    box = QtCore.QRect(
        rect.left() + offset.x(),
        rect.top() + offset.y(),
        text_rect.width() + padding.left() + padding.right(),
        text_rect.height() + padding.top() + padding.bottom(),
    )

    painter.setBrush(QtGui.QColor(0, 0, 0, 170))
    painter.setPen(QtGui.QPen(QtGui.QColor(255, 255, 255, 180)))
    painter.drawRoundedRect(box, 6, 6)

    painter.setPen(QtGui.QPen(QtGui.QColor("white")))
    painter.drawText(
        box.adjusted(
            padding.left(),
            padding.top(),
            -padding.right(),
            -padding.bottom(),
        ),
        QtCore.Qt.TextWordWrap,
        message,
    )

    painter.restore()


def draw_placeholder(painter: QtGui.QPainter, rect: QtCore.QRect, message: str) -> None:
    draw_status_message(painter, rect, message)


def draw_background_image(
    painter: QtGui.QPainter,
    image: QtGui.QImage,
    origin: Point,
    scale_500ths_per_px: float,
    transform: Transform,
    widget_height: int,
) -> None:
    if scale_500ths_per_px <= 0:
        return

    origin_x, origin_y = origin
    pixel_scale = scale_500ths_per_px

    top_left = map_point(origin_x, origin_y, transform, widget_height)
    bottom_right = map_point(
        origin_x + image.width() * pixel_scale,
        origin_y - image.height() * pixel_scale,
        transform,
        widget_height,
    )

    painter.save()
    painter.setRenderHint(QtGui.QPainter.SmoothPixmapTransform, True)
    painter.drawImage(QtCore.QRectF(top_left, bottom_right).normalized(), image)
    painter.restore()


def map_point(x: float, y: float, transform: Transform, widget_height: int) -> QtCore.QPointF:
    scale, offsets = transform
    px = offsets[0] + x * scale
    py = offsets[1] + y * scale
    return QtCore.QPointF(px, widget_height - py)


def _draw_polyline(
    painter: QtGui.QPainter,
    points: Iterable[Point],
    transform: Transform,
    widget_height: int,
    color: str,
    width: float,
) -> None:
    painter.save()
    painter.setRenderHint(QtGui.QPainter.Antialiasing, True)
    pen = QtGui.QPen(QtGui.QColor(color), width)
    pen.setCapStyle(QtCore.Qt.RoundCap)
    pen.setJoinStyle(QtCore.Qt.RoundJoin)
    painter.setPen(pen)

    path = QtGui.QPainterPath()
    iterator = iter(points)
    try:
        first = next(iterator)
    except StopIteration:
        painter.restore()
        return

    start_point = map_point(first[0], first[1], transform, widget_height)
    path.moveTo(start_point)

    for x, y in iterator:
        path.lineTo(map_point(x, y, transform, widget_height))

    painter.drawPath(path)
    painter.restore()


def draw_centerlines(
    painter: QtGui.QPainter,
    centerline_polylines: Iterable[Iterable[Point]],
    selected_section_points: Iterable[Point],
    transform: Transform,
    widget_height: int,
) -> None:
    for polyline in centerline_polylines:
        _draw_polyline(painter, polyline, transform, widget_height, color="lightgray", width=3)

    selected_points = list(selected_section_points)
    if not selected_points:
        return

    _draw_polyline(
        painter,
        selected_points,
        transform,
        widget_height,
        color="yellow",
        width=4,
    )


def draw_curve_markers(
    painter: QtGui.QPainter,
    sections,
    selected_curve_index: int | None,
    transform: Transform,
    widget_height: int,
) -> None:
    if not sections:
        return

    painter.save()
    painter.setRenderHint(QtGui.QPainter.Antialiasing, True)
    default_color = QtGui.QColor(140, 140, 140)
    highlight_color = QtGui.QColor("magenta")

    for section in sections:
        center = getattr(section, "center", None)
        if center is None:
            continue

        is_selected = getattr(section, "section_id", None) == selected_curve_index
        color = highlight_color if is_selected else default_color
        width = 2 if is_selected else 1

        painter.setPen(QtGui.QPen(color, width))
        painter.setBrush(QtGui.QBrush(color))

        start = getattr(section, "start", None)
        end = getattr(section, "end", None)
        if start is None or end is None:
            continue

        center_point = map_point(center[0], center[1], transform, widget_height)
        start_point = map_point(start[0], start[1], transform, widget_height)
        end_point = map_point(end[0], end[1], transform, widget_height)

        painter.drawLine(QtCore.QLineF(center_point, start_point))
        painter.drawLine(QtCore.QLineF(center_point, end_point))
        painter.drawEllipse(center_point, 4, 4)

    painter.restore()


def draw_section_endpoints(
    painter: QtGui.QPainter,
    section_endpoints: list[tuple[Point, Point]],
    selected_section_index: int | None,
    transform: Transform,
    widget_height: int,
) -> None:
    if not section_endpoints:
        return

    painter.save()
    painter.setRenderHint(QtGui.QPainter.Antialiasing, True)

    base_color = QtGui.QColor(0, 220, 255)
    base_pen = QtGui.QPen(base_color, 1)
    base_brush = QtGui.QBrush(base_color)

    size = 6.0
    half = size / 2

    painter.setPen(base_pen)
    painter.setBrush(base_brush)

    for start, end in section_endpoints:
        for point in (start, end):
            mapped = map_point(point[0], point[1], transform, widget_height)
            painter.drawRect(QtCore.QRectF(mapped.x() - half, mapped.y() - half, size, size))

    if selected_section_index is not None and 0 <= selected_section_index < len(section_endpoints):
        _, end_point = section_endpoints[selected_section_index]
        mapped_end = map_point(end_point[0], end_point[1], transform, widget_height)

        highlight_size = 12.0
        highlight_half = highlight_size / 2

        highlight_pen = QtGui.QPen(QtGui.QColor("yellow"), 2)
        painter.setPen(highlight_pen)
        painter.setBrush(QtCore.Qt.NoBrush)
        painter.drawRect(
            QtCore.QRectF(
                mapped_end.x() - highlight_half,
                mapped_end.y() - highlight_half,
                highlight_size,
                highlight_size,
            )
        )

    painter.restore()


def draw_start_finish_line(
    painter: QtGui.QPainter,
    mapping: tuple[Point, Point, Point] | None,
    transform: Transform,
    widget_height: int,
) -> None:
    if mapping is None:
        return

    (cx, cy), normal, tangent = mapping
    scale, _ = transform
    if scale == 0:
        return

    half_length_track = 12.0 / scale
    direction_length_track = 10.0 / scale

    start = map_point(
        cx - normal[0] * half_length_track,
        cy - normal[1] * half_length_track,
        transform,
        widget_height,
    )
    end = map_point(
        cx + normal[0] * half_length_track,
        cy + normal[1] * half_length_track,
        transform,
        widget_height,
    )

    direction_start = end
    direction_end = map_point(
        cx + normal[0] * half_length_track + tangent[0] * direction_length_track,
        cy + normal[1] * half_length_track + tangent[1] * direction_length_track,
        transform,
        widget_height,
    )

    pen = QtGui.QPen(QtGui.QColor("white"), 3.0)
    pen.setCapStyle(QtCore.Qt.RoundCap)

    painter.save()
    painter.setRenderHint(QtGui.QPainter.Antialiasing, True)
    painter.setPen(pen)
    painter.drawLine(QtCore.QLineF(start, end))
    painter.drawLine(QtCore.QLineF(direction_start, direction_end))
    painter.restore()


def interpolate_dlat_along_polyline(points, start_dlat, end_dlat):
    """
    Returns list of (point, dlat) tuples.
    Assumes polyline spans start_dlat → end_dlat monotonically.
    """
    total_len = sum(
        QtCore.QLineF(points[i - 1], points[i]).length()
        for i in range(1, len(points))
    )

    result = []
    acc = 0.0
    result.append((points[0], start_dlat))

    for i in range(1, len(points)):
        seg_len = QtCore.QLineF(points[i - 1], points[i]).length()
        acc += seg_len
        t = acc / total_len if total_len > 0 else 0.0
        dlat = start_dlat + t * (end_dlat - start_dlat)
        result.append((points[i], dlat))

    return result


def resolve_surface_at_dlat(dlat, fsections):
    for fs in fsections:
        if fs.start_dlat <= dlat <= fs.end_dlat:
            return fs.surface_type
    return None


def split_polyline_by_surface(points, start_dlat, end_dlat, fsections):
    samples = interpolate_dlat_along_polyline(points, start_dlat, end_dlat)

    segments = []
    current_surface = None
    current_points = []

    for point, dlat in samples:
        surface = resolve_surface_at_dlat(dlat, fsections)

        if surface != current_surface:
            if len(current_points) >= 2:
                segments.append((current_surface, current_points))
            current_surface = surface
            current_points = [point]
        else:
            current_points.append(point)

    if len(current_points) >= 2:
        segments.append((current_surface, current_points))

    return segments
