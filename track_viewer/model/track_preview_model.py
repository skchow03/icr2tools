"""Model-layer state for the track preview and AI line caching.

This module owns in-memory track geometry, boundaries, and AI line records.
It belongs to the model layer and is intentionally free of rendering logic
and UI concerns; persistence is delegated to services.
"""
from __future__ import annotations

import math
from pathlib import Path
from typing import List, Tuple

import numpy as np
from PyQt5 import QtCore

from icr2_core.lp.csv2lp import load_csv as load_lp_csv
from icr2_core.lp.loader import LP_RESOLUTION, papy_speed_to_mph
from icr2_core.lp.lpcalc import get_fake_radius1, get_fake_radius2, get_fake_radius3
from icr2_core.lp.rpy import Rpy
from icr2_core.trk.surface_mesh import GroundSurfaceStrip
from icr2_core.trk.trk_classes import TRKFile
from icr2_core.trk.trk_utils import dlong2sect, getbounddlat, getxyz
from track_viewer.ai.ai_line_service import AiLineLoadTask, LpPoint, load_ai_line_records
from track_viewer.ai.racing_line_optimizer import optimize_race_line, build_legal_dlat_envelope
from track_viewer.ai.minimum_time_optimizer import optimize_minimum_time
from track_viewer.ai.geometric_line_optimizer import optimize_geometric
from track_viewer.ai.pathfinder_line_generator import generate_pathfinder
from track_viewer.ai.indycar_speed_model import CarPerformance, speed_profile_mph
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
        self.trk_file_path: Path | None = None
        self.available_lp_files: List[str] = []
        self.visible_lp_files: set[str] = set()
        self._ai_lines: dict[str, List[LpPoint]] | None = None
        self._pending_ai_line_loads: set[str] = set()
        self._ai_line_tasks: set[AiLineLoadTask] = set()
        self._ai_line_generation = 0
        self._ai_line_cache_generation = 0
        self._manual_lp_overrides: set[str] = set()
        self._dirty_lp_files: set[str] = set()
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
        self.trk_file_path = None
        self._reset_ai_lines()
        self._dirty_lp_files.clear()
        self.visible_lp_files = {
            name for name in self.visible_lp_files if name in self.available_lp_files
        }
        for name in sorted(self.visible_lp_files):
            self._queue_ai_line_load(name)

    def load_trk_file(self, trk_path: Path) -> None:
        """Load a standalone TRK file and rebuild derived geometry caches."""
        track_data = self._io_service.load_trk_file(trk_path)
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
        self.available_lp_files = []
        self.track_path = None
        self.trk_file_path = trk_path
        self._reset_ai_lines()
        self._dirty_lp_files.clear()
        self.visible_lp_files = set()

    def _reset_ai_lines(self) -> None:
        self._ai_lines = None
        self._pending_ai_line_loads.clear()
        self._ai_line_tasks.clear()
        self._ai_line_generation += 1
        self._ai_line_cache_generation += 1
        self._manual_lp_overrides.clear()
        self._dirty_lp_files.clear()

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

    def lp_line_dirty(self, name: str) -> bool:
        if name == "center-line":
            return False
        return name in self._dirty_lp_files

    def mark_lp_line_dirty(self, name: str) -> None:
        if name == "center-line" or name not in self.available_lp_files:
            return
        self._dirty_lp_files.add(name)

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
        self._dirty_lp_files.add(lp_name)
        return True

    def generate_lp_line(
        self,
        lp_name: str,
        speed_mph: float,
        dlat: float,
        *,
        boundary_index: int | None = None,
        wall_margin: float = 0.0,
    ) -> tuple[bool, str]:
        """Generate a new LP line at a fixed DLAT or offset from a boundary."""
        if self.trk is None or not self.centerline:
            return False, "No track loaded to generate LP data."
        if not lp_name or lp_name == "center-line":
            return False, "Select a valid LP line to replace."
        if lp_name not in self.available_lp_files:
            return False, f"{lp_name} is not available for editing."
        current_track_length = float(getattr(self.trk, "trklength", 0) or 0)
        if current_track_length > 0:
            self.track_length = current_track_length
        track_length = float(self.track_length or 0)
        if track_length <= 0:
            return False, "Track length is not available."
        if boundary_index is not None and boundary_index < 0:
            return False, "Boundary index must be zero or greater."
        record_count = max(2, math.ceil(track_length / LP_RESOLUTION) + 1)
        speed_raw = int(round(speed_mph * 5280 / 9))
        records: list[LpPoint] = []
        for index in range(record_count):
            dlong = track_length if index == record_count - 1 else index * LP_RESOLUTION
            current_dlat = float(dlat)
            if boundary_index is not None:
                try:
                    sect_id, subsect = dlong2sect(self.trk, float(dlong))
                except Exception as exc:
                    return False, f"Failed to locate section for DLONG {dlong:.0f}: {exc}"
                section = self.trk.sects[sect_id]
                if boundary_index >= section.num_bounds:
                    return (
                        False,
                        f"Boundary {boundary_index} is unavailable in section {sect_id} "
                        f"(has {section.num_bounds} boundaries).",
                    )
                wall_dlat = getbounddlat(self.trk, sect_id, subsect, boundary_index)
                current_dlat = wall_dlat + float(wall_margin)
            try:
                x, y, _ = getxyz(self.trk, float(dlong), current_dlat, self.centerline)
            except Exception as exc:
                return False, f"Failed to build LP record at DLONG {dlong:.0f}: {exc}"
            records.append(
                LpPoint(
                    x=x,
                    y=y,
                    dlong=float(dlong),
                    dlat=current_dlat,
                    speed_raw=speed_raw,
                    speed_mph=float(speed_mph),
                    lateral_speed=0.0,
                )
            )
        if self._ai_lines is None:
            self._ai_lines = {}
        self._ai_lines.pop(lp_name, None)
        self._ai_lines[lp_name] = records
        self._manual_lp_overrides.add(lp_name)
        self._pending_ai_line_loads.discard(lp_name)
        self._ai_line_cache_generation += 1
        self._dirty_lp_files.add(lp_name)
        return True, f"Generated {lp_name} LP line with {record_count} records."

    def generate_candidate_race_line(
        self, lp_name: str, margin_feet: float, *, pit_side: str = "auto",
        lookahead_feet: float = 60.0, corner_width_pct: int = 75,
        apex_position_pct: int = 60, max_speed_mph: float = 230.0,
        pit_speed_start_dlong: float | None = None,
        pit_speed_end_dlong: float | None = None,
        car_performance: CarPerformance | None = None,
        side_preference: str = "none",
        side_preference_pct: int = 0,
        compare_candidates: bool = False,
        progress_callback=None,
    ) -> tuple[bool, str]:
        """Replace the selected in-memory LP path and regenerate its speeds."""
        if not lp_name or lp_name == "center-line":
            return False, "Select an LP line first."
        if self.trk is None or not self.centerline or lp_name not in self.available_lp_files:
            return False, f"Load a track folder containing {lp_name}.LP first."
        if max_speed_mph <= 0:
            return False, "Maximum speed must be greater than zero."
        existing = self.get_ai_line_records_immediate(lp_name)
        if len(existing) < 9:
            return False, f"{lp_name}.LP needs at least eight path samples."
        track_length = float(self.trk.trklength)
        has_terminal = abs(existing[-1].dlong - track_length) < 1.0
        unique = existing[:-1] if has_terminal else existing
        try:
            dlats = optimize_race_line(
                self.trk, self.centerline, [p.dlong for p in unique],
                margin_feet=margin_feet,
                reference_dlats=[p.dlat for p in unique],
                pit_side=pit_side,
                lookahead_feet=lookahead_feet,
                corner_width_pct=corner_width_pct,
                apex_position_pct=apex_position_pct,
                side_preference=side_preference,
                side_preference_pct=side_preference_pct,
            )
            def evaluate_candidate(candidate_dlats):
                xy = []
                for old, dlat in zip(unique, candidate_dlats):
                    x, y, _ = getxyz(self.trk, old.dlong, dlat, self.centerline)
                    xy.append((x / 6000.0, y / 6000.0))
                candidate_speeds = np.minimum(
                    speed_profile_mph(xy, car_performance), max_speed_mph
                )
                xy_array = np.asarray(xy, dtype=float)
                distances = np.linalg.norm(
                    np.roll(xy_array, -1, axis=0) - xy_array, axis=1
                )
                segment_mph = (
                    candidate_speeds + np.roll(candidate_speeds, -1)
                ) * 0.5
                if np.any(segment_mph <= 0.01):
                    return float("inf"), candidate_speeds
                seconds = float(np.sum(
                    (distances / 5280.0) / segment_mph
                ) * 3600.0)
                return seconds, candidate_speeds

            # The geometric solution is the seed. Optional comparison mode
            # explores nearby complete-lap solutions with the car model.
            candidates = [(dlats, apex_position_pct, corner_width_pct, lookahead_feet)]
            if compare_candidates:
                max_progress = 30
                if progress_callback:
                    progress_callback(1, max_progress, "Evaluating baseline")

                # First search lookahead independently. This keeps the search
                # broad enough to alter corner recognition/transition timing
                # without multiplying every width/apex combination by five.
                lookahead_values = []
                for factor in (0.67, 0.83, 1.0, 1.25, 1.5):
                    value = float(np.clip(lookahead_feet * factor, 10.0, 500.0))
                    value = round(value / 5.0) * 5.0
                    if value not in lookahead_values:
                        lookahead_values.append(value)
                seen = {(apex_position_pct, corner_width_pct, float(lookahead_feet))}
                for trial_lookahead in lookahead_values:
                    key = (apex_position_pct, corner_width_pct, float(trial_lookahead))
                    if key in seen:
                        continue
                    seen.add(key)
                    trial = optimize_race_line(
                        self.trk, self.centerline, [p.dlong for p in unique],
                        margin_feet=margin_feet,
                        reference_dlats=[p.dlat for p in unique],
                        pit_side=pit_side, lookahead_feet=trial_lookahead,
                        corner_width_pct=corner_width_pct,
                        apex_position_pct=apex_position_pct,
                        side_preference=side_preference,
                        side_preference_pct=side_preference_pct,
                    )
                    candidates.append((
                        trial, apex_position_pct, corner_width_pct, trial_lookahead
                    ))
                    if progress_callback:
                        progress_callback(
                            len(candidates), max_progress,
                            f"Testing lookahead {trial_lookahead:g} ft"
                        )

                # Score the lookahead-only candidates now and use the best
                # lookahead as the base for the width/apex search.
                lookahead_scored = []
                for candidate_dlats, candidate_apex, candidate_width, candidate_lookahead in candidates:
                    lap_seconds, candidate_speeds = evaluate_candidate(candidate_dlats)
                    lookahead_scored.append((
                        lap_seconds, candidate_dlats, candidate_speeds,
                        candidate_apex, candidate_width, candidate_lookahead,
                    ))
                lookahead_scored.sort(key=lambda item: item[0])
                search_lookahead = lookahead_scored[0][5]

                # Explore width/apex around the fastest lookahead. This avoids
                # a full Cartesian product while still capturing the strongest
                # interaction between transition distance and corner shape.
                for apex_delta in (-10, -5, 0, 5, 10):
                    for width_delta in (-15, -8, 8, 15):
                        trial_apex = int(np.clip(apex_position_pct + apex_delta, 40, 80))
                        trial_width = int(np.clip(corner_width_pct + width_delta, 0, 100))
                        key = (trial_apex, trial_width, float(search_lookahead))
                        if key in seen:
                            continue
                        seen.add(key)
                        trial = optimize_race_line(
                            self.trk, self.centerline, [p.dlong for p in unique],
                            margin_feet=margin_feet,
                            reference_dlats=[p.dlat for p in unique],
                            pit_side=pit_side, lookahead_feet=search_lookahead,
                            corner_width_pct=trial_width,
                            apex_position_pct=trial_apex,
                            side_preference=side_preference,
                            side_preference_pct=side_preference_pct,
                        )
                        candidates.append((
                            trial, trial_apex, trial_width, search_lookahead
                        ))
                        if progress_callback:
                            progress_callback(
                                min(len(candidates), max_progress - 2), max_progress,
                                f"Generating candidate {len(candidates)}"
                            )

            scored = []
            for score_index, (
                candidate_dlats, candidate_apex, candidate_width, candidate_lookahead
            ) in enumerate(candidates, 1):
                if compare_candidates and progress_callback:
                    progress_callback(
                        min(24 + score_index, 28), 30,
                        f"Scoring candidate {score_index} of {len(candidates)}"
                    )
                lap_seconds, candidate_speeds = evaluate_candidate(candidate_dlats)
                scored.append((
                    lap_seconds, candidate_dlats, candidate_speeds,
                    candidate_apex, candidate_width, candidate_lookahead,
                ))

            # Remove parameter duplicates created by range clipping/rounding.
            deduped = {}
            for item in scored:
                key = (item[3], item[4], round(float(item[5]), 3))
                previous = deduped.get(key)
                if previous is None or item[0] < previous[0]:
                    deduped[key] = item
            scored = sorted(deduped.values(), key=lambda item: item[0])

            if compare_candidates:
                best = scored[0]
                refine_seen = {
                    (item[3], item[4], round(float(item[5]), 3)) for item in scored
                }
                # Refine all three dimensions around the coarse winner.
                for apex_delta, width_delta, lookahead_delta in (
                    (-3, -4, 0.0), (3, 4, 0.0),
                    (0, -4, -10.0), (0, 4, 10.0),
                ):
                    trial_apex = int(np.clip(best[3] + apex_delta, 40, 80))
                    trial_width = int(np.clip(best[4] + width_delta, 0, 100))
                    trial_lookahead = float(np.clip(
                        best[5] + lookahead_delta, 10.0, 500.0
                    ))
                    key = (trial_apex, trial_width, round(trial_lookahead, 3))
                    if key in refine_seen:
                        continue
                    refine_seen.add(key)
                    trial = optimize_race_line(
                        self.trk, self.centerline, [p.dlong for p in unique],
                        margin_feet=margin_feet,
                        reference_dlats=[p.dlat for p in unique],
                        pit_side=pit_side, lookahead_feet=trial_lookahead,
                        corner_width_pct=trial_width,
                        apex_position_pct=trial_apex,
                        side_preference=side_preference,
                        side_preference_pct=side_preference_pct,
                    )
                    lap_seconds, candidate_speeds = evaluate_candidate(trial)
                    scored.append((
                        lap_seconds, trial, candidate_speeds,
                        trial_apex, trial_width, trial_lookahead,
                    ))
                scored.sort(key=lambda item: item[0])

                # One meaningful per-corner parameter pass. The previous
                # repeated/fine passes were expensive for very small gains.
                global_best = scored[0]
                local_overrides = {}
                local_trials = 0
                accepted_changes = 0
                max_local_corners = 24
                detected_corner_count = max_local_corners

                for corner_index in range(max_local_corners):
                    current = {
                        "apex_position_pct": global_best[3],
                        "corner_width_pct": global_best[4],
                    }
                    corner_best = global_best
                    corner_best_override = None
                    found_effect = False
                    for apex_delta, width_delta in (
                        (-8, 0), (8, 0), (0, -10), (0, 10),
                        (-5, 8), (5, 8),
                    ):
                        trial_setting = {
                            "apex_position_pct": int(np.clip(
                                current["apex_position_pct"] + apex_delta, 40, 80
                            )),
                            "corner_width_pct": int(np.clip(
                                current["corner_width_pct"] + width_delta, 0, 100
                            )),
                        }
                        override = dict(local_overrides)
                        override[corner_index] = trial_setting
                        trial = optimize_race_line(
                            self.trk, self.centerline, [p.dlong for p in unique],
                            margin_feet=margin_feet,
                            reference_dlats=[p.dlat for p in unique],
                            pit_side=pit_side, lookahead_feet=global_best[5],
                            corner_width_pct=global_best[4],
                            apex_position_pct=global_best[3],
                            side_preference=side_preference,
                            side_preference_pct=side_preference_pct,
                            local_overrides=override,
                        )
                        lap_seconds, candidate_speeds = evaluate_candidate(trial)
                        local_trials += 1
                        delta = np.max(np.abs(
                            np.asarray(trial) - np.asarray(global_best[1])
                        ))
                        if delta > 1e-6:
                            found_effect = True
                        if lap_seconds < corner_best[0] - 0.001:
                            corner_best = (
                                lap_seconds, trial, candidate_speeds,
                                global_best[3], global_best[4], global_best[5],
                            )
                            corner_best_override = trial_setting
                    if not found_effect:
                        detected_corner_count = corner_index
                        break
                    if corner_best_override is not None:
                        local_overrides[corner_index] = corner_best_override
                        global_best = corner_best
                        accepted_changes += 1
                    if progress_callback:
                        progress_callback(
                            29, 30,
                            f"Optimizing corner {corner_index + 1}"
                        )

                # Cheap targeted refinement: revisit only corners that
                # already proved useful in the broad pass. This avoids another
                # full-track coordinate-descent pass while giving accepted
                # corners a small chance to settle between coarse steps.
                refinement_trials = 0
                refinement_changes = 0
                for corner_index in list(sorted(local_overrides))[:12]:
                    current = local_overrides[corner_index]
                    corner_best = global_best
                    corner_best_override = current
                    for apex_delta, width_delta in (
                        (-3, 0), (3, 0), (0, -4), (0, 4),
                    ):
                        trial_setting = {
                            "apex_position_pct": int(np.clip(
                                current["apex_position_pct"] + apex_delta, 40, 80
                            )),
                            "corner_width_pct": int(np.clip(
                                current["corner_width_pct"] + width_delta, 0, 100
                            )),
                        }
                        if trial_setting == current:
                            continue
                        override = dict(local_overrides)
                        override[corner_index] = trial_setting
                        trial = optimize_race_line(
                            self.trk, self.centerline, [p.dlong for p in unique],
                            margin_feet=margin_feet,
                            reference_dlats=[p.dlat for p in unique],
                            pit_side=pit_side, lookahead_feet=global_best[5],
                            corner_width_pct=global_best[4],
                            apex_position_pct=global_best[3],
                            side_preference=side_preference,
                            side_preference_pct=side_preference_pct,
                            local_overrides=override,
                        )
                        lap_seconds, candidate_speeds = evaluate_candidate(trial)
                        refinement_trials += 1
                        if lap_seconds < corner_best[0] - 0.001:
                            corner_best = (
                                lap_seconds, trial, candidate_speeds,
                                global_best[3], global_best[4], global_best[5],
                            )
                            corner_best_override = trial_setting
                    if corner_best[0] < global_best[0] - 0.001:
                        local_overrides[corner_index] = corner_best_override
                        global_best = corner_best
                        refinement_changes += 1
                    if progress_callback:
                        progress_callback(
                            29, 30,
                            f"Refining accepted corner {corner_index + 1}"
                        )

                if local_overrides:
                    scored.append(global_best)
                    scored.sort(key=lambda item: item[0])
                local_summary = ""
                if local_overrides:
                    settings = ", ".join(
                        f"C{index + 1}={value['corner_width_pct']}%/"
                        f"{value['apex_position_pct']}%"
                        for index, value in sorted(local_overrides.items())
                    )
                    local_summary = (
                        f" Local corner optimization tested {local_trials} variations, "
                        f"accepted {accepted_changes} changes, and kept "
                        f"{len(local_overrides)} overrides: "
                        f"{settings}. Targeted refinement tested {refinement_trials} "
                        f"variations and kept {refinement_changes} changes."
                    )
                else:
                    local_summary = (
                        f" Local corner optimization tested {local_trials} variations; "
                        f"none improved the global solution. Targeted refinement "
                        f"tested {refinement_trials} variations and kept "
                        f"{refinement_changes} changes."
                    )
            else:
                local_summary = ""

            best = scored[0]
            (
                best_lap_seconds, unique_dlats, speeds,
                chosen_apex, chosen_width, chosen_lookahead,
            ) = best
            if compare_candidates:
                baseline = next(
                    item for item in scored
                    if item[3] == apex_position_pct
                    and item[4] == corner_width_pct
                    and abs(item[5] - lookahead_feet) < 0.001
                )
                baseline_seconds = baseline[0]
                slowest_seconds = max(item[0] for item in scored)
                baseline_offsets = np.asarray(baseline[1], dtype=float) / 6000.0
                separations = []
                for item in scored:
                    diff = np.abs(
                        np.asarray(item[1], dtype=float) / 6000.0 - baseline_offsets
                    )
                    separations.extend(diff.tolist())
                avg_separation = float(np.mean(separations))
                max_separation = float(np.max(separations))

                # Diagnose where the winning geometry actually differs from
                # the requested baseline. Group adjacent LP records into
                # regions so a single corner appears once rather than as a
                # long list of individual samples.
                winner_diff = np.abs(
                    np.asarray(best[1], dtype=float) / 6000.0 - baseline_offsets
                )
                significant = winner_diff >= max(2.0, 0.35 * float(np.max(winner_diff)))
                regions = []
                start_index = None
                for idx, is_significant in enumerate(significant):
                    if is_significant and start_index is None:
                        start_index = idx
                    elif not is_significant and start_index is not None:
                        regions.append((start_index, idx - 1))
                        start_index = None
                if start_index is not None:
                    regions.append((start_index, len(significant) - 1))

                region_details = []
                for start_idx, end_idx in regions:
                    local = winner_diff[start_idx:end_idx + 1]
                    peak_rel = int(np.argmax(local))
                    peak_idx = start_idx + peak_rel
                    region_details.append((
                        float(local[peak_rel]), start_idx, end_idx, peak_idx
                    ))
                region_details.sort(reverse=True)
                difference_summary = ""
                if region_details:
                    descriptions = []
                    for peak_ft, start_idx, end_idx, peak_idx in region_details[:5]:
                        start_dlong = float(unique[start_idx].dlong)
                        end_dlong = float(unique[end_idx].dlong)
                        peak_dlong = float(unique[peak_idx].dlong)
                        descriptions.append(
                            f"DLONG {start_dlong:.0f}-{end_dlong:.0f} "
                            f"(peak {peak_ft:.2f} ft at {peak_dlong:.0f})"
                        )
                    difference_summary = (
                        " Winner-vs-baseline largest difference regions: "
                        + "; ".join(descriptions) + "."
                    )
                else:
                    difference_summary = (
                        " Winner stayed within 2 ft of the baseline everywhere."
                    )

                top_summary = ", ".join(
                    f"{item[0]:.3f}s ({item[4]}% width/{item[3]}% apex/"
                    f"{item[5]:g} ft lookahead)"
                    for item in scored[:3]
                )
                search_summary = (
                    f" Compared {len(scored)} candidates: baseline "
                    f"{baseline_seconds:.3f}s, winner {best_lap_seconds:.3f}s "
                    f"({best_lap_seconds - baseline_seconds:+.3f}s), slowest "
                    f"{slowest_seconds:.3f}s. Relative to baseline, candidates "
                    f"averaged {avg_separation:.2f} ft lateral separation and "
                    f"reached {max_separation:.2f} ft maximum."
                    f"{difference_summary}{local_summary} Top 3: {top_summary}."
                )
                if progress_callback:
                    progress_callback(30, 30, "Finalizing fastest candidate")
            else:
                search_summary = ""
            if lp_name == "PIT" and pit_speed_start_dlong is not None and pit_speed_end_dlong is not None:
                start = float(pit_speed_start_dlong) % track_length
                end = float(pit_speed_end_dlong) % track_length
                for index, point in enumerate(unique):
                    dlong = float(point.dlong) % track_length
                    in_zone = (
                        start <= dlong <= end if start <= end
                        else dlong >= start or dlong <= end
                        )
                    if in_zone:
                        speeds[index] = min(79.0, max_speed_mph)

            if has_terminal:
                dlats = unique_dlats + [unique_dlats[0]]
                speed_values = speeds.tolist() + [float(speeds[0])]
            else:
                dlats = unique_dlats
                speed_values = speeds.tolist()
            records = []
            for old, dlat, speed_mph in zip(existing, dlats, speed_values):
                x, y, _ = getxyz(self.trk, old.dlong, dlat, self.centerline)
                records.append(LpPoint(
                    x=x, y=y, dlong=old.dlong, dlat=dlat,
                    speed_raw=int(round(speed_mph * 5280 / 9)),
                    speed_mph=float(speed_mph),
                    lateral_speed=old.lateral_speed,
                ))
        except (ValueError, IndexError, TypeError, ArithmeticError) as exc:
            return False, f"Could not generate a candidate line: {exc}"
        if len(records) != len(existing):
            return False, "The generated path did not match the LP record count."
        if self._ai_lines is None:
            self._ai_lines = {}
        self._ai_lines[lp_name] = records
        self._manual_lp_overrides.add(lp_name)
        self._pending_ai_line_loads.discard(lp_name)
        self._ai_line_cache_generation += 1
        self._dirty_lp_files.add(lp_name)
        pit_note = (
            " PIT speed-limit zone capped at 79 mph."
            if lp_name == "PIT" and pit_speed_start_dlong is not None
            and pit_speed_end_dlong is not None else ""
        )
        return True, (
            f"Generated a {len(records)}-record candidate {lp_name} path with "
            f"{margin_feet:g} ft center clearance from the paved edge. "
            f"Pit: {pit_side}; lookahead: {lookahead_feet:g} ft; "
            f"requested corner width/apex: {corner_width_pct}%/{apex_position_pct}%; "
            + (
                f"lap-time search selected: {chosen_width}%/{chosen_apex}%/"
                f"{chosen_lookahead:g} ft "
                f"from {len(scored)} candidates ({best_lap_seconds:.3f} s modeled); "
                if compare_candidates else
                f"single-line mode ({best_lap_seconds:.3f} s modeled); "
            ) + 
            f"maximum speed: {max_speed_mph:g} mph."
            f"{search_summary}"
            f"{pit_note} Speeds use the 1995 CART performance model. "
            f"Lateral-speed fields were retained; review/recalculate them before "
            f"saving {lp_name}.LP."
        )

    def generate_pathfinder_line(
        self, lp_name: str, margin_feet: float = 5.0, *,
        progress_callback=None,
        max_speed_mph: float = 230.0,
        car_performance: CarPerformance | None = None,
    ) -> tuple[bool, str]:
        """Construct a new LP path using straight/arc beam search."""
        if not lp_name or lp_name == "center-line":
            return False, "Select an LP line first."
        existing = self.get_ai_line_records_immediate(lp_name)
        if len(existing) < 16:
            return False, f"{lp_name}.LP needs at least 16 path samples."
        track_length = float(self.trk.trklength)
        has_terminal = abs(existing[-1].dlong - track_length) < 1.0
        unique = existing[:-1] if has_terminal else existing
        dlongs = [p.dlong for p in unique]
        seed = [p.dlat for p in unique]
        lower, upper = build_legal_dlat_envelope(
            self.trk, self.centerline, dlongs, seed,
            margin_feet=margin_feet, pit_side="auto",
        )
        center_xy = []
        for old in unique:
            cx, cy, _ = getxyz(self.trk, old.dlong, 0.0, self.centerline)
            center_xy.append((cx / 6000.0, cy / 6000.0))

        # Determine whether positive ICR2 DLAT points to the geometric left or
        # right of increasing DLONG. Pathfinder needs this only to convert a
        # world-space centerline projection back into signed DLAT.
        c0 = np.asarray(center_xy[0], dtype=float)
        tangent = np.asarray(center_xy[1], dtype=float) - np.asarray(center_xy[-1], dtype=float)
        tangent_norm = max(float(np.linalg.norm(tangent)), 1.0e-12)
        tangent /= tangent_norm
        px, py, _ = getxyz(
            self.trk, unique[0].dlong, 6000.0, self.centerline
        )
        positive_offset = np.asarray((px / 6000.0, py / 6000.0), dtype=float) - c0
        cross = tangent[0] * positive_offset[1] - tangent[1] * positive_offset[0]
        dlat_sign = 1.0 if cross >= 0.0 else -1.0

        dlats, tested, intervals, commit_retries, continuity_recoveries = generate_pathfinder(
            dlongs, lower, upper, seed,
            center_xy=center_xy,
            start_xy=None,
            track_length_feet=track_length / 6000.0,
            dlat_sign=dlat_sign,
            progress_callback=progress_callback,
        )
        xy = []
        for old, dlat in zip(unique, dlats):
            x, y, _ = getxyz(self.trk, old.dlong, dlat, self.centerline)
            xy.append((x / 6000.0, y / 6000.0))
        speeds = np.minimum(speed_profile_mph(xy, car_performance), max_speed_mph)
        arr = np.asarray(xy, dtype=float)
        ds = np.linalg.norm(np.roll(arr, -1, axis=0) - arr, axis=1)
        segment_mph = np.maximum((speeds + np.roll(speeds, -1)) * 0.5, 0.01)
        lap_seconds = float(np.sum((ds / 5280.0) / segment_mph) * 3600.0)
        distance_miles = float(np.sum(ds) / 5280.0)
        avg_mph = distance_miles / max(lap_seconds / 3600.0, 1e-9)

        records = []
        for old, dlat, speed in zip(unique, dlats, speeds):
            x, y, _ = getxyz(self.trk, old.dlong, dlat, self.centerline)
            records.append(LpPoint(
                x=x, y=y, dlong=old.dlong, dlat=float(dlat),
                speed_raw=int(round(float(speed) * 5280.0 / 9.0)),
                speed_mph=float(speed), lateral_speed=old.lateral_speed,
            ))
        if has_terminal:
            first = records[0]
            records.append(LpPoint(
                x=first.x, y=first.y, dlong=track_length, dlat=first.dlat,
                speed_raw=first.speed_raw, speed_mph=first.speed_mph,
                lateral_speed=first.lateral_speed,
            ))
        self._ai_lines[lp_name] = records
        self._manual_lp_overrides.add(lp_name)
        self._dirty_lp_files.add(lp_name)
        self._ai_line_cache_generation += 1
        return True, (
            "MODEL: Pathfinder\n"
            f"LP: {lp_name}\n"
            f"Planning intervals: {intervals}\n"
            f"Arc/straight states tested: {tested}\n"
            f"Rejected non-continuous first arcs: {commit_retries}\n"
            f"Continuity recoveries: {continuity_recoveries}\n"
            f"Estimated lap: {lap_seconds:.3f} s\n"
            f"Average speed: {avg_mph:.2f} mph\n"
            f"LP distance: {distance_miles:.3f} mi\n\n"
            "Method: receding-horizon world-space arc casting. Pathfinder "
            "casts true XY straight/circular trajectories, projects them back "
            "onto the local centerline to measure actual DLONG progress, rejects "
            "arcs that leave the legal corridor, tests a second-stage continuation "
            "beam, commits one LP interval, then replans. No vehicle physics, "
            "lap-time simulation, apex %, width %, or corner classification is "
            "used to choose the path. Speeds are calculated only after the path "
            "is complete using the same car-performance model as the other generators. "
            "Lateral-speed values are retained."
        )

    def optimize_geometric_line(
        self, lp_name: str, margin_feet: float = 5.0, *,
        progress_callback=None,
    ) -> tuple[bool, str]:
        """Optimize selected LP using path geometry only; no vehicle physics."""
        if not lp_name or lp_name == "center-line":
            return False, "Select an LP line first."
        existing = self.get_ai_line_records_immediate(lp_name)
        if len(existing) < 16:
            return False, f"{lp_name}.LP needs at least 16 path samples."
        track_length = float(self.trk.trklength)
        has_terminal = abs(existing[-1].dlong - track_length) < 1.0
        unique = existing[:-1] if has_terminal else existing
        dlongs = [p.dlong for p in unique]
        seed = [p.dlat for p in unique]
        lower, upper = build_legal_dlat_envelope(
            self.trk, self.centerline, dlongs, seed,
            margin_feet=margin_feet, pit_side="auto",
        )

        def build_xy(dlats):
            result = []
            for old, dlat in zip(unique, dlats):
                x, y, _ = getxyz(self.trk, old.dlong, float(dlat), self.centerline)
                result.append((x / 6000.0, y / 6000.0))
            return result

        dlats, before, after, trials, accepted = optimize_geometric(
            seed, lower, upper, build_xy, progress_callback=progress_callback
        )
        records = []
        for old, dlat in zip(unique, dlats):
            x, y, _ = getxyz(self.trk, old.dlong, dlat, self.centerline)
            records.append(LpPoint(
                x=x, y=y, dlong=old.dlong, dlat=float(dlat),
                speed_raw=old.speed_raw, speed_mph=old.speed_mph,
                lateral_speed=old.lateral_speed,
            ))
        if has_terminal:
            first = records[0]
            records.append(LpPoint(
                x=first.x, y=first.y, dlong=track_length, dlat=first.dlat,
                speed_raw=first.speed_raw, speed_mph=first.speed_mph,
                lateral_speed=first.lateral_speed,
            ))
        self._ai_lines[lp_name] = records
        self._manual_lp_overrides.add(lp_name)
        self._dirty_lp_files.add(lp_name)
        self._ai_line_cache_generation += 1
        improvement = 100.0 * (before - after) / max(abs(before), 1e-12)
        return True, (
            "MODEL: Geometric Optimize\n"
            f"LP: {lp_name}\n"
            f"Path variations tested: {trials}\n"
            f"Accepted changes: {accepted}\n"
            f"Geometry objective: {before:.8g} -> {after:.8g} "
            f"({improvement:.2f}% lower)\n\n"
            "Objective: low/coherent curvature, smooth curvature change, and "
            "limited unnecessary path length. No vehicle physics or lap-time "
            "simulation was used. Existing speed and lateral-speed values were retained."
        )

    def optimize_minimum_time_line(
        self, lp_name: str, margin_feet: float = 5.0, *,
        max_speed_mph: float = 230.0,
        car_performance: CarPerformance | None = None,
        progress_callback=None,
    ) -> tuple[bool, str]:
        """Optimize the selected LP's lateral path directly for modeled lap time."""
        if not lp_name or lp_name == "center-line":
            return False, "Select an LP line first."
        existing = self.get_ai_line_records_immediate(lp_name)
        if len(existing) < 16:
            return False, f"{lp_name}.LP needs at least 16 path samples."
        track_length = float(self.trk.trklength)
        has_terminal = abs(existing[-1].dlong - track_length) < 1.0
        unique = existing[:-1] if has_terminal else existing
        dlongs = [p.dlong for p in unique]
        seed = [p.dlat for p in unique]

        def evaluate(candidate_dlats):
            xy = []
            for old, dlat in zip(unique, candidate_dlats):
                x, y, _ = getxyz(self.trk, old.dlong, float(dlat), self.centerline)
                xy.append((x / 6000.0, y / 6000.0))
            speeds = np.minimum(speed_profile_mph(xy, car_performance), max_speed_mph)
            arr = np.asarray(xy, dtype=float)
            ds = np.linalg.norm(np.roll(arr, -1, axis=0) - arr, axis=1)
            segment_mph = (speeds + np.roll(speeds, -1)) * 0.5
            if np.any(segment_mph <= 0.01):
                return float("inf"), speeds
            seconds = float(np.sum((ds / 5280.0) / segment_mph) * 3600.0)
            return seconds, speeds

        # Select the legal corridor once. From this point onward the
        # minimum-time optimizer is independent of apex/width/lookahead and
        # never calls the geometric racing-line optimizer.
        lower_dlats, upper_dlats = build_legal_dlat_envelope(
            self.trk, self.centerline, dlongs, seed,
            margin_feet=margin_feet, pit_side="auto",
        )

        baseline_time, _ = evaluate(seed)
        (
            dlats, speeds, best_time, trials, accepted, sensitive_regions,
        ) = optimize_minimum_time(
            seed, lower_dlats, upper_dlats, evaluate,
            progress_callback=progress_callback, coarse_controls=48,
        )

        records = []
        for old, dlat, speed in zip(unique, dlats, speeds):
            x, y, _ = getxyz(self.trk, old.dlong, dlat, self.centerline)
            records.append(LpPoint(
                x=x, y=y, dlong=old.dlong, dlat=float(dlat),
                speed_raw=int(round(float(speed) * 5280.0 / 9.0)),
                speed_mph=float(speed), lateral_speed=old.lateral_speed,
            ))
        if has_terminal:
            first = records[0]
            records.append(LpPoint(
                x=first.x, y=first.y, dlong=track_length, dlat=first.dlat,
                speed_raw=first.speed_raw, speed_mph=first.speed_mph,
                lateral_speed=first.lateral_speed,
            ))
        self._ai_lines[lp_name] = records
        self._manual_lp_overrides.add(lp_name)
        self._dirty_lp_files.add(lp_name)
        self._ai_line_cache_generation += 1
        return True, (
            f"Minimum-time optimized {lp_name}: {baseline_time:.3f} s -> "
            f"{best_time:.3f} s ({best_time - baseline_time:+.3f} s). "
            f"Tested {trials} direct path variations, found {sensitive_regions} "
            f"sensitive regions, and accepted {accepted} changes. "
            "This search used the precomputed legal track envelope and did not "
            "call the geometric racing-line optimizer. Lateral-speed values were "
            "retained; recalculate them if needed."
        )

    def lp_lap_statistics(self, lp_name: str) -> tuple[bool, str, float, float]:
        """Estimate lap time and average speed from the current LP speed profile."""
        if self.trk is None or not self.centerline:
            return False, "Load a track first.", 0.0, 0.0
        if not lp_name or lp_name == "center-line" or lp_name not in self.available_lp_files:
            return False, "Select an LP line first.", 0.0, 0.0
        records = self.get_ai_line_records_immediate(lp_name)
        if len(records) < 3:
            return False, f"{lp_name}.LP does not contain enough records.", 0.0, 0.0
        track_length = float(self.trk.trklength)
        has_terminal = abs(records[-1].dlong - track_length) < 1.0
        points = records[:-1] if has_terminal else records
        if len(points) < 3:
            return False, f"{lp_name}.LP does not contain enough unique records.", 0.0, 0.0
        xy = np.array([(p.x / 6000.0, p.y / 6000.0) for p in points], dtype=float)
        distances_ft = np.linalg.norm(np.roll(xy, -1, axis=0) - xy, axis=1)
        speeds_mph = np.array([max(0.0, float(p.speed_mph)) for p in points])
        next_speeds = np.roll(speeds_mph, -1)
        # Integrate each segment using mean endpoint speed. This uses the actual
        # LP path distance rather than nominal centerline length.
        segment_mph = (speeds_mph + next_speeds) * 0.5
        if np.any(segment_mph <= 0.01):
            return False, f"{lp_name}.LP contains zero/invalid speeds.", 0.0, 0.0
        hours = np.sum((distances_ft / 5280.0) / segment_mph)
        distance_miles = float(np.sum(distances_ft) / 5280.0)
        if hours <= 0.0:
            return False, "Could not calculate lap time.", 0.0, 0.0
        lap_seconds = float(hours * 3600.0)
        average_mph = distance_miles / float(hours)
        return True, (
            f"{lp_name}.LP estimated lap: {lap_seconds:.3f} s; "
            f"average speed: {average_mph:.2f} mph; "
            f"LP distance: {distance_miles:.3f} mi."
        ), lap_seconds, average_mph

    def closest_boundary_elevation_at(self, x: float, y: float) -> int | None:
        """Return the nearest boundary elevation to a world-space XY coordinate."""
        if self.trk is None or not self.centerline:
            return None

        best_distance_sq: float | None = None
        best_z: float | None = None
        track_length = float(getattr(self.trk, "trklength", 0) or 0.0)

        for section_index, section in enumerate(getattr(self.trk, "sects", [])):
            section_length = float(getattr(section, "length", 0.0) or 0.0)
            if section_length <= 0:
                continue
            section_start = float(getattr(section, "start_dlong", 0.0) or 0.0)
            sample_count = max(2, min(33, int(math.ceil(section_length / 2000.0)) + 1))

            for sample_index in range(sample_count):
                ratio = sample_index / (sample_count - 1)
                dlong = section_start + section_length * ratio
                if track_length > 0:
                    dlong %= track_length
                for boundary_index in range(int(getattr(section, "num_bounds", 0) or 0)):
                    try:
                        dlat = getbounddlat(self.trk, section_index, ratio, boundary_index)
                        bx, by, bz = getxyz(self.trk, dlong, dlat, self.centerline)
                    except Exception:
                        continue
                    distance_sq = (float(bx) - float(x)) ** 2 + (float(by) - float(y)) ** 2
                    if best_distance_sq is None or distance_sq < best_distance_sq:
                        best_distance_sq = distance_sq
                        best_z = float(bz)

        if best_z is None:
            return None
        return int(round(best_z))

    def _create_lp_records_from_replay(
        self,
        rpy: Rpy,
        car_id: int,
        start_frame: int,
        end_frame: int,
    ) -> tuple[list[LpPoint] | None, str]:
        if self.trk is None or not self.centerline or self.track_length is None:
            return None, "No track loaded to generate LP data."
        if car_id not in rpy.car_index:
            return None, "Selected replay car is unavailable."
        car_index = rpy.car_index.index(car_id)
        dlongs = rpy.cars[car_index].dlong
        dlats = rpy.cars[car_index].dlat
        if not dlongs or not dlats:
            return None, "Replay lap data is empty."
        start = max(0, start_frame - 2)
        end = min(len(dlongs), end_frame + 2)
        if end <= start:
            return None, "Replay lap range is invalid."
        frames = end - start
        if frames < 5:
            return None, "Replay lap is too short to generate LP data."
        track_length = int(self.track_length or self.trk.trklength or 0)
        if track_length <= 0:
            return None, "Track length is not available."

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
                return None, f"Unable to calculate replay radius at frame {i}."

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
                    return None, "Replay radius calculation produced zero values."
                a = (
                    (2 * t1_radius[prev] - t1_dlat[cur] - t1_dlat[prev])
                    * (t1_dlong[cur] - t1_dlong[prev])
                    / denom
                )
                b = t1_dlat[cur] - t1_dlat[prev]
                t1_prev_rw_len.append(math.sqrt(a**2 + b**2))
            if next_frame >= frames:
                return None, "Replay lap data is too short for interpolation."

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
                return None, "Replay lap data has duplicate DLONG entries."
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
                return None, f"Unable to calculate LP radius at record {i}."

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
                    return None, "LP radius calculation produced zero values."
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
                return None, f"Failed to project LP record at DLONG {dlong:.0f}: {exc}"
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
            return None, "No LP records were generated from the replay lap."
        return records, "Generated LP records from replay lap."

    def generate_lp_line_from_replay(
        self,
        lp_name: str,
        rpy: Rpy,
        car_id: int,
        start_frame: int,
        end_frame: int,
    ) -> tuple[bool, str]:
        if not lp_name or lp_name == "center-line":
            return False, "Select a valid LP line to replace."
        if lp_name not in self.available_lp_files:
            return False, f"{lp_name} is not available for editing."
        records, message = self._create_lp_records_from_replay(
            rpy, car_id, start_frame, end_frame
        )
        if records is None:
            return False, message
        if self._ai_lines is None:
            self._ai_lines = {}
        self._ai_lines[lp_name] = records
        self._manual_lp_overrides.add(lp_name)
        self._pending_ai_line_loads.discard(lp_name)
        self._ai_line_cache_generation += 1
        self._dirty_lp_files.add(lp_name)
        return True, f"Generated {lp_name} LP line from replay lap."

    def copy_lp_speeds_from_replay(
        self,
        lp_name: str,
        rpy: Rpy,
        car_id: int,
        start_frame: int,
        end_frame: int,
    ) -> tuple[bool, str]:
        if not lp_name or lp_name == "center-line":
            return False, "Select a valid LP line to update."
        if lp_name not in self.available_lp_files:
            return False, f"{lp_name} is not available for editing."
        existing_records = self._get_ai_line_records(lp_name)
        if not existing_records:
            return False, f"No {lp_name} LP records are loaded."
        replay_records, message = self._create_lp_records_from_replay(
            rpy, car_id, start_frame, end_frame
        )
        if replay_records is None:
            return False, message
        if len(existing_records) != len(replay_records):
            return False, "Replay lap speed data does not match the LP record count."
        updated_records: list[LpPoint] = []
        for record, replay_record in zip(existing_records, replay_records):
            updated_records.append(
                LpPoint(
                    x=record.x,
                    y=record.y,
                    dlong=record.dlong,
                    dlat=record.dlat,
                    speed_raw=replay_record.speed_raw,
                    speed_mph=replay_record.speed_mph,
                    lateral_speed=record.lateral_speed,
                    angle_deg=record.angle_deg,
                )
            )
        if self._ai_lines is None:
            self._ai_lines = {}
        self._ai_lines[lp_name] = updated_records
        self._manual_lp_overrides.add(lp_name)
        self._pending_ai_line_loads.discard(lp_name)
        self._ai_line_cache_generation += 1
        self._dirty_lp_files.add(lp_name)
        return True, f"Updated {lp_name} LP speeds from replay lap."

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
        self._dirty_lp_files.discard(lp_name)
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
            self._dirty_lp_files.discard(lp_name)
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

    def export_all_lp_csvs(self, output_dir: Path) -> tuple[bool, str]:
        """Export all available AI lines to CSV files."""
        if not self.available_lp_files:
            return False, "No LP files are available for export."
        if not output_dir.exists():
            return False, "Selected export folder does not exist."
        if not output_dir.is_dir():
            return False, "Selected export path is not a folder."
        exported: list[str] = []
        failures: list[str] = []
        for lp_name in sorted(self.available_lp_files):
            records = self.get_ai_line_records_immediate(lp_name)
            if not records:
                failures.append(f"{lp_name} (no records loaded)")
                continue
            try:
                output_path = output_dir / f"{lp_name}.csv"
                self._io_service.export_lp_csv(output_path, lp_name, records)
            except Exception as exc:
                failures.append(f"{lp_name} ({exc})")
                continue
            exported.append(lp_name)
        if failures:
            prefix = (
                f"Exported {len(exported)} LP file(s)."
                if exported
                else "No LP files exported."
            )
            message = "\n".join(
                [prefix, "Failed to export:", *[f"- {item}" for item in failures]]
            )
            return False, message
        return True, f"Exported {len(exported)} LP file(s)."

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
            (
                num_lp_recs,
                lp_rw_speed,
                lp_dlat,
                lp_dlong,
                lp_lateral_speed,
            ) = load_lp_csv(str(csv_path), track_length, include_lateral_speed=True)
        except Exception as exc:
            return False, f"Failed to import CSV: {exc}"
        if num_lp_recs < 2:
            return False, "CSV does not contain enough LP records."
        records: list[LpPoint] = []
        for speed_raw, dlat, dlong, lateral_speed in zip(
            lp_rw_speed, lp_dlat, lp_dlong, lp_lateral_speed
        ):
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
                    lateral_speed=float(lateral_speed),
                )
            )
        if self._ai_lines is None:
            self._ai_lines = {}
        self._ai_lines[lp_name] = records
        self._manual_lp_overrides.add(lp_name)
        self._pending_ai_line_loads.discard(lp_name)
        self._ai_line_cache_generation += 1
        self._dirty_lp_files.add(lp_name)
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
