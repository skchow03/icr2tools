from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Dict

import numpy as np
from .color_utils import lab_to_rgb_u8, rgb_to_lab
from .quantizer import Quantizer
from .palette import load_sunny_palette, save_palette

OPTIMIZED_START = 176
OPTIMIZED_END = 245
OPTIMIZED_SLOTS = OPTIMIZED_END - OPTIMIZED_START + 1
BROWN_BASE_INDEX = 244
BROWN_DARK_INDEX = 245


def _nearest_centroid_indices(
    samples: np.ndarray, centers: np.ndarray, chunk_size: int = 16_384
) -> np.ndarray:
    labels = np.empty(samples.shape[0], dtype=np.intp)
    for start in range(0, samples.shape[0], chunk_size):
        chunk = samples[start : start + chunk_size]
        diff = chunk[:, None, :] - centers[None, :, :]
        distances = np.einsum("ijk,ijk->ij", diff, diff, optimize=True)
        labels[start : start + chunk.shape[0]] = np.argmin(distances, axis=1)
    return labels


def _initial_centers_kmeans_plus_plus(
    samples: np.ndarray, n_clusters: int, rng: np.random.Generator
) -> np.ndarray:
    centers = np.empty((n_clusters, samples.shape[1]), dtype=np.float64)
    first = int(rng.integers(samples.shape[0]))
    centers[0] = samples[first]
    closest_dist_sq = np.sum((samples - centers[0]) ** 2, axis=1)

    for i in range(1, n_clusters):
        total = float(np.sum(closest_dist_sq))
        if total <= 0.0:
            centers[i:] = centers[i - 1]
            break
        next_idx = int(rng.choice(samples.shape[0], p=closest_dist_sq / total))
        centers[i] = samples[next_idx]
        new_dist_sq = np.sum((samples - centers[i]) ** 2, axis=1)
        closest_dist_sq = np.minimum(closest_dist_sq, new_dist_sq)
    return centers


def _kmeans(
    samples: np.ndarray,
    n_clusters: int,
    *,
    n_init: int,
    random_state: int,
    max_iter: int = 100,
) -> np.ndarray:
    samples = np.asarray(samples, dtype=np.float64)
    if samples.ndim != 2 or samples.shape[1] != 3:
        raise ValueError("samples must have shape (n_samples, 3)")
    if n_clusters < 1:
        raise ValueError("n_clusters must be at least 1")
    if samples.shape[0] < n_clusters:
        raise ValueError("n_clusters cannot exceed the number of samples")
    if n_clusters == 1:
        return np.mean(samples, axis=0, keepdims=True)

    best_centers: np.ndarray | None = None
    best_inertia = np.inf
    seed_sequence = np.random.SeedSequence(random_state)

    for child_seed in seed_sequence.spawn(max(1, n_init)):
        rng = np.random.default_rng(child_seed)
        centers = _initial_centers_kmeans_plus_plus(samples, n_clusters, rng)
        labels = np.zeros(samples.shape[0], dtype=np.intp)

        for _ in range(max_iter):
            labels = _nearest_centroid_indices(samples, centers)
            new_centers = centers.copy()
            for cluster in range(n_clusters):
                members = samples[labels == cluster]
                if members.size:
                    new_centers[cluster] = np.mean(members, axis=0)
                else:
                    distances = np.sum((samples - centers[labels]) ** 2, axis=1)
                    new_centers[cluster] = samples[int(np.argmax(distances))]
            if np.allclose(new_centers, centers, rtol=1e-5, atol=1e-5):
                centers = new_centers
                break
            centers = new_centers

        labels = _nearest_centroid_indices(samples, centers)
        inertia = float(np.sum((samples - centers[labels]) ** 2))
        if inertia < best_inertia:
            best_inertia = inertia
            best_centers = centers.copy()

    if best_centers is None:
        raise RuntimeError("k-means failed to initialize")
    return best_centers


def optimized_slot_count(dirt_present: bool) -> int:
    return OPTIMIZED_SLOTS - 2 if dirt_present else OPTIMIZED_SLOTS


@dataclass
class OptimizationResult:
    palette: np.ndarray
    indexed_images: dict[str, np.ndarray]
    quantized_images: dict[str, np.ndarray]


