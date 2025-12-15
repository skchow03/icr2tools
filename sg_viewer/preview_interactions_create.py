from __future__ import annotations

import math
from dataclasses import replace
from typing import TYPE_CHECKING

from PyQt5 import QtCore, QtGui

from sg_viewer.curve_solver import _solve_curve_with_fixed_heading
from sg_viewer.sg_geometry import signed_radius_from_heading, update_section_geometry
from sg_viewer.sg_model import SectionPreview

if TYPE_CHECKING:
    from sg_viewer.preview_widget import SGPreviewWidget


Point = tuple[float, float]


class StraightCreationInteraction:
    def __init__(self, widget: "SGPreviewWidget") -> None:
        self.widget = widget
        self.active = False
        self.start: Point | None = None
        self.end: Point | None = None
        self.heading: tuple[float, float] | None = None
        self.connection: tuple[int, str] | None = None

    def reset(self) -> None:
        self.active = False
        self.start = None
        self.end = None
        self.heading = None
        self.connection = None

    def begin(self) -> bool:
        if not self.widget._sampled_bounds:
            return False

        self.widget._set_new_straight_active(True)
        self.start = None
        self.end = None
        self.heading = None
        self.connection = None
        self.widget._status_message = "Click to place the start of the new straight."
        self.widget.update()
        return True

    def handle_press(self, event: QtGui.QMouseEvent) -> bool:
        if not self.active or event.button() != QtCore.Qt.LeftButton:
            return False

        widget_size = (self.widget.width(), self.widget.height())
        transform = self.widget._controller.current_transform(widget_size)
        if transform is None:
            return False

        track_point = self.widget._controller.map_to_track(
            event.pos(), widget_size, self.widget.height(), transform
        )
        if track_point is None:
            return False

        if self.start is None:
            constrained_start = self.widget._unconnected_node_hit(event.pos())
            if constrained_start is None:
                self.start = track_point
                self.widget._status_message = (
                    "Selected start; move cursor to set heading, click to finalize."
                )
                self.widget.update()
            else:
                section_index, endtype, start_point, heading = constrained_start
                self.start = start_point
                self.end = start_point
                self.heading = heading
                self.connection = (section_index, endtype)
                self.widget._status_message = (
                    "Extending straight from unconnected node; move to set the heading."
                )
                self.widget._is_panning = False
                self.widget._last_mouse_pos = None
                self.widget._press_pos = None
                self.widget.update()
        else:
            if self.end is None:
                return True

            self.widget._finalize_new_straight(self.end)

        event.accept()
        return True

    def handle_move(self, pos: QtCore.QPoint) -> bool:
        if not self.active or self.start is None:
            return False

        widget_size = (self.widget.width(), self.widget.height())
        transform = self.widget._controller.current_transform(widget_size)
        if transform is None:
            return False

        track_point = self.widget._controller.map_to_track(
            QtCore.QPointF(pos), widget_size, self.widget.height(), transform
        )
        if track_point is None:
            return False

        constrained_end = self.apply_heading_constraint(self.start, track_point)
        self.end = constrained_end
        length = math.hypot(
            constrained_end[0] - self.start[0], constrained_end[1] - self.start[1]
        )
        self.widget._status_message = f"New straight length: {length:.1f} (click to set end)."
        self.widget.update()
        return True

    def apply_heading_constraint(self, start_point: Point, candidate: Point) -> Point:
        if self.heading is None:
            return candidate

        hx, hy = self.heading
        vx = candidate[0] - start_point[0]
        vy = candidate[1] - start_point[1]
        projected_length = max(0.0, vx * hx + vy * hy)
        return (start_point[0] + hx * projected_length, start_point[1] + hy * projected_length)


