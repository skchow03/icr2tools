from __future__ import annotations

import copy
import math
from dataclasses import replace

from PyQt5 import QtCore

from icr2_core.sg_elevation import sg_xsect_altitude_grade_at
from sg_viewer.geometry.centerline_utils import (
    compute_start_finish_mapping_from_centerline,
)
from sg_viewer.geometry.dlong import set_start_finish
from sg_viewer.geometry.picking import project_point_to_segment
from sg_viewer.geometry.sg_geometry import rebuild_centerline_from_sections, scale_section
from sg_viewer.geometry.topology import is_closed_loop, loop_length
from sg_viewer.models.sg_model import SectionPreview
from sg_viewer.preview.edit_session import apply_preview_to_sgfile
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

    def _split_xsect_elevations(self, index: int, split_fraction: float) -> None:
        sg_data = self._document.sg_data
        if (
            sg_data is None
            or split_fraction <= 0.0
            or split_fraction >= 1.0
            or index < 0
            or index >= len(sg_data.sects)
        ):
            return

        num_xsects = sg_data.num_xsects
        if num_xsects <= 0:
            return

        original_section = sg_data.sects[index]
        if not original_section.alt or not original_section.grade:
            return

        new_section = copy.deepcopy(original_section)
        original_alt = list(original_section.alt)
        original_grade = list(original_section.grade)

        split_altitudes: list[int] = []
        split_grades: list[int] = []
        for xsect_idx in range(num_xsects):
            altitude, grade = sg_xsect_altitude_grade_at(
                sg_data, index, split_fraction, xsect_idx
            )
            split_altitudes.append(int(round(altitude)))
            split_grades.append(int(round(grade)))

        original_section.alt = split_altitudes
        original_section.grade = split_grades
        new_section.alt = original_alt
        new_section.grade = original_grade

        sg_data.sects.insert(index + 1, new_section)
        sg_data.num_sects = len(sg_data.sects)
        if len(sg_data.header) > 4:
            sg_data.header[4] = sg_data.num_sects
        self._bump_sg_version()

    def _sg_track_length(self, sg_data) -> float:
        if sg_data is None:
            return 0.0

        max_end = 0.0
        for section in getattr(sg_data, "sects", []):
            start_dlong = float(getattr(section, "start_dlong", 0.0))
            length = float(getattr(section, "length", 0.0))
            if length < 0:
                continue
            max_end = max(max_end, start_dlong + length)
        return max_end

    def _section_at_dlong(self, sg_data, dlong: float) -> tuple[int, float] | None:
        sections = list(getattr(sg_data, "sects", []))
        if not sections:
            return None

        track_length = self._sg_track_length(sg_data)
        if track_length <= 0:
            return None

        normalized = float(dlong) % track_length
        for idx, section in enumerate(sections):
            start_dlong = float(getattr(section, "start_dlong", 0.0))
            length = float(getattr(section, "length", 0.0))
            if length <= 0:
                continue
            end_dlong = start_dlong + length
            if normalized < start_dlong:
                continue
            if normalized <= end_dlong or math.isclose(normalized, end_dlong):
                subsect = (normalized - start_dlong) / length if length else 0.0
                subsect = min(max(subsect, 0.0), 1.0)
                return idx, subsect

        last_idx = len(sections) - 1
        last_length = float(getattr(sections[last_idx], "length", 0.0))
        return last_idx, 1.0 if last_length > 0 else 0.0

    def _expanded_drag_indices(
        self, indices: list[int] | None, total_sections: int
    ) -> list[int] | None:
        if not indices:
            return None
        expanded: set[int] = set()
        for index in indices:
            if index < 0 or index >= total_sections:
                continue
            expanded.add(index)
            if index - 1 >= 0:
                expanded.add(index - 1)
            if index + 1 < total_sections:
                expanded.add(index + 1)
        if not expanded:
            return None
        return sorted(expanded)

    def _section_geometry_changed(self, old_sg, new_sg) -> bool:
        old_sections = list(getattr(old_sg, "sects", []))
        new_sections = list(getattr(new_sg, "sects", []))
        if len(old_sections) != len(new_sections):
            return True
        for old_section, new_section in zip(old_sections, new_sections):
            if (
                int(getattr(old_section, "start_dlong", 0))
                != int(getattr(new_section, "start_dlong", 0))
            ):
                return True
            if int(getattr(old_section, "length", 0)) != int(
                getattr(new_section, "length", 0)
            ):
                return True
        return False

    def _recalculate_elevations_after_drag(
        self, affected_indices: list[int] | None = None
    ) -> bool:
        if self._sgfile is None:
            return False

        if not self._section_manager.sections:
            return False

        if self._refresh_section_dlongs_after_drag():
            if not self._section_manager.sections:
                return False

        old_sg = copy.deepcopy(self._sgfile)
        if not old_sg.sects or old_sg.num_xsects <= 0:
            return False

        if any(not sect.alt or not sect.grade for sect in self._sgfile.sects):
            return False

        try:
            self.apply_preview_to_sgfile()
        except ValueError:
            return False

        num_xsects = old_sg.num_xsects
        sections_to_update = self._expanded_drag_indices(
            affected_indices, len(self._sgfile.sects)
        )
        updated = False
        if sections_to_update is None:
            indices = range(len(self._sgfile.sects))
        else:
            indices = sections_to_update
        for index in indices:
            if index < 0 or index >= len(self._sgfile.sects):
                continue
            section = self._sgfile.sects[index]
            start_dlong = float(getattr(section, "start_dlong", 0.0))
            length = float(getattr(section, "length", 0.0))
            end_dlong = start_dlong + length
            location = self._section_at_dlong(old_sg, end_dlong)
            if location is None:
                continue
            old_index, subsect = location
            for xsect_idx in range(num_xsects):
                altitude, grade = sg_xsect_altitude_grade_at(
                    old_sg, old_index, subsect, xsect_idx
                )
                updated_altitude = int(round(altitude))
                updated_grade = int(round(grade))
                if (
                    section.alt[xsect_idx] != updated_altitude
                    or section.grade[xsect_idx] != updated_grade
                ):
                    updated = True
                section.alt[xsect_idx] = updated_altitude
                section.grade[xsect_idx] = updated_grade

        if updated:
            geometry_changed = self._section_geometry_changed(old_sg, self._sgfile)
            if geometry_changed:
                self._elevation_profile_cache.clear()
            for xsect_idx in range(num_xsects):
                self._mark_xsect_bounds_dirty(xsect_idx)
        if updated and self._emit_sections_changed is not None:
            self._emit_sections_changed()
        return updated

    def _refresh_section_dlongs_after_drag(self) -> bool:
        sections = list(self._section_manager.sections)
        if not sections:
            return False

        dlong = 0.0
        updated_sections: list[SectionPreview] = []
        changed = False
        for idx, section in enumerate(sections):
            current_start = (
                float(section.start_dlong) if section.start_dlong is not None else dlong
            )
            if not math.isclose(current_start, dlong):
                changed = True
            updated_sections.append(
                replace(section, section_id=idx, start_dlong=dlong)
            )
            dlong += float(getattr(section, "length", 0.0))

        if changed:
            self.set_sections(updated_sections)
        return changed

    def _commit_split(self) -> None:
        idx = self._split_hover_section_index
        point = self._split_hover_point

        if idx is None or point is None:
            return

        section = self._section_manager.sections[idx]
        original_length = float(section.length)
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
        if original_length > 0 and idx < len(sections):
            split_fraction = float(sections[idx].length) / original_length
            self._split_xsect_elevations(idx, split_fraction)
        self._split_fsects_by_section(idx)
        self.set_sections(sections)
        if self._sgfile is not None:
            self.apply_preview_to_sgfile()
            if self._emit_sections_changed is not None:
                self._emit_sections_changed()
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

    def _ensure_default_elevations(self, sections: list[SectionPreview]) -> None:
        sg_data = self._document.sg_data
        if sg_data is None or sg_data.num_xsects <= 0:
            return

        if len(sg_data.sects) < len(sections):
            apply_preview_to_sgfile(sg_data, sections, self._fsects_by_section)

        num_xsects = sg_data.num_xsects
        for section in sg_data.sects:
            if not section.alt or len(section.alt) < num_xsects:
                current = list(section.alt) if section.alt else []
                current.extend([0] * (num_xsects - len(current)))
                section.alt = current
            if not section.grade or len(section.grade) < num_xsects:
                current = list(section.grade) if section.grade else []
                current.extend([0] * (num_xsects - len(current)))
                section.grade = current

    def set_sections(
        self,
        sections: list[SectionPreview],
        start_finish_dlong: float | None = None,
        *,
        changed_indices: list[int] | None = None,
    ) -> None:
        self._clear_split_hover()

        old_sections = list(self._section_manager.sections)
        old_fsects = list(self._fsects_by_section)

        preserved_start_finish_dlong = start_finish_dlong
        if preserved_start_finish_dlong is None:
            preserved_start_finish_dlong = self._start_finish_dlong
        if preserved_start_finish_dlong is None:
            preserved_start_finish_dlong = self._current_start_finish_dlong()

        needs_rebuild = self._section_manager.set_sections(
            sections, changed_indices=changed_indices
        )
        self._realign_fsects_after_recalc(old_sections, old_fsects)

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
        self._ensure_default_elevations(sections)
        self._has_unsaved_changes = True
        if self._emit_sections_changed is not None:
            self._emit_sections_changed()
        self._context.request_repaint()
        self._bump_sg_version()

    def update_drag_preview(self, sections: list[SectionPreview]) -> None:
        if len(sections) != len(self._section_manager.sections):
            self.set_sections(sections)
            return

        self._clear_split_hover()
        updated = self._section_manager.update_drag_preview(sections)
        if not updated:
            return

        self._sampled_bounds = self._section_manager.sampled_bounds
        self._sampled_centerline = self._section_manager.sampled_centerline

        self._update_node_status()

        self._selection.update_context(
            self._section_manager.sections,
            self._track_length,
            self._section_manager.centerline_index,
            self._section_manager.sampled_dlongs,
        )
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
