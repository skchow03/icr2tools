from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Dict

import numpy as np
from sklearn.cluster import KMeans
from skimage import color
from skimage.util import img_as_float

from .quantizer import Quantizer
from .palette import load_sunny_palette, save_palette

OPTIMIZED_START = 176
OPTIMIZED_END = 243
OPTIMIZED_SLOTS = OPTIMIZED_END - OPTIMIZED_START + 1
BROWN_BASE_INDEX = 244
BROWN_DARK_INDEX = 245


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
        rgb_float = img_as_float(rgb.astype(np.uint8))
        return color.rgb2lab(rgb_float)

    @staticmethod
    def _lab_to_rgb_u8(lab: np.ndarray) -> np.ndarray:
        rgb = color.lab2rgb(lab)
        rgb = np.clip(np.round(rgb * 255.0), 0, 255)
        return rgb.astype(np.uint8)

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
            kmeans = KMeans(n_clusters=budget, n_init=5, random_state=self.random_state)
            kmeans.fit(sampled_lab)
            all_centroids.append(kmeans.cluster_centers_)
        if not all_centroids:
            raise ValueError("No textures available for optimization")
        return np.vstack(all_centroids)

    def _final_optimized_lab(self, centroids: np.ndarray) -> np.ndarray:
        n_clusters = min(OPTIMIZED_SLOTS, centroids.shape[0])
        kmeans = KMeans(n_clusters=n_clusters, n_init=8, random_state=self.random_state)
        kmeans.fit(centroids)
        final_centers = kmeans.cluster_centers_
        if n_clusters < OPTIMIZED_SLOTS:
            repeats = np.tile(final_centers[-1:], (OPTIMIZED_SLOTS - n_clusters, 1))
            final_centers = np.vstack([final_centers, repeats])
        return final_centers[:OPTIMIZED_SLOTS]

    def _compute_brown_pair(self) -> tuple[np.ndarray, np.ndarray]:
        candidates: list[np.ndarray] = []
        for image in self.rgb_images.values():
            flat = image.reshape(-1, 3)
            mask = (flat[:, 0] > flat[:, 1]) & (flat[:, 1] > flat[:, 2]) & (flat[:, 0] < 200)
            filtered = flat[mask]
            if filtered.size:
                candidates.append(filtered)
        if candidates:
            pixels = np.vstack(candidates)
            if pixels.shape[0] > self.max_texture_samples:
                rng = np.random.default_rng(self.random_state)
                idx = rng.choice(pixels.shape[0], size=self.max_texture_samples, replace=False)
                pixels = pixels[idx]
            lab_pixels = self._rgb_to_lab(pixels.reshape(-1, 1, 3)).reshape(-1, 3)
            kmeans = KMeans(n_clusters=1, n_init=5, random_state=self.random_state)
            kmeans.fit(lab_pixels)
            base_lab = kmeans.cluster_centers_[0]
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
        centroids = self._stage1_centroids()
        optimized_lab = self._final_optimized_lab(centroids)
        optimized_rgb = self._lab_to_rgb_u8(optimized_lab)

        palette[OPTIMIZED_START : OPTIMIZED_END + 1] = optimized_rgb
        if self.dirt_present:
            brown_base, brown_dark = self._compute_brown_pair()
            palette[BROWN_BASE_INDEX] = brown_base
            palette[BROWN_DARK_INDEX] = brown_dark
        return palette

    def compute_quantized_images(self, full_palette: np.ndarray | None = None) -> tuple[dict[str, np.ndarray], dict[str, np.ndarray]]:
        palette = np.asarray(full_palette if full_palette is not None else self.compute_palette(), dtype=np.uint8)
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
    parser.add_argument("output_palette", type=Path, nargs="?", default=Path("sunny_optimized.pcx"))
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
