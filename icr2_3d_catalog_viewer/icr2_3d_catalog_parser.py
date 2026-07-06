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
import csv
import json
import re
import sys
from dataclasses import asdict
from pathlib import Path
from typing import Any

try:
    from sg_viewer.io.track3d_catalog import parse_track3d_catalog
except ModuleNotFoundError:  # Allow running this script directly from its own directory.
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
    from sg_viewer.io.track3d_catalog import parse_track3d_catalog


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
    """Parse a text .3D file and return the legacy dictionary shape.

    The typed implementation lives in :mod:`sg_viewer.io.track3d_catalog`;
    this wrapper keeps the standalone viewer/export CLI compatible with its
    existing JSON and CSV output code.
    """
    return asdict(parse_track3d_catalog(path))


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
