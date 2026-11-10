"""ICR2 3DO AI CLI: inspect, generate and validate without the CAD GUI."""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

from .inspector import write_package
from .parametric import RecipeError
from .stage2 import generate_package, validate_path
from .visual_regression import DEFAULT_CAMERAS, CAMERAS, render_previews, compare_previews


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
    generate.add_argument("--objects-folder", type=Path,
                          help="Validate all EXTERN .3do files in this directory (never copy them)")
    generate.add_argument("--views", action="store_true",
                          help="Add Stage 1 orthographic projections to analysis")
    generate.add_argument("--no-analysis", action="store_true",
                          help="Skip Stage 1 inspection reports (still compile and validate)")

    validate = commands.add_parser(
        "validate", help="Compile-check .3D or parse-check .3do without writing")
    validate.add_argument("input", type=Path, help="Existing N3 .3D or .3do file")


    preview = commands.add_parser(
        "preview", help="Camera-specific filled BSP/PMP previews; not game screenshots")
    preview.add_argument("input", type=Path, help="Compiled .3do or editable .3D")
    preview.add_argument("-o", "--output", type=Path, required=True,
                         help="New output directory, never overwritten")

    compare = commands.add_parser(
        "compare", help="Render before/after with common framing and pixel-diff reports")
    compare.add_argument("before", type=Path, help="Baseline .3do or .3D")
    compare.add_argument("after", type=Path, help="Candidate .3do or .3D")
    compare.add_argument("-o", "--output", type=Path, required=True,
                         help="New comparison output directory")
    compare.add_argument("--tolerance", type=int, default=0,
                         help="Ignore RGB-channel deltas at or below 0-255")
    compare.add_argument("--max-diff-ratio", type=float,
                         help="Fail after producing images if any view exceeds this changed-pixel fraction")

    for command in (preview, compare):
        command.add_argument("--cameras", nargs="+", default=DEFAULT_CAMERAS,
                             choices=sorted(CAMERAS))
        command.add_argument("--width", type=int, default=700)
        command.add_argument("--height", type=int, default=500)
        command.add_argument("--objects-folder", type=Path)
        command.add_argument("--texture-folder", type=Path)
        command.add_argument("--palette", type=Path,
                             help="Optional 8-bit PCX palette override; default local SUNNY.PCX or CAD gamepal.pcx")
        command.add_argument("--appearance", type=Path,
                             help="Driver RECOLOR/MIP wrapper for current model")
        command.add_argument("--bsp-mode", choices=["original","off"],
                             default="original")
        command.add_argument("--no-textures", action="store_true",
                             help="Use palette-colored fills instead of MIP sampling")
        command.add_argument("--strict-assets", action="store_true",
                             help="Require all referenced resources to resolve without warnings")

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
        elif args.command == "preview":
            summary = render_previews(
                args.input, args.output, cameras=args.cameras,
                width=args.width, height=args.height,
                objects_folder=args.objects_folder,
                texture_folder=args.texture_folder, palette_file=args.palette,
                appearance=args.appearance, bsp_mode=args.bsp_mode,
                textures=not args.no_textures, strict_assets=args.strict_assets)
            result = {
                "output_directory": str(args.output),
                "cameras": summary["cameras"], "warnings": summary["warnings"],
                "rendered_sprites": sum(
                    v["rendered_sprites"] for v in summary["statistics"].values()),
            }
        elif args.command == "compare":
            summary = compare_previews(
                args.before, args.after, args.output, cameras=args.cameras,
                width=args.width, height=args.height,
                objects_folder=args.objects_folder,
                texture_folder=args.texture_folder, palette_file=args.palette,
                appearance=args.appearance, bsp_mode=args.bsp_mode,
                textures=not args.no_textures, tolerance=args.tolerance,
                max_diff_ratio=args.max_diff_ratio,
                strict_assets=args.strict_assets)
            result = {
                "output_directory": str(args.output),
                "maximum_changed_fraction": summary["maximum_changed_fraction"],
                "threshold_passed": summary["threshold_passed"],
                "warnings": summary["warnings"],
            }
            if not summary["threshold_passed"]:
                print(json.dumps(result, indent=2, sort_keys=True))
                parser.exit(3, "Visual regression threshold exceeded; images saved.\n")
        elif args.command == "generate":
            if args.views and args.no_analysis:
                parser.error("--views cannot be combined with --no-analysis")
            package = generate_package(
                args.recipe, args.output, with_views=args.views,
                with_analysis=not args.no_analysis,
                objects_folder=args.objects_folder)
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
