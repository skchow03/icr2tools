"""Stable source-level pointer names for N3 vertex declarations.

Labels live in the human-authored .3D source, never in binary .3DO.
The compiler's Document maps declarations to the current body's offsets; no
coordinate or UV based matching is used, since coincident vertices are common
around MIP seams and repeated geometry.
"""
from __future__ import annotations

import re

IDENTIFIER=re.compile(r"^[A-Za-z_][A-Za-z0-9_-]*$")
AUTO_OFFSET=re.compile(r"^_\d+$")
RESERVED={
    "NIL","3D","VERSION","POLY","LINE","LIST","FACE","FACE2","BSPF",
    "BSPA","BSP2","BSPN","MATERIAL","MIP","GROUP","DYNAMIC","EXTERN",
    "SUPEROBJ","SWITCH","DISTANCE","PMP2","SRB","RECOLOR","DYNO","DATA","ROOT"
}
TOKEN=re.compile(r'%[^\n]*|"(?:[^"]|"")*"|[A-Za-z_][A-Za-z0-9_-]*')


def names_for_vertices(model,document,*,original_n3):
    """Return offset -> label from actual source declarations.

    Auto-generated _123 tokens are not treated as user pointer names
    when a session began with a binary .3DO. A standalone .3D may validly
    use such names and is therefore preserved as authored.
    """
    if model is None or document is None:
        return {}
    out={}
    for statement in document.statements:
        if statement.offset not in model.vertices:
            continue
        if not statement.command.lstrip().startswith("["):
            continue
        name=statement.label
        if not original_n3 and AUTO_OFFSET.fullmatch(name):
            continue
        out[statement.offset]=name
    return out


def declaration_label(model,document,offset):
    """Name of the current source declaration, including generated names."""
    if document is not None:
        for statement in document.statements:
            if statement.offset==offset and statement.command.lstrip().startswith("["):
                return statement.label
    return f"_{offset}"


def rename_vertex_in_source(source,document,old_label,new_label):
    """Rename the declaration and its symbol references, not strings/comments.

    Raises ValueError before any mutation for empty, invalid or duplicate
    names. Does not touch MIP filenames, comments, or partial symbol matches.
    """
    name=new_label.strip()
    if not IDENTIFIER.fullmatch(name) or name.upper() in RESERVED:
        raise ValueError("Pointer name must be an identifier (letters, digits, "
                         "underscores or hyphens; start with letter or underscore) "
                         "and cannot be an N3 keyword.")
    if document is None:
        raise ValueError("N3 source metadata unavailable for renaming.")
    existing={statement.label for statement in document.statements}
    if old_label not in existing:
        raise ValueError(f"Cannot find vertex declaration {old_label!r} in source.")
    if name!=old_label and name in existing:
        raise ValueError(f"Pointer name {name!r} is already in use.")
    if name==old_label:
        return source
    def replace(match):
        token=match.group(0)
        if token.startswith(("%",'"')):
            return token
        return name if token==old_label else token
    return TOKEN.sub(replace,source)
