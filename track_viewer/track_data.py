"""Data models and loaders for the track preview widget."""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import List, Optional, Tuple

from PyQt5 import QtCore

from icr2_core.lp.loader import load_lp_file
from icr2_core.trk.trk_classes import TRKFile
from icr2_core.trk.trk_utils import getxyz
from track_viewer.geometry import CenterlineIndex, build_centerline_index, sample_centerline
from track_viewer.io_service import TrackIOService


@dataclass
class LpPoint:
    x: float
    y: float
    dlong: float
    dlat: float
    speed_mph: float


@dataclass
class LoadedTrackData:
    track_folder: Path
    trk: TRKFile
    centerline: list[tuple[float, float]]
    surface_mesh: list
    surface_bounds: tuple[float, float, float, float] | None
    available_lp_files: list[str]
    track_length: float
    sampled_centerline: list[tuple[float, float]]
    sampled_dlongs: list[float]
    sampled_bounds: tuple[float, float, float, float] | None
    centerline_index: CenterlineIndex | None
    boundary_edges: list[tuple[Tuple[float, float], Tuple[float, float]]]
    bounds: tuple[float, float, float, float] | None


class TrackLoader:
    """Load and prepare track data for the preview widget."""

    def __init__(self, io_service: TrackIOService | None = None) -> None:
        self._io_service = io_service or TrackIOService()

    def load_track(self, track_folder: Path) -> LoadedTrackData:
        track_data = self._io_service.load_track(track_folder)
        sampled, sampled_dlongs, sampled_bounds = sample_centerline(
            track_data.trk, track_data.centerline
        )
        boundary_edges = self._build_boundary_edges(track_data.trk, track_data.centerline)
        centerline_index = build_centerline_index(sampled, sampled_bounds)
        bounds = self._merge_bounds(track_data.surface_bounds, sampled_bounds)

        return LoadedTrackData(
            track_folder=track_folder,
            trk=track_data.trk,
            centerline=track_data.centerline,
            surface_mesh=track_data.surface_mesh,
            surface_bounds=track_data.surface_bounds,
            available_lp_files=track_data.available_lp_files,
            track_length=track_data.track_length,
            sampled_centerline=sampled,
            sampled_dlongs=sampled_dlongs,
            sampled_bounds=sampled_bounds,
            centerline_index=centerline_index,
            boundary_edges=boundary_edges,
            bounds=bounds,
        )

    def load_ai_line_records(
        self,
        lp_name: str,
        track_folder: Path,
        trk: TRKFile,
        cline: list[tuple[float, float]],
        track_length: float | None,
    ) -> List[LpPoint]:
        lp_path = track_folder / f"{lp_name}.LP"
        if not lp_path.exists():
            return []

        length_arg = int(track_length) if track_length is not None else None
        try:
            ai_line = load_lp_file(lp_path, track_length=length_arg)
        except Exception:
            return []

        points: List[LpPoint] = []
        for record in ai_line:
            try:
                x, y, _ = getxyz(trk, float(record.dlong), record.dlat, cline)
            except Exception:
                continue
            points.append(
                LpPoint(
                    x=x,
                    y=y,
                    dlong=float(record.dlong),
                    dlat=float(record.dlat),
                    speed_mph=float(record.speed_mph),
                )
            )
        return points

    @staticmethod
    def _merge_bounds(
        *bounds: Tuple[float, float, float, float] | None,
    ) -> Tuple[float, float, float, float] | None:
        valid = [b for b in bounds if b]
        if not valid:
            return None
        min_x = min(b[0] for b in valid)
        max_x = max(b[1] for b in valid)
        min_y = min(b[2] for b in valid)
        max_y = max(b[3] for b in valid)
        return (min_x, max_x, min_y, max_y)

    @staticmethod
    def _build_boundary_edges(
        trk: TRKFile | None,
        cline: Optional[List[Tuple[float, float]]],
    ) -> List[tuple[Tuple[float, float], Tuple[float, float]]]:
        """Create boundary line segments directly from TRK section data."""

        if trk is None or cline is None:
            return []

        edges: List[tuple[Tuple[float, float], Tuple[float, float]]] = []

        for sect in trk.sects:
            start_dlong = sect.start_dlong
            end_dlong = sect.start_dlong + sect.length

            if sect.type == 1:
                num_subsects = 1
            else:
                num_subsects = max(1, round(sect.length / 60000))

            for bound_idx in range(sect.num_bounds):
                start_dlat = sect.bound_dlat_start[bound_idx]
                end_dlat = sect.bound_dlat_end[bound_idx]

                for sub_idx in range(num_subsects):
                    sub_start_dlong = start_dlong + (
                        (end_dlong - start_dlong) * sub_idx / num_subsects
                    )
                    if sub_idx == num_subsects - 1:
                        sub_end_dlong = end_dlong
                    else:
                        sub_end_dlong = start_dlong + (
                            (end_dlong - start_dlong) * (sub_idx + 1) / num_subsects
                        )

                    sub_start_dlat = start_dlat + (
                        (end_dlat - start_dlat) * sub_idx / num_subsects
                    )
                    sub_end_dlat = start_dlat + (
                        (end_dlat - start_dlat) * (sub_idx + 1) / num_subsects
                    )

                    start_x, start_y, _ = getxyz(
                        trk, sub_start_dlong, sub_start_dlat, cline
                    )
                    end_x, end_y, _ = getxyz(trk, sub_end_dlong, sub_end_dlat, cline)

                    edges.append(((start_x, start_y), (end_x, end_y)))

        return edges