class SunnyPaletteOptimizer:
    def __init__(
        self,
        rgb_images: Dict[str, np.ndarray],
        per_texture_color_budget: Dict[str, int],
        fixed_palette: np.ndarray,
        dirt_present: bool,
        *,
        random_state: int = 7,
        max_texture_samples: int = 50_000,
    ) -> None:
        self.rgb_images = rgb_images
        self.per_texture_color_budget = per_texture_color_budget
        self.fixed_palette = np.asarray(fixed_palette, dtype=np.uint8)
        self.dirt_present = dirt_present
        self.random_state = random_state
        self.max_texture_samples = max_texture_samples

        if self.fixed_palette.shape != (256, 3):
            raise ValueError("fixed_palette must have shape (256, 3)")

    @staticmethod
    def _rgb_to_lab(rgb: np.ndarray) -> np.ndarray:
        return rgb_to_lab(rgb.astype(np.uint8))

    @staticmethod
    def _lab_to_rgb_u8(lab: np.ndarray) -> np.ndarray:
        return lab_to_rgb_u8(lab)

    def _sample_pixels(self, rgb_image: np.ndarray) -> np.ndarray:
        flat = rgb_image.reshape(-1, 3)
        if flat.shape[0] <= self.max_texture_samples:
            return flat
        rng = np.random.default_rng(self.random_state)
        idx = rng.choice(flat.shape[0], size=self.max_texture_samples, replace=False)
        return flat[idx]

    def _stage1_centroids(self) -> np.ndarray:
        all_centroids: list[np.ndarray] = []
        for name, image in self.rgb_images.items():
            budget = max(1, int(self.per_texture_color_budget.get(name, 1)))
            sampled_rgb = self._sample_pixels(image)
            sampled_lab = self._rgb_to_lab(sampled_rgb.reshape(-1, 1, 3)).reshape(-1, 3)
            if sampled_lab.shape[0] < budget:
                budget = sampled_lab.shape[0]
            all_centroids.append(
                _kmeans(sampled_lab, budget, n_init=5, random_state=self.random_state)
            )
        if not all_centroids:
            raise ValueError("No textures available for optimization")
        return np.vstack(all_centroids)

    def _final_optimized_lab(
        self, centroids: np.ndarray, slot_count: int
    ) -> np.ndarray:
        n_clusters = min(slot_count, centroids.shape[0])
        final_centers = _kmeans(
            centroids, n_clusters, n_init=8, random_state=self.random_state
        )
        if n_clusters < slot_count:
            repeats = np.tile(final_centers[-1:], (slot_count - n_clusters, 1))
            final_centers = np.vstack([final_centers, repeats])
        return final_centers[:slot_count]

    def _reorder_optimized_colors(
        self, optimized_rgb: np.ndarray, slot_count: int
    ) -> np.ndarray:
        """Sort optimized colors into a more coherent progression.

        Neutrals are grouped first by lightness; chromatic colors are grouped by hue,
        then by lightness.
        """
        if optimized_rgb.shape != (slot_count, 3):
            raise ValueError("optimized_rgb must have shape (slot_count, 3)")

        lab = self._rgb_to_lab(optimized_rgb.reshape(-1, 1, 3)).reshape(-1, 3)
        chroma = np.hypot(lab[:, 1], lab[:, 2])
        hue = (np.degrees(np.arctan2(lab[:, 2], lab[:, 1])) + 360.0) % 360.0
        lightness = lab[:, 0]

        neutral_mask = chroma < 8.0
        neutral_idx = np.where(neutral_mask)[0]
        chromatic_idx = np.where(~neutral_mask)[0]

        neutral_order = neutral_idx[np.argsort(lightness[neutral_idx], kind="stable")]
        chromatic_order = chromatic_idx[
            np.lexsort((lightness[chromatic_idx], hue[chromatic_idx]))
        ]
        order = np.concatenate([neutral_order, chromatic_order])
        return optimized_rgb[order]

    def _compute_brown_pair(self) -> tuple[np.ndarray, np.ndarray]:
        candidates: list[np.ndarray] = []
        for image in self.rgb_images.values():
            flat = image.reshape(-1, 3)
            mask = (
                (flat[:, 0] > flat[:, 1])
                & (flat[:, 1] > flat[:, 2])
                & (flat[:, 0] < 200)
            )
            filtered = flat[mask]
            if filtered.size:
                candidates.append(filtered)
        if candidates:
            pixels = np.vstack(candidates)
            if pixels.shape[0] > self.max_texture_samples:
                rng = np.random.default_rng(self.random_state)
                idx = rng.choice(
                    pixels.shape[0], size=self.max_texture_samples, replace=False
                )
                pixels = pixels[idx]
            lab_pixels = self._rgb_to_lab(pixels.reshape(-1, 1, 3)).reshape(-1, 3)
            base_lab = _kmeans(lab_pixels, 1, n_init=5, random_state=self.random_state)[
                0
            ]
        else:
            fallback = np.array([[120, 90, 55]], dtype=np.uint8)
            base_lab = self._rgb_to_lab(fallback.reshape(-1, 1, 3)).reshape(-1, 3)[0]

        dark_lab = base_lab.copy()
        dark_lab[0] = max(0.0, dark_lab[0] - 15.0)

        base_rgb = self._lab_to_rgb_u8(base_lab.reshape(1, 3))[0]
        dark_rgb = self._lab_to_rgb_u8(dark_lab.reshape(1, 3))[0]
        return base_rgb, dark_rgb

    def compute_palette(self) -> np.ndarray:
        palette = self.fixed_palette.copy()
        slot_count = optimized_slot_count(self.dirt_present)
        optimized_end = OPTIMIZED_START + slot_count - 1
        centroids = self._stage1_centroids()
        optimized_lab = self._final_optimized_lab(centroids, slot_count)
        optimized_rgb = self._lab_to_rgb_u8(optimized_lab)
        optimized_rgb = self._reorder_optimized_colors(optimized_rgb, slot_count)

        palette[OPTIMIZED_START : optimized_end + 1] = optimized_rgb
        if self.dirt_present:
            brown_base, brown_dark = self._compute_brown_pair()
            palette[BROWN_BASE_INDEX] = brown_base
            palette[BROWN_DARK_INDEX] = brown_dark
        return palette

    def compute_quantized_images(
        self, full_palette: np.ndarray | None = None
    ) -> tuple[dict[str, np.ndarray], dict[str, np.ndarray]]:
        palette = np.asarray(
            full_palette if full_palette is not None else self.compute_palette(),
            dtype=np.uint8,
        )
        quantizer = Quantizer(palette)
        indexed: dict[str, np.ndarray] = {}
        quantized: dict[str, np.ndarray] = {}
        for name, image in self.rgb_images.items():
            indexed_img, quantized_img = quantizer.quantize_image(image)
            indexed[name] = indexed_img
            quantized[name] = quantized_img
        return indexed, quantized


