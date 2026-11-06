"""Read-only Papyrus 8-bit MIP asset resolver and GPU texture-atlas builder.

MIP pixels remain palette indices. The shader converts indices with a separate
256-entry PCX palette, so selecting a new palette never rebuilds this atlas.
Uses the same validated MIP decoder as the existing CAD preview.
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import numpy as np

from texture_preview import load_mip, TextureError


@dataclass
class TextureAtlas:
    pixels: np.ndarray  # uint8, (height,width), OpenGL GL_R8UI
    polygon_rects: dict[int, tuple[int, int, int, int]]
    loaded_names: tuple[str, ...] = ()
    missing_names: tuple[str, ...] = ()
    errors: tuple[str, ...] = ()
    textured_polygons: int = 0
    # Exact, resolved files that made it into this atlas, including nested
    # materials and user overrides. Used by the read-only MIP UV browser.
    loaded_paths: tuple[str, ...] = ()

    @property
    def size_bytes(self):
        return self.pixels.nbytes


def load_palette(path):
    """Return strict PCX VGA trailer as uint8 RGB[256,3].

    The trailing VGA palette is independent of PCX RLE image contents.
    Rejecting malformed files avoids silently displaying incorrect colors.
    """
    data = Path(path).read_bytes()
    if len(data) < 897 or data[0] != 0x0a or data[-769] != 0x0c:
        raise ValueError("Expected 8-bit PCX with trailing 256-color VGA palette")
    return np.frombuffer(data[-768:], dtype=np.uint8).copy().reshape(256, 3)



def find_model_sunny_palette(model_path):
    """Find SUNNY.PCX beside the opened .3D/.3DO (case-insensitively).

    Only the opened model's immediate folder is searched. Referenced 3DO
    folders, the texture-folder override, and subdirectories cannot change
    the palette selected for the parent model. Do not load or modify files
    during lookup; the worker validates PCX contents separately.
    """
    folder = Path(model_path).parent
    for name in ("SUNNY.PCX", "sunny.pcx"):
        candidate = folder / name
        if candidate.is_file():
            return candidate
    try:
        # Stable if a case-sensitive filesystem contains multiple variants.
        candidates = sorted(
            (entry for entry in folder.iterdir()
             if entry.name.casefold() == "sunny.pcx" and entry.is_file()),
            key=lambda entry: entry.name)
    except OSError:
        return None
    return candidates[0] if candidates else None


def find_texture(name, model_path, texture_folder=None):
    """Resolve one DOS-style MIP basename, case-insensitively, locally only."""
    safe = Path(str(name)).name
    if not safe or safe != str(name) or safe in (".", ".."):
        return None
    model_dir = Path(model_path).parent
    candidates = (
        texture_folder, model_dir, model_dir / "textures",
        model_dir / "mip", model_dir / "mips",
    )
    wanted = safe.casefold()
    if not wanted.endswith(".mip"):
        wanted += ".mip"
    for directory in candidates:
        if directory is None:
            continue
        folder = Path(directory)
        if not folder.is_dir():
            continue
        # Exact file lookups first; on Windows these are normally already
        # case-insensitive. On Linux/macOS track assets may use uppercase.
        direct = folder / wanted
        if direct.is_file():
            return direct
        match = next((entry for entry in folder.iterdir()
                      if entry.is_file() and entry.name.casefold() == wanted), None)
        if match is not None:
            return match
    return None


def _pack(images, max_side):
    """Deterministic shelf packing with an upper bound on GPU atlas memory.

    Returns rects and an integer atlas. Oversized or excess textures remain
    untextured (palette-colored) with explicit error messages.
    """
    if not images:
        return {}, np.zeros((1, 1), dtype=np.uint8), []
    sorted_images = sorted(images.items(), key=lambda pair:
                           (-pair[1].shape[0], -pair[1].shape[1], pair[0]))
    max_w = max(img.shape[1] for _, img in sorted_images)
    if max_w > max_side:
        raise ValueError("MIP wider than maximum GPU atlas")
    area = sum(img.size for _, img in sorted_images)
    width = max(256, 1 << (max_w - 1).bit_length())
    width = min(max_side, width)
    attempt = None
    while width <= max_side:
        x = y = row_h = 0
        locations = {}
        overflow = []
        for name, image in sorted_images:
            h, w = image.shape
            if w > width or h > max_side:
                overflow.append(name)
                continue
            if x + w > width:
                y += row_h
                x = row_h = 0
            if y + h > max_side:
                overflow.append(name)
                continue
            locations[name] = (x, y, w, h)
            x += w
            row_h = max(row_h, h)
        height = y + row_h
        attempt = (locations, overflow, height, width)
        if not overflow or width == max_side:
            break
        width *= 2
    locations, overflow, height, width = attempt
    atlas = np.zeros((max(1, height), width), dtype=np.uint8)
    for name, (x, y, w, h) in locations.items():
        atlas[y:y+h, x:x+w] = images[name]
    return locations, atlas, overflow


def build_atlas(model, model_path, *, texture_folder=None,
                fallback_mip=None, mip_overrides=None, body_mip=None,
                max_side=4096):
    """Build the atlas for reachable POLY [T] records, with diagnostic counts.

    Referenced MATERIAL filenames take priority. The optional explicit
    fallback MIP applies only to otherwise-unassigned POLY [T] records.
    """
    if not 32 <= max_side <= 8192:
        raise ValueError("max_side must be in 32..8192")
    assignments = {}
    paths = {}
    missing = set()
    errors = []
    textured_count = 0
    fallback = Path(fallback_mip) if fallback_mip else None
    body_override = Path(body_mip) if body_mip else None
    body_polygons = getattr(model, 'body_polygons', frozenset())
    overrides = {str(name).casefold(): Path(path)
                 for name, path in (mip_overrides or {}).items()}
    for off, polygon in model.polygons.items():
        if polygon.kind != 2:
            continue
        textured_count += 1
        name = model.polygon_materials.get(off)
        if body_override is not None and off in body_polygons:
            # A manually selected car livery affects ONLY the base car
            # POLY[T] faces. The wheel1/wheel2 DYNAMIC materials retain
            # their separate MIPs, just as in the CPU editor.
            path = body_override if body_override.is_file() else None
            if path is None:
                missing.add(body_override.name)
                continue
        elif name:
            # Explicit car livery assignment wins over MATERIAL filename,
            # but the source's original name remains the lookup key.
            path = overrides.get(name.casefold())
            if path is None:
                # For inherited MATERIAL, use wrapper's location.
                source = getattr(model, 'polygon_sources', {}).get(off, model_path)
                path = find_texture(name, source, texture_folder)
            if path is None or not path.is_file():
                missing.add(name)
                continue
        elif fallback is not None:
            path = fallback if fallback.is_file() else None
            if path is None:
                missing.add(fallback.name)
                continue
        else:
            continue
        key = str(path.resolve()).casefold()
        paths.setdefault(key, path)
        assignments[off] = key

    images = {}
    for key, path in paths.items():
        try:
            first = load_mip(path)[0]
            image = np.ascontiguousarray(np.asarray(first, dtype=np.uint8))
            if image.ndim != 2:
                raise TextureError("Expected one 8-bit indexed image")
            images[key] = image
        except (OSError, ValueError, TextureError) as exc:
            errors.append(f"{path.name}: {exc}")
    rects, pixels, overflow = _pack(images, max_side)
    if overflow:
        errors.append(f"{len(overflow)} MIPs exceed {max_side}x{max_side} atlas capacity")
    polygon_rects = {off:rects[key] for off, key in assignments.items()
                     if key in rects}
    loaded_paths = tuple(str(path) for path in sorted(
        (paths[key] for key in rects),
        key=lambda path: (path.name.casefold(), str(path).casefold())))
    return TextureAtlas(
        np.ascontiguousarray(pixels), polygon_rects,
        tuple(Path(path).name for path in loaded_paths),
        tuple(sorted(missing)), tuple(errors), textured_count,
        loaded_paths,
    )
