from __future__ import annotations

import math

from PyQt5 import QtCore

from sg_viewer.geometry.centerline_utils import (
    compute_start_finish_mapping_from_centerline,
)
from sg_viewer.geometry.dlong import set_start_finish
from sg_viewer.geometry.picking import project_point_to_segment
from sg_viewer.geometry.sg_geometry import rebuild_centerline_from_sections, scale_section
from sg_viewer.geometry.topology import is_closed_loop, loop_length
from sg_viewer.models.sg_model import SectionPreview
from sg_viewer.preview.preview_mutations import project_point_to_polyline
from sg_viewer.preview.runtime_ops_core import Point


class _RuntimeEditingMixin:
    # ------------------------------------------------------------------
    # Delete section
    # ------------------------------------------------------------------
    def begin_delete_section(self) -> bool:
        if not self._section_manager.sections:
            return False

        self._set_delete_section_active(True)
        self._status_message = "Click a section to delete it."
        self._context.request_repaint()
        return True

    def cancel_delete_section(self) -> None:
        self._set_delete_section_active(False)

    def _set_delete_section_active(self, active: bool) -> None:
        if active:
            changed = self._editor.begin_delete_section(self._section_manager.sections)
        else:
            changed = self._editor.cancel_delete_section()

        if not changed:
            return

        if active:
            self.cancel_split_section()
            self._apply_creation_update(
                self._creation_controller.deactivate_creation()
            )
        if self._emit_delete_mode_changed is not None:
            self._emit_delete_mode_changed(active)

    # ------------------------------------------------------------------
    # Split section
    # ------------------------------------------------------------------
    def begin_split_section(self) -> bool:
        if not self._section_manager.sections:
            return False

        if self._split_section_mode:
            return True

        self._split_previous_status_message = self._status_message
        self._clear_split_hover()
        self._split_section_mode = True
        self._apply_creation_update(self._creation_controller.deactivate_creation())
        self.set_status_text(
            "Hover over a straight or curve section to choose split point."
        )
        if self._emit_split_section_mode_changed is not None:
            self._emit_split_section_mode_changed(True)
        self.request_repaint()
        return True

    def cancel_split_section(self) -> None:
        if not self._split_section_mode and self._split_hover_point is None:
            return

        self._exit_split_section_mode()

    def _update_split_hover(self, screen_pos: QtCore.QPoint) -> None:
        widget_size = self._widget_size()
        transform = self.current_transform(widget_size)
        if transform is None:
            self._clear_split_hover()
            return

        track_point = self.map_to_track(
            screen_pos, widget_size, self._widget_height(), transform
        )
        if track_point is None:
            self._clear_split_hover()
            return

        section_index = self._selection.find_section_at_point(
            screen_pos,
            lambda p: self.map_to_track(p, widget_size, self._widget_height(), transform),
            transform,
        )
        if section_index is None:
            self._clear_split_hover()
            return

        section = self._section_manager.sections[section_index]
        if section.type_name not in {"straight", "curve"}:
            self._clear_split_hover()
            return

        if section.type_name == "straight":
            projected = project_point_to_segment(track_point, section.start, section.end)
        else:
            projected = project_point_to_polyline(track_point, section.polyline)
        if projected is None:
            self._clear_split_hover()
            return

        self._split_hover_point = projected
        self._split_hover_section_index = section_index
        self.request_repaint()

    def _clear_split_hover(self) -> None:
        if (
            self._split_hover_point is not None
            or self._split_hover_section_index is not None
        ):
            self._split_hover_point = None
            self._split_hover_section_index = None
            self.request_repaint()

    def _commit_split(self) -> None:
        idx = self._split_hover_section_index
        point = self._split_hover_point

        if idx is None or point is None:
            return

        section = self._section_manager.sections[idx]
        if section.type_name == "curve":
            result = self._editor.split_curve_section(
                list(self._section_manager.sections), idx, point
            )
        else:
            result = self._editor.split_straight_section(
                list(self._section_manager.sections), idx, point
            )
        if result is None:
            return

        sections, track_length = result
        self._track_length = track_length
        self._split_fsects_by_section(idx)
        self.set_sections(sections)
        self._validate_section_fsects_alignment()
        if idx + 1 < len(sections):
            self._selection.set_selected_section(idx + 1)
        self._exit_split_section_mode("Split complete.")

    def _exit_split_section_mode(self, status_message: str | None = None) -> None:
        self._split_section_mode = False
        self._clear_split_hover()
        if status_message is not None:
            self._status_message = status_message
        elif self._split_previous_status_message is not None:
            self._status_message = self._split_previous_status_message
        self._split_previous_status_message = None
        if self._emit_split_section_mode_changed is not None:
            self._emit_split_section_mode_changed(False)
        self._show_status(self._status_message)
        self.request_repaint()

    def _can_drag_section_node(self, section: SectionPreview) -> bool:
        return self._editor.can_drag_section_node(
            self._section_manager.sections, section
        )

    def _can_drag_section_polyline(
        self, section: SectionPreview, index: int | None = None
    ) -> bool:
        return self._editor.can_drag_section_polyline(
            self._section_manager.sections, section, index
        )

    def _connected_neighbor_index(self, index: int, direction: str) -> int | None:
        return self._editor.connected_neighbor_index(
            self._section_manager.sections, index, direction
        )

    def _get_drag_chain(self, index: int | None) -> list[int] | None:
        return self._editor.get_drag_chain(self._section_manager.sections, index)

    def _can_drag_node(self, section: SectionPreview, endtype: str) -> bool:
        return self._editor.can_drag_node(
            self._section_manager.sections, section, endtype
        )

    def update_split_hover(self, pos: QtCore.QPoint) -> None:
        self._update_split_hover(pos)

    def commit_split(self) -> None:
        self._commit_split()

    def handle_delete_click(self, pos: QtCore.QPoint) -> bool:
        return self._handle_delete_click(pos)

    def _handle_delete_click(self, pos: QtCore.QPoint) -> bool:
        widget_size = self._widget_size()
        transform = self.current_transform(widget_size)
        if transform is None:
            return False

        selection_index = self._selection.find_section_at_point(
            pos,
            lambda p: self._controller.map_to_track(
                p, widget_size, self._widget_height(), transform
            ),
            transform,
        )
        if selection_index is None:
            self._status_message = "Click a section to delete it."
            self._context.request_repaint()
            return False

        self._delete_section(selection_index)
        return True

    def _delete_section(self, index: int) -> None:
        new_sections, track_length, status = self._editor.delete_section(
            list(self._section_manager.sections), index
        )
        if not status:
            return

        self._track_length = track_length
        self._delete_fsects_by_section(index)
        self.set_sections(new_sections)
        self._validate_section_fsects_alignment()
        self._selection.set_selected_section(None)
        self._status_message = status
        self._set_delete_section_active(False)

    def scale_track_to_length(self, target_length: float) -> str | None:
        """Scale the current closed loop to ``target_length`` DLONG (500ths)."""

        sections = self._section_manager.sections
        if not sections or not is_closed_loop(sections):
            return None

        try:
            current_length = loop_length(sections)
        except ValueError:
            return None

        if current_length <= 0:
            return None

        factor = target_length / current_length
        if math.isclose(factor, 1.0, rel_tol=1e-9):
            return "Track already at desired length."

        scaled_sections = [scale_section(sect, factor) for sect in sections]
        scaled_start_finish = self._start_finish_dlong
        if scaled_start_finish is not None:
            scaled_start_finish *= factor

        self.set_sections(scaled_sections, start_finish_dlong=scaled_start_finish)

        return f"Scaled track by {factor:.3f}× to {target_length:.0f} DLONG."

    def _current_start_finish_dlong(self) -> float | None:
        if self._track_length is None or self._track_length <= 0:
            return None

        if self._start_finish_dlong is not None:
            return float(self._start_finish_dlong) % float(self._track_length)

        if (
            self._start_finish_mapping is None
            or self._section_manager.centerline_index is None
            or not self._section_manager.sampled_dlongs
        ):
            return None

        track_length = self._track_length
        if track_length is None and self._section_manager.sampled_dlongs:
            track_length = self._section_manager.sampled_dlongs[-1]

        if track_length is None or track_length <= 0:
            return None

        (cx, cy), _, _ = self._start_finish_mapping
        return self._trk_overlay.project_point_to_centerline(
            (cx, cy),
            self._section_manager.centerline_index,
            self._section_manager.sampled_dlongs,
            track_length,
        )

    def set_sections(
        self, sections: list[SectionPreview], start_finish_dlong: float | None = None
    ) -> None:
        self._clear_split_hover()

        preserved_start_finish_dlong = start_finish_dlong
        if preserved_start_finish_dlong is None:
            preserved_start_finish_dlong = self._start_finish_dlong
        if preserved_start_finish_dlong is None:
            preserved_start_finish_dlong = self._current_start_finish_dlong()

        needs_rebuild = self._section_manager.set_sections(sections)

        self._sampled_bounds = self._section_manager.sampled_bounds
        self._sampled_centerline = self._section_manager.sampled_centerline
        if self._section_manager.sampled_dlongs:
            self._track_length = self._section_manager.sampled_dlongs[-1]
        self._update_start_finish_mapping(preserved_start_finish_dlong)

        if needs_rebuild:
            self._update_fit_scale()

        self._update_node_status()

        self._selection.update_context(
            self._section_manager.sections,
            self._track_length,
            self._section_manager.centerline_index,
            self._section_manager.sampled_dlongs,
        )
        if preserved_start_finish_dlong is not None and self._track_length:
            self._start_finish_dlong = float(preserved_start_finish_dlong) % float(
                self._track_length
            )
        self._has_unsaved_changes = True
        if self._emit_sections_changed is not None:
            self._emit_sections_changed()
        self._context.request_repaint()

    def rebuild_after_start_finish(self, sections: list[SectionPreview]) -> None:
        (
            cline,
            sampled_dlongs,
            sampled_bounds,
            centerline_index,
        ) = rebuild_centerline_from_sections(sections)

        track_length = sampled_dlongs[-1] if sampled_dlongs else 0.0

        self._section_manager.load_sections(
            sections=sections,
            section_endpoints=[(sect.start, sect.end) for sect in sections],
            sampled_centerline=cline,
            sampled_dlongs=sampled_dlongs,
            sampled_bounds=sampled_bounds or (0.0, 0.0, 0.0, 0.0),
            centerline_index=centerline_index,
        )
        self._sampled_bounds = self._section_manager.sampled_bounds
        self._sampled_centerline = self._section_manager.sampled_centerline
        self._track_length = track_length
        self._start_finish_mapping = None
        self._start_finish_dlong = 0.0 if track_length > 0 else None

        previous_block_state = self._selection.blockSignals(True)
        try:
            self._selection.reset(
                self._section_manager.sections,
                self._track_length,
                self._section_manager.centerline_index,
                self._section_manager.sampled_dlongs,
            )
            self._update_node_status()
            self._update_start_finish_mapping(0.0 if track_length > 0 else None)
        finally:
            self._selection.blockSignals(previous_block_state)

        self._has_unsaved_changes = True
        if self._emit_sections_changed is not None:
            self._emit_sections_changed()
        self._selection.set_selected_section(
            0 if self._section_manager.sections else None
        )

    def _compute_start_finish_mapping_from_samples(
        self, start_dlong: float | None
    ) -> tuple[Point, Point, Point] | None:
        if (
            start_dlong is None
            or self._track_length is None
            or self._track_length <= 0
        ):
            return None

        points = self._section_manager.sampled_centerline
        dlongs = self._section_manager.sampled_dlongs
        if len(points) < 2 or len(points) != len(dlongs):
            return None

        target = float(start_dlong) % float(self._track_length)

        for idx in range(len(dlongs) - 1):
            seg_start = points[idx]
            seg_end = points[idx + 1]
            seg_span = dlongs[idx + 1] - dlongs[idx]
            if seg_span <= 0:
                continue
            if not (dlongs[idx] <= target <= dlongs[idx + 1]):
                continue

            fraction = (target - dlongs[idx]) / seg_span
            cx = seg_start[0] + (seg_end[0] - seg_start[0]) * fraction
            cy = seg_start[1] + (seg_end[1] - seg_start[1]) * fraction

            dx = seg_end[0] - seg_start[0]
            dy = seg_end[1] - seg_start[1]
            length = math.hypot(dx, dy)
            if length == 0:
                return None

            tangent = (dx / length, dy / length)
            normal = (-tangent[1], tangent[0])
            return (cx, cy), normal, tangent

        start = points[0]
        end = points[1]
        dx = end[0] - start[0]
        dy = end[1] - start[1]
        length = math.hypot(dx, dy)
        if length == 0:
            return None

        tangent = (dx / length, dy / length)
        normal = (-tangent[1], tangent[0])
        return start, normal, tangent

    def _update_start_finish_mapping(self, start_dlong: float | None) -> None:
        mapping = self._compute_start_finish_mapping_from_samples(start_dlong)

        if mapping is None and start_dlong is not None:
            mapping = self._trk_overlay.compute_start_finish_mapping(
                start_dlong, self._track_length
            )

        if mapping is None:
            mapping = compute_start_finish_mapping_from_centerline(
                self._section_manager.sampled_centerline
            )

        self._start_finish_mapping = mapping
        if start_dlong is not None and self._track_length:
            self._start_finish_dlong = float(start_dlong) % float(self._track_length)

    def set_start_finish_at_selected_section(self) -> None:
        if not self._section_manager.sections:
            return

        selected_index = self._selection.selected_section_index
        if selected_index is None:
            self._show_status("Select a section to set start/finish")
            return

        if not is_closed_loop(self._section_manager.sections):
            self._show_status("Track must be closed to set start/finish")
            return

        try:
            new_sections = set_start_finish(
                self._section_manager.sections, selected_index
            )
        except ValueError:
            self._show_status("Track must be closed to set start/finish")
            return
        except RuntimeError:
            self._show_status("Invalid loop topology; cannot set start/finish")
            return

        self.rebuild_after_start_finish(new_sections)
        self._show_status("Start/finish set to selected section (now section 0)")
