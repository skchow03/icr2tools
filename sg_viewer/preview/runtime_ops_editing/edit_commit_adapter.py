from __future__ import annotations

import copy
import math
from dataclasses import replace

from icr2_core.sg_elevation import sg_xsect_altitude_grade_at
from sg_viewer.models.sg_model import SectionPreview
from sg_viewer.preview.edit_session import apply_preview_to_sgfile


class _RuntimeEditCommitAdapterMixin:
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

    def _recalculate_elevations_after_drag(
        self, affected_indices: list[int] | None = None
    ) -> bool:
        self._last_elevation_recalc_message = None
        if self._sgfile is None:
            self._last_elevation_recalc_message = "No SG file is loaded."
            return False

        if not self._section_manager.sections:
            self._last_elevation_recalc_message = "No sections are available."
            return False

        if self._refresh_section_dlongs_after_drag():
            if not self._section_manager.sections:
                self._last_elevation_recalc_message = (
                    "No sections are available after refreshing DLONGs."
                )
                return False

        old_sg = copy.deepcopy(self._sgfile)
        if not old_sg.sects or old_sg.num_xsects <= 0:
            self._last_elevation_recalc_message = (
                "The SG file has no sections or cross sections."
            )
            return False

        if any(not sect.alt or not sect.grade for sect in self._sgfile.sects):
            self._last_elevation_recalc_message = (
                "The SG file is missing elevation or grade data."
            )
            return False

        try:
            self.apply_preview_to_sgfile()
        except ValueError as exc:
            self._last_elevation_recalc_message = (
                f"Failed to apply preview geometry: {exc}"
            )
            return False

        num_xsects = old_sg.num_xsects
        sections_to_update = self._expanded_drag_indices(
            affected_indices, len(self._sgfile.sects)
        )
        updated = False
        missing_locations = 0
        processed_sections = 0
        if sections_to_update is None:
            indices = range(len(self._sgfile.sects))
        else:
            indices = sections_to_update
        for index in indices:
            if index < 0 or index >= len(self._sgfile.sects):
                continue
            processed_sections += 1
            section = self._sgfile.sects[index]
            start_dlong = float(getattr(section, "start_dlong", 0.0))
            length = float(getattr(section, "length", 0.0))
            end_dlong = start_dlong + length
            location = self._section_at_dlong(old_sg, end_dlong)
            if location is None:
                missing_locations += 1
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
                self._elevation_profile_alt_cache.clear()
                self._elevation_profile_dirty.clear()
            for xsect_idx in range(num_xsects):
                self._mark_xsect_bounds_dirty(xsect_idx)
        if updated and self._emit_sections_changed is not None:
            self._emit_sections_changed()
        if updated:
            self._last_elevation_recalc_message = "Recalculated elevation profile."
            return True
        if processed_sections > 0 and missing_locations == processed_sections:
            self._last_elevation_recalc_message = (
                "Unable to map updated sections to prior elevation data."
            )
            return False
        self._last_elevation_recalc_message = (
            "Elevation values already match the current geometry."
        )
        return True

    def recalculate_elevations(self, affected_indices: list[int] | None = None) -> bool:
        return self._recalculate_elevations_after_drag(affected_indices)

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

    def _update_source_section_ids_after_split(
        self,
        sections: list[SectionPreview],
        split_index: int,
        source_index: int,
    ) -> list[SectionPreview]:
        if source_index < 0:
            return sections

        updated_sections: list[SectionPreview] = []
        for sect in sections:
            current_source = getattr(sect, "source_section_id", -1)
            if current_source is not None and current_source > source_index:
                updated_sections.append(
                    replace(sect, source_section_id=current_source + 1)
                )
            else:
                updated_sections.append(sect)

        if split_index < len(updated_sections):
            updated_sections[split_index] = replace(
                updated_sections[split_index], source_section_id=source_index
            )
        if split_index + 1 < len(updated_sections):
            updated_sections[split_index + 1] = replace(
                updated_sections[split_index + 1], source_section_id=source_index + 1
            )

        return updated_sections

    def _commit_split(self) -> None:
        idx = self._split_hover_section_index
        point = self._split_hover_point

        if idx is None or point is None:
            return

        section = self._section_manager.sections[idx]
        source_index = getattr(section, "source_section_id", idx)
        if source_index is None or source_index < 0:
            source_index = idx
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
            self._split_xsect_elevations(source_index, split_fraction)
            sections = self._update_source_section_ids_after_split(
                sections, idx, source_index
            )
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
