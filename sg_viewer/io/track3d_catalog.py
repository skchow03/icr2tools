"""Read-only catalog parser for ICR2/N2-style text .3D files.

The parser builds an organizational map of generated track .3D source:
DYNAMIC TSO definitions, ObjectList definitions, FACE blocks, section LOD
lists, index entries, and per-section summary data.
"""

from __future__ import annotations

import collections
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


LABEL_RE = re.compile(r"^([A-Za-z_][\w\-.]*):\s*(.*)")
TSO_RE = re.compile(r'^(__TSO\d+):\s*DYNAMIC\s+(.+?)\s*,\s*EXTERN\s+"([^"]+)"\s*;', re.S)
OBJ_RE = re.compile(r"^(ObjectList_([LR])(\d+)_(\d+)):\s*LIST\s*\{(.*?)\}\s*;", re.S)
DETAIL_RE = re.compile(r"^(DetailList_(\d+)-(\d+)([HML]?)):\s*LIST\s*\{(.*?)\}\s*;", re.S)
FACE_RE = re.compile(r"^(sec(?P<section>\d+)_s(?P<sub>\d+)_(?P<lod>HI|MED|LO)):\s+FACE\b")
SEC_LIST_RE = re.compile(r"^(sec(\d+)_l(\d+)):\s*LIST\s*\{(.*?)\}\s*;", re.S)
DLONG_RE = re.compile(r"Outputing section from dlong\s*=\s*(\d+)\s*to dlong\s*=\s*(\d+)")


@dataclass(frozen=True)
class Track3DSourceSpan:
    start_line: int
    end_line: int
    start_offset: int | None
    end_offset: int | None
    text: str


@dataclass(frozen=True)
class Track3DTsoDefinition:
    line: int
    span: Track3DSourceSpan
    x: int
    y: int
    z: int
    rot: int
    extern: str
    params: list[int]


@dataclass(frozen=True)
class Track3DObjectListDefinition:
    line: int
    span: Track3DSourceSpan
    side: str
    section: int
    subsection: int
    items: list[str]
    externs: list[str | None]


@dataclass(frozen=True)
class Track3DDetailListDefinition:
    line: int
    span: Track3DSourceSpan
    section: int
    subsection: int
    lod_suffix: str
    items: list[str]
    externs: list[str | None]


@dataclass(frozen=True)
class Track3DFaceBlock:
    label: str
    line: int
    span: Track3DSourceSpan
    section: int
    subsection: int
    lod: str
    dlong_start: int | None
    dlong_end: int | None
    object_lists: list[str]
    detail_lists: list[str]
    topo_lists: list[str]
    materials: list[str]


@dataclass(frozen=True)
class Track3DSectionList:
    line: int
    span: Track3DSourceSpan
    section: int
    layout: int
    entries: list[str]
    dlongs: list[int]


@dataclass(frozen=True)
class Track3DSectionSummary:
    section: int
    subsections: list[int]
    lod_counts: dict[str, int]
    dlong_ranges: list[tuple[int, int]]
    object_lists: list[str]
    detail_lists: list[str]
    section_lists: list[str]


@dataclass(frozen=True)
class Track3DCatalog:
    source: str
    counts: dict[str, int]
    tsos: dict[str, Track3DTsoDefinition] = field(default_factory=dict)
    object_lists: dict[str, Track3DObjectListDefinition] = field(default_factory=dict)
    detail_lists: dict[str, Track3DDetailListDefinition] = field(default_factory=dict)
    faces: list[Track3DFaceBlock] = field(default_factory=list)
    section_lists: dict[str, Track3DSectionList] = field(default_factory=dict)
    index: list[str] = field(default_factory=list)
    index_span: Track3DSourceSpan | None = None
    section_summary: list[Track3DSectionSummary] = field(default_factory=list)


def capture_statement(lines: list[str], start_idx: int) -> tuple[str, int, int]:
    """Capture a label statement and return text plus 0-based start/end lines.

    Capture stops at the first semicolon in the statement, or immediately before
    the next label if no semicolon has been seen. This keeps malformed or
    block-style labels from consuming the following label statement.
    """
    chunk: list[str] = []
    for j in range(start_idx, len(lines)):
        if j > start_idx and LABEL_RE.match(lines[j]):
            return "\n".join(chunk), start_idx, j - 1
        chunk.append(lines[j])
        if ";" in lines[j]:
            return "\n".join(chunk), start_idx, j
    return "\n".join(chunk), start_idx, len(lines) - 1


