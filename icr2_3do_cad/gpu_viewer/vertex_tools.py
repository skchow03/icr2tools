"""Pure helpers for GPU vertex dots and conservative N3 source edits.

Coordinates and selection refer to *root model* vertex body offsets, not
flattened external/DYNAMIC geometry. Nothing here writes a binary file.
"""
from __future__ import annotations

from decimal import Decimal
import re

import numpy as np

from three_do import INT32_LO, INT32_HI


_VERTEX_CMD = re.compile(
    r"^\[\s*<\s*[-+]?\d+(?:\.\d+)?\s*,\s*[-+]?\d+(?:\.\d+)?\s*,"
    r"\s*[-+]?\d+(?:\.\d+)?\s*>\s*"
    r"(?:,\s*T\s*=\s*<\s*\d+\s*,\s*\d+\s*>)?\s*\]$", re.I | re.S
)


def check_values(xyz, uv=None):
    if len(xyz) != 3:
        raise ValueError("XYZ requires exactly three integers")
    xyz = tuple(int(value) for value in xyz)
    if any(value < INT32_LO or value > INT32_HI for value in xyz):
        raise ValueError("XYZ must remain inside signed 32-bit range")
    if uv is not None:
        if len(uv) != 2:
            raise ValueError("UV requires exactly two integers")
        uv = tuple(int(value) for value in uv)
        if any(value < 0 or value > 65535 for value in uv):
            raise ValueError("UV must be unsigned 16-bit (0–65535)")
    return xyz, uv


def source_vertex_text(xyz, uv=None, coordinate_scale=1):
    xyz, uv = check_values(xyz, uv)
    scale = Decimal(str(coordinate_scale))
    if not scale.is_finite() or scale <= 0:
        raise ValueError("Invalid N3 coordinate scale")
    def field(value):
        number = Decimal(value) / scale
        return format(number, "f").rstrip("0").rstrip(".") if "." in format(number, "f") else str(number)
    coords = ", ".join(field(value) for value in xyz)
    suffix = f", T=<{uv[0]}, {uv[1]}>" if uv is not None else ""
    return f"[<{coords}>{suffix}]"


def patch_vertex_source(source, label, xyz, uv=None, *, coordinate_scale=1):
    """Replace only one vertex declaration, preserving comments and other N3.

    Label is taken from the last validated compiler Document, never guessed
    from a possibly stale binary record offset.
    """
    if not re.fullmatch(r"[A-Za-z_][A-Za-z_0-9-]*", label):
        raise ValueError("Invalid N3 vertex label")
    declaration = re.compile(r"(?m)^[ \t]*" + re.escape(label) + r"[ \t]*:[ \t]*")
    matches = list(declaration.finditer(source))
    if len(matches) != 1:
        raise ValueError(f"Expected one N3 declaration for {label!r}")
    start = matches[0].end()
    semi = source.find(";", start)
    if semi < 0:
        raise ValueError(f"Unterminated vertex declaration {label!r}")
    previous = source[start:semi]
    if not _VERTEX_CMD.fullmatch(previous.strip()):
        raise ValueError(f"{label!r} is not an editable vertex declaration")
    was_textured = re.search(r",\s*T\s*=", previous, re.I) is not None
    if was_textured != (uv is not None):
        raise ValueError("Cannot change textured vertex type")
    replacement = source_vertex_text(xyz, uv, coordinate_scale)
    # Keep original indentation and whitespace adjacent to the declaration.
    leading = previous[:len(previous)-len(previous.lstrip())]
    trailing = previous[len(previous.rstrip()):]
    return source[:start] + leading + replacement + trailing + source[semi:]


def project_vertices(xyz, center, scale, mvp, width, height):
    """Return projected logical Qt pixel coordinates and front-clipped mask.

    Apply the identical model recenter/scale and MVP as the OpenGL shader.
    Handles both orthographic and perspective projections without GL reads.
    """
    xyz = np.asarray(xyz, dtype=np.float64).reshape((-1, 3))
    if not len(xyz):
        return np.zeros((0, 3)), np.zeros(0, dtype=bool)
    normed = (xyz - np.asarray(center, dtype=np.float64)) / float(scale)
    homogeneous = np.column_stack((normed, np.ones(len(xyz))))
    clip = homogeneous @ np.asarray(mvp, dtype=np.float64).T
    valid = clip[:, 3] > 1e-9
    ndc = np.full((len(xyz), 3), np.nan)
    np.divide(clip[:, :3], clip[:, 3, None], out=ndc,
              where=valid[:, None])
    valid &= np.isfinite(ndc).all(axis=1)
    valid &= (np.abs(ndc[:, 0]) <= 1.0) & (np.abs(ndc[:, 1]) <= 1.0)
    valid &= (ndc[:, 2] >= -1.0) & (ndc[:, 2] <= 1.0)
    projected = np.column_stack((
        (ndc[:, 0] + 1) * width * .5,
        (1 - ndc[:, 1]) * height * .5,
        ndc[:, 2],
    ))
    return projected, valid


def pick_vertex(offsets, pixels, visible, x, y, radius=11.0):
    """Choose closest visible vertex, breaking coincident ties by depth."""
    offsets = np.asarray(offsets)
    pixels = np.asarray(pixels)
    visible = np.asarray(visible, dtype=bool)
    if len(offsets) == 0:
        return None
    d2 = (pixels[:, 0] - x)**2 + (pixels[:, 1] - y)**2
    matches = np.flatnonzero(visible & np.isfinite(d2) & (d2 <= radius**2))
    if not len(matches):
        return None
    candidates = sorted(matches, key=lambda i: (float(d2[i]), float(pixels[i, 2])))
    return int(offsets[candidates[0]])


def drag_along_axis(xyz, axis, pixel_dx, pixel_dy, step, center, scale,
                    mvp, width, height):
    """Compute one quantized Papyrus axis movement using projected basis."""
    if axis not in "XYZ" or len(axis) != 1 or step < 1:
        raise ValueError("Choose an X/Y/Z axis and a positive integer step")
    xyz, _ = check_values(xyz)
    index = "XYZ".index(axis)
    sample = max(1, round(0.001 * float(scale)))
    endpoint = list(xyz)
    endpoint[index] += sample
    points, visible = project_vertices((xyz, endpoint), center, scale, mvp, width, height)
    if not visible.all():
        raise ValueError("Selected axis cannot be dragged from this camera")
    basis = (points[1, :2] - points[0, :2]) / sample
    size = float(basis @ basis)
    if size < 1e-14:
        raise ValueError("Chosen axis is edge-on; orbit the camera")
    delta = (float(pixel_dx) * basis[0] + float(pixel_dy) * basis[1]) / size
    delta = round(delta / step) * step
    moved = list(xyz)
    moved[index] = max(INT32_LO, min(INT32_HI, moved[index] + delta))
    return tuple(moved)
