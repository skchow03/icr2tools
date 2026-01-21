from __future__ import annotations

# IMPORTANT:
# SG Viewer preview must NOT depend on TRK.
# TRK is optional and must never be required for live editing.

from pathlib import Path

from icr2_core.trk.sg_classes import SGFile
from icr2_core.trk.trk_classes import TRKFile
from icr2_core.trk.trk_utils import get_cline_pos
from track_viewer.geometry import build_centerline_index, sample_centerline

from sg_viewer.geometry.centerline_utils import compute_start_finish_mapping_from_centerline
from sg_viewer.geometry.sg_geometry import (
    build_section_polyline,
    derive_heading_vectors,
    rebuild_centerline_from_sections,
)
from sg_viewer.models.preview_fsection import PreviewFSection
from sg_viewer.models.sg_model import Point, PreviewData, SectionPreview

def load_preview(path: Path) -> PreviewData:
    sgfile = SGFile.from_sg(str(path))
    return load_preview_from_sgfile(sgfile, status_message=f"Loaded {path.name}")


def load_preview_from_sgfile(
    sgfile: SGFile,
    *,
    status_message: str,
) -> PreviewData:
    return _build_preview_data(sgfile, trk=None, status_message=status_message)


def enable_trk_overlay(preview: PreviewData) -> None:
    trk = TRKFile.from_sgfile(preview.sgfile)
    cline = get_cline_pos(trk)
    object.__setattr__(preview, "trk", trk)
    object.__setattr__(preview, "cline", cline)


def _build_preview_data(
    sgfile: SGFile,
    trk: TRKFile | None,
    *,
    status_message: str,
) -> PreviewData:
    sections = _build_sections(sgfile, trk)
    sampled, sampled_dlongs, bounds, centerline_index = rebuild_centerline_from_sections(sections)

    if not sampled or bounds is None:
        raise ValueError("Failed to build centreline from SG file")

    cline = None
    if trk is not None:
        cline = get_cline_pos(trk)
        trk_sampled, trk_dlongs, trk_bounds = sample_centerline(trk, cline)
        if trk_sampled and trk_bounds is not None:
            sampled = trk_sampled
            sampled_dlongs = trk_dlongs
            bounds = trk_bounds
            centerline_index = build_centerline_index(sampled, bounds)

    track_length = float(sampled_dlongs[-1]) if sampled_dlongs else 0.0
    start_finish_mapping = compute_start_finish_mapping_from_centerline(sampled)
    section_endpoints = [(sect.start, sect.end) for sect in sections]

    return PreviewData(
        sg=sgfile,
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
        fsections=build_fsections(sgfile),
        status_message=status_message,
    )


def _build_sections(
    sgfile: SGFile,
    trk: TRKFile | None,
) -> list[SectionPreview]:
    _ = trk
    sections: list[SectionPreview] = []

    if not sgfile.sects:
        return sections

    for idx, sg_sect in enumerate(sgfile.sects):
        start_dlong = float(sg_sect.start_dlong)
        length = float(sg_sect.length)

        start = (float(sg_sect.start_x), float(sg_sect.start_y))
        end = (
            float(getattr(sg_sect, "end_x", start[0])),
            float(getattr(sg_sect, "end_y", start[1])),
        )
        start_dlat = float(getattr(sg_sect, "start_dlat", 0.0))
        end_dlat = float(getattr(sg_sect, "end_dlat", 0.0))

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
                start_dlat=start_dlat,
                end_dlat=end_dlat,
            )
        )

    return sections


def build_fsections(sgfile: SGFile) -> list[PreviewFSection]:
    fsections: list[PreviewFSection] = []
    for sect in sgfile.sects or []:
        ftype1_list = list(getattr(sect, "ftype1", []))
        ftype2_list = list(getattr(sect, "ftype2", []))
        fstart_list = list(getattr(sect, "fstart", []))
        fend_list = list(getattr(sect, "fend", []))

        for idx, ftype1 in enumerate(ftype1_list):
            start_dlat = float(fstart_list[idx]) if idx < len(fstart_list) else 0.0
            end_dlat = float(fend_list[idx]) if idx < len(fend_list) else 0.0
            type2 = int(ftype2_list[idx]) if idx < len(ftype2_list) else 0

            fsections.append(
                PreviewFSection(
                    start_dlat=start_dlat,
                    end_dlat=end_dlat,
                    surface_type=int(ftype1),
                    type2=type2,
                )
            )

    return fsections


def build_fsects_by_section(sgfile: SGFile) -> list[list[PreviewFSection]]:
    fsects_by_section: list[list[PreviewFSection]] = []
    for sect in sgfile.sects or []:
        ftype1_list = list(getattr(sect, "ftype1", []))
        ftype2_list = list(getattr(sect, "ftype2", []))
        fstart_list = list(getattr(sect, "fstart", []))
        fend_list = list(getattr(sect, "fend", []))

        section_fsects: list[PreviewFSection] = []
        for idx, ftype1 in enumerate(ftype1_list):
            start_dlat = float(fstart_list[idx]) if idx < len(fstart_list) else 0.0
            end_dlat = float(fend_list[idx]) if idx < len(fend_list) else 0.0
            type2 = int(ftype2_list[idx]) if idx < len(ftype2_list) else 0
            section_fsects.append(
                PreviewFSection(
                    start_dlat=start_dlat,
                    end_dlat=end_dlat,
                    surface_type=int(ftype1),
                    type2=type2,
                )
            )

        fsects_by_section.append(section_fsects)

    return fsects_by_section
