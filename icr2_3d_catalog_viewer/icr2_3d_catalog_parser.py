#!/usr/bin/env python3
"""
ICR2/N2-style .3D catalog parser.

Purpose:
  Build an organizational map of a .3D text file:
  - DYNAMIC TSOs and their EXTERN object names
  - ObjectList_L/R<section>_<subsection> definitions
  - sec<section>_s<subsection>_<HI|MED|LO> FACE blocks
  - DLONG ranges from generated comments
  - DetailList_* references
  - TOPO_* references
  - sec<section>_l<layout> LOD/index lists and their DATA DLONG thresholds
  - final index list

This is intentionally read-only. It is meant to become an SG CREATE
integration layer later, not a writer yet.
"""

from __future__ import annotations

import argparse
import collections
import csv
import json
import re
from pathlib import Path
from typing import Any


LABEL_RE = re.compile(r"^([A-Za-z_][\w\-.]*):\s*(.*)")
TSO_RE = re.compile(r'^(__TSO\d+):\s*DYNAMIC\s+(.+?)\s*,\s*EXTERN\s+"([^"]+)"\s*;')
OBJ_RE = re.compile(r"^(ObjectList_([LR])(\d+)_(\d+)):\s*LIST\s*\{(.*?)\}\s*;", re.S)
FACE_RE = re.compile(r"^(sec(?P<section>\d+)_s(?P<sub>\d+)_(?P<lod>HI|MED|LO)):\s+FACE\b")
SEC_LIST_RE = re.compile(r"^(sec(\d+)_l(\d+)):\s*LIST\s*\{(.*?)\}\s*;", re.S)
DLONG_RE = re.compile(r"Outputing section from dlong\s*=\s*(\d+)\s*to dlong\s*=\s*(\d+)")


def capture_statement(lines: list[str], start_idx: int) -> tuple[str, int]:
    """Capture a label statement until the first semicolon line."""
    chunk: list[str] = []
    for j in range(start_idx, len(lines)):
        chunk.append(lines[j])
        if ";" in lines[j]:
            return "\n".join(chunk), j
    return "\n".join(chunk), len(lines) - 1


def label_positions(lines: list[str]) -> list[tuple[int, str, str]]:
    out = []
    for i, line in enumerate(lines):
        m = LABEL_RE.match(line)
        if m:
            out.append((i, m.group(1), m.group(2)))
    return out


