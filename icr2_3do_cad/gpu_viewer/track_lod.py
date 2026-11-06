"""Recognize Papyrus track section HI/MED/LO tables in .3D and .3DO.

The standalone N3 compiler retains the source layout:
    index: LIST { DATA hash, sec0_l0, ... }
    secN_lM: LIST { HI x4, MED x2, LO x1, DATA metadata }

Original track .3DO compilers instead expand the index into a root LIST:
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
from bisect import bisect_right


DETAIL_SLOTS = {"hi": (0, 4), "med": (4, 6), "lo": (6, 7)}


def _list_slots(model, offset):
    """Return raw LIST children, preserving NIL positions, or None."""
    if model.records.get(offset) != 11:
        return None
    count = struct.unpack_from("<i", model.body, offset + 4)[0]
    if count < 0 or offset + 8 + count * 4 > len(model.body):
        return None
    return struct.unpack_from(f"<{count}i", model.body, offset + 8)


def _track_index_root(model):
    """Return the indexed track LIST, beneath any stock SUPEROBJ wrappers.

    Papyrus stock tracks such as Vancouver use SUPEROBJ { previous-index,
    DYNAMIC scenery... } as the real .3DO root. The previous pointer
    leads to the ordinary compiled track index. Never replace the SUPEROBJ
    itself: its other children are legitimate trackside objects.

    A non-track SUPEROBJ is still rejected by section-index validation.
    """
    offset = model.root_offset
    visited = set()
    while model.records.get(offset) == 16 and offset not in visited:
        visited.add(offset)
        # The preceding-object pointer at +4 is parsed by Model already.
        offset = struct.unpack_from('<i', model.body, offset + 4)[0]
    return offset

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
    root_items = _list_slots(model, _track_index_root(model))
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
        root_items = _list_slots(model, _track_index_root(model))
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
                result[_track_index_root(model)] = ordered
    return result


def model_kind(model, pointer):
    """NIL is either a zero pointer or a reference to flavor-zero."""
    return model.records.get(pointer) if model is not None else None


# The four DATA integers are the DLONG start of the corresponding HI
# subsegments. The source layout refers to this DATA directly as LIST slot 8.
# Papyrus' original binary compiler leaves a 20-byte DATA record directly
# BEFORE each seven-pointer section LIST, but unlinks it from the scene graph.
# Consequently Model.records does not know about these compiled DATA records.
_DATA_TAG = -(1 << 31) + 17
DEFAULT_WINDOW_COUNTS = (8, 5, 3)  # each side of camera; current = HI


def _section_data_values(model, offset):
    """Read a four-DLONG DATA record at a known body offset, if valid."""
    if offset < 0 or offset + 20 > len(model.body):
        return None
    tag, *values = struct.unpack_from("<5i", model.body, offset)
    if (tag != _DATA_TAG or any(value < 0 for value in values)
            or values != sorted(values)):
        return None
    return tuple(values)


def track_section_dlongs(model, sections):
    """Get four DLONG start positions for every detected track section.

    For .3D, the eighth LIST pointer addresses DATA; for original .3DO,
    the unlinked DATA bytes precede each seven-pointer LIST. Binary alias
    LISTs can refer to the same geometry and some initial aliases lack a
    preceding DATA record: look up the equivalent four values from the other
    copies of the same seven-pointer signature in the full expanded index.

    Return an empty mapping if metadata is missing or ambiguous. This avoids
    placing a moving camera on guessed coordinates. The legacy global HI/MED/
    LO selection remains available if metadata cannot be recovered.
    """
    if not sections:
        return {}
    root = _list_slots(model, _track_index_root(model))
    if not root:
        return {}
    source = model.records.get(root[0]) == 17
    candidates = (root[1:] if source else
                  _list_slots(model, root[0]) or ())
    by_signature = {}
    for offset in candidates:
        slots = _list_slots(model, offset)
        if slots is None:
            continue
        signature = slots[:7]
        if source:
            metadata = (_section_data_values(model, slots[7])
                        if len(slots) == 8 else None)
        else:
            metadata = (_section_data_values(model, offset - 20)
                        if len(slots) == 7 else None)
        if metadata is None:
            continue
        if signature in by_signature and by_signature[signature] != metadata:
            # Conflicting copies cannot safely be correlated with one DLONG.
            return {}
        by_signature[signature] = metadata

    result = {}
    for offset, geometry in sections.items():
        metadata = by_signature.get(tuple(geometry))
        if metadata is None:
            return {}
        result[offset] = metadata
    if len(set(values[0] for values in result.values())) != len(result):
        # Two different section layouts claiming the same start are ambiguous.
        return {}
    return result


def selected_track_section_window_lists(
        sections, dlongs, *, model, camera_dlong, track_length,
        counts=DEFAULT_WINDOW_COUNTS):
    """Build camera-local HI/MED/LO LIST overrides, omitting all other sections.

    The section containing DLONG (from the DATA start values) is HI.
    In BOTH directions from that section, the next counts[0] sections use
    HI, then counts[1] MED, then counts[2] LO. Other sections are omitted.
    On closed tracks this wraps across the start/finish line. A section may
    appear in overlapping windows on short tracks; closest/highest detail wins.

    Returns an empty root override if all requested counts are zero except
    for the current section. Does not mutate the model or its polygon VBO.
    """
    if not sections or set(dlongs) != set(sections):
        raise ValueError("Track section DLONG metadata is incomplete")
    if (not isinstance(counts, (tuple, list)) or len(counts) != 3
            or any(not isinstance(n, int) or n < 0 for n in counts)):
        raise ValueError("HI/MED/LO window counts must be three nonnegative integers")
    if not isinstance(track_length, (int, float)) or track_length <= 0:
        raise ValueError("Track lap length must be positive")
    if not isinstance(camera_dlong, (int, float)):
        raise ValueError("Camera DLONG must be numeric")

    ordered = sorted(sections, key=lambda offset: dlongs[offset][0])
    starts = [dlongs[offset][0] for offset in ordered]
    if starts[0] != 0 or starts[-1] >= track_length:
        raise ValueError("Section starts must cover DLONG zero within track length")

    current = bisect_right(starts, camera_dlong % track_length) - 1
    n = len(ordered)
    ranks = {ordered[current]: "hi"}
    hi, med, lo = counts
    for distance in range(1, min(n, hi + med + lo + 1)):
        tier = ("hi" if distance <= hi else
                "med" if distance <= hi + med else "lo")
        for direction in (1, -1):
            offset = ordered[(current + direction * distance) % n]
            # The closest window has priority on short tracks.
            ranks.setdefault(offset, tier)

    overrides = {}
    for offset, tier in ranks.items():
        start, end = DETAIL_SLOTS[tier]
        overrides[offset] = tuple(
            p for p in sections[offset][start:end]
            if p and model_kind(model, p) != 0)
    # Use the track's original painter order for the selected sections,
    # not DLONG-sorted order, so polygons preserve their authored ordering.
    overrides[_track_index_root(model)] = tuple(
        offset for offset in sections if offset in ranks)
    return overrides
