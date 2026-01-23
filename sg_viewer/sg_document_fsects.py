from __future__ import annotations

import copy
from typing import TypedDict

from icr2_core.trk.sg_classes import SGFile

FSECT_EPSILON = 1e-6
GROUND_TYPES = {0, 1, 2, 3, 4, 5, 6}


class FSection(TypedDict):
    start_dlat: float
    end_dlat: float
    surface_type: int
    type2: int


def normalize_fsections(fsects: list[FSection]) -> list[FSection]:
    normalized: list[FSection] = []
    for fsect in fsects:
        data = copy.deepcopy(fsect)
        start = float(data.get("start_dlat", 0.0))
        end = float(data.get("end_dlat", 0.0))
        surface_type = int(data.get("surface_type", 0))
        type2 = int(data.get("type2", 0))

        if start > end:
            start, end = end, start

        if abs(start - end) < FSECT_EPSILON:
            continue

        normalized.append(
            {
                "start_dlat": start,
                "end_dlat": end,
                "surface_type": surface_type,
                "type2": type2,
            }
        )

    normalized.sort(key=lambda item: (item["start_dlat"], item["end_dlat"]))
    return normalized


def insert_fsection(
    sg_data: SGFile, section_id: int, index: int, fsect: FSection
) -> list[FSection]:
    section = _get_section(sg_data, section_id)
    fsects = _extract_fsections(section)
    if index < 0 or index > len(fsects):
        raise IndexError("F-section index out of range.")
    fsects.insert(index, copy.deepcopy(fsect))
    normalized = normalize_fsections(fsects)
    _apply_fsections(section, normalized)
    return normalized


def update_fsection(
    sg_data: SGFile, section_id: int, index: int, **fields: object
) -> list[FSection]:
    section = _get_section(sg_data, section_id)
    fsects = _extract_fsections(section)
    if index < 0 or index >= len(fsects):
        raise IndexError("F-section index out of range.")
    updated = copy.deepcopy(fsects[index])
    for key, value in fields.items():
        updated[key] = copy.deepcopy(value)
    fsects[index] = updated
    normalized = normalize_fsections(fsects)
    _apply_fsections(section, normalized)
    return normalized


def delete_fsection(sg_data: SGFile, section_id: int, index: int) -> list[FSection]:
    section = _get_section(sg_data, section_id)
    fsects = _extract_fsections(section)
    if index < 0 or index >= len(fsects):
        raise IndexError("F-section index out of range.")
    fsects.pop(index)
    normalized = normalize_fsections(fsects)
    _apply_fsections(section, normalized)
    return normalized


def replace_fsections(
    sg_data: SGFile, section_id: int, new_fsects: list[FSection]
) -> list[FSection]:
    section = _get_section(sg_data, section_id)
    normalized = normalize_fsections([copy.deepcopy(fsect) for fsect in new_fsects])
    _apply_fsections(section, normalized)
    return normalized


def _get_section(sg_data: SGFile, section_id: int) -> SGFile.Section:
    if section_id < 0 or section_id >= len(sg_data.sects):
        raise IndexError("Section index out of range.")
    return sg_data.sects[section_id]


def _extract_fsections(section: SGFile.Section) -> list[FSection]:
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
    return fsects


def _apply_fsections(section: SGFile.Section, fsects: list[FSection]) -> None:
    section.num_fsects = len(fsects)
    section.ftype1 = [int(fsect["surface_type"]) for fsect in fsects]
    section.ftype2 = [int(fsect["type2"]) for fsect in fsects]
    section.fstart = [int(round(fsect["start_dlat"])) for fsect in fsects]
    section.fend = [int(round(fsect["end_dlat"])) for fsect in fsects]

    section.ground_ftype = []
    section.ground_fstart = []
    section.ground_fend = []
    section.bound_ftype1 = []
    section.bound_ftype2 = []
    section.bound_fstart = []
    section.bound_fend = []

    for fsect in fsects:
        surface_type = int(fsect["surface_type"])
        start = int(round(fsect["start_dlat"]))
        end = int(round(fsect["end_dlat"]))
        if surface_type in GROUND_TYPES:
            section.ground_ftype.append(surface_type)
            section.ground_fstart.append(start)
            section.ground_fend.append(end)
        else:
            section.bound_ftype1.append(surface_type)
            section.bound_ftype2.append(int(fsect["type2"]))
            section.bound_fstart.append(start)
            section.bound_fend.append(end)

    section.num_ground_fsects = len(section.ground_ftype)
    section.num_boundaries = len(section.bound_ftype1)
