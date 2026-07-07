from __future__ import annotations


def normalize_mrk_side(value: str) -> str:
    normalized = value.strip().lower()
    if normalized == "right":
        return "Right"
    return "Left"


def auto_detect_mrk_side(model: object, section_index: int, boundary_index: int) -> str:
    if model is None or section_index < 0 or section_index >= len(model.fsects):
        return "Left"
    fsect = model.fsects[section_index]
    if boundary_index < 0 or boundary_index >= len(fsect.boundaries):
        return "Left"
    boundary = fsect.boundaries[boundary_index]
    start = boundary.attrs.get("dlat_start")
    end = boundary.attrs.get("dlat_end")
    if start is not None and end is not None:
        mean_dlat = (float(start) + float(end)) * 0.5
        if mean_dlat < 0:
            return "Right"
        if mean_dlat > 0:
            return "Left"
    return "Left"


def mrk_target_length_for_surface_type(surface_type: int, *, length_multiplier: float, armco_height_500ths: float, wall_height_500ths: float) -> float:
    multiplier = max(0.1, float(length_multiplier))
    if surface_type == 8:
        return max(1.0, float(armco_height_500ths) * multiplier)
    return max(1.0, float(wall_height_500ths) * multiplier)
