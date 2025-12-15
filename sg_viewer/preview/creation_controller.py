from __future__ import annotations

import math
from dataclasses import dataclass, replace
from typing import Callable, Optional

from sg_viewer.geometry.curve_solver import _solve_curve_with_fixed_heading
from sg_viewer.geometry.sg_geometry import signed_radius_from_heading, update_section_geometry
from sg_viewer.models.sg_model import SectionPreview
from sg_viewer.preview.geometry import apply_heading_constraint

Point = tuple[float, float]


@dataclass
class CreationEvent:
    pos: tuple[float, float]
    button: Optional[str] = None


@dataclass
class CreationEventContext:
    map_to_track: Callable[[tuple[float, float]], Optional[Point]]
    find_unconnected_node: Callable[[tuple[float, float]], Optional[tuple[int, str, Point, tuple[float, float] | None]]]


@dataclass
class CreationPreviewState:
    new_straight_active: bool
    new_straight_start: Point | None
    new_straight_end: Point | None
    new_curve_active: bool
    new_curve_start: Point | None
    new_curve_end: Point | None
    new_curve_preview: SectionPreview | None


@dataclass
class CreationUpdate:
    handled: bool = False
    repaint: bool = False
    stop_panning: bool = False
    finalize_straight: bool = False
    finalize_curve: bool = False
    status_changed: bool = False
    straight_mode_changed: bool = False
    curve_mode_changed: bool = False


class CreationController:
    def __init__(self) -> None:
        self._status_text = ""

        self._straight_active = False
        self._straight_start: Point | None = None
        self._straight_end: Point | None = None
        self._straight_heading: tuple[float, float] | None = None
        self._straight_connection: tuple[int, str] | None = None

        self._curve_active = False
        self._curve_start: Point | None = None
        self._curve_end: Point | None = None
        self._curve_heading: tuple[float, float] | None = None
        self._curve_preview: SectionPreview | None = None
        self._curve_connection: tuple[int, str] | None = None

        self._straight_interaction = StraightCreationInteraction(self)
        self._curve_interaction = CurveCreationInteraction(self)

    @property
    def status_text(self) -> str:
        return self._status_text

    @property
    def straight_interaction(self) -> "StraightCreationInteraction":
        return self._straight_interaction

    @property
    def curve_interaction(self) -> "CurveCreationInteraction":
        return self._curve_interaction

    @property
    def straight_active(self) -> bool:
        return self._straight_active

    @property
    def curve_active(self) -> bool:
        return self._curve_active

    def reset(self) -> CreationUpdate:
        prev_straight = self._straight_active
        prev_curve = self._curve_active
        prev_status = self._status_text

        self._straight_active = False
        self._straight_start = None
        self._straight_end = None
        self._straight_heading = None
        self._straight_connection = None

        self._curve_active = False
        self._curve_start = None
        self._curve_end = None
        self._curve_heading = None
        self._curve_preview = None
        self._curve_connection = None

        self._status_text = ""

        return CreationUpdate(
            handled=True,
            status_changed=prev_status != self._status_text,
            straight_mode_changed=prev_straight != self._straight_active,
            curve_mode_changed=prev_curve != self._curve_active,
        )

    def begin_new_straight(self, can_begin: bool) -> CreationUpdate:
        if not can_begin:
            return CreationUpdate(handled=False)

        prev_straight = self._straight_active
        prev_curve = self._curve_active
        prev_status = self._status_text

        self._straight_active = True
        self._curve_active = False
        self._straight_start = None
        self._straight_end = None
        self._straight_heading = None
        self._straight_connection = None
        self._curve_connection = None
        self._curve_start = None
        self._curve_end = None
        self._curve_heading = None
        self._curve_preview = None
        self._status_text = "Click to place the start of the new straight."

        return CreationUpdate(
            handled=True,
            repaint=True,
            status_changed=prev_status != self._status_text,
            straight_mode_changed=prev_straight != self._straight_active,
            curve_mode_changed=prev_curve != self._curve_active,
        )

    def begin_new_curve(self, can_begin: bool) -> CreationUpdate:
        if not can_begin:
            return CreationUpdate(handled=False)

        prev_straight = self._straight_active
        prev_curve = self._curve_active
        prev_status = self._status_text

        self._curve_active = True
        self._straight_active = False
        self._curve_start = None
        self._curve_end = None
        self._curve_heading = None
        self._curve_preview = None
        self._curve_connection = None
        self._straight_connection = None
        self._straight_start = None
        self._straight_end = None
        self._straight_heading = None
        self._status_text = "Click an unconnected node to start the new curve."

        return CreationUpdate(
            handled=True,
            repaint=True,
            status_changed=prev_status != self._status_text,
            straight_mode_changed=prev_straight != self._straight_active,
            curve_mode_changed=prev_curve != self._curve_active,
        )

    def deactivate_creation(self) -> CreationUpdate:
        prev_straight = self._straight_active
        prev_curve = self._curve_active

        self._straight_active = False
        self._curve_active = False
        self._straight_start = None
        self._straight_end = None
        self._straight_heading = None
        self._straight_connection = None
        self._curve_start = None
        self._curve_end = None
        self._curve_heading = None
        self._curve_preview = None
        self._curve_connection = None

        return CreationUpdate(
            handled=True,
            straight_mode_changed=prev_straight != self._straight_active,
            curve_mode_changed=prev_curve != self._curve_active,
        )

    def handle_mouse_press(
        self, event: CreationEvent, context: CreationEventContext
    ) -> CreationUpdate:
        update = self._curve_interaction.handle_press(event, context)
        if update.handled:
            return update
        return self._straight_interaction.handle_press(event, context)

    def handle_mouse_move(
        self, pos: tuple[float, float], context: CreationEventContext
    ) -> CreationUpdate:
        update = self._curve_interaction.handle_move(pos, context)
        if update.handled:
            return update
        return self._straight_interaction.handle_move(pos, context)

    def handle_mouse_release(
        self, event: CreationEvent, context: CreationEventContext
    ) -> CreationUpdate:
        return CreationUpdate(handled=False)

    def finish_straight(self, status_text: str | None) -> CreationUpdate:
        prev_status = self._status_text
        prev_straight = self._straight_active

        self._straight_active = False
        self._straight_start = None
        self._straight_end = None
        self._straight_heading = None
        self._straight_connection = None

        if status_text is not None:
            self._status_text = status_text

        return CreationUpdate(
            handled=True,
            repaint=True,
            status_changed=prev_status != self._status_text,
            straight_mode_changed=prev_straight != self._straight_active,
        )

    def finish_curve(self, status_text: str | None) -> CreationUpdate:
        prev_status = self._status_text
        prev_curve = self._curve_active

        self._curve_active = False
        self._curve_start = None
        self._curve_end = None
        self._curve_heading = None
        self._curve_preview = None
        self._curve_connection = None

        if status_text is not None:
            self._status_text = status_text

        return CreationUpdate(
            handled=True,
            repaint=True,
            status_changed=prev_status != self._status_text,
            curve_mode_changed=prev_curve != self._curve_active,
        )

    def preview_sections(self) -> CreationPreviewState:
        return CreationPreviewState(
            new_straight_active=self._straight_active,
            new_straight_start=self._straight_start,
            new_straight_end=self._straight_end,
            new_curve_active=self._curve_active,
            new_curve_start=self._curve_start,
            new_curve_end=self._curve_end,
            new_curve_preview=self._curve_preview,
        )


