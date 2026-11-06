"""Track-only, read-only Papyrus HORIZ.3DO/HORIZ.3D background scene.

Skybox is a separate GPU pass: its default eye is raw (0, 0, 100)
while its orientation follows the main camera. This avoids translation
parallax and keeps sky geometry out of the track's BSP and frame bounds.
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import numpy as np

from gpu_viewer.model_assets import candidate_model_paths, load_model_candidate
from gpu_viewer.mesh import make_mesh
from gpu_viewer.scene import build_scene, ordered_scene_indices
from gpu_viewer.textures import build_atlas

SKY_EYE = (0.0, 0.0, 100.0)


@dataclass
class TrackSkybox:
    path: Path
    model: object
    mesh: object
    atlas: object
    indices: np.ndarray


def skybox_candidates(track_path, objects_folder=None):
    """Search track directories, trying every .3do before any .3d."""
    path = Path(track_path)
    return candidate_model_paths(
        "horiz", (path.parent, path.parent / "objects", objects_folder))


def find_track_skybox(track_path, objects_folder=None):
    """Find valid HORIZ.3DO or a standalone HORIZ.3D alternative."""
    for candidate in skybox_candidates(track_path, objects_folder):
        try:
            load_model_candidate(candidate)
        except (OSError, ValueError, UnicodeError, OverflowError):
            continue
        return candidate
    return None


def load_track_skybox(path, palette, *, texture_folder=None):
    """Prepare background geometry on a worker without OpenGL operations."""
    path = Path(path)
    model = load_model_candidate(path)
    scene = build_scene(model)
    atlas = build_atlas(scene.geometry, path, texture_folder=texture_folder)
    mesh = make_mesh(scene.geometry, palette, atlas)
    # Use the default raw HORIZ eye for painter ordering. The viewport
    # can position its virtual sky eye independently at draw time.
    indices, _, _ = ordered_scene_indices(
        scene, mesh, SKY_EYE, None, bsp_mode="off")
    if indices.size == 0:
        raise ValueError(f"{path.name} contains no renderable skybox polygons")
    return TrackSkybox(path, model, mesh, atlas, indices)


def load_preferred_track_skybox(track_path, palette, *,
                                objects_folder=None, texture_folder=None):
    """Find fully renderable sky: valid .3do first, then valid .3d."""
    problems = []
    for candidate in skybox_candidates(track_path, objects_folder):
        try:
            sky = load_track_skybox(
                candidate, palette, texture_folder=texture_folder)
        except (OSError, ValueError, UnicodeError, OverflowError) as exc:
            problems.append(f"{candidate.name}: {exc}")
            continue
        return sky, "; ".join(problems) if problems else None
    return None, "; ".join(problems) if problems else None


def skybox_view_matrix(camera_view, mesh, eye=SKY_EYE):
    """World-axis orientation from the main camera, but sky-local position.

    Mesh positions are (raw_xyz - mesh.center) / mesh.scale, so the fixed
    raw sky eye must be converted to the same coordinates. The camera's
    *translation* is ignored, and rotation is retained, including pitch.
    """
    matrix = np.identity(4, dtype=np.float64)
    rotation = np.asarray(camera_view, dtype=np.float64)[:3, :3]
    local_eye = (
        np.asarray(eye, dtype=np.float64)
        - np.asarray(mesh.center, dtype=np.float64)
    ) / mesh.scale
    matrix[:3, :3] = rotation
    matrix[:3, 3] = -rotation @ local_eye
    return matrix
