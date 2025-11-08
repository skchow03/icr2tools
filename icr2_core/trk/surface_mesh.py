"""Utilities for building ground surface meshes from TRK data."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable, List, Optional, Sequence, Tuple

from .trk_classes import TRKFile
from .trk_utils import get_cline_pos, getxyz


Point2D = Tuple[float, float]


@dataclass(frozen=True)
class GroundSurfaceStrip:
    """Represents a single ground f-section rendered as a polygon."""

    points: Tuple[Point2D, Point2D, Point2D, Point2D]
    ground_type: int


def build_ground_surface_mesh(
    trk: TRKFile,
    cline: Optional[Sequence[Tuple[float, float]]] = None,
    *,
    min_area: float = 1e-3,
) -> List[GroundSurfaceStrip]:
    """Generate ground surface polygons for each f-section in ``trk``.

    Parameters
    ----------
    trk:
        Parsed TRK file describing the track geometry.
    cline:
        Optional cached centreline coordinates to avoid recomputation. If ``None``
        the centreline is computed using :func:`get_cline_pos`.
    min_area:
        Minimum polygon area (in game units squared) required for a strip to be
        included in the final mesh. Degenerate quads smaller than this threshold
        are ignored to avoid rendering artefacts.
    """

    if trk is None:
        return []

    if cline is None:
        cline = get_cline_pos(trk)

    strips: List[GroundSurfaceStrip] = []

    for sect_idx, sect in enumerate(trk.sects):
        if sect.ground_fsects <= 0:
            continue

        # Type 1 sections (straights) rarely need subdivision but road sections
        # benefit from multiple slices to follow curvature.
        if sect.type == 1:
            num_subsects = 1
        else:
            num_subsects = max(1, round(sect.length / 60000))

        strips.extend(
            _build_section_quads(
                trk,
                cline,
                sect_idx,
                sect.start_dlong,
                sect.start_dlong + sect.length,
                num_subsects=num_subsects,
                min_area=min_area,
            )
        )

    return strips


def compute_mesh_bounds(
    mesh: Iterable[GroundSurfaceStrip],
) -> Optional[Tuple[float, float, float, float]]:
    """Compute the axis-aligned bounds for a mesh of ground strips."""

    xs: List[float] = []
    ys: List[float] = []
    for strip in mesh:
        for x, y in strip.points:
            xs.append(x)
            ys.append(y)

    if not xs or not ys:
        return None

    return min(xs), max(xs), min(ys), max(ys)


def _build_section_quads(
    trk: TRKFile,
    cline: Sequence[Tuple[float, float]],
    sect_idx: int,
    start_dlong: float,
    end_dlong: float,
    *,
    num_subsects: int,
    min_area: float,
) -> List[GroundSurfaceStrip]:
    sect = trk.sects[sect_idx]
    if sect.ground_fsects <= 0:
        return []

    strips: List[GroundSurfaceStrip] = []

    left_boundary_start = sect.bound_dlat_start[sect.num_bounds - 1]
    left_boundary_end = sect.bound_dlat_end[sect.num_bounds - 1]
    subsection_length = (end_dlong - start_dlong) / max(1, num_subsects)
    left_increment = (left_boundary_end - left_boundary_start) / max(1, num_subsects)

    for sub_idx in range(num_subsects):
        sub_start_dlong = start_dlong + subsection_length * sub_idx
        if sub_idx == num_subsects - 1:
            sub_end_dlong = end_dlong
        else:
            sub_end_dlong = start_dlong + subsection_length * (sub_idx + 1)

        left_start = left_boundary_start + left_increment * sub_idx
        left_end = left_boundary_start + left_increment * (sub_idx + 1)

        for ground_idx in range(sect.ground_fsects - 1, -1, -1):
            right_start_total = sect.ground_dlat_start[ground_idx]
            right_end_total = sect.ground_dlat_end[ground_idx]
            right_span = right_end_total - right_start_total

            right_start = right_start_total + right_span * (sub_idx / num_subsects)
            right_end = right_start_total + right_span * ((sub_idx + 1) / num_subsects)

            polygon = _quad_polygon(
                trk,
                cline,
                sub_start_dlong,
                sub_end_dlong,
                left_start,
                left_end,
                right_start,
                right_end,
            )

            if _polygon_area(polygon) <= min_area:
                continue

            strips.append(
                GroundSurfaceStrip(
                    points=polygon,
                    ground_type=sect.ground_type[ground_idx],
                )
            )

            left_start = right_start
            left_end = right_end

    return strips


def _quad_polygon(
    trk: TRKFile,
    cline: Sequence[Tuple[float, float]],
    start_dlong: float,
    end_dlong: float,
    left_start: float,
    left_end: float,
    right_start: float,
    right_end: float,
) -> Tuple[Point2D, Point2D, Point2D, Point2D]:
    ls_x, ls_y, _ = getxyz(trk, start_dlong, left_start, cline)
    le_x, le_y, _ = getxyz(trk, end_dlong, left_end, cline)
    rs_x, rs_y, _ = getxyz(trk, start_dlong, right_start, cline)
    re_x, re_y, _ = getxyz(trk, end_dlong, right_end, cline)
    return (ls_x, ls_y), (le_x, le_y), (re_x, re_y), (rs_x, rs_y)


def _polygon_area(points: Sequence[Point2D]) -> float:
    if len(points) < 3:
        return 0.0

    area = 0.0
    for idx, (x1, y1) in enumerate(points):
        x2, y2 = points[(idx + 1) % len(points)]
        area += x1 * y2 - x2 * y1
    return abs(area) * 0.5

