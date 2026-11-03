"""Recognize Papyrus track section HI/MED/LO tables in .3D and .3DO.

The standalone N3 compiler retains the source layout:
    index: LIST { DATA hash, sec0_l0, ... }
    secN_lM: LIST { HI x4, MED x2, LO x1, DATA metadata }

The original track .3DO compiler instead expands the hash into the root:
    root: LIST { expanded LIST, section-pointer-per-hash-bin, ... }
    section LIST: { HI x4, MED x2, LO x1 } (seven pointers)

The expanded LIST references the same polygons as the section pointers, and
must be skipped for a fixed-section-detail view. Both formats are identified
structurally, without relying on source labels or file extensions.
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


def detect_track_section_lods(model):
    """Map each recognized section LIST to its seven positional LOD pointers.

    A binary NIL may be a nonzero pointer to a flavor-zero record; preserve
    that reference because Model.switched_polygons already ignores such nodes.
    Return an empty mapping rather than guessing on an unfamiliar structure.
    """
    root_items = _list_slots(model, model.root_offset)
    if not root_items or len(root_items) < 2:
        return {}

    first_kind = model.records.get(root_items[0])
    if first_kind == 17:
        # Standalone .3D compiled in memory: hash DATA, then eight-slot
        # section records whose eighth entry is their metadata DATA.
        section_offsets = root_items[1:]
        source_layout = True
    elif first_kind == 11:
        # Original .3DO track: generated root LIST contains an expanded
        # index and repeated section pointers corresponding to hash bins.
        # Deduplicate pointers; the reference order is the source section order.
        section_offsets = tuple(dict.fromkeys(root_items[1:]))
        expanded = _list_slots(model, root_items[0])
        if not expanded or len(root_items) - 1 <= len(section_offsets):
            return {}
        if len(expanded) != 2 * len(section_offsets):
            return {}
        # The middle half of this track-index variant is exactly the
        # sequential section list. Require that signature to avoid treating
        # ordinary 3DO LIST models as tracks.
        start = (len(expanded) - len(section_offsets)) // 2
        if expanded[start:start + len(section_offsets)] != section_offsets:
            return {}
        source_layout = False
    else:
        return {}

    sections = {}
    for offset in section_offsets:
        slots = _list_slots(model, offset)
        if slots is None or len(slots) != (8 if source_layout else 7):
            return {}
        if source_layout and (slots[7] <= 0 or
                              model.records.get(slots[7]) != 17):
            return {}
        geometry_slots = slots[:7]
        if not any(model.records.get(p) not in (0, None) for p in geometry_slots):
            return {}
        if any(p < 0 or (p and model.records.get(p) in (None, 17))
               for p in geometry_slots):
            return {}
        sections[offset] = geometry_slots
    return sections


def selected_track_section_lists(sections, detail, *, model=None):
    """Override the section nodes with exactly one HI/MED/LO tier.

    The root override suppresses the generated .3DO index LIST, which
    otherwise traverses every LOD before the chosen section pointers.
    For standalone .3D it also suppresses the non-renderable hash DATA.
    No geometry or bytes are modified.
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
            ordered = tuple(dict.fromkeys(root_items[1:]))
            if len(ordered) == len(sections) and set(ordered) == set(sections):
                result[model.root_offset] = ordered
    return result


def model_kind(model, pointer):
    """NIL is either a zero pointer or a reference to flavor-zero."""
    return model.records.get(pointer) if model is not None else None
