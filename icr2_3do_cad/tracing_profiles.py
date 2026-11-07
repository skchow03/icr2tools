"""Persist reusable, named tracing-image calibrations outside game assets.

Profiles reference an image by its absolute filesystem path (no embedded pixels).
Model-relative placement stores the original mesh center, so a restored image
keeps its physical scale/rotation but follows another model's origin.
This module is Qt/GL-free and deliberately never touches .3D/.3DO files.
"""
from __future__ import annotations

import json
import math
import os
import tempfile
from dataclasses import replace
from pathlib import Path

from tracing_reference import PLANES, TracingReference

VERSION = 1
MAX_PROFILES = 1000
MAX_SIZE = 2_000_000


class ProfileError(ValueError):
    """An invalid, unavailable, or conflicting saved profile."""


def _point(value, description, *, optional=False):
    if value is None and optional:
        return None
    if (not isinstance(value, (list, tuple)) or len(value) != 2
            or any(isinstance(n, bool) or
                   not isinstance(n, (int, float)) or
                   not math.isfinite(n) for n in value)):
        raise ProfileError(f"{description} must be two finite numbers")
    return tuple(float(n) for n in value)


def _name(value):
    if (not isinstance(value, str) or not value.strip()
            or len(value.strip()) > 100 or
            any(ord(c) < 32 for c in value)):
        raise ProfileError("Profile name must be 1–100 printable characters")
    return value.strip()


def _mesh_center(mesh):
    center = getattr(mesh, "center", None)
    if (center is None or len(center) != 3 or
            any(not math.isfinite(float(v)) for v in center)):
        raise ProfileError("Current model mesh center is unavailable")
    return tuple(float(v) for v in center)


def _center_uv(mesh, plane):
    center = _mesh_center(mesh)
    u, v, _, _ = PLANES[plane]
    return center[u], center[v]


def encode_profile(name, reference, mesh):
    """Snapshot all calibration settings, including relative model placement."""
    name = _name(name)
    center_uv = _center_uv(mesh, reference.plane)
    return {
        "name": name,
        "image_path": str(reference.path.expanduser().resolve()),
        "width": reference.width,
        "height": reference.height,
        "plane": reference.plane,
        "anchor_pixel": list(reference.anchor_pixel),
        "world_anchor": list(reference.world_anchor),
        "mesh_center_uv": list(center_uv),
        "units_per_pixel": reference.units_per_pixel,
        "rotation_degrees": reference.rotation_degrees,
        "opacity": reference.opacity,
        "visible": reference.visible,
        "point_a": list(reference.point_a) if reference.point_a else None,
        "point_b": list(reference.point_b) if reference.point_b else None,
        "calibration_distance": reference.calibration_distance,
    }


def decode_profile(data, mesh, *, placement="relative"):
    """Restore with saved dimensions, calibration and optional recentering.

    relative: preserve raw model-unit offset from the original mesh center.
    absolute: preserve the exact stored world U/V coordinates.
    """
    if placement not in ("relative", "absolute"):
        raise ProfileError("Placement must be relative or absolute")
    if not isinstance(data, dict):
        raise ProfileError("Malformed tracing profile")
    try:
        _name(data["name"])
        path_text = data["image_path"]
        if not isinstance(path_text, str) or not path_text.strip():
            raise ProfileError("Missing image path in profile")
        path = Path(path_text)
        if not path.is_absolute():
            raise ProfileError("Saved reference path must be absolute")
        plane = data["plane"]
        if plane not in PLANES:
            raise ProfileError("Invalid tracing plane")
        width, height = data["width"], data["height"]
        if (type(width) is not int or type(height) is not int or
                width <= 0 or height <= 0 or
                width * height > 40_000_000):
            raise ProfileError("Invalid saved image dimensions")
        anchor = _point(data["anchor_pixel"], "Image anchor")
        world = _point(data["world_anchor"], "World anchor")
        center = _point(data["mesh_center_uv"], "Saved model center")
        if placement == "relative":
            current = _center_uv(mesh, plane)
            world = (world[0] + current[0] - center[0],
                     world[1] + current[1] - center[1])
        ref = TracingReference(
            path=path, width=width, height=height, plane=plane,
            anchor_pixel=anchor, world_anchor=world,
            units_per_pixel=float(data["units_per_pixel"]),
            rotation_degrees=float(data["rotation_degrees"]),
            opacity=float(data["opacity"]),
            visible=data["visible"],
            point_a=_point(data.get("point_a"), "Calibration A", optional=True),
            point_b=_point(data.get("point_b"), "Calibration B", optional=True),
            calibration_distance=(float(data["calibration_distance"])
                                  if data.get("calibration_distance") is not None
                                  else None),
        )
        if type(ref.visible) is not bool:
            raise ProfileError("Invalid visibility flag")
        if (ref.calibration_distance is not None and
                (not math.isfinite(ref.calibration_distance) or
                 ref.calibration_distance <= 0)):
            raise ProfileError("Invalid calibration distance")
        if (ref.point_a is not None and ref.point_b is not None and
                (ref.point_a[0]-ref.point_b[0])**2 +
                (ref.point_a[1]-ref.point_b[1])**2 <= 1e-12):
            raise ProfileError("Identical calibration points")
        return ref
    except (KeyError, ValueError, TypeError, OverflowError) as exc:
        if isinstance(exc, ProfileError):
            raise
        raise ProfileError(f"Saved tracing profile is invalid: {exc}") from exc