def parse_3d(path: str | Path) -> dict[str, Any]:
    path = Path(path)
    text = path.read_text(errors="replace")
    lines = text.splitlines()
    labels = label_positions(lines)

    tsos: dict[str, Any] = {}
    for i, line in enumerate(lines, 1):
        m = TSO_RE.match(line.strip())
        if not m:
            continue
        nums = [int(x.strip()) for x in m.group(2).split(",")]
        tsos[m.group(1)] = {
            "line": i,
            "x": nums[0],
            "y": nums[1],
            "z": nums[2],
            "rot": nums[3],
            "extern": m.group(3),
            "params": nums,
        }

    object_lists: dict[str, Any] = {}
    for i, label, _rest in labels:
        if not label.startswith("ObjectList_"):
            continue
        stmt, _end = capture_statement(lines, i)
        m = OBJ_RE.match(stmt.strip())
        if not m:
            continue
        items = [x.strip() for x in m.group(5).replace("\n", " ").split(",") if x.strip()]
        object_lists[label] = {
            "line": i + 1,
            "side": m.group(2),
            "section": int(m.group(3)),
            "subsection": int(m.group(4)),
            "items": items,
            "externs": [tsos.get(item, {}).get("extern") for item in items],
        }

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
        face_positions.append(
            (i, m.group(1), int(m.group("section")), int(m.group("sub")), m.group("lod"), dlong)
        )

    faces = []
    for idx, (i, label, section, subsection, lod, dlong) in enumerate(face_positions):
        end = face_positions[idx + 1][0] if idx + 1 < len(face_positions) else len(lines)
        block = "\n".join(lines[i:end])

        object_refs = sorted(set(re.findall(r"\bObjectList_[LR]\d+_\d+\b", block)))
        detail_refs = sorted(set(re.findall(r"\bDetailList_\d+-\d+[HML]?\b", block)))
        topo_refs = sorted(set(re.findall(r"\bTOPO_sec\d+_s\d+_[LR]_(?:HI|MED|LO)\b", block)))

        mats = []
        for mip_name, texture_name in re.findall(r'MIP\s*=\s*"([^"]+)"|__([A-Za-z0-9_]+)__\.c', block):
            mats.append(mip_name or texture_name)

        faces.append({
            "label": label,
            "line": i + 1,
            "section": section,
            "subsection": subsection,
            "lod": lod,
            "dlong_start": dlong[0] if dlong else None,
            "dlong_end": dlong[1] if dlong else None,
            "object_lists": object_refs,
            "detail_lists": detail_refs,
            "topo_lists": topo_refs,
            "materials": sorted(set(mats)),
        })

    section_lists: dict[str, Any] = {}
    for i, label, _rest in labels:
        if not re.match(r"^sec\d+_l\d+$", label):
            continue
        stmt, _end = capture_statement(lines, i)
        m = SEC_LIST_RE.match(stmt.strip())
        if not m:
            continue
        body = m.group(4)
        data = re.search(r"DATA\s*\{([^}]*)\}", body, re.S)
        dlongs = [int(x) for x in re.findall(r"\d+", data.group(1))] if data else []
        front = re.sub(r"DATA\s*\{.*?\}", "", body, flags=re.S)
        entries = [x.strip() for x in front.split(",") if x.strip()]
        section_lists[label] = {
            "line": i + 1,
            "section": int(m.group(2)),
            "layout": int(m.group(3)),
            "entries": entries,
            "dlongs": dlongs,
        }

    index_entries = []
    for i, label, _rest in labels:
        if label != "index":
            continue
        stmt, _end = capture_statement(lines, i)
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
        bucket = by_section[face["section"]]
        bucket["subsections"].add(face["subsection"])
        bucket["lod_counts"][face["lod"]] += 1
        if face["dlong_start"] is not None:
            bucket["dlong_ranges"].add((face["dlong_start"], face["dlong_end"]))
        bucket["object_lists"].update(face["object_lists"])
        bucket["detail_lists"].update(face["detail_lists"])

    for label, sec_list in section_lists.items():
        by_section[sec_list["section"]]["section_lists"].add(label)

    section_summary = []
    for section in sorted(by_section):
        bucket = by_section[section]
        section_summary.append({
            "section": section,
            "subsections": sorted(bucket["subsections"]),
            "lod_counts": dict(bucket["lod_counts"]),
            "dlong_ranges": sorted(bucket["dlong_ranges"]),
            "object_lists": sorted(bucket["object_lists"]),
            "detail_lists": sorted(bucket["detail_lists"]),
            "section_lists": sorted(bucket["section_lists"]),
        })

    return {
        "source": path.name,
        "counts": {
            "tsos": len(tsos),
            "object_lists": len(object_lists),
            "faces": len(faces),
            "section_lists": len(section_lists),
            "index_entries": len(index_entries),
        },
        "tsos": tsos,
        "object_lists": object_lists,
        "faces": faces,
        "section_lists": section_lists,
        "index": index_entries,
        "section_summary": section_summary,
    }


def write_outputs(catalog: dict[str, Any], output_prefix: str | Path) -> None:
    prefix = Path(output_prefix)
    prefix.with_suffix(".json").write_text(json.dumps(catalog, indent=2), encoding="utf-8")

    with prefix.with_suffix(".sections.csv").open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(
            f,
            fieldnames=[
                "section",
                "subsections",
                "lod_counts",
                "dlong_ranges",
                "object_lists",
                "detail_lists",
                "section_lists",
            ],
        )
        writer.writeheader()
        for row in catalog["section_summary"]:
            writer.writerow({
                key: json.dumps(value) if isinstance(value, (list, dict)) else value
                for key, value in row.items()
            })

    with prefix.with_suffix(".faces.csv").open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(
            f,
            fieldnames=[
                "label",
                "line",
                "section",
                "subsection",
                "lod",
                "dlong_start",
                "dlong_end",
                "object_lists",
                "detail_lists",
                "topo_lists",
                "materials",
            ],
        )
        writer.writeheader()
        for row in catalog["faces"]:
            writer.writerow({
                key: json.dumps(value) if isinstance(value, list) else value
                for key, value in row.items()
            })


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("input_3d", help="Path to text .3D file")
    parser.add_argument("-o", "--output-prefix", default="3d_catalog", help="Output path prefix")
    args = parser.parse_args()

    catalog = parse_3d(args.input_3d)
    write_outputs(catalog, args.output_prefix)
    print(json.dumps(catalog["counts"], indent=2))


if __name__ == "__main__":
    main()