def _load_images_from_folder(folder: Path, max_dim: int = 512) -> dict[str, np.ndarray]:
    from PIL import Image

    images: dict[str, np.ndarray] = {}
    for path in sorted(folder.iterdir()):
        if path.suffix.lower() not in {".png", ".jpg", ".jpeg", ".bmp"}:
            continue
        with Image.open(path) as img:
            img = img.convert("RGB")
            img.thumbnail((max_dim, max_dim), Image.Resampling.LANCZOS)
            images[path.name] = np.asarray(img, dtype=np.uint8)
    return images


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="Prototype SUNNY palette optimizer")
    parser.add_argument("image_folder", type=Path)
    parser.add_argument("input_palette", type=Path, help="Path to existing sunny.pcx")
    parser.add_argument(
        "output_palette", type=Path, nargs="?", default=Path("sunny_optimized.pcx")
    )
    parser.add_argument("--dirt-present", action="store_true")
    args = parser.parse_args()

    images = _load_images_from_folder(args.image_folder)
    if not images:
        raise SystemExit("No input images found")

    budget = max(1, OPTIMIZED_SLOTS // len(images))
    budgets = {name: budget for name in images}

    fixed_palette = load_sunny_palette(args.input_palette)
    optimizer = SunnyPaletteOptimizer(images, budgets, fixed_palette, args.dirt_present)
    optimized_palette = optimizer.compute_palette()
    save_palette(args.output_palette, optimized_palette)

    print(f"Loaded {len(images)} textures")
    print(f"Wrote optimized palette to {args.output_palette}")
