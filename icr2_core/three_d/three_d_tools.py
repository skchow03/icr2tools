from __future__ import annotations

import argparse
import json
import re
import sys
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Sequence

SECTION_START_MARKER = "Outputing section from dlong"
SECTION_END_MARKER = ";"
VERTEX_RE = re.compile(r"\[<\s*(-?\d+)\s*,\s*(-?\d+)\s*,\s*(-?\d+)\s*")


class ToolError(Exception):
    """Raised when the .3D file structure is not what the tool expects."""


@dataclass
class SectionInfo:
    name: str
    start_row: int
    end_row: int


@dataclass
class ChangeReport:
    input_path: str | None = None
    output_path: str | None = None
    wrote_output: bool = False
    dry_run: bool = False
    total_sections: int = 0
    flipped_fences: list[str] = field(default_factory=list)
    missing_fences: list[str] = field(default_factory=list)
    simple_sections_fixed: list[str] = field(default_factory=list)
    multi_boundary_sections_fixed: list[str] = field(default_factory=list)
    skipped_already_fixed_simple: list[str] = field(default_factory=list)
    skipped_already_fixed_multi: list[str] = field(default_factory=list)
    sections_written: int = 0
    vertices_shifted: int = 0
    tsos_labeled: int = 0
    warnings: list[str] = field(default_factory=list)

    def summary_lines(self) -> list[str]:
        lines: list[str] = []
        if self.input_path:
            lines.append(f"Input: {self.input_path}")
        if self.total_sections:
            lines.append(f"Cataloged {self.total_sections} section(s).")
        if self.flipped_fences:
            lines.append(f"Flipped fences in {len(self.flipped_fences)} section(s).")
        if self.missing_fences:
            lines.append(f"No fence found in {len(self.missing_fences)} requested section(s).")
        if self.simple_sections_fixed:
            lines.append(f"Applied simple see-through fix to {len(self.simple_sections_fixed)} section(s).")
        if self.multi_boundary_sections_fixed:
            lines.append(
                f"Applied multi-boundary see-through fix to {len(self.multi_boundary_sections_fixed)} section(s)."
            )
        if self.skipped_already_fixed_simple:
            lines.append(
                f"Skipped {len(self.skipped_already_fixed_simple)} simple section(s) that already looked fixed."
            )
        if self.skipped_already_fixed_multi:
            lines.append(
                f"Skipped {len(self.skipped_already_fixed_multi)} multi-boundary section(s) that already looked fixed."
            )
        if self.sections_written:
            lines.append(f"Wrote {self.sections_written} section name(s).")
        if self.vertices_shifted:
            lines.append(f"Shifted {self.vertices_shifted} vertex reference(s).")
        if self.tsos_labeled:
            lines.append(f"Relabeled {self.tsos_labeled} TSO pointer(s).")
        if self.dry_run:
            lines.append("Dry run only. No output file written.")
        elif self.wrote_output and self.output_path:
            lines.append(f"Wrote output: {self.output_path}")
        if self.warnings:
            lines.append(f"Warnings: {len(self.warnings)}")
        if not lines:
            lines.append("No changes made.")
        return lines

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class InspectionReport:
    input_path: str
    total_sections: int
    simple_candidates: list[str]
    multi_candidates: list[str]
    already_fixed_simple: list[str]
    already_fixed_multi: list[str]

    def summary_lines(self) -> list[str]:
        return [
            f"Input: {self.input_path}",
            f"Cataloged {self.total_sections} section(s).",
            f"Simple sections needing see-through fix: {len(self.simple_candidates)}",
            f"Multi-boundary sections needing see-through fix: {len(self.multi_candidates)}",
            f"Simple sections already looking fixed: {len(self.already_fixed_simple)}",
            f"Multi-boundary sections already looking fixed: {len(self.already_fixed_multi)}",
        ]

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def read_text_lines(path: str | Path) -> list[str]:
    return Path(path).read_text(encoding="utf-8", errors="ignore").splitlines(True)


def write_text_lines(path: str | Path, lines: Sequence[str]) -> None:
    Path(path).write_text("".join(lines), encoding="utf-8")


def find_row(data: Sequence[str], start_row: int, text: str, end_row: int | None = None) -> int | None:
    stop = len(data) if end_row is None else min(end_row, len(data))
    for row in range(start_row, stop):
        if text in data[row]:
            return row
    return None


def find_rows(data: Sequence[str], start_row: int, text: str, end_row: int | None = None) -> list[int]:
    stop = len(data) if end_row is None else min(end_row, len(data))
    return [row for row in range(start_row, stop) if text in data[row]]


