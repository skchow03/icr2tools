from __future__ import annotations

from pathlib import Path

from PyQt5 import QtGui

from icr2_core.trk.trk_classes import TRKFile
from sg_viewer.geometry.topology import is_closed_loop, loop_length
from sg_viewer.model import selection
from sg_viewer.model.preview_fsection import PreviewFSection
from sg_viewer.model.sg_model import SectionPreview
from sg_viewer.preview.creation_controller import CreationController, CreationUpdate
from sg_viewer.preview.preview_defaults import create_empty_sgfile
from sg_viewer.services.preview_background import PreviewBackground
from sg_viewer.preview.transform import ViewTransform
from sg_viewer.model.preview_state import SgPreviewViewState
from sg_viewer.ui.preview_interaction import PreviewInteraction
from sg_viewer.ui.preview_section_manager import PreviewSectionManager
from sg_viewer.preview.runtime_ops.base_context import Point, logger


class _RuntimeCorePreviewMixin:
    @property
    def preview_fsections(self) -> list[PreviewFSection]:
        if self._preview_data is None:
            return []
        return list(self._preview_data.fsections)

    def get_section_fsects(self, section_index: int | None) -> list[PreviewFSection]:
        if section_index is None:
            return []
        if section_index < 0 or section_index >= len(self._fsects_by_section):
            return []
        return list(self._fsects_by_section[section_index])

    def set_status(self, text: str) -> None:
        self._status_message = text
        self._context.request_repaint()

    def set_status_text(self, text: str) -> None:
        self.set_status(text)

    def last_elevation_recalc_message(self) -> str | None:
        return self._last_elevation_recalc_message

    def request_repaint(self) -> None:
        self._context.request_repaint()

    def log_debug(self, message: str, *args: object) -> None:
        logger.debug(message, *args)

    def enable_trk_overlay(self) -> TRKFile | None:
        trk = self._trk_overlay.enable(self._preview_data)
        self._trk = trk
        return trk

    def start_new_track(self) -> None:
        self.clear("New track ready. Click New Straight to start drawing.")
        self._sgfile = create_empty_sgfile()
        self._preview_data = None
        self._trk_overlay.disable(None)
        self._suppress_document_dirty = True
        self._document.set_sg_data(self._sgfile)
        self._suppress_document_dirty = False
        self._set_default_view_bounds()
        self._sampled_centerline = []
        self._track_length = 0.0
        self._start_finish_dlong = None
        self._fsects_by_section = []
        self._has_unsaved_changes = False
        self._update_fit_scale()
        self._context.request_repaint()

    def load_background_image(self, path: Path) -> None:
        self._background.load_image(path)
        self._fit_view_to_background()
        self._context.request_repaint()

    def clear_background_image(self) -> None:
        self._background.clear()
        self._context.request_repaint()

    def begin_new_straight(self) -> bool:
        self.cancel_split_section()
        update = self._creation_controller.begin_new_straight(
            bool(self._sampled_bounds)
        )
        self._apply_creation_update(update)
        return update.handled

    def begin_new_curve(self) -> bool:
        self.cancel_split_section()
        update = self._creation_controller.begin_new_curve(bool(self._sampled_bounds))
        self._apply_creation_update(update)
        return update.handled

    def cancel_creation(self) -> None:
        update = self._creation_controller.deactivate_creation()
        update.repaint = True
        self._apply_creation_update(update)

    def set_background_settings(
        self, scale_500ths_per_px: float, origin: Point
    ) -> None:
        self._background.scale_500ths_per_px = scale_500ths_per_px
        self._background.world_xy_at_image_uv_00 = origin
        self._fit_view_to_background()
        self._context.request_repaint()

    def get_background_settings(self) -> tuple[float, Point]:
        return (
            self._background.scale_500ths_per_px,
            self._background.world_xy_at_image_uv_00,
        )

    def _background_bounds(self) -> tuple[float, float, float, float] | None:
        return self._background.bounds()

    def _combine_bounds_with_background(
        self, bounds: tuple[float, float, float, float]
    ) -> tuple[float, float, float, float]:
        return self._viewport.combine_bounds_with_background(bounds)

    def _fit_view_to_background(self) -> None:
        if self._drag_transform_active:
            return
        active_bounds = self._transform_controller.fit_view_to_background(
            self._section_manager.sampled_bounds, self._widget_size()
        )
        if active_bounds is None:
            return

        self._section_manager.sampled_bounds = active_bounds
        self._sampled_bounds = active_bounds

    def get_background_image_path(self) -> Path | None:
        return self._background.image_path

    def has_background_image(self) -> bool:
        return self._background.image is not None

    @property
    def background(self) -> PreviewBackground:
        return self._background

    @property
    def section_manager(self) -> PreviewSectionManager:
        return self._section_manager

    @property
    def selection_manager(self) -> selection.SelectionManager:
        return self._selection

    @property
    def interaction(self) -> PreviewInteraction:
        return self._interaction

    @property
    def creation_controller(self) -> CreationController:
        return self._creation_controller

    @property
    def show_curve_markers(self) -> bool:
        return self._show_curve_markers

    @property
    def show_axes(self) -> bool:
        return self._show_axes

    @property
    def show_sg_fsects(self) -> bool:
        return self._show_sg_fsects

    @property
    def show_mrk_notches(self) -> bool:
        return self._show_mrk_notches

    @property
    def selected_mrk_wall(self) -> tuple[int, int, int]:
        return self._selected_mrk_wall

    @property
    def highlighted_mrk_walls(self) -> tuple[tuple[int, int, int, int, str], ...]:
        return self._highlighted_mrk_walls

    @property
    def show_tsd_lines(self) -> bool:
        return self._show_tsd_lines

    @property
    def show_tsd_selected_section_only(self) -> bool:
        return self._show_tsd_selected_section_only

    @property
    def tsd_lines(self):
        return self._tsd_lines

    @property
    def tsd_palette(self):
        return self._tsd_palette

    @property
    def show_xsect_dlat_line(self) -> bool:
        return self._show_xsect_dlat_line

    @property
    def show_background_image(self) -> bool:
        return self._show_background_image

    @property
    def track_opacity(self) -> float:
        return self._track_opacity


    @property
    def integrity_boundary_violation_points(self) -> tuple[Point, ...]:
        return self._integrity_boundary_violation_points

    @property
    def background_brightness(self) -> float:
        return self._background.brightness_pct

    @property
    def selected_xsect_dlat(self) -> float | None:
        if self._selected_xsect_index is None or self._sgfile is None:
            return None
        if self._selected_xsect_index < 0:
            return None
        if self._selected_xsect_index >= len(self._sgfile.xsect_dlats):
            return None
        return float(self._sgfile.xsect_dlats[self._selected_xsect_index])

    @property
    def start_finish_mapping(self) -> tuple[Point, Point, Point] | None:
        return self._start_finish_mapping

    @property
    def status_message(self) -> str:
        return self._status_message

    @property
    def sg_preview_model(self):
        return self._sg_preview_model

    @property
    def sg_preview_view_state(self) -> SgPreviewViewState:
        return self._sg_preview_view_state

    def sg_preview_transform(self, widget_height: int) -> ViewTransform | None:
        widget_size = self._widget_size()
        transform = self.current_transform(widget_size)
        if transform is None:
            return None
        scale, offsets = transform
        return ViewTransform(scale=scale, offset=(offsets[0], widget_height - offsets[1]))

    @property
    def split_section_mode(self) -> bool:
        return self._split_section_mode

    @property
    def split_hover_point(self) -> Point | None:
        return self._split_hover_point

    def _apply_creation_update(self, update: CreationUpdate) -> None:
        if update is None:
            return
        if update.stop_panning:
            self._stop_panning()
        if update.status_changed:
            self._status_message = self._creation_controller.status_text
        if update.straight_mode_changed:
            if self._creation_controller.straight_active:
                self._set_delete_section_active(False)
                self.cancel_split_section()
                self._transform_controller.lock_user_transform(self._widget_size())
            if self._emit_new_straight_mode_changed is not None:
                self._emit_new_straight_mode_changed(
                    self._creation_controller.straight_active
                )
        if update.curve_mode_changed:
            if self._creation_controller.curve_active:
                self._set_delete_section_active(False)
                self.cancel_split_section()
                self._transform_controller.lock_user_transform(self._widget_size())
            if self._emit_new_curve_mode_changed is not None:
                self._emit_new_curve_mode_changed(
                    self._creation_controller.curve_active
                )
        if update.finalize_straight:
            self._finalize_new_straight()
        if update.finalize_curve:
            self._finalize_new_curve()
        if update.repaint:
            self._context.request_repaint()

    def _on_selection_changed(self, selection_value: object) -> None:
        if self._emit_selected_section_changed is not None:
            self._emit_selected_section_changed(selection_value)
        self._context.request_repaint()

    def get_section_set(self) -> tuple[list[SectionPreview], float | None]:
        track_length = (
            float(self._track_length) if self._track_length is not None else None
        )
        return list(self._section_manager.sections), track_length

    def track_length_message(self) -> str:
        sections = self._section_manager.sections
        if not sections or not is_closed_loop(sections):
            return "Complete the loop to show track length"

        try:
            total_length = loop_length(sections)
        except ValueError:
            return "Complete the loop to show track length"

        miles = total_length / (500.0 * 12 * 5280)
        return (
            f"Track length: {total_length:.0f} DLONG (500ths) — {miles:.3f} miles"
        )

    def set_trk_comparison(self, trk: TRKFile | None) -> None:
        self._trk_overlay.set_trk_comparison(trk)
        self._trk = trk

    def set_show_curve_markers(self, visible: bool) -> None:
        self._show_curve_markers = visible
        self._context.request_repaint()

    def set_show_axes(self, visible: bool) -> None:
        self._show_axes = visible
        self._context.request_repaint()

    def set_show_background_image(self, visible: bool) -> None:
        self._show_background_image = visible
        self._context.request_repaint()

    def set_show_sg_fsects(self, visible: bool) -> None:
        self._show_sg_fsects = visible
        self._context.request_repaint()

    def set_show_mrk_notches(self, visible: bool) -> None:
        self._show_mrk_notches = visible
        self._context.request_repaint()

    def set_show_tsd_lines(self, visible: bool) -> None:
        self._show_tsd_lines = visible
        self._context.request_repaint()

    def set_show_tsd_selected_section_only(self, selected_only: bool) -> None:
        self._show_tsd_selected_section_only = selected_only
        self._context.request_repaint()

    def set_tsd_lines(self, lines) -> None:
        self._tsd_lines = tuple(lines)
        self._context.request_repaint()

    def set_tsd_palette(self, palette) -> None:
        self._tsd_palette = tuple(palette)
        self._context.request_repaint()

    def set_selected_mrk_wall(self, boundary_index: int, section_index: int, wall_index: int) -> None:
        self._selected_mrk_wall = (
            max(0, int(boundary_index)),
            max(0, int(section_index)),
            max(0, int(wall_index)),
        )
        self._context.request_repaint()

    def set_highlighted_mrk_walls(self, entries: list[tuple[int, int, int, int, str]] | tuple[tuple[int, int, int, int, str], ...]) -> None:
        normalized: list[tuple[int, int, int, int, str]] = []
        for boundary_index, section_index, start_wall, wall_count, color in entries:
            parsed = QtGui.QColor(color)
            resolved = parsed.name().upper() if parsed.isValid() else "#FFFF00"
            normalized.append((
                max(0, int(boundary_index)),
                max(0, int(section_index)),
                max(0, int(start_wall)),
                max(0, int(wall_count)),
                resolved,
            ))
        self._highlighted_mrk_walls = tuple(normalized)
        self._context.request_repaint()

    def set_show_xsect_dlat_line(self, visible: bool) -> None:
        self._show_xsect_dlat_line = visible
        self._context.request_repaint()


    def set_integrity_boundary_violation_points(self, points: list[Point] | tuple[Point, ...]) -> None:
        self._integrity_boundary_violation_points = tuple((float(point[0]), float(point[1])) for point in points)
        self._context.request_repaint()

    def clear_integrity_boundary_violation_points(self) -> None:
        if not self._integrity_boundary_violation_points:
            return
        self._integrity_boundary_violation_points = ()
        self._context.request_repaint()

    def set_track_opacity(self, opacity: float) -> None:
        self._track_opacity = max(0.0, min(1.0, float(opacity)))
        self._context.request_repaint()

    def set_background_brightness(self, brightness_pct: float) -> None:
        self._background.brightness_pct = max(-100.0, min(100.0, float(brightness_pct)))
        self._context.request_repaint()

    def set_selected_xsect_index(self, index: int | None) -> None:
        self._selected_xsect_index = int(index) if index is not None else None
        self._context.request_repaint()

    def activate_set_start_finish_mode(self) -> None:
        """Backward-compatible alias for setting start/finish."""
        self.set_start_finish_at_selected_section()

    def select_next_section(self) -> None:
        if not self._selection.sections:
            return

        if self._selection.selected_section_index is None:
            self._selection.set_selected_section(0)
            return

        next_index = (self._selection.selected_section_index + 1) % len(
            self._selection.sections
        )
        self._selection.set_selected_section(next_index)

    def select_previous_section(self) -> None:
        if not self._selection.sections:
            return

        if self._selection.selected_section_index is None:
            self._selection.set_selected_section(len(self._selection.sections) - 1)
            return

        prev_index = (self._selection.selected_section_index - 1) % len(
            self._selection.sections
        )
        self._selection.set_selected_section(prev_index)

    def get_section_headings(self) -> list[selection.SectionHeadingData]:
        return self._selection.get_section_headings()

    def get_xsect_metadata(self) -> list[tuple[int, float]]:
        if self._sgfile is None:
            return []
        return [(idx, float(dlat)) for idx, dlat in enumerate(self._sgfile.xsect_dlats)]

    def get_section_range(self, index: int) -> tuple[float, float] | None:
        if (
            not self._section_manager.sections
            or index < 0
            or index >= len(self._section_manager.sections)
        ):
            return None
        start = float(self._section_manager.sections[index].start_dlong)
        end = start + float(self._section_manager.sections[index].length)
        return start, end

    def get_section_xsect_values(
        self, section_id: int, xsect_index: int
    ) -> tuple[int | None, int | None]:
        sg_data = self._document.sg_data
        if (
            sg_data is None
            or section_id < 0
            or section_id >= len(sg_data.sects)
            or xsect_index < 0
            or xsect_index >= sg_data.num_xsects
        ):
            return None, None

        section = sg_data.sects[section_id]
        altitude = section.alt[xsect_index] if xsect_index < len(section.alt) else None
        grade = section.grade[xsect_index] if xsect_index < len(section.grade) else None
        return altitude, grade

    def get_section_xsect_altitudes(self, section_id: int) -> list[int | None]:
        sg_data = self._document.sg_data
        if sg_data is None or section_id < 0 or section_id >= len(sg_data.sects):
            return []

        section = sg_data.sects[section_id]
        num_xsects = sg_data.num_xsects
        altitudes: list[int | None] = []
        for idx in range(num_xsects):
            altitudes.append(section.alt[idx] if idx < len(section.alt) else None)
        return altitudes

    def get_section_xsect_grades(self, section_id: int) -> list[int | None]:
        sg_data = self._document.sg_data
        if sg_data is None or section_id < 0 or section_id >= len(sg_data.sects):
            return []

        section = sg_data.sects[section_id]
        num_xsects = sg_data.num_xsects
        grades: list[int | None] = []
        for idx in range(num_xsects):
            grades.append(section.grade[idx] if idx < len(section.grade) else None)
        return grades
