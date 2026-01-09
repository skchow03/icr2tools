"""Shared geometry helpers for the track viewer widget."""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List, Tuple

from icr2_core.lp.loader import load_lp_file
from icr2_core.trk.trk_utils import getxyz
from track_viewer.common.lp_file_utils import resolve_lp_path


Point = Tuple[float, float]


@dataclass
class CenterlineIndex:
    segments: List[Tuple[Point, Point]]
    grid: Dict[tuple[int, int], List[int]]
    origin: Tuple[float, float] | None
    cell_size: float | None
    bounds: Tuple[float, float, float, float] | None


def sample_centerline(
    trk,
    cline: List[Tuple[float, float]],
    step: int = 10000,
) -> Tuple[List[Point], List[float], Tuple[float, float, float, float] | None]:
    if not trk or not cline:
        return [], [], None

    pts: List[Point] = []
    dlongs: List[float] = []
    dlong = 0
    while dlong < trk.trklength:
        x, y, _ = getxyz(trk, dlong, 0, cline)
        pts.append((x, y))
        dlongs.append(dlong)
        dlong += step

    if trk.trklength > 0:
        x, y, _ = getxyz(trk, trk.trklength, 0, cline)
        pts.append((x, y))
        dlongs.append(float(trk.trklength))

    if pts and pts[0] != pts[-1]:
        pts.append(pts[0])
        dlongs.append(float(trk.trklength))

    bounds = None
    if pts:
        xs = [p[0] for p in pts]
        ys = [p[1] for p in pts]
        bounds = (min(xs), max(xs), min(ys), max(ys))
    return pts, dlongs, bounds


def build_centerline_index(
    sampled_centerline: List[Point],
    sampled_bounds: Tuple[float, float, float, float] | None,
) -> CenterlineIndex:
    grid: dict[tuple[int, int], list[int]] = {}
    origin: tuple[float, float] | None = None
    cell_size: float | None = None
    segments: list[tuple[Point, Point]] = []

    if sampled_centerline and sampled_bounds:
        min_x, max_x, min_y, max_y = sampled_bounds
        span_x = max_x - min_x
        span_y = max_y - min_y
        span = max(span_x, span_y)
        if span > 0:
            target_cells = 64
            cell_size = max(span / target_cells, 1.0)
            origin = (min_x, min_y)

            for index, start in enumerate(sampled_centerline):
                end = sampled_centerline[(index + 1) % len(sampled_centerline)]
                segments.append((start, end))
                min_sx = min(start[0], end[0])
                max_sx = max(start[0], end[0])
                min_sy = min(start[1], end[1])
                max_sy = max(start[1], end[1])
                gx0 = int((min_sx - min_x) // cell_size)
                gx1 = int((max_sx - min_x) // cell_size)
                gy0 = int((min_sy - min_y) // cell_size)
                gy1 = int((max_sy - min_y) // cell_size)
                for gx in range(gx0, gx1 + 1):
                    for gy in range(gy0, gy1 + 1):
                        grid.setdefault((gx, gy), []).append(index)

    return CenterlineIndex(segments, grid, origin, cell_size, sampled_bounds)


def query_centerline_segments(index: CenterlineIndex, x: float, y: float) -> list[int]:
    if not index.grid or index.origin is None or index.cell_size is None:
        return list(range(len(index.segments)))

    ox, oy = index.origin
    cell = index.cell_size
    gx = int((x - ox) // cell)
    gy = int((y - oy) // cell)

    candidates: set[int] = set()
    for radius in range(0, 3):
        for cx in range(gx - radius, gx + radius + 1):
            for cy in range(gy - radius, gy + radius + 1):
                candidates.update(index.grid.get((cx, cy), ()))
        if candidates:
            break

    if not candidates:
        return list(range(len(index.segments)))
    return list(candidates)


def project_point_to_centerline(
    cursor: Tuple[float, float],
    index: CenterlineIndex,
    sampled_dlongs: List[float],
    track_length: float,
) -> tuple[Point | None, float | None, float]:
    if not index.segments or not sampled_dlongs or track_length <= 0:
        return None, None, float("inf")

    cursor_x, cursor_y = cursor
    best_point: Point | None = None
    best_dlong: float | None = None
    best_distance_sq = float("inf")

    segment_indices = query_centerline_segments(index, cursor_x, cursor_y)
    for seg_index in segment_indices:
        start, end = index.segments[seg_index]
        start_dlong = sampled_dlongs[seg_index]
        end_dlong = sampled_dlongs[(seg_index + 1) % len(sampled_dlongs)]
        dlong_delta = end_dlong - start_dlong
        if dlong_delta <= 0:
            dlong_delta += track_length

        sx, sy = start
        ex, ey = end
        vx = ex - sx
        vy = ey - sy
        if vx == 0 and vy == 0:
            continue
        t = ((cursor_x - sx) * vx + (cursor_y - sy) * vy) / (vx * vx + vy * vy)
        t = max(0.0, min(1.0, t))
        proj_x = sx + vx * t
        proj_y = sy + vy * t

        distance_sq = (cursor_x - proj_x) ** 2 + (cursor_y - proj_y) ** 2
        if distance_sq < best_distance_sq:
            best_distance_sq = distance_sq
            projected_dlong = start_dlong + dlong_delta * t
            if projected_dlong >= track_length:
                projected_dlong -= track_length
            best_point = (proj_x, proj_y)
            best_dlong = projected_dlong

    return best_point, best_dlong, best_distance_sq


def load_ai_line(
    trk,
    cline: List[Tuple[float, float]],
    track_folder: Path,
    lp_name: str,
    *,
    track_length: float | None = None,
) -> List[Point]:
    if trk is None or not cline:
        return []

    lp_path = resolve_lp_path(track_folder, lp_name)
    if lp_path is None:
        return []

    length_arg = int(track_length) if track_length is not None else None
    try:
        ai_line = load_lp_file(lp_path, track_length=length_arg)
    except Exception:
        return []

    points: List[Point] = []
    for record in ai_line:
        try:
            x, y, _ = getxyz(trk, float(record.dlong), record.dlat, cline)
        except Exception:
            continue
        points.append((x, y))
    return points