def catalog_sections(data: Sequence[str]) -> list[SectionInfo]:
    sections: list[SectionInfo] = []
    for row, line in enumerate(data):
        if SECTION_START_MARKER in line:
            name_row = row + 1
            if name_row >= len(data):
                raise ToolError(f"Missing section name after row {row + 1}.")
            sec_name = data[name_row].split(":", 1)[0].strip()
            end_row = find_row(data, name_row, SECTION_END_MARKER)
            if end_row is None:
                raise ToolError(f"Could not find end of section {sec_name!r}.")
            sections.append(SectionInfo(sec_name, name_row, end_row))
    return sections


def load_section_names(path: str | Path) -> list[str]:
    return [line.strip() for line in Path(path).read_text(encoding="utf-8").splitlines() if line.strip()]


def _replace_int_vertices(line: str, dx: int, dy: int, dz: int) -> tuple[str, int]:
    count = 0

    def repl(match: re.Match[str]) -> str:
        nonlocal count
        count += 1
        x, y, z = (int(match.group(i)) for i in range(1, 4))
        return f"[< {x + dx}, {y + dy}, {z + dz} "

    return VERTEX_RE.sub(repl, line), count


def move_vertices(data: Sequence[str], offset: tuple[int, int, int]) -> tuple[list[str], int]:
    dx, dy, dz = offset
    out: list[str] = []
    shifted = 0
    for line in data:
        new_line, count = _replace_int_vertices(line, dx, dy, dz)
        out.append(new_line)
        shifted += count
    return out, shifted


def output_sections(data: Sequence[str], output_file: str | Path, substring: str = "HI") -> int:
    sections = catalog_sections(data)
    names = [section.name for section in sections if substring in section.name]
    Path(output_file).write_text("\n".join(names) + ("\n" if names else ""), encoding="utf-8")
    return len(names)


def label_tsos(data: Sequence[str]) -> tuple[list[str], int]:
    tso_dict: dict[str, str] = {}
    count = 0
    row = 0
    while row < len(data):
        line = data[row]
        if "DYNAMIC" in line:
            pointer = line.split(":", 1)[0].strip()
            tso_dict[pointer] = f"__TSO{count}"
            count += 1
        elif "LIST" in line:
            break
        row += 1

    out = list(data)
    for i, line in enumerate(out):
        for old, new in tso_dict.items():
            if old in line:
                line = line.replace(old, new)
        out[i] = line
    return out, len(tso_dict)


def flip_fences(data: Sequence[str], sections_to_flip: Sequence[str], side: str) -> tuple[list[str], list[str], list[str]]:
    if side not in {"left", "right"}:
        raise ToolError("side must be 'left' or 'right'.")

    out = list(data)
    sections = {section.name: section for section in catalog_sections(out)}
    changed: list[str] = []
    missing: list[str] = []

    wall_text = f"Output {side} side wall"

    for section_name in sections_to_flip:
        if section_name not in sections:
            raise ToolError(f"Section {section_name!r} not found in file.")
        section = sections[section_name]
        wall_row = find_row(out, section.start_row, wall_text, section.end_row)
        if wall_row is None:
            missing.append(section_name)
            continue
        fence_row = find_row(out, wall_row, "Fence poles", section.end_row)
        if fence_row is None:
            missing.append(section_name)
            continue

        try:
            a = [int(x) for x in re.findall(r"-?\d+", out[fence_row + 17])]
            b = [int(x) for x in re.findall(r"-?\d+", out[fence_row + 18])]
            c = [int(x) for x in re.findall(r"-?\d+", out[fence_row + 19])]
            d = [int(x) for x in re.findall(r"-?\d+", out[fence_row + 20])]
        except IndexError as exc:
            raise ToolError(f"Fence geometry block was incomplete in section {section_name!r}.") from exc

        if not all(len(v) >= 3 for v in (a, b, c, d)):
            raise ToolError(f"Fence geometry parse failed in section {section_name!r}.")

        c_x2, c_y2 = -(c[0] - b[0]), -(c[1] - b[1])
        d_x2, d_y2 = -(d[0] - a[0]), -(d[1] - a[1])
        new_c = [b[0] + c_x2, b[1] + c_y2, c[2]]
        new_d = [a[0] + d_x2, a[1] + d_y2, d[2]]

        new_c_string = f"                [< {new_c[0]}, {new_c[1]}, {new_c[2]}>],\n"
        new_d_string = f"                [< {new_d[0]}, {new_d[1]}, {new_d[2]}>]\n"

        out[fence_row + 19] = new_c_string
        out[fence_row + 20] = new_d_string
        out[fence_row + 25] = new_d_string
        changed.append(section_name)

    return out, changed, missing