class StraightCreationInteraction:
    def __init__(self, controller: CreationController) -> None:
        self._controller = controller

    @property
    def active(self) -> bool:
        return self._controller.straight_active

    @property
    def start(self) -> Point | None:
        return self._controller._straight_start

    @property
    def end(self) -> Point | None:
        return self._controller._straight_end

    @property
    def heading(self) -> tuple[float, float] | None:
        return self._controller._straight_heading

    @property
    def connection(self) -> tuple[int, str] | None:
        return self._controller._straight_connection

    def handle_press(
        self, event: CreationEvent, context: CreationEventContext
    ) -> CreationUpdate:
        if not self._controller.straight_active or event.button != "left":
            return CreationUpdate()

        track_point = context.map_to_track(event.pos)
        if track_point is None:
            return CreationUpdate()

        prev_status = self._controller._status_text

        if self._controller._straight_start is None:
            constrained_start = context.find_unconnected_node(event.pos)
            if constrained_start is None:
                self._controller._straight_start = track_point
                self._controller._status_text = (
                    "Selected start; move cursor to set heading, click to finalize."
                )
                return CreationUpdate(
                    handled=True,
                    repaint=True,
                    status_changed=prev_status != self._controller._status_text,
                )

            section_index, endtype, start_point, heading = constrained_start
            self._controller._straight_start = start_point
            self._controller._straight_end = start_point
            self._controller._straight_heading = heading
            self._controller._straight_connection = (section_index, endtype)
            self._controller._status_text = (
                "Extending straight from unconnected node; move to set the heading."
            )
            return CreationUpdate(
                handled=True,
                repaint=True,
                status_changed=prev_status != self._controller._status_text,
                stop_panning=True,
            )

        if self._controller._straight_end is None:
            return CreationUpdate(handled=True)

        return CreationUpdate(handled=True, finalize_straight=True)

    def handle_move(
        self, pos: tuple[float, float], context: CreationEventContext
    ) -> CreationUpdate:
        if not self._controller.straight_active or self._controller._straight_start is None:
            return CreationUpdate()

        track_point = context.map_to_track(pos)
        if track_point is None:
            return CreationUpdate()

        constrained_end = self.apply_heading_constraint(
            self._controller._straight_start, track_point
        )
        self._controller._straight_end = constrained_end
        length = math.hypot(
            constrained_end[0] - self._controller._straight_start[0],
            constrained_end[1] - self._controller._straight_start[1],
        )
        prev_status = self._controller._status_text
        self._controller._status_text = (
            f"New straight length: {length:.1f} (click to set end)."
        )
        return CreationUpdate(
            handled=True,
            repaint=True,
            status_changed=prev_status != self._controller._status_text,
        )

    def apply_heading_constraint(self, start_point: Point, candidate: Point) -> Point:
        return apply_heading_constraint(start_point, self._controller._straight_heading, candidate)


