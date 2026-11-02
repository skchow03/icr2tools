"""Read-only Papyrus car RECOLOR table parsing.

Individual-car 3DO files commonly contain an unreferenced RECOLOR flavor
at body offset zero and a MATERIAL wrapper whose child is the shared carshape.
RECOLOR contains palette-index remappings, not RGB values or MIP pixels.
"""
from __future__ import annotations

import struct

TAG_RECOLOR = -(1 << 31) + 14
MAX_RECOLOR_PAIRS = 256


def recolor_table(model):
    """Return old palette index -> new palette index from car RECOLOR nodes.

    RECOLOR is normally at body offset zero, outside the graph reachable from
    the root MATERIAL. Inspect it explicitly, then allow other aligned locations
    only if the full record validates. Never mutate the 3DO Model.
    """
    body = model.body
    if len(body) < 8:
        return {}
    candidate_offsets = [0]
    magic = struct.pack('<i', TAG_RECOLOR)
    # Some custom carsets position the table elsewhere. Require a unique,
    # well-formed record so normal vertex/plane data is not interpreted.
    candidate_offsets.extend(i for i in range(4, len(body)-7, 4)
                             if body[i:i+4] == magic)
    tables = []
    for offset in candidate_offsets:
        if body[offset:offset+4] != magic:
            continue
        count = struct.unpack_from('<i', body, offset+4)[0]
        if not 1 <= count <= MAX_RECOLOR_PAIRS:
            continue
        end = offset + 8 + count * 8
        if end > len(body):
            continue
        vals = struct.unpack_from('<' + 'i'*(count*2), body, offset+8)
        keys, colors = vals[::2], vals[1::2]
        if (len(set(keys)) != count or
                any(v < 0 or v > 255 for v in keys + colors)):
            continue
        tables.append((offset, dict(zip(keys, colors))))
    # The usual root-leading table takes priority if multiple candidates
    # somehow match. Otherwise prefer an unambiguous single valid record.
    if not tables:
        return {}
    tables.sort(key=lambda x: x[0])
    return tables[0][1]


def recolor_index(index, remaps):
    """Apply inner-to-outer car wrapper mappings to a polygon palette slot."""
    for table in reversed(remaps):
        index = table.get(index, index)
    return index
