from __future__ import annotations

from dataclasses import dataclass

from PyQt5 import QtGui

from sg_viewer.services import sg_rendering

FENCE_TYPE2 = {2, 6, 10, 14}
SURFACE_TYPES = {0, 1, 2, 3, 4, 5, 6}


@dataclass(frozen=True)
class FSectionStyle:
    role: str
    surface_color: QtGui.QColor | None = None
    boundary_color: QtGui.QColor | None = None
    boundary_width: float | None = None
    is_fence: bool = False


def resolve_fsection_style(
    surface_type: int | None, type2: int | None
) -> FSectionStyle | None:
    if surface_type is None:
        return None
    key = (int(surface_type), int(type2) if type2 is not None else None)
    style = _FSECTION_STYLE_MAP.get(key)
    if style is None:
        style = _FSECTION_STYLE_MAP.get((int(surface_type), None))
    return style


def _build_surface_styles() -> dict[tuple[int, int | None], FSectionStyle]:
    styles: dict[tuple[int, int | None], FSectionStyle] = {}
    for surface_type, color in sg_rendering.SURFACE_COLORS.items():
        if int(surface_type) not in SURFACE_TYPES:
            continue
        styles[(int(surface_type), None)] = FSectionStyle(
            role="surface",
            surface_color=QtGui.QColor(color),
        )
    return styles


def _build_boundary_styles() -> dict[tuple[int, int | None], FSectionStyle]:
    styles: dict[tuple[int, int | None], FSectionStyle] = {}
    for type1, color in ((7, sg_rendering.WALL_COLOR), (8, sg_rendering.ARMCO_COLOR)):
        styles[(type1, None)] = FSectionStyle(
            role="boundary",
            boundary_color=QtGui.QColor(color),
            boundary_width=2.0,
            is_fence=False,
        )
        for fence_type2 in FENCE_TYPE2:
            styles[(type1, fence_type2)] = FSectionStyle(
                role="boundary",
                boundary_color=QtGui.QColor(color),
                boundary_width=2.0,
                is_fence=True,
            )
    return styles


_FSECTION_STYLE_MAP: dict[tuple[int, int | None], FSectionStyle] = {
    **_build_surface_styles(),
    **_build_boundary_styles(),
}
