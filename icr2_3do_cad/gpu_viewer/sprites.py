"""CPU-side, read-only PMP/PMP2 preparation for the GPU viewer.

PMP files contain palette indices and missing-span transparency. Decode with
the same validated CPU sprite reader, but store index/alpha (not palette RGB)
so changing the PCX palette recolors the sprites without reloading them.
The Qt/OpenGL context is never accessed from this module or its load worker.
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from math import hypot
import numpy as np

from dynamic_scene import ExternalResolver
from pmp_preview import load_pmp, PMPError


# A grayscale identity palette lets us reuse the CPU's validated PMP decoder
# without baking any particular PCX palette into the GPU sprite textures.
_INDEX_PALETTE = tuple((i, i, i) for i in range(256))


@dataclass(frozen=True)
class SpritePlacement:
    instance_id: int
    offset: int
    image_key: str
    xyz: tuple[float, float, float]
    size: float
    bounds: tuple[int, int, int, int]

    @property
    def normalized_pixel_size(self):
        x0, y0, x1, y1 = self.bounds
        return abs(self.size) / max(1, x1 - x0, y1 - y0)


@dataclass
class SpriteResources:
    # Each RG8 image stores 8-bit palette index and 8-bit alpha, both cropped.
    images: dict[str, np.ndarray]
    placements: dict[tuple[int, int], SpritePlacement]
    bounds_points: tuple[tuple[float, float, float], ...]
    warnings: tuple[str, ...]

    @property
    def decoded_bytes(self):
        return sum(image.nbytes for image in self.images.values())


def prepare_scene_sprites(scene, *, objects_folder=None, texture_folder=None,
                          max_images=2048, max_bytes=32 * 1024 * 1024):
    """Resolve every loaded 3DO instance's PMP/PMP2 variants, active or not.

    BSP selects a sprite per camera angle later, without reloading files.
    One path is decoded once and shared by all instances; every occurrence
    retains its own transformed world-space anchor and size.
    """
    resolver = ExternalResolver(objects_folder)
    extra_dirs = ((texture_folder,) if texture_folder is not None else ())
    images = {}
    placements = {}
    warnings = []
    bounds_points = []
    for instance_id, instance in enumerate(scene.instances):
        for offset, sprite in instance.model.pmp_sprites.items():
            vertex = instance.model.vertices.get(sprite.vertex_ref)
            if vertex is None:
                warnings.append(
                    f"{instance.model.path.name}: PMP @{offset} missing anchor vertex")
                continue
            location = resolver.find(
                sprite.name, instance.model.path, extra_dirs=extra_dirs,
                extension=".pmp")
            if location is None:
                warnings.append(
                    f"{instance.model.path.name}: missing {sprite.name}.pmp")
                continue
            key = str(location.resolve()).casefold()
            if key not in images:
                if len(images) >= max_images:
                    warnings.append(
                        f"PMP budget exceeded: maximum {max_images} unique images")
                    continue
                try:
                    decoded = load_pmp(location, _INDEX_PALETTE)
                    rgba = np.asarray(decoded.rgba, dtype=np.uint8)
                    image = np.ascontiguousarray(
                        np.stack((rgba[:, :, 0], rgba[:, :, 3]), axis=-1))
                    if (sum(x.nbytes for x in images.values()) + image.nbytes >
                            max_bytes):
                        warnings.append(
                            f"{location.name}: PMP memory budget exceeded")
                        continue
                    images[key] = (image, decoded.bounds)
                except (OSError, PMPError, ValueError) as exc:
                    warnings.append(f"{location.name}: {exc}")
                    continue
            image, bounds = images[key]
            origin = tuple(map(float, instance.transform.apply(vertex.xyz)))
            item = SpritePlacement(
                instance_id, offset, key, origin, float(sprite.size), bounds)
            placements[instance_id, offset] = item
            # Include the sprite billboard's approximate spherical extent in
            # Frame All / mesh normalization, even if the 3DO has no polygons.
            # CPU preview interprets size as the cropped bitmap's width/height.
            px = item.normalized_pixel_size
            x0, y0, x1, y1 = bounds
            radius = max(
                hypot(x - 128, y - 128) * px
                for x in (x0, x1) for y in (y0, y1))
            for sign in (-1.0, 1.0):
                bounds_points.append(
                    tuple(float(v + sign * radius) for v in origin))

    return SpriteResources(
        {key: img for key, (img, _) in images.items()},
        placements, tuple(bounds_points),
        tuple(dict.fromkeys(warnings)))


def draw_runs(indices_count, sprite_events):
    """Partition a single EBO into painter-ordered polygon/sprite commands.

    Sprite event positions are *element index* counts into the same GPU EBO
    used before PMP support. No vertex repacking or BSP rule changes needed.
    """
    last = 0
    commands = []
    for index_pos, key in sprite_events:
        if not last <= index_pos <= indices_count:
            raise ValueError("PMP insertion index outside GPU polygon buffer")
        if index_pos > last:
            commands.append(("polygons", last, index_pos - last))
        commands.append(("pmp", key))
        last = index_pos
    if last < indices_count:
        commands.append(("polygons", last, indices_count - last))
    return commands
