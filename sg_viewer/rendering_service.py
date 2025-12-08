from __future__ import annotations

from typing import Iterable, Tuple

from PyQt5 import QtGui

from sg_viewer import sg_rendering

Point = Tuple[float, float]
Transform = tuple[float, tuple[float, float]]


def paint_preview(
    painter: QtGui.QPainter,
    rect: QtGui.QRect,
    background: QtGui.QColor,
    sampled_centerline: list[Point],
    centerline_polylines: list[list[Point]],
    selected_section_points: list[Point],
    section_endpoints: list[tuple[Point, Point]],
    selected_section_index: int | None,
    show_curve_markers: bool,
    sections: Iterable,
    selected_curve_index: int | None,
    start_finish_mapping: tuple[Point, Point, Point] | None,
    transform: Transform | None,
    widget_height: int,
    status_message: str,
) -> None:
    painter.fillRect(rect, background)

    if not sampled_centerline:
        sg_rendering.draw_placeholder(painter, rect, status_message)
        painter.end()
        return

    if not transform:
        sg_rendering.draw_placeholder(painter, rect, "Unable to fit view")
        painter.end()
        return

    sg_rendering.draw_centerlines(
        painter,
        centerline_polylines,
        selected_section_points,
        transform,
        widget_height,
    )

    if show_curve_markers:
        sg_rendering.draw_curve_markers(
            painter,
            [sect for sect in sections if getattr(sect, "center", None) is not None],
            selected_curve_index,
            transform,
            widget_height,
        )


    sg_rendering.draw_start_finish_line(
        painter,
        start_finish_mapping,
        transform,
        widget_height,
    )
