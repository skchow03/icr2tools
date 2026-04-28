from __future__ import annotations

import numpy as np
from scipy.spatial import KDTree
from skimage import color
from skimage.util import img_as_float


class Quantizer:
    def __init__(self, full_palette: np.ndarray) -> None:
        palette = np.asarray(full_palette, dtype=np.uint8)
        if palette.shape != (256, 3):
            raise ValueError("full_palette must be shape (256, 3)")
        self.palette = palette
        palette_lab = color.rgb2lab(img_as_float(palette.reshape(1, 256, 3))).reshape(256, 3)
        self._tree = KDTree(palette_lab)

    def quantize_image(self, rgb_image: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
        rgb = np.asarray(rgb_image, dtype=np.uint8)
        h, w, _ = rgb.shape
        lab = color.rgb2lab(img_as_float(rgb))
        distances, indices = self._tree.query(lab.reshape(-1, 3))
        _ = distances
        indexed = indices.reshape(h, w).astype(np.uint8)
        quantized_rgb = self.palette[indexed]
        return indexed, quantized_rgb.astype(np.uint8)
