from __future__ import annotations

from pathlib import Path
from typing import Iterable, List

from icr2_core.trk.sg_classes import SGFile
from icr2_core.trk.trk_classes import TRKFile
from icr2_core.trk.trk_utils import getxyz
from track_viewer.geometry import CenterlineIndex, build_centerline_index, sample_centerline

from sg_viewer.sg_geometry import build_section_polyline, derive_heading_vectors
from sg_viewer.sg_model import Point, PreviewData, SectionPreview

def load_preview(path: Path) -> PreviewData:
    sgfile = SGFile.from_sg(str(path))
    trk = TRKFile.from_sg(str(path))
    cline = get_cline_pos(trk)
    sampled, sampled_dlongs, bounds = sample_centerline(trk, cline)

    if not sampled or bounds is None:
        raise ValueError("Failed to build centreline from SG file")

    centerline_index = build_centerline_index(sampled, bounds)
    track_length = float(trk.trklength)
    start_finish_mapping = _centerline_point_normal_and_tangent(trk, cline, track_length, 0.0)
    sections = _build_sections(sgfile, trk, cline, track_length)
    section_endpoints = [(sect.start, sect.end) for sect in sections]

    return PreviewData(
        sgfile=sgfile,
        trk=trk,
        cline=cline,
        sampled_centerline=sampled,
        sampled_dlongs=sampled_dlongs,
        sampled_bounds=bounds,
        centerline_index=centerline_index,
        track_length=track_length,
        start_finish_mapping=start_finish_mapping,
        sections=sections,
        section_endpoints=section_endpoints,
        status_message=f"Loaded {path.name}",
    )


def _build_sections(
    sgfile: SGFile, trk: TRKFile, cline: Iterable[Point] | None, track_length: float
) -> list[SectionPreview]:
    sections: list[SectionPreview] = []

    if cline is None or track_length <= 0:
        return sections

    for idx, (sg_sect, trk_sect) in enumerate(zip(sgfile.sects, trk.sects)):
        start_dlong = float(trk_sect.start_dlong) % track_length
        length = float(trk_sect.length)

        start = (float(sg_sect.start_x), float(sg_sect.start_y))
        end = (
            float(getattr(sg_sect, "end_x", start[0])),
            float(getattr(sg_sect, "end_y", start[1])),
        )

        center = None
        radius = None
        sang1 = sang2 = eang1 = eang2 = None
        if getattr(sg_sect, "type", None) == 2:
            center = (float(sg_sect.center_x), float(sg_sect.center_y))
            radius = float(sg_sect.radius)
            sang1 = float(sg_sect.sang1)
            sang2 = float(sg_sect.sang2)
            eang1 = float(sg_sect.eang1)
            eang2 = float(sg_sect.eang2)

        polyline = build_section_polyline(
            "curve" if getattr(sg_sect, "type", None) == 2 else "straight",
            start,
            end,
            center,
            radius,
            (sang1, sang2) if sang1 is not None and sang2 is not None else None,
            (eang1, eang2) if eang1 is not None and eang2 is not None else None,
        )

        start_heading, end_heading = derive_heading_vectors(polyline, sang1, sang2, eang1, eang2)

        sections.append(
            SectionPreview(
                section_id=idx,
                type_name="curve" if getattr(sg_sect, "type", None) == 2 else "straight",
                previous_id=int(getattr(sg_sect, "sec_prev", idx - 1)),
                next_id=int(getattr(sg_sect, "sec_next", idx + 1)),
                start=start,
                end=end,
                start_dlong=start_dlong,
                length=length,
                center=center,
                sang1=sang1,
                sang2=sang2,
                eang1=eang1,
                eang2=eang2,
                radius=radius,
                start_heading=start_heading,
                end_heading=end_heading,
                polyline=polyline,
            )
        )

    return sections


def _centerline_point_normal_and_tangent(
    trk: TRKFile, cline: Iterable[Point] | None, track_length: float, dlong: float
) -> tuple[tuple[float, float], tuple[float, float], tuple[float, float]] | None:
    if cline is None or track_length <= 0:
        return None

    def _wrap(value: float) -> float:
        while value < 0:
            value += track_length
        while value >= track_length:
            value -= track_length
        return value

    base = _wrap(float(dlong))
    delta = max(50.0, track_length * 0.002)
    prev_dlong = _wrap(base - delta)
    next_dlong = _wrap(base + delta)

    px, py, _ = getxyz(trk, prev_dlong, 0, cline)
    nx, ny, _ = getxyz(trk, next_dlong, 0, cline)
    cx, cy, _ = getxyz(trk, base, 0, cline)

    vx = nx - px
    vy = ny - py
    length = (vx * vx + vy * vy) ** 0.5
    if length == 0:
        return None

    tangent = (vx / length, vy / length)
    normal = (-vy / length, vx / length)

    return (cx, cy), normal, tangent


# Delayed import to avoid circular dependency
from icr2_core.trk.trk_utils import get_cline_pos  # noqa: E402  pylint: disable=C0413
