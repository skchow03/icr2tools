import numpy as np

from sunny_optimizer.model import OPTIMIZED_SLOTS, SunnyPaletteOptimizer


def test_reorder_optimized_colors_places_neutrals_first_and_sorted() -> None:
    optimizer = SunnyPaletteOptimizer(
        rgb_images={"a": np.zeros((1, 1, 3), dtype=np.uint8)},
        per_texture_color_budget={"a": 1},
        fixed_palette=np.zeros((256, 3), dtype=np.uint8),
        dirt_present=False,
    )

    neutral_dark = np.array([20, 20, 20], dtype=np.uint8)
    neutral_light = np.array([220, 220, 220], dtype=np.uint8)
    red = np.array([255, 0, 0], dtype=np.uint8)
    blue = np.array([0, 0, 255], dtype=np.uint8)

    colors = np.tile(red, (OPTIMIZED_SLOTS, 1))
    colors[0] = red
    colors[1] = neutral_light
    colors[2] = blue
    colors[3] = neutral_dark

    reordered = optimizer._reorder_optimized_colors(colors)

    np.testing.assert_array_equal(reordered[0], neutral_dark)
    np.testing.assert_array_equal(reordered[1], neutral_light)
