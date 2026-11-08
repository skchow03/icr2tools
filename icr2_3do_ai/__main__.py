"""Command-line entry point: python -m icr2_3do_ai inspect MODEL.3DO."""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from .inspector import write_package


def main(argv=None):
    parser = argparse.ArgumentParser(
        prog="python -m icr2_3do_ai",
        description="Export AI-readable 3DO/N3 scene, geometry and diagnostics reports.")
    parser.add_argument("command", choices=("inspect",),
                        help="Read a model and generate a structured analysis package")
    parser.add_argument("input", type=Path, help="Existing .3do or N3 .3D file")
    parser.add_argument("-o", "--output", type=Path,
                        help="Output directory (default: <filename>_analysis)")
    parser.add_argument("--objects-folder", type=Path,
                        help="Folder containing external referenced .3do/.3d objects")
    parser.add_argument("--texture-folder", type=Path,
                        help="Folder containing referenced .mip texture files")
    parser.add_argument("--appearance", type=Path,
                        help="Optional driver RECOLOR/MIP wrapper to preview on the model")
    parser.add_argument("--views", action="store_true",
                        help="Include wireframe top, front and side PNG projections")
    parser.add_argument("--source", action="store_true",
                        help="Include existing N3 source or compilable source export")
    parser.add_argument("--overwrite", action="store_true",
                        help="Allow replacing existing report files (never source assets)")
    args = parser.parse_args(argv)
    output = args.output or (args.input.parent / (args.input.stem + "_analysis"))
    try:
        summary = write_package(
            args.input, output, objects_folder=args.objects_folder,
            texture_folder=args.texture_folder, appearance_path=args.appearance,
            with_views=args.views, with_source=args.source, overwrite=args.overwrite)
    except (OSError, ValueError) as exc:
        parser.exit(2, f"3DO inspection failed: {exc}\n")
    print(json.dumps({
        "output_directory": str(output),
        "counts": summary["counts"],
        "appearance_wrapper": summary["appearance_wrapper"],
    }, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