def _insert_before_finish(data: list[str], section: SectionInfo, block: list[str]) -> None:
    finish_row = find_row(data, section.start_row, "% Finish the segment", section.end_row)
    if finish_row is None:
        raise ToolError(f"Could not locate '% Finish the segment' in {section.name!r}.")
    data[finish_row:finish_row] = block


def _extract_rows(data: list[str], start: int, end: int) -> list[str]:
    block = data[start:end]
    del data[start:end]
    return block


def inspect_see_through_candidates(data: Sequence[str]) -> InspectionReport:
    sections = catalog_sections(data)
    simple_candidates: list[str] = []
    multi_candidates: list[str] = []
    already_fixed_simple: list[str] = []
    already_fixed_multi: list[str] = []

    for section in sections:
        start_row, end_row = section.start_row, section.end_row
        surface_row = find_row(data, start_row, "% Output road surface", end_row)
        inner_bsp_start = find_row(data, start_row, "% Output BSP for boundary 1", end_row)
        dyno_rows = find_rows(data, start_row, "DYNO", end_row)

        if inner_bsp_start is not None:
            if surface_row is not None and inner_bsp_start > surface_row:
                already_fixed_multi.append(section.name)
            else:
                multi_candidates.append(section.name)
        elif dyno_rows:
            if surface_row is not None and min(dyno_rows) > surface_row:
                already_fixed_simple.append(section.name)
            else:
                simple_candidates.append(section.name)

    return InspectionReport(
        input_path="",
        total_sections=len(sections),
        simple_candidates=simple_candidates,
        multi_candidates=multi_candidates,
        already_fixed_simple=already_fixed_simple,
        already_fixed_multi=already_fixed_multi,
    )


def fix_see_through_elevation(
    data: Sequence[str],
) -> tuple[list[str], list[str], list[str], list[str], list[str]]:
    out = list(data)
    simple_fixed: list[str] = []
    multi_fixed: list[str] = []
    skipped_simple: list[str] = []
    skipped_multi: list[str] = []

    index = 0
    while True:
        sections = catalog_sections(out)
        if index >= len(sections):
            break
        section = sections[index]
        start_row, end_row = section.start_row, section.end_row

        surface_row = find_row(out, start_row, "% Output road surface", end_row)
        inner_bsp_start = find_row(out, start_row, "% Output BSP for boundary 1", end_row)

        if inner_bsp_start is not None:
            if surface_row is not None and inner_bsp_start > surface_row:
                skipped_multi.append(section.name)
                index += 1
                continue

            inner_bsp_end = find_row(out, inner_bsp_start, "% Output right side wall", end_row)
            if inner_bsp_end is None:
                raise ToolError(f"Could not locate '% Output right side wall' in {section.name!r}.")

            detached_block = _extract_rows(out, inner_bsp_start, inner_bsp_end)
            out.insert(inner_bsp_start, "NIL,\n")

            refreshed = {s.name: s for s in catalog_sections(out)}[section.name]
            block_to_insert = [",\n"] + detached_block + ["NIL\n"]
            _insert_before_finish(out, refreshed, block_to_insert)
            multi_fixed.append(section.name)
        else:
            dyno_rows = [row for row in range(start_row, end_row) if "DYNO" in out[row]]
            if dyno_rows:
                if surface_row is not None and min(dyno_rows) > surface_row:
                    skipped_simple.append(section.name)
                    index += 1
                    continue

                dyno_lines = [out[row] for row in dyno_rows]
                for row in dyno_rows:
                    out[row] = "NIL,\n"

                refreshed = {s.name: s for s in catalog_sections(out)}[section.name]
                block_to_insert = [",\n"] + dyno_lines + ["\n"]
                _insert_before_finish(out, refreshed, block_to_insert)
                simple_fixed.append(section.name)
        index += 1

    return out, simple_fixed, multi_fixed, skipped_simple, skipped_multi