def line_offsets(text: str) -> list[int]:
    offsets: list[int] = []
    cursor = 0
    for raw_line in text.splitlines(keepends=True):
        offsets.append(cursor)
        cursor += len(raw_line)
    if not offsets and text == "":
        offsets.append(0)
    return offsets


def source_span(
    lines: list[str], offsets: list[int], start_idx: int, end_idx: int
) -> Track3DSourceSpan:
    text = "\n".join(lines[start_idx : end_idx + 1])
    start_offset = offsets[start_idx] if start_idx < len(offsets) else None
    end_offset = (
        offsets[end_idx] + len(lines[end_idx])
        if end_idx < len(lines) and end_idx < len(offsets)
        else None
    )
    return Track3DSourceSpan(
        start_line=start_idx + 1,
        end_line=end_idx + 1,
        start_offset=start_offset,
        end_offset=end_offset,
        text=text,
    )


def label_positions(lines: list[str]) -> list[tuple[int, str, str]]:
    out: list[tuple[int, str, str]] = []
    for i, line in enumerate(lines):
        m = LABEL_RE.match(line)
        if m:
            out.append((i, m.group(1), m.group(2)))
    return out


def parse_track3d_catalog(path: str | Path) -> Track3DCatalog:
    """Parse a text .3D file into a typed catalog of track entities."""
    path = Path(path)
    text = path.read_text(errors="replace")
    lines = text.splitlines()
    offsets = line_offsets(text)
    labels = label_positions(lines)

    tsos: dict[str, Track3DTsoDefinition] = {}
    for i, label, _rest in labels:
        stmt, start, end = capture_statement(lines, i)
        m = TSO_RE.match(stmt.strip())
        if not m:
            continue
        nums = [int(x.strip()) for x in m.group(2).replace("\n", " ").split(",")]
        tsos[m.group(1)] = Track3DTsoDefinition(
            line=i + 1,
            span=source_span(lines, offsets, start, end),
            x=nums[0],
            y=nums[1],
            z=nums[2],
            rot=nums[3],
            extern=m.group(3),
            params=nums,
        )

    object_lists: dict[str, Track3DObjectListDefinition] = {}
    for i, label, _rest in labels:
        if not label.startswith("ObjectList_"):
            continue
        stmt, start, end = capture_statement(lines, i)
        m = OBJ_RE.match(stmt.strip())
        if not m:
            continue
        items = [x.strip() for x in m.group(5).replace("\n", " ").split(",") if x.strip()]
        object_lists[label] = Track3DObjectListDefinition(
            line=i + 1,
            span=source_span(lines, offsets, start, end),
            side=m.group(2),
            section=int(m.group(3)),
            subsection=int(m.group(4)),
            items=items,
            externs=[tsos.get(item).extern if item in tsos else None for item in items],
        )

    detail_lists: dict[str, Track3DDetailListDefinition] = {}
    for i, label, _rest in labels:
        if not label.startswith("DetailList_"):
            continue
        stmt, start, end = capture_statement(lines, i)
        m = DETAIL_RE.match(stmt.strip())
        if not m:
            continue
        items = [x.strip() for x in m.group(5).replace("\n", " ").split(",") if x.strip()]
        detail_lists[label] = Track3DDetailListDefinition(
            line=i + 1,
            span=source_span(lines, offsets, start, end),
            section=int(m.group(2)),
            subsection=int(m.group(3)),
            lod_suffix=m.group(4),
            items=items,
            externs=[tsos.get(item).extern if item in tsos else None for item in items],
        )

    face_positions: list[tuple[int, str, int, int, str, tuple[int, int] | None]] = []
    for i, line in enumerate(lines):
        m = FACE_RE.match(line)
        if not m:
            continue
        dlong = None
        for k in range(max(0, i - 5), i):
            dm = DLONG_RE.search(lines[k])
            if dm:
                dlong = (int(dm.group(1)), int(dm.group(2)))
        face_positions.append((i, m.group(1), int(m.group("section")), int(m.group("sub")), m.group("lod"), dlong))

    faces: list[Track3DFaceBlock] = []
    label_indices = [pos for pos, _label, _rest in labels]
    for idx, (i, label, section, subsection, lod, dlong) in enumerate(face_positions):
        next_labels = [pos for pos in label_indices if pos > i]
        end = next_labels[0] if next_labels else len(lines)
        block = "\n".join(lines[i:end])
        object_refs = sorted(set(re.findall(r"\bObjectList_[LR]\d+_\d+\b", block)))
        detail_refs = sorted(set(re.findall(r"\bDetailList_\d+-\d+[HML]?\b", block)))
        topo_refs = sorted(set(re.findall(r"\bTOPO_sec\d+_s\d+_[LR]_(?:HI|MED|LO)\b", block)))
        mats = []
        for mip_name, texture_name in re.findall(r'MIP\s*=\s*"([^"]+)"|__([A-Za-z0-9_]+)__\.c', block):
            mats.append(mip_name or texture_name)
        faces.append(Track3DFaceBlock(
            label=label,
            line=i + 1,
            span=source_span(lines, offsets, i, end - 1),
            section=section,
            subsection=subsection,
            lod=lod,
            dlong_start=dlong[0] if dlong else None,
            dlong_end=dlong[1] if dlong else None,
            object_lists=object_refs,
            detail_lists=detail_refs,
            topo_lists=topo_refs,
            materials=sorted(set(mats)),
        ))

    section_lists: dict[str, Track3DSectionList] = {}
    for i, label, _rest in labels:
        if not re.match(r"^sec\d+_l\d+$", label):
            continue
        stmt, start, end = capture_statement(lines, i)
        m = SEC_LIST_RE.match(stmt.strip())
        if not m:
            continue
        body = m.group(4)
        data = re.search(r"DATA\s*\{([^}]*)\}", body, re.S)
        dlongs = [int(x) for x in re.findall(r"\d+", data.group(1))] if data else []
        front = re.sub(r"DATA\s*\{.*?\}", "", body, flags=re.S)
        entries = [x.strip() for x in front.split(",") if x.strip()]
        section_lists[label] = Track3DSectionList(
            line=i + 1,
            span=source_span(lines, offsets, start, end),
            section=int(m.group(2)),
            layout=int(m.group(3)),
            entries=entries,
            dlongs=dlongs,
        )

    index_entries: list[str] = []
    index_span: Track3DSourceSpan | None = None
    for i, label, _rest in labels:
        if label != "index":
            continue
        stmt, start, end = capture_statement(lines, i)
        index_span = source_span(lines, offsets, start, end)
        body = re.search(r"\{(.*?)\}", stmt, re.S)
        if body:
            index_entries = [x.strip() for x in body.group(1).replace("\n", " ").split(",") if x.strip()]
        break

    by_section: dict[int, Any] = collections.defaultdict(
        lambda: {
            "subsections": set(),
            "lod_counts": collections.Counter(),
            "dlong_ranges": set(),
            "object_lists": set(),
            "detail_lists": set(),
            "section_lists": set(),
        }
    )

    for face in faces:
        bucket = by_section[face.section]
        bucket["subsections"].add(face.subsection)
        bucket["lod_counts"][face.lod] += 1
        if face.dlong_start is not None and face.dlong_end is not None:
            bucket["dlong_ranges"].add((face.dlong_start, face.dlong_end))
        bucket["object_lists"].update(face.object_lists)
        bucket["detail_lists"].update(face.detail_lists)

    for label, sec_list in section_lists.items():
        by_section[sec_list.section]["section_lists"].add(label)

    section_summary = [
        Track3DSectionSummary(
            section=section,
            subsections=sorted(bucket["subsections"]),
            lod_counts=dict(bucket["lod_counts"]),
            dlong_ranges=sorted(bucket["dlong_ranges"]),
            object_lists=sorted(bucket["object_lists"]),
            detail_lists=sorted(bucket["detail_lists"]),
            section_lists=sorted(bucket["section_lists"]),
        )
        for section, bucket in sorted(by_section.items())
    ]

    return Track3DCatalog(
        source=path.name,
        counts={
            "tsos": len(tsos),
            "object_lists": len(object_lists),
            "detail_lists": len(detail_lists),
            "faces": len(faces),
            "section_lists": len(section_lists),
            "index_entries": len(index_entries),
        },
        tsos=tsos,
        object_lists=object_lists,
        detail_lists=detail_lists,
        faces=faces,
        section_lists=section_lists,
        index=index_entries,
        index_span=index_span,
        section_summary=section_summary,
    )
