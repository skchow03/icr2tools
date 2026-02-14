from __future__ import annotations

import copy

from sg_viewer.model.preview_fsection import PreviewFSection


class _RuntimeCoreCommitMixin:
    def _bump_sg_version(self) -> None:
        self._sg_version += 1
        self._elevation_bounds_cache.clear()
        self._elevation_xsect_bounds_cache.clear()
        self._elevation_xsect_bounds_dirty.clear()
        self._elevation_profile_cache.clear()
        self._elevation_profile_alt_cache.clear()
        self._elevation_profile_dirty.clear()

    def _split_fsects_by_section(self, index: int) -> None:
        original_fsects = (
            self._fsects_by_section[index] if index < len(self._fsects_by_section) else []
        )
        self._fsects_by_section[index] = copy.deepcopy(original_fsects)
        self._fsects_by_section.insert(index + 1, copy.deepcopy(original_fsects))

    def _delete_fsects_by_section(self, index: int) -> None:
        if 0 <= index < len(self._fsects_by_section):
            self._fsects_by_section.pop(index)

    def update_fsection_type(
        self,
        section_index: int,
        fsect_index: int,
        *,
        surface_type: int,
        type2: int,
    ) -> None:
        if section_index < 0 or section_index >= len(self._fsects_by_section):
            return
        fsects = list(self._fsects_by_section[section_index])
        if fsect_index < 0 or fsect_index >= len(fsects):
            return
        current = fsects[fsect_index]
        if current.surface_type == surface_type and current.type2 == type2:
            return
        fsects[fsect_index] = PreviewFSection(
            start_dlat=current.start_dlat,
            end_dlat=current.end_dlat,
            surface_type=surface_type,
            type2=type2,
        )
        self._fsects_by_section[section_index] = fsects
        self._has_unsaved_changes = True
        if self._emit_sections_changed is not None:
            self._emit_sections_changed()
        if not self.refresh_fsections_preview():
            self._context.request_repaint()

    def update_fsection_dlat(
        self,
        section_index: int,
        fsect_index: int,
        *,
        start_dlat: float | None = None,
        end_dlat: float | None = None,
        refresh_preview: bool = True,
        emit_sections_changed: bool = True,
    ) -> None:
        if section_index < 0 or section_index >= len(self._fsects_by_section):
            return
        fsects = list(self._fsects_by_section[section_index])
        if fsect_index < 0 or fsect_index >= len(fsects):
            return
        current = fsects[fsect_index]
        new_start = current.start_dlat if start_dlat is None else float(start_dlat)
        new_end = current.end_dlat if end_dlat is None else float(end_dlat)
        if current.start_dlat == new_start and current.end_dlat == new_end:
            return
        fsects[fsect_index] = PreviewFSection(
            start_dlat=new_start,
            end_dlat=new_end,
            surface_type=current.surface_type,
            type2=current.type2,
        )
        self._fsects_by_section[section_index] = fsects
        self._has_unsaved_changes = True
        if emit_sections_changed and self._emit_sections_changed is not None:
            self._emit_sections_changed()
        if refresh_preview:
            if not self.refresh_fsections_preview():
                self._context.request_repaint()

    def insert_fsection(
        self,
        section_index: int,
        insert_index: int,
        fsect: PreviewFSection,
    ) -> None:
        if section_index < 0 or section_index >= len(self._fsects_by_section):
            return
        fsects = list(self._fsects_by_section[section_index])
        if insert_index < 0:
            insert_index = 0
        if insert_index > len(fsects):
            insert_index = len(fsects)
        fsects.insert(insert_index, fsect)
        self._fsects_by_section[section_index] = fsects
        self._has_unsaved_changes = True
        if self._emit_sections_changed is not None:
            self._emit_sections_changed()
        if not self.refresh_fsections_preview():
            self._context.request_repaint()

    def delete_fsection(
        self,
        section_index: int,
        fsect_index: int,
    ) -> None:
        if section_index < 0 or section_index >= len(self._fsects_by_section):
            return
        fsects = list(self._fsects_by_section[section_index])
        if fsect_index < 0 or fsect_index >= len(fsects):
            return
        fsects.pop(fsect_index)
        self._fsects_by_section[section_index] = fsects
        self._has_unsaved_changes = True
        if self._emit_sections_changed is not None:
            self._emit_sections_changed()
        if not self.refresh_fsections_preview():
            self._context.request_repaint()

    def replace_all_fsects(
        self,
        fsects_by_section: list[list[PreviewFSection]],
    ) -> bool:
        section_count = len(self._section_manager.sections)
        if section_count != len(fsects_by_section):
            return False
        self._fsects_by_section = [list(fsects) for fsects in fsects_by_section]
        self._validate_section_fsects_alignment()
        self._has_unsaved_changes = True
        if self._emit_sections_changed is not None:
            self._emit_sections_changed()
        if not self.refresh_fsections_preview():
            self._context.request_repaint()
            return False
        return True

    def copy_section_fsects(
        self,
        source_index: int,
        target_index: int,
        *,
        edge: str | None = None,
    ) -> bool:
        if (
            source_index == target_index
            or source_index < 0
            or target_index < 0
            or source_index >= len(self._fsects_by_section)
            or target_index >= len(self._fsects_by_section)
        ):
            return False

        if edge in {"start", "end"}:
            edge_profile = self._fsect_edge_profile(source_index, edge)
            self._fsects_by_section[target_index] = copy.deepcopy(edge_profile)
        else:
            source_fsects = self._fsects_by_section[source_index]
            self._fsects_by_section[target_index] = copy.deepcopy(source_fsects)
        self._has_unsaved_changes = True
        if self._emit_sections_changed is not None:
            self._emit_sections_changed()
        if not self.refresh_fsections_preview():
            self._context.request_repaint()
        return True

    def set_xsect_definitions(self, entries: list[tuple[int | None, float]]) -> bool:
        try:
            self._document.set_xsect_definitions(entries)
        except (ValueError, IndexError):
            return False
        return True

    def set_section_xsect_altitude(
        self,
        section_id: int,
        xsect_index: int,
        altitude: float,
        *,
        validate: bool = True,
    ) -> bool:
        try:
            self._document.set_section_xsect_altitude(
                section_id, xsect_index, altitude, validate=validate
            )
        except (ValueError, IndexError):
            return False
        self._mark_xsect_bounds_dirty(xsect_index)
        self._mark_elevation_profile_sections_dirty(section_id, xsect_index)
        return True

    def set_section_xsect_grade(
        self,
        section_id: int,
        xsect_index: int,
        grade: float,
        *,
        validate: bool = True,
    ) -> bool:
        try:
            self._document.set_section_xsect_grade(
                section_id, xsect_index, grade, validate=validate
            )
        except (ValueError, IndexError):
            return False
        self._mark_xsect_bounds_dirty(xsect_index)
        self._mark_elevation_profile_sections_dirty(section_id, xsect_index)
        return True

    def copy_xsect_data_to_all(self, xsect_index: int) -> bool:
        try:
            self._document.copy_xsect_data_to_all(xsect_index)
        except (ValueError, IndexError):
            return False
        self._bump_sg_version()
        return True

    def offset_all_elevations(self, delta: float, *, validate: bool = True) -> bool:
        try:
            self._document.offset_all_elevations(delta, validate=validate)
        except (ValueError, IndexError):
            return False
        self._bump_sg_version()
        return True

    def flatten_all_elevations_and_grade(
        self,
        elevation: float,
        *,
        grade: float = 0.0,
        validate: bool = True,
    ) -> bool:
        try:
            self._document.flatten_all_elevations_and_grade(
                elevation,
                grade=grade,
                validate=validate,
            )
        except (ValueError, IndexError):
            return False
        self._bump_sg_version()
        return True
