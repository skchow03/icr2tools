"""Model-layer state for the track preview and AI line caching.

This module owns in-memory track geometry, boundaries, and AI line records.
It belongs to the model layer and is intentionally free of rendering logic
and UI concerns; persistence is delegated to services.
"""
from __future__ import annotations

import math
from pathlib import Path
from typing import List, Tuple

from PyQt5 import QtCore

from icr2_core.lp.csv2lp import load_csv as load_lp_csv
from icr2_core.lp.loader import LP_RESOLUTION, papy_speed_to_mph
from icr2_core.lp.lpcalc import get_fake_radius1, get_fake_radius2, get_fake_radius3
from icr2_core.lp.rpy import Rpy
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
    """Mutable, in-memory track preview state.

    The model owns the loaded track geometry, cached AI lines, and derived
    indices used by renderers. It is mutable and transient, updated by
    coordinators/controllers, and persisted only via the IO service.
    """

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
        self._ai_line_cache_generation = 0
        self._manual_lp_overrides: set[str] = set()
        self.replay_lap_points: list[LpPoint] = []
        self.replay_lap_label: str | None = None
        self._replay_line_generation = 0

    @property
    def replay_line_generation(self) -> int:
        return self._replay_line_generation

    def set_replay_lap(self, points: list[LpPoint], label: str | None) -> bool:
        if points == self.replay_lap_points and label == self.replay_lap_label:
            return False
        self.replay_lap_points = list(points)
        self.replay_lap_label = label
        self._replay_line_generation += 1
        return True

    def clear_replay_lap(self) -> bool:
        if not self.replay_lap_points and self.replay_lap_label is None:
            return False
        self.replay_lap_points = []
        self.replay_lap_label = None
        self._replay_line_generation += 1
        return True

    def load_track(self, track_folder: Path) -> None:
        """Load track data and rebuild derived geometry caches."""
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
        self._ai_line_cache_generation += 1
        self._manual_lp_overrides.clear()

    def set_visible_lp_files(self, names: list[str] | set[str]) -> bool:
        valid = {name for name in names if name in self.available_lp_files}
        if valid == self.visible_lp_files:
            return False
        self.visible_lp_files = valid
        self._ai_line_cache_generation += 1
        for name in sorted(valid):
            self._queue_ai_line_load(name)
        return True

    def ai_line_available(self) -> bool:
        return bool(self.available_lp_files)

    @property
    def ai_line_cache_generation(self) -> int:
        return self._ai_line_cache_generation

    def ai_line_records(self, name: str) -> list[LpPoint]:
        if name == "center-line" or name not in self.available_lp_files:
            return []
        return self._get_ai_line_records(name)

    def update_lp_record(self, lp_name: str, index: int) -> bool:
        """Recompute a single LP record's world position from DLONG/DLAT."""
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
        self._ai_line_cache_generation += 1
        return True

    def generate_lp_line(
        self, lp_name: str, speed_mph: float, dlat: float
    ) -> tuple[bool, str]:
        """Generate a new LP line at the specified DLAT and speed."""
        if self.trk is None or not self.centerline or self.track_length is None:
            return False, "No track loaded to generate LP data."
        if not lp_name or lp_name == "center-line":
            return False, "Select a valid LP line to replace."
        if lp_name not in self.available_lp_files:
            return False, f"{lp_name} is not available for editing."
        track_length = float(self.track_length)
        if track_length <= 0:
            return False, "Track length is not available."
        record_count = max(2, math.ceil(track_length / LP_RESOLUTION) + 1)
        speed_raw = int(round(speed_mph * 5280 / 9))
        records: list[LpPoint] = []
        for index in range(record_count):
            dlong = track_length if index == record_count - 1 else index * LP_RESOLUTION
            try:
                x, y, _ = getxyz(self.trk, float(dlong), float(dlat), self.centerline)
            except Exception as exc:
                return False, f"Failed to build LP record at DLONG {dlong:.0f}: {exc}"
            records.append(
                LpPoint(
                    x=x,
                    y=y,
                    dlong=float(dlong),
                    dlat=float(dlat),
                    speed_raw=speed_raw,
                    speed_mph=float(speed_mph),
                    lateral_speed=0.0,
                )
            )
        if self._ai_lines is None:
            self._ai_lines = {}
        self._ai_lines[lp_name] = records
        self._manual_lp_overrides.add(lp_name)
        self._pending_ai_line_loads.discard(lp_name)
        self._ai_line_cache_generation += 1
        return True, f"Generated {lp_name} LP line with {record_count} records."

    def generate_lp_line_from_replay(
        self,
        lp_name: str,
        rpy: Rpy,
        car_id: int,
        start_frame: int,
        end_frame: int,
    ) -> tuple[bool, str]:
        if self.trk is None or not self.centerline or self.track_length is None:
            return False, "No track loaded to generate LP data."
        if not lp_name or lp_name == "center-line":
            return False, "Select a valid LP line to replace."
        if lp_name not in self.available_lp_files:
            return False, f"{lp_name} is not available for editing."
        if car_id not in rpy.car_index:
            return False, "Selected replay car is unavailable."
        car_index = rpy.car_index.index(car_id)
        dlongs = rpy.cars[car_index].dlong
        dlats = rpy.cars[car_index].dlat
        if not dlongs or not dlats:
            return False, "Replay lap data is empty."
        start = max(0, start_frame - 2)
        end = min(len(dlongs), end_frame + 2)
        if end <= start:
            return False, "Replay lap range is invalid."
        frames = end - start
        if frames < 5:
            return False, "Replay lap is too short to generate LP data."
        track_length = int(self.track_length or self.trk.trklength or 0)
        if track_length <= 0:
            return False, "Track length is not available."

        t1_dlong: list[int] = []
        t1_dlat: list[int] = []
        t1_radius: list[float] = []
        t1_prev_rw_len: list[float] = [0.0]
        t1_next_rw_len: list[float] = []
        t1_rw_speed: list[float] = [0.0]
        t1_sect: list[int] = []
        t1_sect_type: list[int] = []

        for i in range(start, end):
            t1_dlong.append(int(dlongs[i]))
            t1_dlat.append(int(dlats[i]))
            cur_sect = self._trk_sect_id(self.trk, dlongs[i])
            t1_sect.append(cur_sect)
            t1_sect_type.append(self.trk.sects[cur_sect].type)

        t1_dlong[0] = t1_dlong[0] - track_length
        t1_dlong[1] = t1_dlong[1] - track_length
        t1_dlong[-1] = t1_dlong[-1] + track_length
        t1_dlong[-2] = t1_dlong[-2] + track_length

        for i in range(0, frames):
            cur_frame = i
            next_frame = 4 if i == frames - 1 else i + 1
            if t1_sect_type[cur_frame] == 1 and t1_sect_type[next_frame] == 1:
                t1_radius.append(0.0)
            elif t1_sect_type[cur_frame] == 2 and t1_sect_type[next_frame] == 2:
                if t1_sect[cur_frame] == t1_sect[next_frame]:
                    t1_radius.append(
                        self._trk_sect_radius(self.trk, t1_sect[cur_frame])
                    )
                else:
                    dlongc = self.trk.sects[t1_sect[next_frame]].start_dlong
                    dlong0 = t1_dlong[cur_frame]
                    r0 = self._trk_sect_radius(self.trk, t1_sect[cur_frame])
                    dlong1 = t1_dlong[next_frame]
                    r1 = self._trk_sect_radius(self.trk, t1_sect[next_frame])
                    t1_radius.append(get_fake_radius3(dlongc, dlong0, r0, dlong1, r1))
            elif t1_sect_type[cur_frame] == 1 and t1_sect_type[next_frame] == 2:
                t1_radius.append(
                    get_fake_radius1(
                        self._trk_sect_radius(self.trk, t1_sect[next_frame]),
                        t1_dlong[next_frame],
                        self.trk.sects[t1_sect[next_frame]].start_dlong,
                        t1_dlong[cur_frame],
                    )
                )
                t1_sect_type[cur_frame] = 2
            elif t1_sect_type[cur_frame] == 2 and t1_sect_type[next_frame] == 1:
                t1_radius.append(
                    get_fake_radius2(
                        self._trk_sect_radius(self.trk, t1_sect[cur_frame - 1]),
                        self.trk.sects[t1_sect[next_frame]].start_dlong,
                        t1_dlong[cur_frame],
                        t1_dlong[next_frame],
                    )
                )
            else:
                return False, f"Unable to calculate replay radius at frame {i}."

        for i in range(1, frames):
            cur = i
            prev = i - 1
            next_frame = 4 if i == frames - 1 else i + 1
            if t1_sect_type[prev] == 1:
                a = (t1_dlong[cur] - t1_dlong[prev]) ** 2
                b = (t1_dlat[cur] - t1_dlat[prev]) ** 2
                t1_prev_rw_len.append(math.sqrt(a + b))
            else:
                denom = 2 * float(t1_radius[prev])
                if denom == 0:
                    return False, "Replay radius calculation produced zero values."
                a = (
                    (2 * t1_radius[prev] - t1_dlat[cur] - t1_dlat[prev])
                    * (t1_dlong[cur] - t1_dlong[prev])
                    / denom
                )
                b = t1_dlat[cur] - t1_dlat[prev]
                t1_prev_rw_len.append(math.sqrt(a**2 + b**2))
            if next_frame >= frames:
                return False, "Replay lap data is too short for interpolation."

        for i in range(0, frames):
            next_frame = 4 if i == frames - 1 else i + 1
            t1_next_rw_len.append(t1_prev_rw_len[next_frame])

        for i in range(1, frames):
            t1_rw_speed.append(
                (t1_prev_rw_len[i] + t1_next_rw_len[i]) / 2 * 54000 / 31680000
            )

        num_lp_recs = (track_length // 65536) + 2
        lp_dlong: list[float] = []
        lp_dlat: list[float] = []
        lp_rw_speed: list[float] = []

        for i in range(0, num_lp_recs):
            cur_dlong = track_length if i == num_lp_recs - 1 else i * 65536
            lp_dlong.append(cur_dlong)
            ref_index = None
            for j in range(0, len(t1_dlong) - 1):
                if t1_dlong[j] <= cur_dlong < t1_dlong[j + 1]:
                    ref_index = j
                    break
            if ref_index is None:
                if cur_dlong < t1_dlong[0]:
                    ref_index = 0
                else:
                    ref_index = len(t1_dlong) - 2
            denom = t1_dlong[ref_index + 1] - t1_dlong[ref_index]
            if denom == 0:
                return False, "Replay lap data has duplicate DLONG entries."
            cur_dlat = (
                (cur_dlong - t1_dlong[ref_index]) * t1_dlat[ref_index + 1]
                + (t1_dlong[ref_index + 1] - cur_dlong) * t1_dlat[ref_index]
            ) / denom
            lp_dlat.append(cur_dlat)
            cur_rw_speed = (
                (cur_dlong - t1_dlong[ref_index]) * t1_rw_speed[ref_index + 1]
                + (t1_dlong[ref_index + 1] - cur_dlong) * t1_rw_speed[ref_index]
            ) / denom
            lp_rw_speed.append(cur_rw_speed)

        lp_dlong = (
            [track_length - 65536 * 2, track_length - 65536]
            + lp_dlong
            + [
                track_length - lp_dlong[-2],
                (track_length - lp_dlong[-2]) * 2,
            ]
        )

        dlat_start_change = lp_dlat[1] - lp_dlat[0]
        dlat_end_change = lp_dlat[-1] - lp_dlat[-2]
        lp_dlat = (
            [lp_dlat[0] - dlat_start_change * 2, lp_dlat[0] - dlat_start_change]
            + lp_dlat
            + [lp_dlat[-1] + dlat_end_change, lp_dlat[-1] + dlat_end_change * 2]
        )

        speed_start_change = lp_rw_speed[1] - lp_rw_speed[0]
        speed_end_change = lp_rw_speed[-1] - lp_rw_speed[-2]
        lp_rw_speed = (
            [
                lp_rw_speed[0] - speed_start_change * 2,
                lp_rw_speed[0] - speed_start_change,
            ]
            + lp_rw_speed
            + [
                lp_rw_speed[-1] + speed_end_change,
                lp_rw_speed[-1] + speed_end_change * 2,
            ]
        )

        num_lp_recs2 = num_lp_recs + 4
        t3_next_rw_len: list[float] = []
        t3_prev_rw_len: list[float] = []
        t3_next_lp_len: list[float] = []
        t3_prev_lp_len: list[float] = [0.0]
        t3_radius: list[float] = []
        t3_sect: list[int] = []
        t3_sect_type: list[int] = []
        lp_speed: list[float] = [0.0]
        coriolis1: list[float] = [0.0]

        for i in range(0, num_lp_recs2):
            t3_sect_type.append(self._trk_sect_type(self.trk, lp_dlong[i]))
            t3_sect.append(self._trk_sect_id(self.trk, lp_dlong[i]))

        lp_dlong[0] = lp_dlong[0] - track_length
        lp_dlong[1] = lp_dlong[1] - track_length
        lp_dlong[-1] = lp_dlong[-1] + track_length
        lp_dlong[-2] = lp_dlong[-2] + track_length

        for i in range(0, num_lp_recs2):
            cur = i
            prev = num_lp_recs + 2 if i == 0 else i - 1
            next_record = 0 if i == num_lp_recs + 3 else i + 1

            if t3_sect_type[cur] == 1 and t3_sect_type[next_record] == 1:
                t3_radius.append(0.0)
            elif t3_sect_type[cur] == 2 and t3_sect_type[next_record] == 2:
                if t3_sect[cur] == t3_sect[next_record]:
                    t3_radius.append(self._trk_sect_radius(self.trk, t3_sect[cur]))
                else:
                    dlongc = self.trk.sects[t3_sect[next_record]].start_dlong
                    dlong0 = lp_dlong[cur]
                    r0 = self._trk_sect_radius(self.trk, t3_sect[cur])
                    dlong1 = lp_dlong[next_record]
                    r1 = self._trk_sect_radius(self.trk, t3_sect[next_record])
                    t3_radius.append(get_fake_radius3(dlongc, dlong0, r0, dlong1, r1))
            elif t3_sect_type[cur] == 1 and t3_sect_type[next_record] == 2:
                t3_radius.append(
                    get_fake_radius1(
                        self._trk_sect_radius(self.trk, t3_sect[next_record]),
                        lp_dlong[next_record],
                        self.trk.sects[t3_sect[next_record]].start_dlong,
                        lp_dlong[cur],
                    )
                )
                t3_sect_type[cur] = 2
            elif t3_sect_type[cur] == 2 and t3_sect_type[next_record] == 1:
                t3_radius.append(
                    get_fake_radius2(
                        self._trk_sect_radius(self.trk, t3_sect[prev]),
                        self.trk.sects[t3_sect[next_record]].start_dlong,
                        lp_dlong[cur],
                        lp_dlong[next_record],
                    )
                )
            else:
                return False, f"Unable to calculate LP radius at record {i}."

        for i in range(0, num_lp_recs2):
            cur = i
            if i == 0:
                prev = num_lp_recs - 2
                prev_dlong = -65536
            else:
                prev = i - 1
                prev_dlong = int(lp_dlong[prev])
            if i == num_lp_recs - 1:
                next_record = 0
            else:
                next_record = i + 1

            if t3_sect_type[prev] == 1:
                a = (lp_dlong[cur] - prev_dlong) ** 2
                b = (lp_dlat[cur] - lp_dlat[prev]) ** 2
                t3_prev_rw_len.append(math.sqrt(a + b))
            else:
                denom = 2 * float(t3_radius[prev])
                if denom == 0:
                    return False, "LP radius calculation produced zero values."
                a = (
                    (2 * t3_radius[prev] - lp_dlat[cur] - lp_dlat[prev])
                    * (lp_dlong[cur] - lp_dlong[prev])
                    / denom
                )
                b = lp_dlat[cur] - lp_dlat[prev]
                t3_prev_rw_len.append(math.sqrt(a**2 + b**2))

        for i in range(0, num_lp_recs2):
            next_record = 0 if i == num_lp_recs2 - 1 else i + 1
            t3_next_rw_len.append(t3_prev_rw_len[next_record])

        for i in range(0, num_lp_recs2 - 1):
            if t3_radius[i] == 0:
                t3_next_lp_len.append(lp_dlong[i + 1] - lp_dlong[i])
            else:
                t3_next_lp_len.append(
                    (lp_dlong[i + 1] - lp_dlong[i])
                    * (t3_radius[i] - lp_dlat[i])
                    / t3_radius[i]
                )

        for i in range(1, num_lp_recs2 - 1):
            t3_prev_lp_len.append(t3_next_lp_len[i - 1])

        for i in range(1, num_lp_recs2 - 1):
            denom = t3_next_rw_len[i] + t3_prev_rw_len[i]
            if denom == 0:
                lp_speed.append(0.0)
            else:
                lp_speed.append(
                    lp_rw_speed[i] * (t3_prev_lp_len[i] + t3_next_lp_len[i]) / denom
                )

        for i in range(1, num_lp_recs2 - 1):
            denom = lp_dlong[i + 1] - lp_dlong[i - 1]
            if denom == 0:
                coriolis1.append(0.0)
            else:
                coriolis1.append(
                    ((lp_dlat[i + 1] - lp_dlat[i - 1]) / denom)
                    * (lp_speed[i] * 31680000 / 54000)
                )

        records: list[LpPoint] = []
        for i in range(2, num_lp_recs2 - 2):
            speed_raw = int(
                round(lp_speed[i] * (1 / 15) * (1 / 3600) * 6000 * 5280)
            )
            coriolis = float(round(coriolis1[i]))
            dlat = float(round(lp_dlat[i]))
            dlong = float(lp_dlong[i])
            try:
                x, y, _ = getxyz(self.trk, dlong, dlat, self.centerline)
            except Exception as exc:
                return False, f"Failed to project LP record at DLONG {dlong:.0f}: {exc}"
            records.append(
                LpPoint(
                    x=x,
                    y=y,
                    dlong=dlong,
                    dlat=dlat,
                    speed_raw=speed_raw,
                    speed_mph=papy_speed_to_mph(speed_raw),
                    lateral_speed=coriolis,
                )
            )

        if not records:
            return False, "No LP records were generated from the replay lap."
        if self._ai_lines is None:
            self._ai_lines = {}
        self._ai_lines[lp_name] = records
        self._manual_lp_overrides.add(lp_name)
        self._pending_ai_line_loads.discard(lp_name)
        self._ai_line_cache_generation += 1
        return True, f"Generated {lp_name} LP line from replay lap."

    def save_lp_line(self, lp_name: str) -> tuple[bool, str]:
        """Persist the selected AI line back to its LP file."""
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

    def save_all_lp_lines(self) -> tuple[bool, str]:
        """Persist all available AI lines back to their LP files."""
        if self.track_path is None:
            return False, "No track loaded to save LP data."
        if not self.available_lp_files:
            return False, "No LP files are available for saving."
        saved: list[str] = []
        failures: list[str] = []
        for lp_name in sorted(self.available_lp_files):
            records = self.get_ai_line_records_immediate(lp_name)
            if not records:
                failures.append(f"{lp_name} (no records loaded)")
                continue
            try:
                self._io_service.save_lp_line(self.track_path, lp_name, records)
            except Exception as exc:
                failures.append(f"{lp_name} ({exc})")
                continue
            saved.append(lp_name)
        if failures:
            prefix = f"Saved {len(saved)} LP file(s)." if saved else "No LP files saved."
            message = "\n".join(
                [prefix, "Failed to save:", *[f"- {item}" for item in failures]]
            )
            return False, message
        return True, f"Saved {len(saved)} LP file(s)."

    def export_lp_csv(self, lp_name: str, output_path: Path) -> tuple[bool, str]:
        """Export the selected AI line to CSV via the IO service."""
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

    def import_lp_csv(self, lp_name: str, csv_path: Path) -> tuple[bool, str]:
        """Import a CSV file and load it into the selected AI line."""
        if self.trk is None or not self.centerline or self.track_length is None:
            return False, "No track loaded to import LP data."
        if not lp_name or lp_name == "center-line":
            return False, "Select a valid LP line to replace."
        if lp_name not in self.available_lp_files:
            return False, f"{lp_name} is not available for editing."
        track_length = float(self.track_length or self.trk.trklength or 0)
        if track_length <= 0:
            return False, "Track length is not available."
        try:
            num_lp_recs, lp_rw_speed, lp_dlat, lp_dlong = load_lp_csv(
                str(csv_path), track_length
            )
        except Exception as exc:
            return False, f"Failed to import CSV: {exc}"
        if num_lp_recs < 2:
            return False, "CSV does not contain enough LP records."
        records: list[LpPoint] = []
        for speed_raw, dlat, dlong in zip(lp_rw_speed, lp_dlat, lp_dlong):
            try:
                x, y, _ = getxyz(
                    self.trk, float(dlong), float(dlat), self.centerline
                )
            except Exception as exc:
                return False, f"Failed to project LP record at DLONG {dlong:.0f}: {exc}"
            speed_raw_int = int(round(speed_raw))
            records.append(
                LpPoint(
                    x=x,
                    y=y,
                    dlong=float(dlong),
                    dlat=float(dlat),
                    speed_raw=speed_raw_int,
                    speed_mph=papy_speed_to_mph(speed_raw_int),
                    lateral_speed=0.0,
                )
            )
        if self._ai_lines is None:
            self._ai_lines = {}
        self._ai_lines[lp_name] = records
        self._manual_lp_overrides.add(lp_name)
        self._pending_ai_line_loads.discard(lp_name)
        self._ai_line_cache_generation += 1
        return True, f"Loaded {lp_name} from CSV."

    def _queue_ai_line_load(self, lp_name: str) -> None:
        """Schedule a background load of LP records for the given line."""
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
        """Accept loaded LP records if they match the current generation."""
        self._ai_line_tasks.discard(task)
        self._pending_ai_line_loads.discard(lp_name)
        if lp_name in self._manual_lp_overrides:
            return
        if generation != self._ai_line_generation:
            return
        if self._ai_lines is None:
            self._ai_lines = {}
        self._ai_lines[lp_name] = records
        self._ai_line_cache_generation += 1
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
        """Combine surface and centerline bounds into a single envelope."""
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
    def _trk_sect_id(trk: TRKFile, dlong: float) -> int:
        for i in range(0, trk.num_sects - 1):
            if trk.sects[i].start_dlong <= dlong < trk.sects[i + 1].start_dlong:
                return i
        return trk.num_sects - 1

    @staticmethod
    def _trk_sect_type(trk: TRKFile, dlong: float) -> int:
        return trk.sects[TrackPreviewModel._trk_sect_id(trk, dlong)].type

    @staticmethod
    def _trk_sect_radius(trk: TRKFile, sect_id: int) -> float:
        next_id = (sect_id + 1) % trk.num_sects
        a0 = int(trk.sects[sect_id].heading)
        a1 = int(trk.sects[next_id].heading)
        x = (a1 - a0) / 2147483648
        if x > 1:
            x -= 2
        elif x < -1:
            x += 2
        if x == 0:
            return 0.0
        return trk.sects[sect_id].length / (x * math.pi)

    @staticmethod
    def _build_boundary_edges(
        trk: TRKFile | None, cline: list[tuple[float, float]]
    ) -> List[tuple[Tuple[float, float], Tuple[float, float]]]:
        """Sample TRK boundary DLATs into world-space line segments."""
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
