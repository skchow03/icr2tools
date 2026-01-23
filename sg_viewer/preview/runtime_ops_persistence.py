from __future__ import annotations

from pathlib import Path

from icr2_core.trk.sg_classes import SGFile
from icr2_core.sg_elevation import sample_sg_elevation
from sg_viewer.preview.edit_session import apply_preview_to_sgfile
from sg_viewer.services import preview_loader_service
from sg_viewer.ui.elevation_profile import ElevationProfileData, ElevationSource
from sg_viewer.models.preview_fsection import PreviewFSection


class _RuntimePersistenceMixin:
    def _section_geometry_key(self, section: object) -> tuple:
        start = getattr(section, "start", None)
        end = getattr(section, "end", None)
        center = getattr(section, "center", None)
        return (
            getattr(section, "type_name", None),
            start,
            end,
            center,
            getattr(section, "radius", None),
            getattr(section, "sang1", None),
            getattr(section, "sang2", None),
            getattr(section, "eang1", None),
            getattr(section, "eang2", None),
        )

    def _realign_fsects_after_recalc(
        self,
        old_sections: list,
        old_fsects: list[list[PreviewFSection]],
    ) -> None:
        new_sections = list(self._section_manager.sections)
        if (
            not old_sections
            or not new_sections
            or len(old_sections) != len(new_sections)
            or len(old_fsects) != len(old_sections)
        ):
            return

        old_keys = [self._section_geometry_key(section) for section in old_sections]
        new_keys = [self._section_geometry_key(section) for section in new_sections]
        if old_keys == new_keys:
            return

        mapping: dict[tuple, list[list[PreviewFSection]]] = {}
        for key, fsects in zip(old_keys, old_fsects):
            mapping.setdefault(key, []).append(fsects)

        realigned: list[list[PreviewFSection]] = []
        for index, key in enumerate(new_keys):
            bucket = mapping.get(key, [])
            if bucket:
                realigned.append(bucket.pop(0))
            elif index < len(old_fsects):
                realigned.append(old_fsects[index])
            else:
                realigned.append([])

        self._fsects_by_section = realigned

    @property
    def has_unsaved_changes(self) -> bool:
        return self._has_unsaved_changes

    def apply_preview_to_sgfile(self) -> SGFile:
        if self._sgfile is None:
            raise ValueError("No SG file loaded.")
        return apply_preview_to_sgfile(
            self._sgfile,
            self._section_manager.sections,
            self._fsects_by_section,
        )

    def recalculate_dlongs(self) -> bool:
        try:
            sgfile = self.apply_preview_to_sgfile()
        except ValueError:
            return False

        old_sections = list(self._section_manager.sections)
        old_fsects = list(self._fsects_by_section)

        if self._document.sg_data is None:
            self._document.set_sg_data(sgfile)

        self._document.rebuild_dlongs(0, 0)
        self._realign_fsects_after_recalc(old_sections, old_fsects)
        return True

    def refresh_fsections_preview(self) -> bool:
        if self._sgfile is None or self._preview_data is None:
            return False

        try:
            sgfile = self.apply_preview_to_sgfile()
        except ValueError:
            return False

        self._suppress_document_dirty = True
        try:
            self._document.set_sg_data(sgfile, validate=False)
            self._document.rebuild_dlongs(0, 0)
        finally:
            self._suppress_document_dirty = False

        fsections = preview_loader_service.build_fsections(sgfile)
        object.__setattr__(self._preview_data, "fsections", fsections)
        self._context.request_repaint()
        return True

    def save_sg(self, path: Path) -> None:
        """Write the current SG (and any edits) to ``path``."""

        sgfile = self.apply_preview_to_sgfile()

        sgfile.output_sg(str(path))
        self._has_unsaved_changes = False

    def build_elevation_profile(
        self,
        xsect_index: int,
        samples_per_section: int = 24,
        show_trk: bool = False,
    ) -> ElevationProfileData | None:
        _ = show_trk
        if (
            self._sgfile is None
            or self._track_length is None
            or xsect_index < 0
            or xsect_index >= self._sgfile.num_xsects
        ):
            return None

        def _xsect_label(dlat_value: float) -> str:
            return f"X-Section {xsect_index} (DLAT {dlat_value:.0f})"

        if xsect_index >= len(self._sgfile.xsect_dlats):
            return None

        dlat_value = float(self._sgfile.xsect_dlats[xsect_index])

        if self._track_length <= 0:
            track_length = float(self._track_length or 0.0)
            track_length = track_length if track_length > 0 else 1.0
            return ElevationProfileData(
                dlongs=[0.0, track_length],
                sg_altitudes=[0.0, 0.0],
                trk_altitudes=None,
                section_ranges=[],
                track_length=track_length,
                xsect_label=_xsect_label(dlat_value),
                sources=(ElevationSource.SG,),
            )

        dlongs: list[float] = []
        section_ranges: list[tuple[float, float]] = []
        sg_altitudes = sample_sg_elevation(
            self._sgfile,
            xsect_index,
            resolution=samples_per_section,
        )
        trk_altitudes: list[float] | None = None
        sources = (ElevationSource.SG,)

        for sg_sect in self._sgfile.sects:
            sg_length = float(sg_sect.length)
            if sg_length <= 0:
                continue
            start_dlong = float(sg_sect.start_dlong)
            section_ranges.append((start_dlong, start_dlong + sg_length))

            for step in range(samples_per_section + 1):
                fraction = step / samples_per_section
                dlong = start_dlong + fraction * sg_length
                dlongs.append(dlong)

        return ElevationProfileData(
            dlongs=dlongs,
            sg_altitudes=sg_altitudes,
            trk_altitudes=trk_altitudes,
            section_ranges=section_ranges,
            track_length=float(self._track_length),
            xsect_label=_xsect_label(dlat_value),
            sources=sources,
        )

    def get_elevation_profile_bounds(
        self, samples_per_section: int = 24
    ) -> tuple[float, float] | None:
        if self._sgfile is None or self._track_length is None:
            return None

        num_xsects = self._sgfile.num_xsects
        if num_xsects <= 0:
            return None

        min_alt: float | None = None
        max_alt: float | None = None
        for xsect_index in range(num_xsects):
            altitudes = sample_sg_elevation(
                self._sgfile,
                xsect_index,
                resolution=samples_per_section,
            )
            if not altitudes:
                continue
            local_min = min(altitudes)
            local_max = max(altitudes)
            if min_alt is None or local_min < min_alt:
                min_alt = local_min
            if max_alt is None or local_max > max_alt:
                max_alt = local_max

        if min_alt is None or max_alt is None:
            return None

        if min_alt == max_alt:
            min_alt -= 1.0
            max_alt += 1.0

        padding = max(1.0, (max_alt - min_alt) * 0.05)
        return min_alt - padding, max_alt + padding
