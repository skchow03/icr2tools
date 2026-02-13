from __future__ import annotations

from icr2_core.trk.trk_classes import TRKFile
from icr2_core.trk.trk_utils import get_cline_pos
from track_viewer.geometry import project_point_to_centerline

from sg_viewer.geometry.centerline_utils import compute_centerline_normal_and_tangent
from sg_viewer.model.sg_model import PreviewData
from sg_viewer.services import preview_loader_service

Point = tuple[float, float]


class TrkOverlayController:
    def __init__(self) -> None:
        self._trk: TRKFile | None = None
        self._cline: list[Point] | None = None

    def enable(self, preview_data: PreviewData | None) -> TRKFile | None:
        if preview_data is None:
            return None

        if preview_data.trk is None or preview_data.cline is None:
            preview_loader_service.enable_trk_overlay(preview_data)

        self._trk = preview_data.trk
        self._cline = preview_data.cline
        return self._trk

    def disable(self, preview_data: PreviewData | None) -> None:
        if preview_data is not None:
            object.__setattr__(preview_data, "trk", None)
            object.__setattr__(preview_data, "cline", None)
        self._trk = None
        self._cline = None

    def sync_from_preview(self, preview_data: PreviewData | None) -> None:
        if preview_data is None:
            self._trk = None
            self._cline = None
            return
        self._trk = preview_data.trk
        self._cline = preview_data.cline

    def set_trk_comparison(self, trk: TRKFile | None) -> None:
        self._trk = trk
        self._cline = get_cline_pos(trk) if trk is not None else None

    def has_overlay(self) -> bool:
        return self._trk is not None and self._cline is not None

    def compute_start_finish_mapping(
        self, start_dlong: float | None, track_length: float | None
    ) -> tuple[Point, Point, Point] | None:
        if (
            start_dlong is None
            or track_length is None
            or track_length <= 0
            or not self.has_overlay()
        ):
            return None

        return compute_centerline_normal_and_tangent(
            self._trk, self._cline, track_length, start_dlong
        )

    def project_point_to_centerline(
        self,
        point: Point,
        centerline_index: object | None,
        sampled_dlongs: list[float],
        track_length: float,
    ) -> float | None:
        if centerline_index is None or not sampled_dlongs:
            return None

        _, nearest_dlong, _ = project_point_to_centerline(
            point,
            centerline_index,
            sampled_dlongs,
            track_length,
        )
        return nearest_dlong
