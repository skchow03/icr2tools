"""Safe recipe compilation/validation and output packaging for Stage 2.

No in-place patching of existing 3DOs. Generate in a temporary directory,
validate with the existing N3 compiler and the actual binary parser, then
atomically publish a *new* output directory.
"""
from __future__ import annotations

from collections import Counter
from decimal import Decimal
from hashlib import sha256
import json
import os
from pathlib import Path
import shutil
import tempfile

from .inspector import write_package
from .parametric import RecipeError, generate_source

# Preserve the CAD parser/compiler as the single source of 3DO semantics.
from n3_compile import compile_n3_text
from three_do import Model, FormatError


def _read_recipe(path):
    try:
        data = json.loads(Path(path).read_text(encoding="utf-8-sig"),
                          parse_float=Decimal)
    except json.JSONDecodeError as exc:
        raise RecipeError(f"Invalid recipe JSON: {exc}") from exc
    return data


def validate_source(source, *, model_path="generated.3D"):
    """Compile source in memory, verify binary parser agrees and report counts."""
    model, _ = compile_n3_text(source, Path(model_path), associate_planes=False)
    reparsed = Model(model_path, raw_data=model.raw, associate_planes=False)
    if reparsed.raw != model.raw or reparsed.root_offset != model.root_offset:
        raise FormatError("Compiled model failed binary parser round-trip")
    if len(model.polygons) != len(reparsed.polygons):
        raise FormatError("Compiled polygon count changed after reparse")
    if len(model.vertices) != len(reparsed.vertices):
        raise FormatError("Compiled vertex count changed after reparse")
    return model, {
        "compiled": True,
        "source_sha256": sha256(source.encode("utf-8")).hexdigest(),
        "binary_sha256": sha256(model.raw).hexdigest(),
        "bytes": len(model.raw),
        "root_record_offset": model.root_offset,
        "vertices": len(model.vertices),
        "polygons": len(model.polygons),
        "textured_polygons": sum(p.kind == 2 for p in model.polygons.values()),
        "mip_names": list(model.mip_names),
        "record_types": dict(sorted(Counter(
            str(x) for x in model.records.values()).items())),
        "parser_warnings": list(dict.fromkeys(model.warnings)),
        "note": "Compiler and binary parser checked; view-dependent BSP and "
                "in-game draw order are not automatically validated.",
    }


def validate_path(path):
    """Validate existing .3D or .3do without writing any files."""
    path = Path(path)
    if path.suffix.casefold() == ".3d":
        _, details = validate_source(
            path.read_text(encoding="utf-8-sig"), model_path=path)
        return details
    if path.suffix.casefold() == ".3do":
        model = Model(path, associate_planes=False)
        return {
            "compiled": False,
            "binary_sha256": sha256(model.raw).hexdigest(),
            "bytes": len(model.raw),
            "root_record_offset": model.root_offset,
            "vertices": len(model.vertices),
            "polygons": len(model.polygons),
            "textured_polygons": sum(p.kind == 2 for p in model.polygons.values()),
            "mip_names": list(model.mip_names),
            "parser_warnings": list(model.warnings),
            "note": "Existing binary parsed; no source compilation or in-game verification.",
        }
    raise RecipeError("Validation input must be .3D or .3do")


def generate_package(recipe_file, output, *, with_views=False,
                     with_analysis=True):
    """Generate source, compile, reparse, and publish only if every step works.

    If a validation or report step fails, the temporary output folder is
    removed and the intended output location remains absent. Existing output
    directories and original game assets are NEVER overwritten.
    """
    recipe_file, output = Path(recipe_file), Path(output)
    if not recipe_file.is_file():
        raise FileNotFoundError(recipe_file)
    if output.exists():
        raise FileExistsError(f"Output already exists: {output}; choose a new directory")
    if output.resolve() == recipe_file.resolve():
        raise RecipeError("Output location must differ from recipe input")
    recipe = _read_recipe(recipe_file)
    source, manifest = generate_source(recipe)
    model, validation = validate_source(source)
    if len(model.polygons) != manifest["polygon_count"]:
        raise FormatError("Generated polygon count differs from recipe manifest")
    if len(model.vertices) != manifest["vertex_count"]:
        raise FormatError("Generated vertex count differs from recipe manifest")
    if model.warnings:
        raise FormatError("Generated model has parser warnings: " +
                          "; ".join(model.warnings))
    output.parent.mkdir(parents=True, exist_ok=True)
    temporary = Path(tempfile.mkdtemp(prefix=".icr2-n3-", dir=output.parent))
    try:
        shutil.copyfile(recipe_file, temporary / "recipe.json")
        (temporary / "model.3D").write_text(source, encoding="utf-8")
        (temporary / "model.3do").write_bytes(model.raw)
        _json_write(temporary / "manifest.json", manifest)
        _json_write(temporary / "validation.json", validation)
        if with_analysis:
            write_package(
                temporary / "model.3do", temporary / "analysis",
                with_views=with_views)
        if output.exists():
            raise FileExistsError(f"Output created concurrently: {output}")
        # Same filesystem and no existing target. Failure leaves input safe.
        temporary.rename(output)
    finally:
        if temporary.exists():
            shutil.rmtree(temporary)
    return {"output_directory": str(output), "manifest": manifest,
            "validation": validation}


def _json_write(path, obj):
    with Path(path).open("w", encoding="utf-8") as handle:
        json.dump(obj, handle, indent=2, sort_keys=True, allow_nan=False)
        handle.write("\n")