def process_file(
    input_path: str | Path,
    output_path: str | Path | None = None,
    *,
    fix_elevation: bool = False,
    fences_file: str | Path | None = None,
    fence_side: str = "right",
    sections_output: str | Path | None = None,
    move_vertex_offset: tuple[int, int, int] | None = None,
    relabel_tsos: bool = False,
    sections_filter: str = "HI",
    dry_run: bool = False,
) -> ChangeReport:
    data = read_text_lines(input_path)
    report = ChangeReport(
        input_path=str(input_path),
        output_path=str(output_path) if output_path is not None else None,
        dry_run=dry_run,
        total_sections=len(catalog_sections(data)),
    )

    if fences_file is not None:
        section_names = load_section_names(fences_file)
        data, changed, missing = flip_fences(data, section_names, fence_side)
        report.flipped_fences.extend(changed)
        report.missing_fences.extend(missing)

    if fix_elevation:
        data, simple_fixed, multi_fixed, skipped_simple, skipped_multi = fix_see_through_elevation(data)
        report.simple_sections_fixed.extend(simple_fixed)
        report.multi_boundary_sections_fixed.extend(multi_fixed)
        report.skipped_already_fixed_simple.extend(skipped_simple)
        report.skipped_already_fixed_multi.extend(skipped_multi)

    if relabel_tsos:
        data, count = label_tsos(data)
        report.tsos_labeled = count

    if move_vertex_offset is not None:
        data, count = move_vertices(data, move_vertex_offset)
        report.vertices_shifted = count

    if sections_output is not None:
        report.sections_written = output_sections(data, sections_output, sections_filter)

    if output_path is not None and not dry_run:
        write_text_lines(output_path, data)
        report.wrote_output = True

    return report


def inspect_file(input_path: str | Path) -> InspectionReport:
    data = read_text_lines(input_path)
    report = inspect_see_through_candidates(data)
    report.input_path = str(input_path)
    return report


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Utilities for Papyrus .3D files, including Pavel's see-through elevation fix."
    )
    parser.add_argument("input", help="Input .3D file path")
    parser.add_argument("-o", "--output", help="Output .3D file path")
    parser.add_argument(
        "--in-place",
        action="store_true",
        help="Overwrite the input file. Ignored if --output is provided.",
    )
    parser.add_argument(
        "--inspect",
        action="store_true",
        help="Inspect for see-through fix candidates and do not modify the file.",
    )
    parser.add_argument(
        "--fix-elevation",
        action="store_true",
        help="Apply Pavel's see-through elevation ordering fix.",
    )
    parser.add_argument(
        "--flip-fences",
        metavar="SECTIONS_FILE",
        help="Flip fence geometry for sections listed in a text file.",
    )
    parser.add_argument(
        "--fence-side",
        choices=["left", "right"],
        default="right",
        help="Which side fence block to modify when using --flip-fences.",
    )
    parser.add_argument(
        "--write-sections",
        metavar="OUTPUT_FILE",
        help="Write matching section names to a text file.",
    )
    parser.add_argument(
        "--section-filter",
        default="HI",
        help="Substring used by --write-sections. Default: HI",
    )
    parser.add_argument(
        "--move-vertices",
        nargs=3,
        type=int,
        metavar=("DX", "DY", "DZ"),
        help="Apply integer offset to every vertex.",
    )
    parser.add_argument(
        "--label-tsos",
        action="store_true",
        help="Relabel early-file DYNAMIC pointers as __TSO0, __TSO1, ...",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Analyze and apply changes in memory, but do not write the output file.",
    )
    parser.add_argument(
        "--report-json",
        metavar="REPORT_FILE",
        help="Write a JSON report describing what the tool found and changed.",
    )
    parser.add_argument(
        "--quiet",
        action="store_true",
        help="Suppress summary output.",
    )
    return parser


def _write_json_report(path: str | Path, payload: dict[str, Any]) -> None:
    Path(path).write_text(json.dumps(payload, indent=2), encoding="utf-8")


def main(argv: Sequence[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    if args.inspect:
        report = inspect_file(args.input)
        if args.report_json:
            _write_json_report(args.report_json, report.to_dict())
        if not args.quiet:
            for line in report.summary_lines():
                print(line)
        return 0

    output_path = args.output
    if output_path is None and args.in_place:
        output_path = args.input

    if output_path is None and not args.dry_run and (
        args.fix_elevation
        or args.flip_fences
        or args.move_vertices is not None
        or args.label_tsos
    ):
        parser.error("Specify --output, --in-place, or --dry-run when making file modifications.")

    report = process_file(
        args.input,
        output_path=output_path,
        fix_elevation=args.fix_elevation,
        fences_file=args.flip_fences,
        fence_side=args.fence_side,
        sections_output=args.write_sections,
        move_vertex_offset=tuple(args.move_vertices) if args.move_vertices is not None else None,
        relabel_tsos=args.label_tsos,
        sections_filter=args.section_filter,
        dry_run=args.dry_run,
    )

    if args.report_json:
        _write_json_report(args.report_json, report.to_dict())

    if not args.quiet:
        for line in report.summary_lines():
            print(line)
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except ToolError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        raise SystemExit(2)
