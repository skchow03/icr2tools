from __future__ import annotations

import logging
from pathlib import Path

from icr2_core.trk.sg_classes import SGFile
from sg_viewer.preview.sg_overlay_builder import build_sg_preview_model
from sg_viewer.model.sg_model import PreviewData
from sg_viewer.services import preview_loader_service


logger = logging.getLogger(__name__)


class _RuntimeLoadingMixin:
    def clear(self, message: str | None = None) -> None:
        self._controller.clear(message)
        self._preview_data = None
        self._trk_overlay.disable(None)
        self._suppress_document_dirty = True
        self._fsects_by_section = []
        self._document.set_sg_data(None)
        self._suppress_document_dirty = False
        self._bump_sg_version()
        self._section_manager.reset()
        self._sampled_centerline = []
        self._sampled_bounds = None
        self._start_finish_dlong = None
        self._start_finish_mapping = None
        self._disconnected_nodes.clear()
        self._apply_creation_update(self._creation_controller.reset())
        self.cancel_split_section()
        self._editor.reset()
        self._interaction.reset()
        self._interaction_state.reset()
        self._status_message = message or "Select an SG file to begin."
        self._selection.reset([], None, None, [])
        self._set_default_view_bounds()
        self._update_node_status()
        self._sg_preview_model = None
        self._has_unsaved_changes = False
        self._update_fit_scale()
        self._context.request_repaint()

    def _set_default_view_bounds(self) -> None:
        default_bounds = self._viewport.default_bounds()
        self._section_manager.sampled_bounds = default_bounds
        self._sampled_bounds = default_bounds

    def _on_section_changed(self, section_id: int) -> None:
        _ = section_id
        self._refresh_from_document(mark_unsaved=not self._suppress_document_dirty)

    def _on_geometry_changed(self) -> None:
        self._bump_sg_version()
        self._refresh_from_document(mark_unsaved=not self._suppress_document_dirty)

    def _on_elevation_changed(self, section_id: int) -> None:
        sg_data = self._document.sg_data
        if sg_data is None:
            return
        for xsect_index in range(int(sg_data.num_xsects)):
            self._mark_xsect_bounds_dirty(xsect_index)
            self._mark_elevation_profile_sections_dirty(section_id, xsect_index)
        if not self._suppress_document_dirty:
            self._has_unsaved_changes = True
            if self._emit_sections_changed is not None:
                self._emit_sections_changed()
        self._context.request_repaint()

    def _on_elevations_bulk_changed(self) -> None:
        sg_data = self._document.sg_data
        if sg_data is None:
            return
        for xsect_index in range(int(sg_data.num_xsects)):
            self._mark_xsect_bounds_dirty(xsect_index)
            self._mark_elevation_profile_all_sections_dirty(xsect_index)
        if not self._suppress_document_dirty:
            self._has_unsaved_changes = True
            if self._emit_sections_changed is not None:
                self._emit_sections_changed()
        self._context.request_repaint()

    # ------------------------------------------------------------------
    # Loading
    # ------------------------------------------------------------------
    def load_sg_file(self, path: Path) -> None:
        self.cancel_split_section()
        self._last_load_warnings = []
        data = self._controller.load_sg_file(path)
        if data is None:
            self.clear()
            return

        self._load_preview_data(data)

    def load_sg_data(self, sgfile: SGFile, *, status_message: str) -> None:
        self.cancel_split_section()
        self._last_load_warnings = []
        data = preview_loader_service.load_preview_from_sgfile(
            sgfile,
            status_message=status_message,
        )
        self._load_preview_data(data)

    def _load_preview_data(self, data: PreviewData) -> None:

        if data.sgfile is not None:
            logger.debug(
                "Loaded SG preview: sections=%d num_xsects=%s",
                len(data.sgfile.sects),
                getattr(data.sgfile, "num_xsects", None),
            )
        self._preview_data = data
        self._sgfile = data.sgfile
        self._trk = data.trk
        self._sampled_centerline = list(data.sampled_centerline)
        self._sampled_bounds = data.sampled_bounds
        self._track_length = data.track_length
        self._fsects_by_section = preview_loader_service.build_fsects_by_section(
            data.sgfile
        )
        self._trk_overlay.sync_from_preview(data)
        self._disconnected_nodes = set()
        self._apply_creation_update(self._creation_controller.reset())
        self._status_message = data.status_message
        self._selection.reset(
            [],
            None,
            None,
            [],
        )
        self._start_finish_dlong = None
        self._suppress_document_dirty = True
        self._document.set_sg_data(data.sgfile)
        self._last_load_warnings = self._document.last_validation_warnings()
        self._suppress_document_dirty = False
        self._bump_sg_version()
        self._update_fit_scale()
        self._has_unsaved_changes = False
        self._context.request_repaint()

    def last_load_warnings(self) -> list[str]:
        return list(self._last_load_warnings)

    def refresh_geometry(self) -> None:
        self._refresh_from_document(mark_unsaved=True)

    def _refresh_from_document(self, *, mark_unsaved: bool) -> None:
        self._derived_geometry.rebuild_if_needed()

        sections = self._derived_geometry.sections
        sampled_bounds = (
            self._derived_geometry.sampled_bounds or self._viewport.default_bounds()
        )

        self._section_manager.load_sections(
            sections=sections,
            section_endpoints=self._derived_geometry.section_endpoints,
            sampled_centerline=self._derived_geometry.sampled_centerline,
            sampled_dlongs=self._derived_geometry.sampled_dlongs,
            sampled_bounds=sampled_bounds,
            centerline_index=self._derived_geometry.centerline_index,
        )
        self._sampled_bounds = self._section_manager.sampled_bounds
        self._sampled_centerline = self._section_manager.sampled_centerline
        self._track_length = self._derived_geometry.track_length
        self._start_finish_mapping = self._derived_geometry.start_finish_mapping
        if self._track_length <= 0:
            self._start_finish_dlong = None
        elif self._start_finish_dlong is None:
            self._start_finish_dlong = 0.0

        self._update_node_status()
        self._selection.update_context(
            self._section_manager.sections,
            self._track_length,
            self._section_manager.centerline_index,
            self._section_manager.sampled_dlongs,
        )
        self._sg_preview_model = build_sg_preview_model(self._document)
        if len(self._section_manager.sections) != len(self._fsects_by_section):
            if self._document.sg_data is not None:
                self._fsects_by_section = preview_loader_service.build_fsects_by_section(
                    self._document.sg_data
                )
            if len(self._section_manager.sections) != len(self._fsects_by_section):
                logger.warning(
                    "Fsect count desync; realigning fsects (%d) to sections (%d).",
                    len(self._fsects_by_section),
                    len(self._section_manager.sections),
                )
                desired_count = len(self._section_manager.sections)
                if len(self._fsects_by_section) > desired_count:
                    self._fsects_by_section = self._fsects_by_section[:desired_count]
                else:
                    self._fsects_by_section.extend(
                        [[] for _ in range(desired_count - len(self._fsects_by_section))]
                    )
        self._validate_section_fsects_alignment()
        if mark_unsaved:
            self._has_unsaved_changes = True
        if self._emit_sections_changed is not None:
            self._emit_sections_changed()
        self._context.request_repaint()
