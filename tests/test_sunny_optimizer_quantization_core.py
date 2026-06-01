import numpy as np

from sunny_optimizer.model import OPTIMIZED_END, OPTIMIZED_START, SunnyPaletteOptimizer
from sunny_optimizer.quantizer import Quantizer


def _fixed_palette() -> np.ndarray:
    palette = np.zeros((256, 3), dtype=np.uint8)
    palette[:, 0] = np.arange(256, dtype=np.uint8)
    palette[:, 1] = np.arange(255, -1, -1, dtype=np.uint8)
    palette[:, 2] = (np.arange(256, dtype=np.uint16) // 2).astype(np.uint8)
    return palette


def test_compute_palette_shape_and_random_state_determinism() -> None:
    image_a = np.array(
        [
            [[255, 0, 0], [240, 20, 20], [0, 255, 0], [20, 240, 20]],
            [[0, 0, 255], [20, 20, 240], [255, 255, 0], [230, 220, 20]],
        ],
        dtype=np.uint8,
    )
    image_b = np.array(
        [
            [[80, 55, 35], [100, 70, 45], [120, 90, 60], [160, 120, 70]],
            [[10, 10, 10], [80, 80, 80], [180, 180, 180], [240, 240, 240]],
        ],
        dtype=np.uint8,
    )
    fixed = _fixed_palette()

    kwargs = dict(
        rgb_images={"a.png": image_a, "b.png": image_b},
        per_texture_color_budget={"a.png": 4, "b.png": 4},
        fixed_palette=fixed,
        dirt_present=True,
        random_state=123,
    )
    palette_one = SunnyPaletteOptimizer(**kwargs).compute_palette()
    palette_two = SunnyPaletteOptimizer(**kwargs).compute_palette()

    assert palette_one.shape == (256, 3)
    assert palette_one.dtype == np.uint8
    np.testing.assert_array_equal(palette_one, palette_two)
    np.testing.assert_array_equal(
        palette_one[:OPTIMIZED_START], fixed[:OPTIMIZED_START]
    )
    np.testing.assert_array_equal(
        palette_one[OPTIMIZED_END + 1 :], fixed[OPTIMIZED_END + 1 :]
    )


def test_quantize_image_returns_palette_indices_and_is_deterministic() -> None:
    palette = np.zeros((256, 3), dtype=np.uint8)
    palette[1] = np.array([255, 0, 0], dtype=np.uint8)
    palette[2] = np.array([0, 255, 0], dtype=np.uint8)
    palette[3] = np.array([0, 0, 255], dtype=np.uint8)
    image = np.array(
        [
            [[254, 1, 1], [1, 254, 1]],
            [[1, 1, 254], [250, 5, 5]],
        ],
        dtype=np.uint8,
    )

    quantizer = Quantizer(palette)
    indexed_one, quantized_one = quantizer.quantize_image(image)
    indexed_two, quantized_two = quantizer.quantize_image(image)

    assert indexed_one.shape == image.shape[:2]
    assert indexed_one.dtype == np.uint8
    assert int(indexed_one.min()) >= 0
    assert int(indexed_one.max()) <= 255
    np.testing.assert_array_equal(indexed_one, indexed_two)
    np.testing.assert_array_equal(quantized_one, quantized_two)
    np.testing.assert_array_equal(quantized_one, palette[indexed_one])
    np.testing.assert_array_equal(
        indexed_one, np.array([[1, 2], [3, 1]], dtype=np.uint8)
    )


def test_compute_palette_reports_detailed_progress() -> None:
    image = np.array(
        [
            [[255, 0, 0], [240, 20, 20], [0, 255, 0], [20, 240, 20]],
            [[0, 0, 255], [20, 20, 240], [255, 255, 0], [230, 220, 20]],
        ],
        dtype=np.uint8,
    )
    events: list[tuple[str, float]] = []

    optimizer = SunnyPaletteOptimizer(
        rgb_images={"a.png": image},
        per_texture_color_budget={"a.png": 4},
        fixed_palette=_fixed_palette(),
        dirt_present=False,
        random_state=123,
        progress_callback=lambda message, fraction: events.append((message, fraction)),
    )

    optimizer.compute_palette()

    assert len(events) > 4
    assert events[0][0] == "Starting per-texture color clustering"
    assert events[-1] == ("Optimized palette ready", 1.0)
    assert any("Clustering a.png" in message for message, _fraction in events)
    assert all(0.0 <= fraction <= 1.0 for _message, fraction in events)


def test_compute_quantized_images_reports_per_image_progress() -> None:
    image = np.array(
        [
            [[255, 0, 0], [0, 255, 0]],
            [[0, 0, 255], [255, 255, 0]],
        ],
        dtype=np.uint8,
    )
    events: list[tuple[str, float]] = []

    optimizer = SunnyPaletteOptimizer(
        rgb_images={"a.png": image, "b.png": image},
        per_texture_color_budget={"a.png": 2, "b.png": 2},
        fixed_palette=_fixed_palette(),
        dirt_present=False,
        progress_callback=lambda message, fraction: events.append((message, fraction)),
    )

    optimizer.compute_quantized_images(_fixed_palette())

    assert events[0] == ("Quantizing preview a.png (1/2)", 0.0)
    assert events[1] == ("Quantizing preview b.png (2/2)", 0.5)
    assert events[-1] == ("Quantized previews ready", 1.0)
