from __future__ import annotations

from pathlib import Path

from icr2_core.trk.sg_classes import SGFile
from icr2_core.sg_elevation import sample_sg_elevation
from sg_viewer.preview.edit_session import apply_preview_to_sgfile
from sg_viewer.services import preview_loader_service
from sg_viewer.ui.elevation_profile import ElevationProfileData, ElevationSource


class _RuntimePersistenceMixin:
    @property
    def has_unsaved_changes(self) -> bool:
        return self._has_unsaved_changes

    def apply_preview_to_sgfile(self) -> SGFile:
        if self._sgfile is None:
            raise ValueError("No SG file loaded.")
        return apply_preview_to_sgfile(self._sgfile, self._section_manager.sections)

    def recalculate_dlongs(self) -> bool:
        try:
            sgfile = self.apply_preview_to_sgfile()
        except ValueError:
            return False

        if self._document.sg_data is None:
            self._document.set_sg_data(sgfile)

        self._document.rebuild_dlongs(0, 0)
        return True

    def refresh_fsections_preview(self) -> bool:
        if self._sgfile is None or self._preview_data is None:
            return False

        try:
            self.apply_preview_to_sgfile()
        except ValueError:
            return False

        fsections = preview_loader_service.build_fsections(self._sgfile)
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
