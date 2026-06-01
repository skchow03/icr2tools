from __future__ import annotations

import numpy as np

from .color_utils import rgb_to_lab


class Quantizer:
    def __init__(self, full_palette: np.ndarray) -> None:
        palette = np.asarray(full_palette, dtype=np.uint8)
        if palette.shape != (256, 3):
            raise ValueError("full_palette must be shape (256, 3)")
        self.palette = palette
        self._palette_lab = rgb_to_lab(palette).reshape(256, 3)

    def quantize_image(self, rgb_image: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
        rgb = np.asarray(rgb_image, dtype=np.uint8)
        if rgb.ndim != 3 or rgb.shape[2] != 3:
            raise ValueError("rgb_image must have shape (height, width, 3)")

        h, w, _ = rgb.shape
        lab = rgb_to_lab(rgb).reshape(-1, 3)
        indices = self._nearest_palette_indices(lab)
        indexed = indices.reshape(h, w).astype(np.uint8)
        quantized_rgb = self.palette[indexed]
        return indexed, quantized_rgb.astype(np.uint8)

    def _nearest_palette_indices(
        self, lab_pixels: np.ndarray, chunk_size: int = 16_384
    ) -> np.ndarray:
        nearest = np.empty(lab_pixels.shape[0], dtype=np.uint8)
        palette_lab = self._palette_lab.astype(np.float64, copy=False)
        for start in range(0, lab_pixels.shape[0], chunk_size):
            chunk = lab_pixels[start : start + chunk_size].astype(
                np.float64, copy=False
            )
            diff = chunk[:, None, :] - palette_lab[None, :, :]
            distances = np.einsum("ijk,ijk->ij", diff, diff, optimize=True)
            nearest[start : start + chunk.shape[0]] = np.argmin(
                distances, axis=1
            ).astype(np.uint8)
        return nearest
