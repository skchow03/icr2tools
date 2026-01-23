from __future__ import annotations

from typing import Iterable


def _xsect_dlats(sg) -> list[float]:
    dlats: Iterable[float] = getattr(sg, "xsect_dlats", [])
    return [float(value) for value in dlats]


def _denormalize_dlat(sg, dlat: float) -> float:
    dlats = _xsect_dlats(sg)
    if not dlats:
        return dlat

    min_dlat = min(dlats)
    max_dlat = max(dlats)
    if min_dlat == max_dlat:
        return min_dlat

    clamped = min(max(dlat, 0.0), 1.0)
    return min_dlat + (max_dlat - min_dlat) * clamped


def _xsect_pair_for_dlat(dlats: list[float], dlat: float) -> tuple[int, int]:
    if not dlats:
        return 0, 0

    if dlat <= dlats[0]:
        return 0, 0
    if dlat >= dlats[-1]:
        last = len(dlats) - 1
        return last, last

    for idx in range(0, len(dlats) - 1):
        if dlats[idx] <= dlat < dlats[idx + 1]:
            return idx + 1, idx

    last = len(dlats) - 1
    return last, last


def _altitude_for_xsect(sg, sect_idx: int, subsect: float, xsect_idx: int) -> float:
    sections = getattr(sg, "sects", [])
    if not sections:
        return 0.0

    num_sects = len(sections)
    prev_idx = (sect_idx - 1) % num_sects
    cur_sect = sections[sect_idx]
    prev_sect = sections[prev_idx]

    begin_alt = float(prev_sect.alt[xsect_idx])
    end_alt = float(cur_sect.alt[xsect_idx])
    sg_length = float(cur_sect.length)
    if sg_length <= 0:
        return begin_alt

    cur_slope = float(prev_sect.grade[xsect_idx]) / 8192.0
    next_slope = float(cur_sect.grade[xsect_idx]) / 8192.0
    grade1 = (2 * begin_alt / sg_length + cur_slope + next_slope - 2 * end_alt / sg_length) * sg_length
    grade2 = (3 * end_alt / sg_length - 3 * begin_alt / sg_length - 2 * cur_slope - next_slope) * sg_length
    grade3 = cur_slope * sg_length

    t = min(max(subsect, 0.0), 1.0)
    return grade1 * t ** 3 + grade2 * t ** 2 + grade3 * t + begin_alt


def sg_xsect_altitude_grade_at(
    sg,
    sect_idx: int,
    subsect: float,
    xsect_idx: int,
) -> tuple[float, float]:
    """
    Return the altitude and grade at ``subsect`` for a specific x-section.
    ``subsect`` is normalized [0..1] within the section.
    """
    sections = getattr(sg, "sects", [])
    if not sections:
        return 0.0, 0.0

    num_sects = len(sections)
    prev_idx = (sect_idx - 1) % num_sects
    cur_sect = sections[sect_idx]
    prev_sect = sections[prev_idx]

    begin_alt = float(prev_sect.alt[xsect_idx])
    end_alt = float(cur_sect.alt[xsect_idx])
    sg_length = float(cur_sect.length)
    if sg_length <= 0:
        return begin_alt, float(prev_sect.grade[xsect_idx])

    cur_slope = float(prev_sect.grade[xsect_idx]) / 8192.0
    next_slope = float(cur_sect.grade[xsect_idx]) / 8192.0
    grade1 = (
        2 * begin_alt / sg_length + cur_slope + next_slope - 2 * end_alt / sg_length
    ) * sg_length
    grade2 = (
        3 * end_alt / sg_length - 3 * begin_alt / sg_length - 2 * cur_slope - next_slope
    ) * sg_length
    grade3 = cur_slope * sg_length

    t = min(max(subsect, 0.0), 1.0)
    altitude = grade1 * t ** 3 + grade2 * t ** 2 + grade3 * t + begin_alt
    slope = (3 * grade1 * t ** 2 + 2 * grade2 * t + grade3) / sg_length
    return altitude, slope * 8192.0


def sg_altitude_at(
    sg,
    sect_idx: int,
    subsect_idx: int,
    dlat: float,
) -> float:
    """
    Return altitude using SG grade parameters only.
    dlat is normalized [0..1] within the subsection.
    """
    sections = getattr(sg, "sects", [])
    if not sections:
        return 0.0

    dlats = _xsect_dlats(sg)
    actual_dlat = _denormalize_dlat(sg, dlat)
    left_xsect, right_xsect = _xsect_pair_for_dlat(dlats, actual_dlat)

    left_alt = _altitude_for_xsect(sg, sect_idx, subsect_idx, left_xsect)
    right_alt = _altitude_for_xsect(sg, sect_idx, subsect_idx, right_xsect)

    if left_xsect == right_xsect:
        return right_alt

    left_dlat = dlats[left_xsect]
    right_dlat = dlats[right_xsect]
    dlat_distance = left_dlat - right_dlat
    if dlat_distance == 0:
        return right_alt

    dlat_to_right = actual_dlat - right_dlat
    distance_percent = dlat_to_right / dlat_distance
    alt_change = left_alt - right_alt
    return right_alt + alt_change * distance_percent


def sample_sg_elevation(
    sg,
    sect_idx: int,
    resolution: int = 256,
) -> list[float]:
    """
    Return a list of altitude samples across the section.
    """
    sections = getattr(sg, "sects", [])
    if not sections:
        return []

    dlats = _xsect_dlats(sg)
    if sect_idx < 0 or sect_idx >= len(dlats):
        return []

    min_dlat = min(dlats)
    max_dlat = max(dlats)
    if min_dlat == max_dlat:
        dlat_norm = 0.0
    else:
        dlat_norm = (dlats[sect_idx] - min_dlat) / (max_dlat - min_dlat)

    samples = max(int(resolution), 1)
    altitudes: list[float] = []

    for section_index, section in enumerate(sections):
        length = float(section.length)
        if length <= 0:
            continue
        for step in range(samples + 1):
            fraction = step / samples
            altitudes.append(sg_altitude_at(sg, section_index, fraction, dlat_norm))

    return altitudes