class CurveCreationInteraction:
    def __init__(self, controller: CreationController) -> None:
        self._controller = controller

    @property
    def active(self) -> bool:
        return self._controller.curve_active

    @property
    def start(self) -> Point | None:
        return self._controller._curve_start

    @property
    def end(self) -> Point | None:
        return self._controller._curve_end

    @property
    def heading(self) -> tuple[float, float] | None:
        return self._controller._curve_heading

    @property
    def preview(self) -> SectionPreview | None:
        return self._controller._curve_preview

    @property
    def connection(self) -> tuple[int, str] | None:
        return self._controller._curve_connection

    def handle_press(
        self, event: CreationEvent, context: CreationEventContext
    ) -> CreationUpdate:
        if not self._controller.curve_active or event.button != "left":
            return CreationUpdate()

        track_point = context.map_to_track(event.pos)
        if track_point is None:
            return CreationUpdate()

        prev_status = self._controller._status_text

        if self._controller._curve_start is None:
            constrained_start = context.find_unconnected_node(event.pos)
            if constrained_start is None:
                self._controller._status_text = (
                    "New curve must start from an unconnected node."
                )
                return CreationUpdate(
                    handled=True,
                    repaint=True,
                    status_changed=prev_status != self._controller._status_text,
                )

            section_index, endtype, start_point, heading = constrained_start
            if heading is None:
                self._controller._status_text = (
                    "Selected node does not have a usable heading."
                )
                return CreationUpdate(
                    handled=True,
                    repaint=True,
                    status_changed=prev_status != self._controller._status_text,
                )

            self._controller._curve_start = start_point
            self._controller._curve_end = start_point
            self._controller._curve_heading = heading
            self._controller._curve_preview = None
            self._controller._curve_connection = (section_index, endtype)
            self._controller._status_text = (
                "Extending curve from unconnected node; move to set the arc."
            )
            return CreationUpdate(
                handled=True,
                repaint=True,
                status_changed=prev_status != self._controller._status_text,
                stop_panning=True,
            )

        preview = self._build_candidate(track_point)
        if preview is None:
            self._controller._status_text = "Unable to solve a curve for that end point."
            return CreationUpdate(
                handled=True,
                repaint=True,
                status_changed=prev_status != self._controller._status_text,
            )

        self._controller._curve_preview = preview
        self._controller._curve_end = preview.end
        return CreationUpdate(
            handled=True,
            finalize_curve=True,
            status_changed=prev_status != self._controller._status_text,
        )

    def handle_move(
        self, pos: tuple[float, float], context: CreationEventContext
    ) -> CreationUpdate:
        if not self._controller.curve_active or self._controller._curve_start is None:
            return CreationUpdate()

        track_point = context.map_to_track(pos)
        if track_point is None:
            return CreationUpdate()

        preview = self._build_candidate(track_point)
        if preview is None:
            prev_status = self._controller._status_text
            self._controller._status_text = "Unable to solve a curve for that position."
            return CreationUpdate(
                handled=True,
                repaint=True,
                status_changed=prev_status != self._controller._status_text,
            )

        self._controller._curve_preview = preview
        self._controller._curve_end = preview.end
        prev_status = self._controller._status_text
        self._controller._status_text = (
            f"New curve length: {preview.length:.1f} (click to set end)."
        )
        return CreationUpdate(
            handled=True,
            repaint=True,
            status_changed=prev_status != self._controller._status_text,
        )

    def _build_candidate(self, end_point: Point) -> SectionPreview | None:
        if self._controller._curve_start is None or self._controller._curve_heading is None:
            return None

        start_point = self._controller._curve_start
        heading = self._controller._curve_heading
        template = SectionPreview(
            section_id=0,
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
