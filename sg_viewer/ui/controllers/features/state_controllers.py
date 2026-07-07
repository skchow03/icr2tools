from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING, TypeAlias

from PyQt5 import QtCore, QtGui, QtWidgets

from sg_viewer.replacecolors import DEFAULT_TRACK3D_COLORS
from sg_viewer.services.skid_marks import DEFAULT_SKID_COLORS
from sg_viewer.services.trackside_objects import TracksideObject
from sg_viewer.ui.models.tsd_lines_model import TsdLinesTableModel

if TYPE_CHECKING:
    from sg_viewer.services.tsd_io import TrackSurfaceDetailLine
    from sg_viewer.ui.manual_wall_height_dialog import ManualWallHeightOverride
    from sg_viewer.ui.mrk_textures_dialog import MrkTextureDefinition
    from sg_viewer.ui.viewer_controller import LoadedTsdFile
    from sg_viewer.services.tsd_objects import (
        TsdDashedLinesObject,
        TsdDoubleSolidLineObject,
        TsdPitStallsObject,
        TsdTransverseLineObject,
        TsdZebraCrossingObject,
    )


if TYPE_CHECKING:
    TsdObject: TypeAlias = (
        TsdZebraCrossingObject
        | TsdTransverseLineObject
        | TsdDoubleSolidLineObject
        | TsdDashedLinesObject
        | TsdPitStallsObject
    )
else:
    TsdObject: TypeAlias = object


@dataclass
class MrkFeatureState:
    """Mutable MRK feature state shared by legacy viewer-controller methods."""

    texture_definitions: tuple["MrkTextureDefinition", ...] = ()
    is_dirty: bool = False
    manual_wall_height_overrides: list["ManualWallHeightOverride"] = field(default_factory=list)


@dataclass
class TsdFeatureState:
    """Mutable TSD feature state and UI model/timer wiring."""

    window: QtWidgets.QMainWindow
    loaded_files: list["LoadedTsdFile"] = field(default_factory=list)
    objects: list[TsdObject] = field(default_factory=list)
    is_dirty: bool = False
    object_dialog_preview_object: TsdObject | None = None
    editing_object_index: int | None = None
    active_file_index: int | None = None
    suspend_preview_refresh: bool = False
    debug_perf: bool = False
    last_preview_lines: list["TrackSurfaceDetailLine"] = field(default_factory=list)
    last_adjusted_to_sg_ranges: tuple[list[tuple[float, float, float, float]], list[float]] = field(
        default_factory=lambda: ([], [])
    )
    lines_model: TsdLinesTableModel = field(init=False)
    preview_refresh_timer: QtCore.QTimer = field(init=False)

    def __post_init__(self) -> None:
        self.lines_model = TsdLinesTableModel(self.window)
        self.window.tsd_lines_table.setModel(self.lines_model)
        self.preview_refresh_timer = QtCore.QTimer(self.window)
        self.preview_refresh_timer.setSingleShot(True)
        self.preview_refresh_timer.setInterval(60)


@dataclass
class TsoFeatureState:
    """Mutable trackside-object feature state and timers."""

    window: QtWidgets.QMainWindow
    trackside_objects: list[TracksideObject] = field(default_factory=list)
    selected_trackside_object_indices: list[int] = field(default_factory=list)
    objects_tab_selected_trackside_object_indices: list[int] = field(default_factory=list)
    add_mode_active: bool = False
    stamp_mode_active: bool = False
    box_select_mode_active: bool = False
    stamp_filename: str | None = None
    auto_update_relative_z: bool = False
    persist_timer: QtCore.QTimer = field(init=False)
    visibility_sidebar_dirty: bool = False
    visibility_sidebar_refresh_pending: bool = False

    def __post_init__(self) -> None:
        self.persist_timer = QtCore.QTimer(self.window)
        self.persist_timer.setSingleShot(True)
        self.persist_timer.setInterval(750)


@dataclass
class Track3dPaletteFeatureState:
    """Mutable selected TRACK3D and palette/color-replacement state."""

    selected_track3d_path: Path | None = None
    track3d_colors: dict[str, int] = field(default_factory=lambda: dict(DEFAULT_TRACK3D_COLORS))
    sunny_palette: list[QtGui.QColor] | None = None
    sunny_palette_path: Path | None = None
    palette_colors_dialog: QtWidgets.QDialog | None = None
    skid_marks_dialog: QtWidgets.QDialog | None = None
    generated_skid_mark_lines: tuple["TrackSurfaceDetailLine", ...] = ()
    skid_marks_rows_text: str = ""
    skid_marks_colors: tuple[int, ...] = DEFAULT_SKID_COLORS
