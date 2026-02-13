from __future__ import annotations

from sg_viewer.rendering.fsection_style_map import FENCE_TYPE2


def fsect_type_options() -> list[tuple[str, int, int]]:
    fence_type = min(FENCE_TYPE2) if FENCE_TYPE2 else 0
    return [
        ("Grass", 0, 0),
        ("Dry grass", 1, 0),
        ("Dirt", 2, 0),
        ("Sand", 3, 0),
        ("Concrete", 4, 0),
        ("Asphalt", 5, 0),
        ("Paint (Curbing)", 6, 0),
        ("Wall", 7, 0),
        ("Wall (Fence)", 7, fence_type),
        ("Armco", 8, 0),
        ("Armco (Fence)", 8, fence_type),
    ]


def fsect_type_index(surface_type: int, type2: int) -> int:
    is_fence = surface_type in {7, 8} and type2 in FENCE_TYPE2
    for index, (_label, option_surface, option_type2) in enumerate(fsect_type_options()):
        option_fence = option_surface in {7, 8} and option_type2 in FENCE_TYPE2
        if option_surface == surface_type and option_fence == is_fence:
            return index
    return 0


def fsect_type_description(surface_type: int, type2: int) -> str:
    ground_map = {
        0: "Grass",
        1: "Dry grass",
        2: "Dirt",
        3: "Sand",
        4: "Concrete",
        5: "Asphalt",
        6: "Paint (Curbing)",
    }
    if surface_type in ground_map:
        return ground_map[surface_type]
    if surface_type in {7, 8}:
        base = "Wall" if surface_type == 7 else "Armco"
        if type2 in FENCE_TYPE2:
            return f"{base} (Fence)"
        return base
    return "Unknown"