class CurveCreationInteraction:
    def __init__(self, widget: "SGPreviewWidget") -> None:
        self.widget = widget
        self.active = False
        self.start: Point | None = None
        self.end: Point | None = None
        self.heading: tuple[float, float] | None = None
        self.preview: SectionPreview | None = None
        self.connection: tuple[int, str] | None = None

    def reset(self) -> None:
        self.active = False
        self.start = None
        self.end = None
        self.heading = None
        self.preview = None
        self.connection = None

    def begin(self) -> bool:
        if not self.widget._sampled_bounds:
            return False

        self.widget._set_new_curve_active(True)
        self.start = None
        self.end = None
        self.heading = None
        self.preview = None
        self.connection = None
        self.widget._status_message = "Click an unconnected node to start the new curve."
        self.widget.update()
        return True

    def handle_press(self, event: QtGui.QMouseEvent) -> bool:
        if not self.active or event.button() != QtCore.Qt.LeftButton:
            return False

        widget_size = (self.widget.width(), self.widget.height())
        transform = self.widget._controller.current_transform(widget_size)
        if transform is None:
            return False

        track_point = self.widget._controller.map_to_track(
            event.pos(), widget_size, self.widget.height(), transform
        )
        if track_point is None:
            return False

        if self.start is None:
            constrained_start = self.widget._unconnected_node_hit(event.pos())
            if constrained_start is None:
                self.widget._status_message = (
                    "New curve must start from an unconnected node."
                )
                self.widget.update()
                event.accept()
                return True

            section_index, endtype, start_point, heading = constrained_start
            if heading is None:
                self.widget._status_message = "Selected node does not have a usable heading."
                self.widget.update()
                event.accept()
                return True

            self.start = start_point
            self.end = start_point
            self.heading = heading
            self.preview = None
            self.connection = (section_index, endtype)
            self.widget._status_message = (
                "Extending curve from unconnected node; move to set the arc."
            )
            self.widget._is_panning = False
            self.widget._last_mouse_pos = None
            self.widget._press_pos = None
            self.widget.update()
        else:
            preview = self._build_candidate(track_point)
            if preview is None:
                self.widget._status_message = "Unable to solve a curve for that end point."
                self.widget.update()
            else:
                self.preview = preview
                self.end = preview.end
                self.widget._finalize_new_curve()

        event.accept()
        return True

    def handle_move(self, pos: QtCore.QPoint) -> bool:
        if not self.active or self.start is None:
            return False

        widget_size = (self.widget.width(), self.widget.height())
        transform = self.widget._controller.current_transform(widget_size)
        if transform is None:
            return False

        track_point = self.widget._controller.map_to_track(
            QtCore.QPointF(pos), widget_size, self.widget.height(), transform
        )
        if track_point is None:
            return False

        preview = self._build_candidate(track_point)
        if preview is None:
            self.widget._status_message = "Unable to solve a curve for that position."
            self.widget.update()
            return True

        self.preview = preview
        self.end = preview.end
        self.widget._status_message = f"New curve length: {preview.length:.1f} (click to set end)."
        self.widget.update()
        return True

    def _build_candidate(self, end_point: Point) -> SectionPreview | None:
        if self.start is None or self.heading is None:
            return None

        start_point = self.start
        heading = self.heading
        template = SectionPreview(
            section_id=len(self.widget._sections),
            type_name="curve",
            previous_id=-1,
            next_id=-1,
            start=start_point,
            end=end_point,
            start_dlong=0.0,
            length=0.0,
            center=None,
            sang1=None,
            sang2=None,
            eang1=None,
            eang2=None,
            radius=None,
            start_heading=heading,
            end_heading=None,
            polyline=[start_point, end_point],
        )

        candidates = _solve_curve_with_fixed_heading(
            template,
            start_point,
            end_point,
            fixed_point=start_point,
            fixed_heading=heading,
            fixed_point_is_start=True,
            orientation_hint=1.0,
        )
        if not candidates:
            return None

        best_candidate = min(candidates, key=lambda sect: sect.length)
        signed_radius = signed_radius_from_heading(
            heading, start_point, best_candidate.center, best_candidate.radius
        )
        if signed_radius != best_candidate.radius:
            best_candidate = replace(best_candidate, radius=signed_radius)

        return update_section_geometry(best_candidate)


class PreviewCreationAdapter:
    def __init__(self, widget: "SGPreviewWidget") -> None:
        self.straight = StraightCreationInteraction(widget)
        self.curve = CurveCreationInteraction(widget)

    def reset(self) -> None:
        self.straight.reset()
        self.curve.reset()

    def is_active(self) -> bool:
        return self.straight.active or self.curve.active

    def handle_mouse_press(self, event: QtGui.QMouseEvent) -> bool:
        if self.curve.handle_press(event):
            return True
        if self.straight.handle_press(event):
            return True
        return False

    def handle_mouse_move(self, pos: QtCore.QPoint) -> bool:
        if self.curve.handle_move(pos):
            return True
        if self.straight.handle_move(pos):
            return True
        return False
