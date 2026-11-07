"""CPU-side, read-only PMP/PMP2 preparation for the 3DO CAD.

PMP files contain palette indices and missing-span transparency. Decode with
the same validated CPU sprite reader, but store index/alpha (not palette RGB)
so changing the PCX palette recolors the sprites without reloading them.
The Qt/OpenGL context is never accessed from this module or its load worker.
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from math import hypot
from hashlib import blake2s
import numpy as np

from car import recolor_index
from dynamic_scene import ExternalResolver
from pmp_preview import load_pmp, PMPError


# A grayscale identity palette lets us reuse the CPU's validated PMP decoder
# without baking any particular PCX palette into the GPU sprite textures.
_INDEX_PALETTE = tuple((i, i, i) for i in range(256))

# PMP/PMP2 placements use the original 256x256 canvas coordinate frame,
# even though transparency is cropped out when uploading the GPU image.
# The 3DO anchor is at original source row 127, not the visible sprite's
# midpoint. This convention is independent of which rows contain pixels.
PMP_ANCHOR_ROW = 127.0
_IDENTITY_PALETTE = np.arange(256, dtype=np.uint8)


def _recolor_lut(layers):
    """Resolve an instance's car palette remap without changing its PMP asset."""
    if not layers:
        return None
    lookup = np.fromiter(
        (recolor_index(index, layers) for index in range(256)),
        dtype=np.uint8, count=256)
    return None if np.array_equal(lookup, _IDENTITY_PALETTE) else lookup


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
                          max_images=2048, max_bytes=32 * 1024 * 1024,
                          on_activity=None):
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
    if on_activity:
        on_activity(f"Searching PMP/PMP2 records in {len(scene.instances):,} instances")
    for instance_id, instance in enumerate(scene.instances):
        if on_activity and instance_id % 100 == 0:
            on_activity(f"PMP scan: instance {instance_id + 1}/{len(scene.instances)} "
                        f"({instance.model.path.name})")
        # PMPs are indexed colors just like polygon palette slots. Keep
        # original files and the common palette texture unchanged; prepare
        # a separate GPU index image for each distinct driver appearance.
        lookup = _recolor_lut(instance.sprite_recolor_layers)
        suffix = ("#recolor-" + blake2s(lookup.tobytes(), digest_size=12).hexdigest()
                  if lookup is not None else "")
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
            key = str(location.resolve()).casefold() + suffix
            if key not in images:
                if len(images) >= max_images:
                    warnings.append(
                        f"PMP budget exceeded: maximum {max_images} unique images")
                    continue
                try:
                    if on_activity:
                        on_activity(f"Decoding sprite: {location.name} [{location}]")
                    decoded = load_pmp(location, _INDEX_PALETTE)
                    rgba = np.asarray(decoded.rgba, dtype=np.uint8)
                    image = np.ascontiguousarray(
                        np.stack((rgba[:, :, 0], rgba[:, :, 3]), axis=-1))
                    if lookup is not None:
                        # Transform palette *indices*, never RGB or alpha.
                        # Each helmet angle uses the same driver mapping.
                        image[:, :, 0] = lookup[image[:, :, 0]]
                    if (sum(data.nbytes for data, _ in images.values()) +
                            image.nbytes > max_bytes):
                        warnings.append(
                            f"{location.name}: PMP memory budget exceeded")
                        continue
                    images[key] = (image, decoded.bounds)
                    if on_activity:
                        on_activity(f"Sprite decoded: {location.name} "
                                    f"({image.shape[1]}x{image.shape[0]})")
                except (OSError, PMPError, ValueError) as exc:
                    if on_activity:
                        on_activity(f"Sprite failed: {location.name}: {exc}")
                    warnings.append(f"{location.name}: {exc}")
                    continue
            image, bounds = images[key]
            origin = tuple(map(float, instance.transform.apply(vertex.xyz)))
            item = SpritePlacement(
                instance_id, offset, key, origin, float(sprite.size), bounds)
            placements[instance_id, offset] = item
            # Include the sprite billboard's approximate spherical extent in
            # Frame All / mesh normalization, even if the 3DO has no polygons.
            # Size remains measured against the cropped sprite bounds, but
            # the origin for those bounds is always source-canvas row 127.
            px = item.normalized_pixel_size
            x0, y0, x1, y1 = bounds
            radius = max(
                hypot(x - 128, y - PMP_ANCHOR_ROW) * px
                for x in (x0, x1) for y in (y0, y1))
            for sign in (-1.0, 1.0):
                bounds_points.append(
                    tuple(float(v + sign * radius) for v in origin))

    if on_activity:
        on_activity(f"PMP scan finished: {len(images)} images, "
                    f"{len(placements)} placements, {len(warnings)} warnings")
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
