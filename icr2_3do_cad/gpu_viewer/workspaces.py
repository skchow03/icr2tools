"""Workspace labels and conservative file hints for the GPU CAD viewer.

A model's purpose cannot be established from arbitrary 3DO geometry alone.
Only unambiguous appearance wrappers and familiar filenames are suggested;
all other files retain the user's manually selected workspace.
"""
from __future__ import annotations

from pathlib import Path


WORKSPACE_MODES = ("car", "track", "object")

def resolve_lod_distance(mode, distance):
    """Translate a single UI detail-level choice to the existing renderer API."""
    if mode == "auto":
        return "auto"
    if mode == "all":
        return None
    if mode == "manual":
        return distance
    raise ValueError(f"Unknown LOD mode: {mode!r}")


def max_switch_distance(scene):
    """Largest nonnegative RES branch threshold across loaded model instances.

    Include nested external 3DOs: they share the viewer's manual distance.
    Missing external objects have no parsed switches to inspect.
    """
    if scene is None:
        return 0
    return max(
        (int(threshold)
         for instance in scene.instances
         for switch in instance.model.switches.values()
         for threshold, _ in switch.branches
         if threshold > 0),
        default=0,
    )



_CAR_FILENAMES = frozenset({
    "indycar", "roadcar", "pacecar", "panoz", "irl", "cars",
})
_TRACK_FILENAMES = frozenset({"track", "reno"})


def suggest_workspace(path, stats):
    """Return a strong workspace hint, or None when type is ambiguous."""
    if stats.get("appearance_geometry") or stats.get("recolor_pairs", 0):
        return "car"
    if path is None:
        return None
    stem = Path(path).stem.casefold()
    if stem in _CAR_FILENAMES:
        return "car"
    if (stem in _TRACK_FILENAMES or stem.startswith(("track_", "trk_"))
            or stem.endswith("_track")):
        return "track"
    return None


def workspace_scene_summary(mode, stats):
    """Describe the currently loaded scene without assuming its file type."""
    if mode == "track":
        return (
            f"Track scene: {stats.get('model_vertices', 0):,} vertices | "
            f"{stats.get('model_planes', 0):,} planes | "
            f"{stats.get('dynamic_instances', 0):,} external instances | "
            f"{stats.get('switches', 0):,} RES switches | "
            f"{len(stats.get('external_warnings', ()))} unresolved references")
    if mode == "object":
        return (
            f"Object scene: {stats.get('model_polygons', 0):,} polygons | "
            f"{stats.get('mips', 0):,} named MIPs | "
            f"{stats.get('external_objects', 0):,} DYNAMIC references")
    raise ValueError(f"Unknown scene summary: {mode}")
