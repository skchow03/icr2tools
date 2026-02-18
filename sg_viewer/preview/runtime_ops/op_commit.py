from __future__ import annotations

import copy

from sg_viewer.model.preview_fsection import PreviewFSection


class _RuntimeCoreCommitMixin:


    def _snapshot_fsects(self) -> list[list[PreviewFSection]]:
        return [copy.deepcopy(fsects) for fsects in self._fsects_by_section]

    def _snapshot_elevation_state(self) -> dict[str, object] | None:
        sg_data = self._document.sg_data
        if sg_data is None:
            return None
        header = list(getattr(sg_data, "header", []))
        return {
            "num_xsects": int(getattr(sg_data, "num_xsects", 0)),
            "xsect_dlats": list(getattr(sg_data, "xsect_dlats", [])),
            "header": header,
            "sections": [
                {
                    "alt": list(getattr(section, "alt", [])),
                    "grade": list(getattr(section, "grade", [])),
                }
                for section in getattr(sg_data, "sects", [])
            ],
        }

    def _snapshot_track_state(
        self,
    ) -> tuple[
        list[list[PreviewFSection]],
        dict[str, object] | None,
        dict[str, object] | None,
    ]:
        return (
            self._snapshot_fsects(),
            self._snapshot_elevation_state(),
            self._snapshot_topology_state(),
        )

    def _snapshot_topology_state(self) -> dict[str, object] | None:
        return {
            "sections": copy.deepcopy(list(self._section_manager.sections)),
            "start_finish_dlong": self._start_finish_dlong,
        }

    def _restore_track_state(
        self,
        snapshot: tuple[
            list[list[PreviewFSection]],
            dict[str, object] | None,
            dict[str, object] | None,
        ]
        | tuple[list[list[PreviewFSection]], dict[str, object] | None],
    ) -> None:
        if len(snapshot) == 2:
            fsects, elevation_state = snapshot
            topology_state = None
        else:
            fsects, elevation_state, topology_state = snapshot
        self._fsects_by_section = fsects
        self._restore_topology_state(topology_state)
        self._validate_section_fsects_alignment()
        self._restore_elevation_state(elevation_state)

    def _restore_topology_state(self, state: dict[str, object] | None) -> None:
        if not isinstance(state, dict):
            return

        sections = state.get("sections")
        if not isinstance(sections, list):
            return

        self._clear_split_hover()
        self._section_manager.set_sections(copy.deepcopy(sections))
        self._sampled_bounds = self._section_manager.sampled_bounds
        self._sampled_centerline = self._section_manager.sampled_centerline
        if self._section_manager.sampled_dlongs:
            self._track_length = self._section_manager.sampled_dlongs[-1]
        self._update_start_finish_mapping(state.get("start_finish_dlong"))
        self._update_node_status()
        self._selection.update_context(
            self._section_manager.sections,
            self._track_length,
            self._section_manager.centerline_index,
            self._section_manager.sampled_dlongs,
        )

        if self._sgfile is not None:
            try:
                self.apply_preview_to_sgfile()
                self._document.set_sg_data(self._sgfile, validate=False)
            except Exception:
                pass

    def _restore_elevation_state(self, state: dict[str, object] | None) -> None:
        if state is None:
            return
        sg_data = self._document.sg_data
        if sg_data is None:
            return

        sections = list(getattr(sg_data, "sects", []))
        snapshot_sections = list(state.get("sections", []))
        if len(sections) != len(snapshot_sections):
            return

        sg_data.num_xsects = int(state.get("num_xsects", sg_data.num_xsects))
        if len(getattr(sg_data, "header", [])) > 5:
            header = list(state.get("header", []))
            if len(header) > 5:
                sg_data.header[5] = int(header[5])
            else:
                sg_data.header[5] = int(sg_data.num_xsects)

        xsect_dlats = state.get("xsect_dlats", [])
        dtype = getattr(getattr(sg_data, "xsect_dlats", None), "dtype", None)
        if dtype is not None:
            try:
                import numpy as np

                sg_data.xsect_dlats = np.array(xsect_dlats, dtype=dtype)
            except Exception:
                sg_data.xsect_dlats = list(xsect_dlats)
        else:
            sg_data.xsect_dlats = list(xsect_dlats)

        for section, snapshot_section in zip(sections, snapshot_sections):
            if not isinstance(snapshot_section, dict):
                continue
            section.alt = list(snapshot_section.get("alt", []))
            section.grade = list(snapshot_section.get("grade", []))

    def _record_fsect_history(self) -> None:
        if self._suspend_fsect_history:
            return
        self._fsect_undo_stack.append(self._snapshot_track_state())
        self._fsect_redo_stack.clear()

    def begin_fsect_edit_session(self) -> None:
        if self._fsect_edit_session_active:
            return
        self._fsect_edit_session_active = True
        self._fsect_edit_session_snapshot = self._snapshot_fsects()
        self._fsect_edit_session_elevation_snapshot = self._snapshot_elevation_state()

    def commit_fsect_edit_session(self) -> None:
        if not self._fsect_edit_session_active:
            return
        before = self._fsect_edit_session_snapshot
        elevation_before = self._fsect_edit_session_elevation_snapshot
        self._fsect_edit_session_active = False
        self._fsect_edit_session_snapshot = None
        self._fsect_edit_session_elevation_snapshot = None
        if before is None:
            return
        after = self._snapshot_fsects()
        if before == after and elevation_before == self._snapshot_elevation_state():
            return
        if self._suspend_fsect_history:
            return
        self._fsect_undo_stack.append((before, elevation_before, self._snapshot_topology_state()))
        self._fsect_redo_stack.clear()

    def clear_fsect_history(self) -> None:
        if self._suspend_fsect_history:
            return
        self._fsect_undo_stack.clear()
        self._fsect_redo_stack.clear()
        self._fsect_edit_session_snapshot = None
        self._fsect_edit_session_elevation_snapshot = None
        self._fsect_edit_session_active = False

    def undo_fsect_edit(self) -> bool:
        if not self._fsect_undo_stack:
            return False
        self._fsect_redo_stack.append(self._snapshot_track_state())
        restored = self._fsect_undo_stack.pop()
        self._suspend_fsect_history = True
        try:
            self._restore_track_state(restored)
            self._has_unsaved_changes = True
            if self._emit_sections_changed is not None:
                self._emit_sections_changed()
            if not self.refresh_fsections_preview():
                self._context.request_repaint()
        finally:
            self._suspend_fsect_history = False
        return True

    def redo_fsect_edit(self) -> bool:
        if not self._fsect_redo_stack:
            return False
        self._fsect_undo_stack.append(self._snapshot_track_state())
        restored = self._fsect_redo_stack.pop()
        self._suspend_fsect_history = True
        try:
            self._restore_track_state(restored)
            self._has_unsaved_changes = True
            if self._emit_sections_changed is not None:
                self._emit_sections_changed()
            if not self.refresh_fsections_preview():
                self._context.request_repaint()
        finally:
            self._suspend_fsect_history = False
        return True

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
        self._record_fsect_history()
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
        if not self._fsect_edit_session_active:
            self._record_fsect_history()
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
        self._record_fsect_history()
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
        self._record_fsect_history()
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
        self._record_fsect_history()
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
            self._record_fsect_history()
            self._fsects_by_section[target_index] = copy.deepcopy(edge_profile)
        else:
            source_fsects = self._fsects_by_section[source_index]
            self._record_fsect_history()
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
        if not self._fsect_edit_session_active:
            self._record_fsect_history()
        try:
            self._document.set_section_xsect_altitude(
                section_id, xsect_index, altitude, validate=validate
            )
        except (ValueError, IndexError):
            if self._fsect_undo_stack:
                self._fsect_undo_stack.pop()
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
        if not self._fsect_edit_session_active:
            self._record_fsect_history()
        try:
            self._document.set_section_xsect_grade(
                section_id, xsect_index, grade, validate=validate
            )
        except (ValueError, IndexError):
            if self._fsect_undo_stack:
                self._fsect_undo_stack.pop()
            return False
        self._mark_xsect_bounds_dirty(xsect_index)
        self._mark_elevation_profile_sections_dirty(section_id, xsect_index)
        return True

    def copy_xsect_data_to_all(self, xsect_index: int) -> bool:
        self._record_fsect_history()
        try:
            self._document.copy_xsect_data_to_all(xsect_index)
        except (ValueError, IndexError):
            if self._fsect_undo_stack:
                self._fsect_undo_stack.pop()
            return False
        self._bump_sg_version()
        return True

    def offset_all_elevations(self, delta: float, *, validate: bool = True) -> bool:
        self._record_fsect_history()
        try:
            self._document.offset_all_elevations(delta, validate=validate)
        except (ValueError, IndexError):
            if self._fsect_undo_stack:
                self._fsect_undo_stack.pop()
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
        self._record_fsect_history()
        try:
            self._document.flatten_all_elevations_and_grade(
                elevation,
                grade=grade,
                validate=validate,
            )
        except (ValueError, IndexError):
            if self._fsect_undo_stack:
                self._fsect_undo_stack.pop()
            return False
        self._bump_sg_version()
        return True
