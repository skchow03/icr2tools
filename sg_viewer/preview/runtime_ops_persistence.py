from __future__ import annotations

import copy
import logging
from pathlib import Path

from icr2_core.trk.sg_classes import SGFile
from icr2_core.sg_elevation import sample_sg_elevation, sample_sg_elevation_with_dlats
from sg_viewer.preview.edit_session import apply_preview_to_sgfile
from sg_viewer.services import preview_loader_service
from sg_viewer.ui.elevation_profile import ElevationProfileData, ElevationSource
from sg_viewer.models.preview_fsection import PreviewFSection

logger = logging.getLogger(__name__)


class _RuntimePersistenceMixin:
    def _profile_sgfile(self) -> SGFile | None:
        base = self._document.sg_data or self._sgfile
        if base is None:
            return None

        sgfile = copy.deepcopy(base)
        if self._section_manager.sections:
            try:
                apply_preview_to_sgfile(
                    sgfile,
                    self._section_manager.sections,
                    self._fsects_by_section,
                )
            except ValueError:
                pass
        return sgfile

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
        sgfile = apply_preview_to_sgfile(
            self._sgfile,
            self._section_manager.sections,
            self._fsects_by_section,
        )
        self._bump_sg_version()
        return sgfile

    def recalculate_dlongs(self) -> bool:
        try:
            sgfile = self.apply_preview_to_sgfile()
        except ValueError:
            return False

        old_sections = list(self._section_manager.sections)
        old_fsects = list(self._fsects_by_section)

        if self._document.sg_data is None:
            self._document.set_sg_data(sgfile)

        try:
            self._document.rebuild_dlongs(0, 0)
        except ValueError as exc:
            self._show_status(f"Unable to recalculate lengths: {exc}")
            logger.warning("Recalculate dlongs failed: %s", exc)
            return False
        self._elevation_profile_cache.clear()
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
            self._elevation_profile_cache.clear()
        except ValueError as exc:
            self._show_status(f"Unable to refresh Fsects preview: {exc}")
            logger.warning("Refresh fsections preview failed: %s", exc)
            return False
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
        samples_per_section: int = 10,
        show_trk: bool = False,
    ) -> ElevationProfileData | None:
        _ = show_trk
        sgfile = self._profile_sgfile()
        if (
            sgfile is None
            or self._track_length is None
            or xsect_index < 0
            or xsect_index >= sgfile.num_xsects
        ):
            return None

        def _xsect_label(dlat_value: float) -> str:
            return f"X-Section {xsect_index} (DLAT {dlat_value:.0f})"

        if xsect_index >= len(sgfile.xsect_dlats):
            return None

        dlats = [float(value) for value in sgfile.xsect_dlats]
        if xsect_index >= len(dlats):
            return None

        dlat_value = dlats[xsect_index]

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

        cache_key = (samples_per_section, self._sg_version)
        cached = self._elevation_profile_cache.get(cache_key)
        if cached is None:
            dlongs: list[float] = []
            section_ranges: list[tuple[float, float]] = []
            for sg_sect in sgfile.sects:
                sg_length = float(sg_sect.length)
                if sg_length <= 0:
                    continue
                start_dlong = float(sg_sect.start_dlong)
                section_ranges.append((start_dlong, start_dlong + sg_length))

                for step in range(samples_per_section + 1):
                    fraction = step / samples_per_section
                    dlong = start_dlong + fraction * sg_length
                    dlongs.append(dlong)
            self._elevation_profile_cache[cache_key] = (dlongs, section_ranges)
        else:
            dlongs, section_ranges = cached
        min_dlat = min(dlats)
        max_dlat = max(dlats)
        sg_altitudes = sample_sg_elevation_with_dlats(
            sgfile,
            xsect_index,
            dlats,
            min_dlat,
            max_dlat,
            resolution=samples_per_section,
        )
        trk_altitudes: list[float] | None = None
        sources = (ElevationSource.SG,)

        return ElevationProfileData(
            dlongs=list(dlongs),
            sg_altitudes=sg_altitudes,
            trk_altitudes=trk_altitudes,
            section_ranges=list(section_ranges),
            track_length=float(self._track_length),
            xsect_label=_xsect_label(dlat_value),
            sources=sources,
        )

    def get_elevation_profile_bounds(
        self, samples_per_section: int = 10
    ) -> tuple[float, float] | None:
        sgfile = self._profile_sgfile()
        if sgfile is None or self._track_length is None:
            return None

        cache_key = (samples_per_section, self._sg_version)

        num_xsects = sgfile.num_xsects
        if num_xsects <= 0:
            return None

        dlats = [float(value) for value in sgfile.xsect_dlats]
        if not dlats:
            return None

        min_dlat = min(dlats)
        max_dlat = max(dlats)

        per_xsect_cache = self._elevation_xsect_bounds_cache.setdefault(cache_key, {})
        dirty = self._elevation_xsect_bounds_dirty.setdefault(cache_key, set())
        missing = [idx for idx in range(num_xsects) if idx not in per_xsect_cache]
        if missing:
            dirty.update(missing)

        if not dirty and cache_key in self._elevation_bounds_cache:
            return self._elevation_bounds_cache[cache_key]

        for xsect_index in sorted(dirty):
            altitudes = sample_sg_elevation_with_dlats(
                sgfile,
                xsect_index,
                dlats,
                min_dlat,
                max_dlat,
                resolution=samples_per_section,
            )
            if not altitudes:
                per_xsect_cache[xsect_index] = None
                continue
            per_xsect_cache[xsect_index] = (min(altitudes), max(altitudes))
        dirty.clear()

        min_alt: float | None = None
        max_alt: float | None = None
        for xsect_index in range(num_xsects):
            cached = per_xsect_cache.get(xsect_index)
            if cached is None:
                continue
            local_min, local_max = cached
            if min_alt is None or local_min < min_alt:
                min_alt = local_min
            if max_alt is None or local_max > max_alt:
                max_alt = local_max

        if min_alt is None or max_alt is None:
            self._elevation_bounds_cache[cache_key] = None
            return None

        if min_alt == max_alt:
            min_alt -= 1.0
            max_alt += 1.0

        padding = max(1.0, (max_alt - min_alt) * 0.05)
        bounds = (min_alt - padding, max_alt + padding)
        self._elevation_bounds_cache[cache_key] = bounds
        return bounds
