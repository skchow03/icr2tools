"""Recognize Papyrus track section HI/MED/LO tables in .3D and .3DO.

The standalone N3 compiler retains the source layout:
    index: LIST { DATA hash, sec0_l0, ... }
    secN_lM: LIST { HI x4, MED x2, LO x1, DATA metadata }

Original track .3DO compilers instead expand the index into the root:
    root: LIST { expanded LIST, section-pointer-per-hash-bin, ... }
    section LIST: { HI x4, MED x2, LO x1 } (seven pointers)

The expanded index references *all* sections in order. The root's hash
entries reference only some of them, often multiple times. Most other
expanded entries alias the same seven LOD pointers, but in some tracks
(e.g. St. Petersburg and Washington, D.C.) a few carry additional
geometry. Keep one representative per distinct seven-slot signature
rather than assuming the expanded index has exactly twice as many entries
as the hash's unique pointers. Do not render the root's original expanded
index as well, which would draw all three LOD tiers simultaneously.
"""
from __future__ import annotations

import struct


DETAIL_SLOTS = {"hi": (0, 4), "med": (4, 6), "lo": (6, 7)}


def _list_slots(model, offset):
    """Return raw LIST children, preserving NIL positions, or None."""
    if model.records.get(offset) != 11:
        return None
    count = struct.unpack_from("<i", model.body, offset + 4)[0]
    if count < 0 or offset + 8 + count * 4 > len(model.body):
        return None
    return struct.unpack_from(f"<{count}i", model.body, offset + 8)


def _section_geometry_slots(model, offset, *, source_layout):
    """Validate the full positional LOD table, returning seven slots."""
    slots = _list_slots(model, offset)
    if slots is None or len(slots) != (8 if source_layout else 7):
        return None
    if source_layout and (slots[7] <= 0 or model.records.get(slots[7]) != 17):
        return None
    geometry = slots[:7]
    if not any(p and model.records.get(p) not in (0, None) for p in geometry):
        return None
    if any(p < 0 or (p and model.records.get(p) in (None, 17))
           for p in geometry):
        return None
    return geometry


def detect_track_section_lods(model):
    """Map recognized section LIST offsets to seven positional LOD pointers.

    For a compiled binary track, this includes extra sections present only
    in the expanded index. Exact duplicate seven-slot layouts are reduced
    to their first representative to avoid drawing identical polygons twice.
    A binary NIL may be a nonzero pointer to a flavor-zero record.
    """
    root_items = _list_slots(model, model.root_offset)
    if not root_items or len(root_items) < 2:
        return {}

    first_kind = model.records.get(root_items[0])
    if first_kind == 17:
        # Source .3D: DATA hash, followed by indexed 8-entry sections.
        offsets = root_items[1:]
        sections = {}
        for offset in offsets:
            geometry = _section_geometry_slots(
                model, offset, source_layout=True)
            if geometry is None:
                return {}
            sections[offset] = geometry
        return sections

    if first_kind != 11:
        return {}

    # Binary .3DO: a large expanded LIST followed by the hash's repeated
    # section references. The hash subset occurs, in sequence, within the
    # expanded list; intervening/outer sections can be genuinely distinct.
    indexed = tuple(dict.fromkeys(root_items[1:]))
    expanded = _list_slots(model, root_items[0])
    if (not expanded or len(root_items) - 1 <= len(indexed)
            or len(expanded) < len(indexed)):
        return {}
    indexed_set = set(indexed)
    if tuple(off for off in expanded if off in indexed_set) != indexed:
        return {}

    sections = {}
    signatures = set()
    for offset in expanded:
        geometry = _section_geometry_slots(
            model, offset, source_layout=False)
        if geometry is None:
            return {}
        if geometry not in signatures:
            signatures.add(geometry)
            sections[offset] = geometry
    return sections


def selected_track_section_lists(sections, detail, *, model=None):
    """Override source sections and root with exactly one HI/MED/LO tier.

    Binary root indices have an expanded LIST and repeated hash pointers.
    Select only the structurally deduplicated expanded section sequence;
    this includes extra sections absent from the hash, without rendering
    the expanded prelude (which otherwise draws all tiers unfiltered).
    A missing slot remains NIL, not a fallback from another tier.
    """
    if detail not in DETAIL_SLOTS:
        raise ValueError(f"Unknown track section detail: {detail!r}")
    start, end = DETAIL_SLOTS[detail]
    result = {offset: tuple(p for p in slots[start:end]
                            if p and model_kind(model, p) != 0)
              for offset, slots in sections.items()}
    if model is not None and sections:
        root_items = _list_slots(model, model.root_offset)
        if root_items:
            first_kind = model.records.get(root_items[0])
            if first_kind == 17:
                ordered = tuple(dict.fromkeys(root_items[1:]))
            elif first_kind == 11:
                expanded = _list_slots(model, root_items[0])
                ordered = tuple(off for off in expanded if off in sections) if expanded else ()
            else:
                ordered = ()
            if len(ordered) == len(sections) and set(ordered) == set(sections):
                result[model.root_offset] = ordered
    return result


def model_kind(model, pointer):
    """NIL is either a zero pointer or a reference to flavor-zero."""
    return model.records.get(pointer) if model is not None else None
