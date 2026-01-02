"""Model for track preview data and AI line caching."""
from __future__ import annotations

from pathlib import Path
from typing import List, Tuple

from PyQt5 import QtCore

from icr2_core.trk.surface_mesh import GroundSurfaceStrip
from icr2_core.trk.trk_classes import TRKFile
from icr2_core.trk.trk_utils import getxyz
from track_viewer.ai.ai_line_service import AiLineLoadTask, LpPoint, load_ai_line_records
from track_viewer.geometry import (
    CenterlineIndex,
    build_centerline_index,
    sample_centerline,
)
from track_viewer.services.io_service import TrackIOService


class TrackPreviewModel(QtCore.QObject):
    """Track preview state and data loading."""

    aiLineLoaded = QtCore.pyqtSignal(str)

    def __init__(self, io_service: TrackIOService | None = None) -> None:
        super().__init__()
        self._io_service = io_service or TrackIOService()
        self.clear()

    def clear(self) -> None:
        self.trk: TRKFile | None = None
        self.centerline: list[tuple[float, float]] = []
        self.surface_mesh: List[GroundSurfaceStrip] = []
        self.bounds: Tuple[float, float, float, float] | None = None
        self.sampled_centerline: List[Tuple[float, float]] = []
        self.sampled_dlongs: List[float] = []
        self.sampled_bounds: Tuple[float, float, float, float] | None = None
        self.centerline_index: CenterlineIndex | None = None
        self.boundary_edges: List[tuple[Tuple[float, float], Tuple[float, float]]] = []
        self.track_length: float | None = None
        self.track_path: Path | None = None
        self.available_lp_files: List[str] = []
        self.visible_lp_files: set[str] = set()
        self._ai_lines: dict[str, List[LpPoint]] | None = None
        self._pending_ai_line_loads: set[str] = set()
        self._ai_line_tasks: set[AiLineLoadTask] = set()
        self._ai_line_generation = 0

    def load_track(self, track_folder: Path) -> None:
        track_data = self._io_service.load_track(track_folder)
        self.trk = track_data.trk
        self.track_length = track_data.track_length
        self.centerline = track_data.centerline
        self.surface_mesh = track_data.surface_mesh
        self.boundary_edges = self._build_boundary_edges(self.trk, self.centerline)
        sampled, sampled_dlongs, sampled_bounds = sample_centerline(
            self.trk, self.centerline
        )
        self.sampled_centerline = sampled
        self.sampled_dlongs = sampled_dlongs
        self.sampled_bounds = sampled_bounds
        self.centerline_index = build_centerline_index(sampled, sampled_bounds)
        self.bounds = self._merge_bounds(track_data.surface_bounds, sampled_bounds)
        self.available_lp_files = track_data.available_lp_files
        self.track_path = track_folder
        self._reset_ai_lines()
        self.visible_lp_files = {
            name for name in self.visible_lp_files if name in self.available_lp_files
        }
        for name in sorted(self.visible_lp_files):
            self._queue_ai_line_load(name)

    def _reset_ai_lines(self) -> None:
        self._ai_lines = None
        self._pending_ai_line_loads.clear()
        self._ai_line_tasks.clear()
        self._ai_line_generation += 1

    def set_visible_lp_files(self, names: list[str] | set[str]) -> bool:
        valid = {name for name in names if name in self.available_lp_files}
        if valid == self.visible_lp_files:
            return False
        self.visible_lp_files = valid
        for name in sorted(valid):
            self._queue_ai_line_load(name)
        return True

    def ai_line_available(self) -> bool:
        return bool(self.available_lp_files)

    def ai_line_records(self, name: str) -> list[LpPoint]:
        if name == "center-line" or name not in self.available_lp_files:
            return []
        return self._get_ai_line_records(name)

    def update_lp_record(self, lp_name: str, index: int) -> bool:
        if lp_name not in self.available_lp_files:
            return False
        records = self._get_ai_line_records(lp_name)
        if index < 0 or index >= len(records):
            return False
        record = records[index]
        if self.trk is not None and self.centerline:
            try:
                x, y, _ = getxyz(
                    self.trk, float(record.dlong), record.dlat, self.centerline
                )
            except Exception:
                x = record.x
                y = record.y
            record.x = x
            record.y = y
        return True

    def save_lp_line(self, lp_name: str) -> tuple[bool, str]:
        if self.track_path is None:
            return False, "No track loaded to save LP data."
        if not lp_name or lp_name == "center-line":
            return False, "Select a valid LP line to save."
        if lp_name not in self.available_lp_files:
            return False, f"{lp_name} is not available for saving."
        records = self._get_ai_line_records(lp_name)
        if not records:
            return False, f"No {lp_name} LP records are loaded."
        try:
            message = self._io_service.save_lp_line(self.track_path, lp_name, records)
        except Exception as exc:
            return False, f"Failed to save {lp_name}.LP: {exc}"
        return True, message

    def export_lp_csv(self, lp_name: str, output_path: Path) -> tuple[bool, str]:
        if not lp_name or lp_name == "center-line":
            return False, "Select a valid LP line to export."
        if lp_name not in self.available_lp_files:
            return False, f"{lp_name} is not available for export."
        records = self._get_ai_line_records(lp_name)
        if not records:
            return False, f"No {lp_name} LP records are loaded."
        if output_path.suffix.lower() != ".csv":
            output_path = output_path.with_suffix(".csv")
        try:
            message = self._io_service.export_lp_csv(output_path, lp_name, records)
        except Exception as exc:
            return False, f"Failed to export {lp_name} CSV: {exc}"
        return True, message

    def _queue_ai_line_load(self, lp_name: str) -> None:
        if (
            self.track_path is None
            or lp_name in self._pending_ai_line_loads
            or lp_name not in self.available_lp_files
        ):
            return
        if self._ai_lines is not None and lp_name in self._ai_lines:
            return
        self._pending_ai_line_loads.add(lp_name)
        task = AiLineLoadTask(
            self._ai_line_generation,
            lp_name,
            self.trk,
            list(self.centerline),
            self.track_path,
            self.track_length,
        )
        task.signals.loaded.connect(
            lambda generation, lp_name, records, task=task: self._handle_ai_line_loaded(
                task, generation, lp_name, records
            )
        )
        self._ai_line_tasks.add(task)
        QtCore.QThreadPool.globalInstance().start(task)

    def _handle_ai_line_loaded(
        self,
        task: AiLineLoadTask,
        generation: int,
        lp_name: str,
        records: list[LpPoint],
    ) -> None:
        self._ai_line_tasks.discard(task)
        self._pending_ai_line_loads.discard(lp_name)
        if generation != self._ai_line_generation:
            return
        if self._ai_lines is None:
            self._ai_lines = {}
        self._ai_lines[lp_name] = records
        self.aiLineLoaded.emit(lp_name)

    def _get_ai_line_records(self, lp_name: str) -> List[LpPoint]:
        if self._ai_lines is None:
            self._ai_lines = {}
        if lp_name not in self._ai_lines:
            self._queue_ai_line_load(lp_name)
        return self._ai_lines.get(lp_name) or []

    def get_ai_line_records_immediate(self, lp_name: str) -> List[LpPoint]:
        if self._ai_lines is None:
            self._ai_lines = {}
        if lp_name in self._ai_lines and self._ai_lines[lp_name]:
            return self._ai_lines[lp_name]
        records = load_ai_line_records(
            self.trk,
            list(self.centerline),
            self.track_path,
            self.track_length,
            lp_name,
        )
        self._ai_lines[lp_name] = records
        return records

    @staticmethod
    def _merge_bounds(
        surface_bounds: Tuple[float, float, float, float] | None,
        sampled_bounds: Tuple[float, float, float, float] | None,
    ) -> Tuple[float, float, float, float] | None:
        if surface_bounds is None:
            return sampled_bounds
        if sampled_bounds is None:
            return surface_bounds
        min_x = min(surface_bounds[0], sampled_bounds[0])
        max_x = max(surface_bounds[1], sampled_bounds[1])
        min_y = min(surface_bounds[2], sampled_bounds[2])
        max_y = max(surface_bounds[3], sampled_bounds[3])
        return (min_x, max_x, min_y, max_y)

    @staticmethod
    def _build_boundary_edges(
        trk: TRKFile | None, cline: list[tuple[float, float]]
    ) -> List[tuple[Tuple[float, float], Tuple[float, float]]]:
        if trk is None or not cline:
            return []
        edges: list[tuple[tuple[float, float], tuple[float, float]]] = []
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
                    end_x, end_y, _ = getxyz(
                        trk, sub_end_dlong, sub_end_dlat, cline
                    )

                    edges.append(((start_x, start_y), (end_x, end_y)))
        return edges
