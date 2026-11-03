"""Detect Papyrus track section LOD lists without relying on source labels.

A track index root is LIST { DATA hash, sec0_l0, ... }. Every section
record has eight *positional* entries: four HI, two MED, one LO, and a
trailing DATA table. NIL slots are significant, so inspect the raw LIST
rather than Model.children (which strips NIL pointers).

This is deliberately structural: an unrelated 3DO or an incomplete track
index is not assigned a track-detail control.
"""
from __future__ import annotations

import struct


DETAIL_SLOTS = {"hi": (0, 4), "med": (4, 6), "lo": (6, 7)}


def detect_track_section_lods(model):
    """Map section LIST body offsets to their raw seven geometry slots.

    Return an empty dict unless the entire root matches the track layout.
    Works on either a compiled N3 .3D source or a binary track .3DO.
    """
    root = model.root_offset
    if model.records.get(root) != 11:
        return {}
    children = model.children.get(root, ())
    if len(children) < 2 or model.records.get(children[0]) != 17:
        return {}

    sections = {}
    for offset in children[1:]:
        if model.records.get(offset) != 11:
            return {}
        if struct.unpack_from("<i", model.body, offset + 4)[0] != 8:
            return {}
        slots = struct.unpack_from("<8i", model.body, offset + 8)
        if slots[7] <= 0 or model.records.get(slots[7]) != 17:
            return {}
        if not any(slots[:7]):
            return {}
        if any(pointer < 0 or (pointer and model.records.get(pointer) in (None, 17))
               for pointer in slots[:7]):
            return {}
        sections[offset] = slots[:7]
    return sections


def selected_track_section_lists(sections, detail):
    """Override only the track section LISTs with one detail tier.

    Leave the root hash/index traversal and every nested BSP/LIST intact.
    A missing slot is NIL: do not draw a different tier as fallback.
    """
    if detail not in DETAIL_SLOTS:
        raise ValueError(f"Unknown track section detail: {detail!r}")
    start, end = DETAIL_SLOTS[detail]
    return {offset: tuple(pointer for pointer in slots[start:end] if pointer)
            for offset, slots in sections.items()}
