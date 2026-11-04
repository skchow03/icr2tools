"""Identify Papyrus track-surface-detail (TSD) polygons without names.

In N3, a DetailList contains alternating DetailO POLY and DetailN LINE
records. The original 3DO compiler replaces each LINE with a NIL record
(including nonzero flavor-zero NIL pointers); the visible POLY remains.
Optional DYNAMIC trackside objects may follow the pairs. This structural
signature identifies the decals even in compiled tracks where symbols such
as "DetailList_5-1H" and "DetailO_463-0" are unavailable.

Do not infer surface details from palette indices: real tracks use different
colors for their lines, kerbs, arrows and other surface markings. This pass
does not edit source geometry or vertex Z values.
"""
from __future__ import annotations

import struct


def _raw_list_slots(model, offset):
    if model.records.get(offset) != 11:
        return ()
    if offset < 0 or offset + 8 > len(model.body):
        return ()
    count = struct.unpack_from("<i", model.body, offset + 4)[0]
    if not 0 < count < 250_000 or offset + 8 + count * 4 > len(model.body):
        return ()
    return struct.unpack_from(f"<{count}i", model.body, offset + 8)


def _paired_line_or_nil(model, ptr, fill):
    if ptr == 0 or model.records.get(ptr) == 0:
        return True
    line = model.polygons.get(ptr)
    return (line is not None and line.kind == 1
            and len(line.unique_refs) == 2
            and line.color == fill.color
            and set(line.unique_refs).issubset(fill.unique_refs))


def detect_track_surface_details(model):
    """Return only filled marking POLY offsets in credible DetailLists.

    A matching LIST is nonempty, begins with at least one (POLY,LINE/NIL)
    pair, and has no unrelated geometry; only DYNAMIC placements may appear
    after the pairs. Ordinary asphalt and untextured wall polygons are never
    classified merely by proximity, flatness, color, or material name.
    """
    details = set()
    for offset, kind in model.records.items():
        if kind != 11:
            continue
        children = _raw_list_slots(model, offset)
        if len(children) < 2:
            continue
        candidates = []
        index = 0
        while index + 1 < len(children):
            filled = model.polygons.get(children[index])
            if (filled is None or filled.kind != 1
                    or len(filled.unique_refs) < 3
                    or not _paired_line_or_nil(
                        model, children[index + 1], filled)):
                break
            candidates.append(filled.offset)
            index += 2
        if not candidates:
            continue
        # The only permitted trailing payload is one or more trackside
        # DYNAMIC objects; they must NOT be mistaken for markings.
        if all(model.records.get(p) == 15 for p in children[index:]):
            details.update(candidates)
    return frozenset(details)
