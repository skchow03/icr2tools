from __future__ import annotations

from typing import Iterable

from PyQt5 import QtCore, QtGui

from sg_viewer.sg_preview.model import Point, SgPreviewModel
from sg_viewer.sg_preview.transform import ViewTransform
from sg_viewer.sg_preview.view_state import SgPreviewViewState
from sg_viewer.services import sg_rendering

_SURFACE_FILL_RGBA = (60, 160, 120, 110)
_SURFACE_OUTLINE_RGBA = (80, 200, 150, 180)
_BOUNDARY_RGBA = (230, 230, 230, 200)
_FSECT_OUTLINE_RGBA = (120, 180, 220, 160)
_SHOW_FSECT_OUTLINES = False


def render_sg_preview(
    painter,
    model: SgPreviewModel,
    transform: ViewTransform,
    view_state: SgPreviewViewState,
) -> None:
    if model is None or transform is None:
        return

    painter.save()
    painter.setRenderHint(type(painter).Antialiasing, True)

    if view_state.show_surfaces:
        _draw_surfaces(painter, model, transform)

    if view_state.show_boundaries:
        _draw_boundaries(painter, model, transform)

    if _SHOW_FSECT_OUTLINES:
        _draw_fsect_outlines(painter, model, transform)

    painter.restore()


def _draw_surfaces(painter, model: SgPreviewModel, transform: ViewTransform) -> None:
    for fsect in model.fsects:
        for surface in fsect.surfaces:
            surface_type = surface.attrs.get("type1") if surface.attrs else None
            if surface_type is None:
                base_color = sg_rendering.DEFAULT_SURFACE_COLOR
            else:
                base_color = sg_rendering.SURFACE_COLORS.get(
                    int(surface_type), sg_rendering.DEFAULT_SURFACE_COLOR
                )
            fill = _make_color_from_qcolor(painter, base_color, _SURFACE_FILL_RGBA[3])
            outline = _make_color_from_qcolor(
                painter, base_color.darker(130), _SURFACE_OUTLINE_RGBA[3]
            )
            points = _map_points(surface.outline, transform)
            if len(points) < 3:
                continue
            _set_brush(painter, fill)
            _set_pen(painter, outline, 1.0)
            painter.drawPolygon(points)


def _draw_boundaries(painter, model: SgPreviewModel, transform: ViewTransform) -> None:
    color = _make_color(painter, *_BOUNDARY_RGBA)
    _set_pen(painter, color, 1.2)
    for fsect in model.fsects:
        for boundary in fsect.boundaries:
            points = _map_points(boundary.points, transform)
            if len(points) < 2:
                continue
            painter.drawPolyline(points)


def _draw_fsect_outlines(painter, model: SgPreviewModel, transform: ViewTransform) -> None:
    color = _make_color(painter, *_FSECT_OUTLINE_RGBA)
    _set_pen(painter, color, 1.0)
    for fsect in model.fsects:
        for surface in fsect.surfaces:
            points = _map_points(surface.outline, transform)
            if len(points) < 3:
                continue
            painter.drawPolygon(points)


def _map_points(points: Iterable[Point], transform: ViewTransform) -> QtGui.QPolygonF:
    polygon = QtGui.QPolygonF()
    for point in points:
        x, y = transform.world_to_screen(point)
        polygon.append(QtCore.QPointF(x, y))
    return polygon


def _make_color(painter, r: int, g: int, b: int, a: int = 255):
    color = painter.pen().color()
    color.setRgb(r, g, b, a)
    return color


def _make_color_from_qcolor(painter, color: QtGui.QColor, a: int = 255):
    updated = QtGui.QColor(color)
    updated.setAlpha(a)
    return updated


def _set_pen(painter, color, width: float) -> None:
    pen = painter.pen()
    pen.setColor(color)
    pen.setWidthF(width)
    painter.setPen(pen)


def _set_brush(painter, color) -> None:
    brush = painter.brush()
    brush.setColor(color)
    brush.setStyle(QtCore.Qt.SolidPattern)
    painter.setBrush(brush)
