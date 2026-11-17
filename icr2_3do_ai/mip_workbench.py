"""UV-aware, palette-locked MIP art workbench for ICR2 car liveries.

The inspector supplies real polygon UVs. The existing MIP codec supplies
conversion. This module never invents semantic parts, modifies source assets,
or claims that a UV preview proves the in-game renderer's BSP ordering.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import struct

import numpy as np
from PIL import Image, ImageDraw, ImageOps

from icr2_core.mip.mips import img_to_mip
from .inspector import analyze_model  # also configures CAD's sibling imports
from texture_preview import load_mip


SCHEMA = "icr2.mip.workbench.v1"
PLAN_SCHEMA = "icr2.mip.art-plan.v1"


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _palette(path: Path) -> list[int]:
    with Image.open(path) as image:
        if image.mode != "P":
            raise ValueError(f"Palette must be an indexed PCX: {path}")
        colors = image.getpalette()
    if colors is None or len(colors) < 768:
        raise ValueError(f"Palette has fewer than 256 RGB entries: {path}")
    return colors[:768]


def _selected_polygons(geometry: dict, mip_stem: str, material: str | None):
    faces = [
        p for p in geometry["polygons"]
        if p["kind"] == "POLY[T]" and len(p["uvs"]) >= 3
        and all(uv is not None for uv in p["uvs"])
    ]
    if material:
        chosen = [p for p in faces
                  if (p["material"] or "").casefold().removesuffix(".mip")
                  == material.casefold().removesuffix(".mip")]
        strategy = f"explicit material {material}"
    else:
        chosen = [p for p in faces
                  if (p["material"] or "").casefold().removesuffix(".mip")
                  == mip_stem.casefold()]
        strategy = f"material matching {mip_stem}"
        if not chosen:
            chosen = [p for p in faces if p["body_mip_override_eligible"]]
            strategy = "car-body MIP override eligibility"
    if not chosen:
        raise ValueError(
            "No textured faces match the requested MIP. Use --material with "
            "the MATERIAL name shown in the inspector's geometry.json; "
            "external wheel/helmet textures are deliberately not guessed.")
    return chosen, strategy


def export_template(*, model: Path, mip: Path, palette: Path, output: Path,
                    material: str | None = None, appearance: Path | None = None,
                    objects_folder: Path | None = None) -> dict:
    """Create a pixel-exact atlas guide and a traceable polygon manifest."""
    if output.exists():
        raise FileExistsError(f"Output directory already exists: {output}")
    colors = _palette(palette)
    indexed = load_mip(mip)[0]
    width, height = indexed.size
    report = analyze_model(model, objects_folder=objects_folder,
                           appearance_path=appearance)
    polygons, strategy = _selected_polygons(
        report["geometry"], mip.stem, material)

    overlay = Image.new("RGBA", indexed.size, (0, 0, 0, 0))
    pen = ImageDraw.Draw(overlay)
    coverage = np.zeros((height, width), dtype=np.uint16)
    records = []
    for face in polygons:
        uvs = [[float(u), float(v)] for u, v in face["uvs"]]
        pen.line([tuple(uv) for uv in uvs] + [tuple(uvs[0])],
                 fill=(0, 235, 255, 255), width=1)
        polygon_mask = Image.new("1", indexed.size)
        ImageDraw.Draw(polygon_mask).polygon(
            [tuple(uv) for uv in uvs], fill=1)
        np.minimum(coverage + np.asarray(polygon_mask, dtype=np.uint16),
                   65535, out=coverage)
        outside = any(u < 0 or v < 0 or u >= width or v >= height
                      for u, v in uvs)
        records.append({
            "id": face["id"], "source_file": face["source_file"],
            "material": face["material"],
            "body_override_eligible": face["body_mip_override_eligible"],
            "uvs": uvs, "uv_bounds": face["uv_bounds"],
            "outside_atlas": outside,
        })

    output.mkdir(parents=True)
    indexed.putpalette(colors)
    base_rgb = indexed.convert("RGB")
    base_rgb.save(output / "base.png")
    overlay.save(output / "uv_guide.png")
    preview = Image.alpha_composite(base_rgb.convert("RGBA"), overlay)
    preview.resize((width * 4, height * 4),
                   Image.Resampling.NEAREST).save(output / "uv_preview_4x.png")
    manifest = {
        "schema": SCHEMA,
        "model": str(model.resolve()), "appearance": (
            str(appearance.resolve()) if appearance else None),
        "base_mip": {"path": str(mip.resolve()), "sha256": _sha(mip)},
        "palette": {"path": str(palette.resolve()), "sha256": _sha(palette)},
        "dimensions": [width, height],
        "selection": strategy, "polygon_count": len(records),
        "uv_overlap_pixels": int(np.count_nonzero(coverage > 1)),
        "out_of_bounds_polygon_ids": [
            p["id"] for p in records if p["outside_atlas"]],
        "polygons": records,
        "notice": ("Overlapping UV areas may intentionally share texels. "
                   "These UV guides are not evidence of camera-dependent "
                   "BSP visibility or correct in-game appearance."),
    }
    (output / "manifest.json").write_text(
        json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    return {
        "project": str(output), "polygon_count": len(records),
        "uv_overlap_pixels": manifest["uv_overlap_pixels"],
        "out_of_bounds": len(manifest["out_of_bounds_polygon_ids"]),
    }


def _art_to_rect(image: Image.Image, width: int, height: int,
                 fit: str) -> Image.Image:
    art = image.convert("RGBA")
    if fit == "stretch":
        return art.resize((width, height), Image.Resampling.LANCZOS)
    if fit == "contain":
        sized = ImageOps.contain(art, (width, height),
                                 method=Image.Resampling.LANCZOS)
        frame = Image.new("RGBA", (width, height))
        frame.alpha_composite(
            sized, ((width - sized.width) // 2, (height - sized.height) // 2))
        return frame
    raise ValueError(f"Unknown layer fit {fit!r}; choose stretch or contain")


def _nearest_indices(rgb: np.ndarray, palette: list[int],
                     start: int, end: int) -> np.ndarray:
    """Find only carset-legal palette indices; keep existing indices elsewhere."""
    candidates = np.array(palette, dtype=np.int16).reshape(256, 3)[
        start:end + 1]
    output = np.empty(len(rgb), dtype=np.uint8)
    for begin in range(0, len(rgb), 2048):
        pixels = rgb[begin:begin + 2048].astype(np.int16)
        delta = pixels[:, None, :] - candidates[None, :, :]
        distances = np.sum(delta.astype(np.int32) ** 2, axis=2)
        output[begin:begin + len(pixels)] = (
            distances.argmin(axis=1) + start).astype(np.uint8)
    return output


def build_mip(*, project: Path, plan: Path, output: Path,
              base_mip: Path | None = None, palette_path: Path | None = None,
              min_index: int = 32, max_index: int = 175) -> dict:
    """Apply declared art slots, preserving unchanged base-level MIP indices."""
    manifest = json.loads((project / "manifest.json").read_text(encoding="utf-8"))
    if manifest.get("schema") != SCHEMA:
        raise ValueError("Unsupported project manifest schema")
    recipe = json.loads(plan.read_text(encoding="utf-8"))
    if recipe.get("schema") != PLAN_SCHEMA or not isinstance(
            recipe.get("layers"), list) or not recipe["layers"]:
        raise ValueError("Plan must contain a non-empty layers list and schema "
                         + PLAN_SCHEMA)
    if not (0 <= min_index <= max_index <= 255):
        raise ValueError("Invalid inclusive palette-index range")

    base_mip = base_mip or Path(manifest["base_mip"]["path"])
    palette_path = palette_path or Path(manifest["palette"]["path"])
    if (_sha(base_mip) != manifest["base_mip"]["sha256"]
            or _sha(palette_path) != manifest["palette"]["sha256"]):
        raise ValueError("Source MIP or palette differs from the exported template")
    palette = _palette(palette_path)
    original = np.asarray(load_mip(base_mip)[0], dtype=np.uint8)
    height, width = original.shape
    if [width, height] != manifest["dimensions"]:
        raise ValueError("Base MIP dimensions differ from template")
    preview_rgb = Image.fromarray(original, mode="P")
    preview_rgb.putpalette(palette)
    working = preview_rgb.convert("RGBA")
    selected = np.zeros((height, width), dtype=bool)
    occupied = np.zeros((height, width), dtype=bool)
    layer_results = []

    for item in recipe["layers"]:
        if not isinstance(item, dict):
            raise ValueError("Every layer must be a JSON object")
        rect = item.get("rect")
        if (not isinstance(rect, list) or len(rect) != 4
                or not all(type(v) is int for v in rect)):
            raise ValueError("Layer rect must be [x,y,width,height] integers")
        x, y, w, h = rect
        if x < 0 or y < 0 or w < 1 or h < 1 or x + w > width or y + h > height:
            raise ValueError(f"Layer rectangle outside {width}x{height}: {rect}")
        if occupied[y:y+h, x:x+w].any():
            raise ValueError(f"Overlapping layer rectangles are not allowed: {rect}")
        occupied[y:y+h, x:x+w] = True
        path = plan.parent / item["art"]
        with Image.open(path) as source:
            art = _art_to_rect(source, w, h, item.get("fit", "stretch"))
        alpha = np.asarray(art.getchannel("A"), dtype=np.uint8) > 0
        if not alpha.any():
            raise ValueError(f"Art layer is entirely transparent: {path}")
        selected[y:y+h, x:x+w] |= alpha
        working.alpha_composite(art, (x, y))
        layer_results.append({
            "name": item.get("name", path.stem), "art": str(path),
            "rect": rect, "painted_pixels": int(alpha.sum())})

    changed_rgb = np.asarray(working.convert("RGB"), dtype=np.uint8)
    result = original.copy()
    result[selected] = _nearest_indices(
        changed_rgb[selected], palette, min_index, max_index)
    actual_changes = result != original

    output = output.resolve()
    forbidden = {base_mip.resolve(), palette_path.resolve()}
    if output in forbidden or output.exists():
        raise FileExistsError("Output must be a new .mip, never an existing asset")
    if output.suffix.casefold() != ".mip":
        raise ValueError("Output filename must end in .mip")
    preview_path = output.with_suffix(".png")
    report_path = output.with_name(output.stem + "_report.json")
    if preview_path.exists() or report_path.exists():
        raise FileExistsError("Associated preview/report output already exists")
    output.parent.mkdir(parents=True, exist_ok=True)

    indexed = Image.fromarray(result, mode="P")
    indexed.putpalette(palette)
    try:
        # Reuse the established car MIP writer for all downsampled LODs.
        # Its RGB quantization can remap equivalent palette entries, so
        # restore the exact indexed base level afterwards.
        img_to_mip(indexed, str(output), str(palette_path), mode="carset")
        raw = bytearray(output.read_bytes())
        offset = 4 + struct.unpack_from("<i", raw, 32)[0]
        if offset < 0 or offset + result.size > len(raw):
            raise ValueError("Generated MIP has an invalid level-zero offset")
        raw[offset:offset + result.size] = result.tobytes()
        output.write_bytes(raw)
        verified = np.asarray(load_mip(output)[0], dtype=np.uint8)
        if not np.array_equal(verified, result):
            raise ValueError("Compiled MIP does not round-trip exactly")
        indexed.save(preview_path)
        summary = {
            "output_mip": str(output), "palette_range": [min_index, max_index],
            "art_layers": layer_results,
            "changed_base_pixels": int(actual_changes.sum()),
            "changed_outside_slots": int(np.count_nonzero(actual_changes & ~selected)),
            "base_level_preserved_outside_slots": True,
            "note": ("Lower mip levels are regenerated by the existing "
                     "carset MIP converter; review in CAD and in game."),
        }
        report_path.write_text(json.dumps(summary, indent=2) + "\n",
                               encoding="utf-8")
    except Exception:
        output.unlink(missing_ok=True)
        preview_path.unlink(missing_ok=True)
        report_path.unlink(missing_ok=True)
        raise
    return summary


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(
        description="UV-based ICR2 car MIP editing, with palette-safe art slots")
    commands = parser.add_subparsers(dest="command", required=True)
    export = commands.add_parser("export", help="Create an editable MIP/UV guide")
    export.add_argument("--model", type=Path, required=True)
    export.add_argument("--mip", type=Path, required=True)
    export.add_argument("--palette", type=Path, required=True)
    export.add_argument("--appearance", type=Path)
    export.add_argument("--objects-folder", type=Path)
    export.add_argument("--material")
    export.add_argument("-o", "--output", type=Path, required=True)
    build = commands.add_parser("build", help="Composite art slots into a new MIP")
    build.add_argument("--project", type=Path, required=True)
    build.add_argument("--plan", type=Path, required=True)
    build.add_argument("--mip", type=Path, help="Override original MIP path (same SHA required)")
    build.add_argument("--palette", type=Path, help="Override palette path (same SHA required)")
    build.add_argument("--min-index", type=int, default=32)
    build.add_argument("--max-index", type=int, default=175)
    build.add_argument("-o", "--output", type=Path, required=True)
    args = parser.parse_args(argv)
    try:
        if args.command == "export":
            result = export_template(
                model=args.model, mip=args.mip, palette=args.palette,
                output=args.output, material=args.material,
                appearance=args.appearance, objects_folder=args.objects_folder)
        else:
            result = build_mip(
                project=args.project, plan=args.plan, output=args.output,
                base_mip=args.mip, palette_path=args.palette,
                min_index=args.min_index, max_index=args.max_index)
    except (OSError, ValueError, KeyError, TypeError) as error:
        parser.exit(2, f"MIP workbench {args.command} failed: {error}\n")
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
