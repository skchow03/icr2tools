from __future__ import annotations

import numpy as np

_D65 = np.array([0.95047, 1.0, 1.08883], dtype=np.float64)
_EPSILON = 216.0 / 24389.0
_KAPPA = 24389.0 / 27.0


def _rgb_to_unit_float(rgb: np.ndarray) -> np.ndarray:
    arr = np.asarray(rgb)
    if arr.shape[-1] != 3:
        raise ValueError("RGB arrays must have a final dimension of 3")
    if np.issubdtype(arr.dtype, np.floating):
        return np.clip(arr.astype(np.float64, copy=False), 0.0, 1.0)
    return arr.astype(np.float64) / 255.0


def rgb_to_lab(rgb: np.ndarray) -> np.ndarray:
    """Convert sRGB colors to CIE Lab using a D65 reference white."""

    rgb_float = _rgb_to_unit_float(rgb)
    linear = np.where(
        rgb_float > 0.04045,
        ((rgb_float + 0.055) / 1.055) ** 2.4,
        rgb_float / 12.92,
    )

    x = (
        linear[..., 0] * 0.4124564
        + linear[..., 1] * 0.3575761
        + linear[..., 2] * 0.1804375
    )
    y = (
        linear[..., 0] * 0.2126729
        + linear[..., 1] * 0.7151522
        + linear[..., 2] * 0.0721750
    )
    z = (
        linear[..., 0] * 0.0193339
        + linear[..., 1] * 0.1191920
        + linear[..., 2] * 0.9503041
    )
    xyz = np.stack((x, y, z), axis=-1) / _D65

    f = np.where(xyz > _EPSILON, np.cbrt(xyz), (_KAPPA * xyz + 16.0) / 116.0)
    lab = np.empty_like(f)
    lab[..., 0] = 116.0 * f[..., 1] - 16.0
    lab[..., 1] = 500.0 * (f[..., 0] - f[..., 1])
    lab[..., 2] = 200.0 * (f[..., 1] - f[..., 2])
    return lab


def lab_to_rgb_u8(lab: np.ndarray) -> np.ndarray:
    """Convert CIE Lab colors with D65 reference white to uint8 sRGB."""

    lab_arr = np.asarray(lab, dtype=np.float64)
    if lab_arr.shape[-1] != 3:
        raise ValueError("Lab arrays must have a final dimension of 3")

    fy = (lab_arr[..., 0] + 16.0) / 116.0
    fx = fy + lab_arr[..., 1] / 500.0
    fz = fy - lab_arr[..., 2] / 200.0
    f = np.stack((fx, fy, fz), axis=-1)

    f3 = f**3
    xyz_scaled = np.where(f3 > _EPSILON, f3, (116.0 * f - 16.0) / _KAPPA)
    xyz = xyz_scaled * _D65

    r = xyz[..., 0] * 3.2404542 + xyz[..., 1] * -1.5371385 + xyz[..., 2] * -0.4985314
    g = xyz[..., 0] * -0.9692660 + xyz[..., 1] * 1.8760108 + xyz[..., 2] * 0.0415560
    b = xyz[..., 0] * 0.0556434 + xyz[..., 1] * -0.2040259 + xyz[..., 2] * 1.0572252
    linear = np.clip(np.stack((r, g, b), axis=-1), 0.0, 1.0)

    rgb = np.where(
        linear > 0.0031308,
        1.055 * np.power(linear, 1.0 / 2.4) - 0.055,
        12.92 * linear,
    )
    return np.clip(np.round(rgb * 255.0), 0, 255).astype(np.uint8)
