from __future__ import annotations

import copy

from sg_viewer.model.preview_fsection import PreviewFSection
from sg_viewer.sg_document_fsects import FSection, normalize_fsections


def build_fsection_preview(sg_document, section_id: int) -> list[PreviewFSection]:
    sg_data = getattr(sg_document, "sg_data", None)
    if sg_data is None or not getattr(sg_data, "sects", None):
        return []

    if section_id < 0 or section_id >= len(sg_data.sects):
        raise IndexError("Section index out of range.")

    section = sg_data.sects[section_id]
    ftype1_list = list(getattr(section, "ftype1", []))
    ftype2_list = list(getattr(section, "ftype2", []))
    fstart_list = list(getattr(section, "fstart", []))
    fend_list = list(getattr(section, "fend", []))

    fsects: list[FSection] = []
    for idx, ftype1 in enumerate(ftype1_list):
        start_dlat = float(fstart_list[idx]) if idx < len(fstart_list) else 0.0
        end_dlat = float(fend_list[idx]) if idx < len(fend_list) else 0.0
        type2 = int(ftype2_list[idx]) if idx < len(ftype2_list) else 0
        fsects.append(
            {
                "start_dlat": start_dlat,
                "end_dlat": end_dlat,
                "surface_type": int(ftype1),
                "type2": type2,
            }
        )

    normalized = normalize_fsections(copy.deepcopy(fsects))
    return [
        PreviewFSection(
            start_dlat=fsect["start_dlat"],
            end_dlat=fsect["end_dlat"],
            surface_type=fsect["surface_type"],
            type2=fsect["type2"],
        )
        for fsect in normalized
    ]
