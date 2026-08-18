"""Scale texture coordinates for selected materials in a track .3D file."""

from __future__ import annotations

from dataclasses import dataclass
import math
from pathlib import Path
import re

_MATERIAL_START_RE = re.compile(r"^[ \t]*MATERIAL\b", re.IGNORECASE | re.MULTILINE)
_MIP_RE = re.compile(r'\bMIP\s*=\s*"([^"]+)"', re.IGNORECASE)
_TEXTURE_COORD_RE = re.compile(
    r"(?P<prefix>\bt\s*=\s*<\s*)(?P<u>[+-]?\d+)(?P<middle>\s*,\s*)"
    r"(?P<v>[+-]?\d+)(?P<suffix>\s*>)",
    re.IGNORECASE,
)


@dataclass(frozen=True)
class TextureScaleResult:
    """The updated text and the number of matching materials processed."""

    text: str
    materials_altered: int


def _normalized_mip_name(name: str) -> str:
    normalized = name.strip().strip('"').casefold()
    if normalized.endswith(".mip"):
        normalized = normalized[:-4]
    return normalized


def scale_track3d_texture_coordinates(
    text: str, mip_name: str, factor: float = 2.0
) -> TextureScaleResult:
    """Scale all integer ``t=<u,v>`` values in materials using *mip_name*.

    MIP matching is case-insensitive and accepts names both with and without the
    conventional ``.mip`` extension. Scaled values are rounded toward negative
    infinity, as requested by the UI's "round down" behavior.
    """
    target = _normalized_mip_name(mip_name)
    if not target:
        raise ValueError("A MIP name is required.")
    if not math.isfinite(factor) or factor <= 0:
        raise ValueError("The scale factor must be a positive number.")

    starts = [match.start() for match in _MATERIAL_START_RE.finditer(text)]
    if not starts:
        return TextureScaleResult(text, 0)

    output: list[str] = [text[: starts[0]]]
    altered = 0
    for index, start in enumerate(starts):
        end = starts[index + 1] if index + 1 < len(starts) else len(text)
        block = text[start:end]
        mip_match = _MIP_RE.search(block)
        if mip_match and _normalized_mip_name(mip_match.group(1)) == target:
            coordinate_count = 0

            def scale_coordinate(match: re.Match[str]) -> str:
                nonlocal coordinate_count
                coordinate_count += 1
                u = math.floor(int(match.group("u")) * factor)
                v = math.floor(int(match.group("v")) * factor)
                return (
                    f'{match.group("prefix")}{u}{match.group("middle")}'
                    f'{v}{match.group("suffix")}'
                )

            block = _TEXTURE_COORD_RE.sub(scale_coordinate, block)
            if coordinate_count:
                altered += 1
        output.append(block)

    return TextureScaleResult("".join(output), altered)


def scale_track3d_texture_file(
    path: Path, mip_name: str, factor: float = 2.0
) -> TextureScaleResult:
    """Scale coordinates in *path* in place while preserving its text encoding."""
    raw = path.read_bytes()
    text = raw.decode("latin-1")
    result = scale_track3d_texture_coordinates(text, mip_name, factor)
    if result.text != text:
        path.write_bytes(result.text.encode("latin-1"))
    return result
