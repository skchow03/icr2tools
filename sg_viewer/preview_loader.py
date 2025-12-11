from __future__ import annotations

from pathlib import Path
from typing import Iterable

from icr2_core.trk.sg_classes import SGFile
from icr2_core.trk.trk_classes import TRKFile
from track_viewer.geometry import build_centerline_index, sample_centerline

from sg_viewer.centerline_utils import compute_centerline_normal_and_tangent
from sg_viewer.sg_geometry import (
    _heading_from_radius,
    _orientation_from_radii,
    build_section_polyline,
    derive_heading_vectors,
    derive_radius_vectors,
)
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
    start_finish_mapping = compute_centerline_normal_and_tangent(trk, cline, track_length, 0.0)
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

        start_radius, end_radius = derive_radius_vectors(center, start, end, sang1, sang2, eang1, eang2)
        orientation = _orientation_from_radii(start_radius, end_radius)
        start_heading_hint = _heading_from_radius(start_radius, orientation)
        end_heading_hint = _heading_from_radius(end_radius, orientation)

        polyline = build_section_polyline(
            "curve" if getattr(sg_sect, "type", None) == 2 else "straight",
            start,
            end,
            center,
            radius,
            start_heading_hint,
            end_heading_hint,
        )

        start_heading, end_heading = derive_heading_vectors(polyline, start_radius, end_radius)

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


# Delayed import to avoid circular dependency
from icr2_core.trk.trk_utils import get_cline_pos  # noqa: E402  pylint: disable=C0413
