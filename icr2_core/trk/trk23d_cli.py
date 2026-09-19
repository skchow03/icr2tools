"""Command-line entry point for TRK to text .3D conversion."""

from __future__ import annotations

import argparse
from pathlib import Path

from trk3d_builder import Track3DOptions, write_track3d
from trk_classes import TRKFile


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="trk23d",
        description="Convert an IndyCar Racing II .TRK file to Papyrus text .3D.",
    )
    parser.add_argument("trk", type=Path, help="input .TRK file")
    parser.add_argument("output", type=Path, nargs="?", help="output .3D file")
    parser.add_argument(
        "--hi-length", type=int, default=60_000, help="target HI polygon length"
    )
    parser.add_argument(
        "--med-length", type=int, default=120_000, help="target MED polygon length"
    )
    parser.add_argument(
        "--lo-length", type=int, default=240_000, help="target LO polygon length"
    )
    parser.add_argument(
        "--texture-scale",
        type=float,
        default=375.0,
        metavar="UNITS_PER_TEXEL",
        help="texture coordinate scale (default: 375 game units per texel)",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    source = args.trk
    output = args.output or source.with_suffix(".3D")
    options = Track3DOptions(
        high_segment_length=args.hi_length,
        medium_segment_length=args.med_length,
        low_segment_length=args.lo_length,
        texture_units_per_texel=args.texture_scale,
    )
    trk = TRKFile.from_trk(source)
    write_track3d(trk, output, track_name=source.stem, options=options)
    print(f"Wrote {output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
