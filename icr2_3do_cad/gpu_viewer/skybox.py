"""Track-only, read-only Papyrus HORIZ.3DO background scene.

Skybox is a separate GPU pass: its eye remains at raw (0, 0, 1000)
while its orientation follows the main camera. This avoids translation
parallax and keeps sky geometry out of the track's BSP and frame bounds.
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import numpy as np

from three_do import Model
from gpu_viewer.mesh import make_mesh
from gpu_viewer.scene import build_scene, ordered_scene_indices
from gpu_viewer.textures import build_atlas

SKY_EYE = (0.0, 0.0, 1000.0)


@dataclass
class TrackSkybox:
    path: Path
    model: Model
    mesh: object
    atlas: object
    indices: np.ndarray


def find_track_skybox(track_path, objects_folder=None):
    """Find HORIZ.3DO beside the track or in its configured objects folder.

    Lookup is case insensitive on Linux as well as Windows. Never search
    globally or load an unrelated model's skybox.
    """
    path = Path(track_path)
    folders = (path.parent, path.parent / "objects", objects_folder)
    for folder in folders:
        if folder is None:
            continue
        folder = Path(folder)
        if not folder.is_dir():
            continue
        exact = folder / "horiz.3do"
        if exact.is_file():
            return exact
        for candidate in folder.iterdir():
            if candidate.is_file() and candidate.name.casefold() == "horiz.3do":
                return candidate
    return None


def load_track_skybox(path, palette, *, texture_folder=None):
    """Prepare an independent sky mesh/atlas on the worker, with no GL calls."""
    path = Path(path)
    model = Model(path, associate_planes=False)
    scene = build_scene(model)
    atlas = build_atlas(scene.geometry, path, texture_folder=texture_folder)
    mesh = make_mesh(scene.geometry, palette, atlas)
    # The camera is fixed inside the sky, and the sky is authored as a
    # background enclosure. Do not camera-cull its back-facing wall polygons.
    indices, _, _ = ordered_scene_indices(
        scene, mesh, SKY_EYE, None, bsp_mode="off")
    if indices.size == 0:
        raise ValueError(f"{path.name} contains no renderable skybox polygons")
    return TrackSkybox(path, model, mesh, atlas, indices)


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