class TrackPreviewModel(QtCore.QObject):
    """Container for track preview state and visibility toggles."""

    trackChanged = QtCore.pyqtSignal()
    visibilityChanged = QtCore.pyqtSignal()
    flagsChanged = QtCore.pyqtSignal()
    aiLineLoaded = QtCore.pyqtSignal(str)

    def __init__(self) -> None:
        super().__init__()
        self.track_folder: Path | None = None
        self.trk: TRKFile | None = None
        self.centerline: list[tuple[float, float]] = []
        self.surface_mesh: list = []
        self.bounds: tuple[float, float, float, float] | None = None
        self.sampled_centerline: list[tuple[float, float]] = []
        self.sampled_dlongs: list[float] = []
        self.sampled_bounds: tuple[float, float, float, float] | None = None
        self.centerline_index: CenterlineIndex | None = None
        self.available_lp_files: list[str] = []
        self.visible_lp_files: set[str] = set()
        self.ai_lines: dict[str, list[LpPoint]] | None = None
        self.track_length: float | None = None
        self.boundary_edges: list[tuple[Tuple[float, float], Tuple[float, float]]] = []
        self.active_lp_line = "center-line"
        self.flags: list[Tuple[float, float]] = []
        self.show_center_line = True
        self.show_boundaries = True
        self.show_cameras = True
        self.show_zoom_points = False

    def clear(self) -> None:
        self.track_folder = None
        self.trk = None
        self.centerline = []
        self.surface_mesh = []
        self.bounds = None
        self.sampled_centerline = []
        self.sampled_dlongs = []
        self.sampled_bounds = None
        self.centerline_index = None
        self.available_lp_files = []
        self.visible_lp_files = set()
        self.ai_lines = None
        self.track_length = None
        self.boundary_edges = []
        self.active_lp_line = "center-line"
        self.flags = []
        self.trackChanged.emit()
        self.flagsChanged.emit()

    def set_track_data(self, data: LoadedTrackData) -> None:
        self.track_folder = data.track_folder
        self.trk = data.trk
        self.centerline = data.centerline
        self.surface_mesh = data.surface_mesh
        self.bounds = data.bounds
        self.sampled_centerline = data.sampled_centerline
        self.sampled_dlongs = data.sampled_dlongs
        self.sampled_bounds = data.sampled_bounds
        self.centerline_index = data.centerline_index
        self.available_lp_files = data.available_lp_files
        self.track_length = data.track_length
        self.boundary_edges = data.boundary_edges
        self.ai_lines = None
        self.visible_lp_files = {
            name for name in self.visible_lp_files if name in self.available_lp_files
        }
        if self.active_lp_line not in {"center-line", *self.available_lp_files}:
            self.active_lp_line = "center-line"
        self.flags = []
        self.trackChanged.emit()
        self.flagsChanged.emit()

    def set_visible_lp_files(self, names: list[str] | set[str]) -> None:
        valid = {name for name in names if name in self.available_lp_files}
        if valid == self.visible_lp_files:
            return
        self.visible_lp_files = valid
        self.visibilityChanged.emit()

    def set_active_lp_line(self, name: str) -> None:
        target = "center-line"
        if name in self.available_lp_files:
            target = name
        elif name == "center-line":
            target = name
        if target == self.active_lp_line:
            return
        self.active_lp_line = target
        self.visibilityChanged.emit()

    def set_show_center_line(self, show: bool) -> None:
        if self.show_center_line != show:
            self.show_center_line = show
            self.visibilityChanged.emit()

    def set_show_boundaries(self, show: bool) -> None:
        if self.show_boundaries != show:
            self.show_boundaries = show
            self.visibilityChanged.emit()

    def set_show_cameras(self, show: bool) -> None:
        if self.show_cameras != show:
            self.show_cameras = show
            self.visibilityChanged.emit()

    def set_show_zoom_points(self, show: bool) -> None:
        if self.show_zoom_points != show:
            self.show_zoom_points = show
            self.visibilityChanged.emit()

    def set_flags(self, flags: list[Tuple[float, float]]) -> None:
        self.flags = list(flags)
        self.flagsChanged.emit()

    def add_flag(self, coords: Tuple[float, float]) -> None:
        self.flags.append(coords)
        self.flagsChanged.emit()

    def remove_flag(self, index: int) -> None:
        if 0 <= index < len(self.flags):
            del self.flags[index]
            self.flagsChanged.emit()

    def ai_line_records(self, lp_name: str, loader: TrackLoader) -> List[LpPoint]:
        if (
            self.track_folder is None
            or self.trk is None
            or not self.centerline
            or self.track_length is None
        ):
            return []

        if self.ai_lines is None:
            self.ai_lines = {}

        if lp_name not in self.ai_lines:
            self.ai_lines[lp_name] = loader.load_ai_line_records(
                lp_name, self.track_folder, self.trk, self.centerline, self.track_length
            )
            self.aiLineLoaded.emit(lp_name)

        return self.ai_lines.get(lp_name) or []

    def ai_line_points(self, lp_name: str, loader: TrackLoader) -> List[Tuple[float, float]]:
        return [(p.x, p.y) for p in self.ai_line_records(lp_name, loader)]