class TracingProfileStore:
    """Atomic JSON library: named profiles, no image bytes, no game edits."""

    def __init__(self, path):
        self.path = Path(path)

    def _read(self):
        if not self.path.exists():
            return []
        try:
            if self.path.stat().st_size > MAX_SIZE:
                raise ProfileError("Tracing profile library is too large")
            data = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, UnicodeError, json.JSONDecodeError) as exc:
            raise ProfileError(f"Cannot read tracing profiles: {exc}") from exc
        if (not isinstance(data, dict) or data.get("version") != VERSION
                or not isinstance(data.get("profiles"), list)):
            raise ProfileError("Unsupported or malformed tracing profile library")
        profiles = data["profiles"]
        if len(profiles) > MAX_PROFILES:
            raise ProfileError("Too many tracing profiles")
        names = set()
        for item in profiles:
            if not isinstance(item, dict):
                raise ProfileError("Malformed tracing profile entry")
            name = _name(item.get("name"))
            if name.casefold() in names:
                raise ProfileError("Duplicate tracing profile names")
            names.add(name.casefold())
        return profiles

    def names(self):
        return sorted((p["name"] for p in self._read()), key=str.casefold)

    def has(self, name):
        value = _name(name).casefold()
        return any(p["name"].casefold() == value for p in self._read())

    def _write(self, profiles):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        payload = json.dumps(
            {"version": VERSION, "profiles": profiles}, indent=2,
            ensure_ascii=False, allow_nan=False) + "\n"
        if len(payload.encode("utf-8")) > MAX_SIZE:
            raise ProfileError("Tracing profile library exceeds 2 MB")
        tmp = None
        try:
            with tempfile.NamedTemporaryFile(
                    mode="w", encoding="utf-8", newline="\n",
                    dir=self.path.parent, prefix=".tracing_profiles_",
                    suffix=".tmp", delete=False) as stream:
                tmp = Path(stream.name)
                stream.write(payload)
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(tmp, self.path)
        except OSError as exc:
            raise ProfileError(f"Cannot save tracing profiles: {exc}") from exc
        finally:
            if tmp is not None:
                tmp.unlink(missing_ok=True)

    def save(self, name, reference, mesh, *, overwrite=False):
        record = encode_profile(name, reference, mesh)
        profiles = self._read()
        matches = [i for i, item in enumerate(profiles)
                   if item["name"].casefold() == record["name"].casefold()]
        if matches:
            if not overwrite:
                raise ProfileError(f"Profile '{name}' already exists")
            # Preserve the existing capitalization on an explicit overwrite.
            record["name"] = profiles[matches[0]]["name"]
            profiles[matches[0]] = record
        else:
            if len(profiles) >= MAX_PROFILES:
                raise ProfileError("Tracing profile library is full")
            profiles.append(record)
        self._write(profiles)

    def load(self, name, mesh, *, placement="relative"):
        folded = _name(name).casefold()
        for entry in self._read():
            if entry["name"].casefold() == folded:
                return decode_profile(entry, mesh, placement=placement)
        raise ProfileError(f"Tracing profile '{name}' was not found")

    def delete(self, name):
        folded = _name(name).casefold()
        profiles = self._read()
        remaining = [p for p in profiles if p["name"].casefold() != folded]
        if len(profiles) == len(remaining):
            raise ProfileError(f"Tracing profile '{name}' was not found")
        self._write(remaining)
