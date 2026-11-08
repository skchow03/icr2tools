"""ICR2 3DO AI CLI: inspect, generate and validate without the CAD GUI."""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

from .inspector import write_package
from .parametric import RecipeError
from .stage2 import generate_package, validate_path


def main(argv=None):
    parser = argparse.ArgumentParser(
        prog="python -m icr2_3do_ai",
        description="Inspect existing ICR2 3DOs or generate N3 models from JSON recipes.")
    commands = parser.add_subparsers(dest="command", required=True)

    inspect = commands.add_parser(
        "inspect", help="Read an existing model and write semantic JSON reports")
    inspect.add_argument("input", type=Path, help="Existing .3do or .3D file")
    inspect.add_argument("-o", "--output", type=Path,
                         help="Output directory (default: <filename>_analysis)")
    inspect.add_argument("--objects-folder", type=Path,
                         help="Folder containing referenced .3do/.3d objects")
    inspect.add_argument("--texture-folder", type=Path,
                         help="Folder containing referenced .mip texture files")
    inspect.add_argument("--appearance", type=Path,
                         help="Optional driver RECOLOR/MIP appearance to preview")
    inspect.add_argument("--views", action="store_true",
                         help="Add wireframe side/top/front projections")
    inspect.add_argument("--source", action="store_true",
                         help="Add original or exported N3 source")
    inspect.add_argument("--overwrite", action="store_true",
                         help="Allow replacing existing report files")

    generate = commands.add_parser(
        "generate", help="Build N3 source and a binary from a declarative JSON recipe")
    generate.add_argument("recipe", type=Path, help="Validated recipe JSON")
    generate.add_argument("-o", "--output", type=Path, required=True,
                          help="NEW output folder; existing directories are never overwritten")
    generate.add_argument("--views", action="store_true",
                          help="Add Stage 1 orthographic projections to analysis")
    generate.add_argument("--no-analysis", action="store_true",
                          help="Skip Stage 1 inspection reports (still compile and validate)")

    validate = commands.add_parser(
        "validate", help="Compile-check .3D or parse-check .3do without writing")
    validate.add_argument("input", type=Path, help="Existing N3 .3D or .3do file")

    args = parser.parse_args(argv)
    try:
        if args.command == "inspect":
            output = args.output or (
                args.input.parent / (args.input.stem + "_analysis"))
            summary = write_package(
                args.input, output, objects_folder=args.objects_folder,
                texture_folder=args.texture_folder,
                appearance_path=args.appearance,
                with_views=args.views, with_source=args.source,
                overwrite=args.overwrite)
            result = {
                "output_directory": str(output),
                "counts": summary["counts"],
                "appearance_wrapper": summary["appearance_wrapper"],
            }
        elif args.command == "generate":
            if args.views and args.no_analysis:
                parser.error("--views cannot be combined with --no-analysis")
            package = generate_package(
                args.recipe, args.output, with_views=args.views,
                with_analysis=not args.no_analysis)
            result = {
                "output_directory": package["output_directory"],
                "components": package["manifest"]["component_count"],
                "vertices": package["validation"]["vertices"],
                "polygons": package["validation"]["polygons"],
                "compiled": package["validation"]["compiled"],
            }
        else:
            result = validate_path(args.input)
    except (OSError, ValueError) as exc:
        parser.exit(2, f"3DO AI {args.command} failed: {exc}\n")
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    sys.exit(main())
