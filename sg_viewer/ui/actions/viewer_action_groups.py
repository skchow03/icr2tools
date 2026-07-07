from __future__ import annotations

from dataclasses import dataclass
from typing import Callable

from PyQt5 import QtWidgets

Callback = Callable[[], None]


def _action(text: str, parent: QtWidgets.QWidget, callback: Callback | None = None, shortcut: str | None = None, enabled: bool | None = None) -> QtWidgets.QAction:
    action = QtWidgets.QAction(text, parent)
    if shortcut is not None:
        action.setShortcut(shortcut)
    if enabled is not None:
        action.setEnabled(enabled)
    if callback is not None:
        action.triggered.connect(callback)
    return action


@dataclass(frozen=True)
class FileActions:
    parent: QtWidgets.QWidget
    start_new_track: Callback
    import_sg_file_dialog: Callback
    open_project_file_dialog: Callback
    load_sunny_palette_dialog: Callback
    import_trk_file_dialog: Callback
    import_trk_from_dat_file_dialog: Callback
    save_current_file: Callback
    save_project_file_dialog: Callback
    save_file_dialog: Callback
    convert_sg_to_trk: Callback
    export_current_sg_to_csv: Callback
    close_window: Callback

    def __post_init__(self) -> None:
        object.__setattr__(self, "new_action", _action("New Project", self.parent, self.start_new_track, "Ctrl+N"))
        object.__setattr__(self, "import_sg_action", _action("Import .SG…", self.parent, self.import_sg_file_dialog, "Ctrl+O"))
        object.__setattr__(self, "open_project_action", _action("Open Project…", self.parent, self.open_project_file_dialog))
        object.__setattr__(self, "load_sunny_palette_action", _action("Import SUNNY.PCX…", self.parent, self.load_sunny_palette_dialog))
        object.__setattr__(self, "import_trk_action", _action("Import TRK…", self.parent, self.import_trk_file_dialog))
        object.__setattr__(self, "import_trk_from_dat_action", _action("Import TRK from DAT…", self.parent, self.import_trk_from_dat_file_dialog))
        object.__setattr__(self, "open_recent_menu", QtWidgets.QMenu("Open Recent", self.parent))
        object.__setattr__(self, "save_current_action", _action("Save Project", self.parent, self.save_current_file, "Ctrl+S", False))
        object.__setattr__(self, "save_action", _action("Save Project As…", self.parent, self.save_project_file_dialog, "Ctrl+Shift+S", True))
        object.__setattr__(self, "save_project_action", _action("Export to SG file…", self.parent, self.save_file_dialog))
        object.__setattr__(self, "convert_trk_action", _action("Export to TRK…", self.parent, self.convert_sg_to_trk))
        object.__setattr__(self, "export_csv_action", _action("Export .SG data to .CSV", self.parent, self.export_current_sg_to_csv))
        object.__setattr__(self, "quit_action", _action("Quit", self.parent, self.close_window, "Ctrl+Q"))


@dataclass(frozen=True)
class ViewActions:
    parent: QtWidgets.QWidget
    open_background_file_dialog: Callback
    show_background_settings_dialog: Callback
    show_view_options_dialog: Callback
    choose_project_working_folder: Callback
    clear_project_working_folder: Callback
    show_track_section_dlongs_dialog: Callback

    def __post_init__(self) -> None:
        object.__setattr__(self, "open_background_action", _action("Load Background Image…", self.parent, self.open_background_file_dialog, "Ctrl+B"))
        object.__setattr__(self, "background_settings_action", _action("Background Image Settings…", self.parent, self.show_background_settings_dialog, enabled=False))
        object.__setattr__(self, "view_options_action", _action("View Options…", self.parent, self.show_view_options_dialog))
        object.__setattr__(self, "set_project_working_folder_action", _action("Set Project Working Folder…", self.parent, self.choose_project_working_folder))
        object.__setattr__(self, "clear_project_working_folder_action", _action("Clear Project Working Folder", self.parent, self.clear_project_working_folder, enabled=False))
        object.__setattr__(self, "show_section_dlongs_action", _action("Track Section DLONGs…", self.parent, self.show_track_section_dlongs_dialog))
        for attr, text, checked in (
            ("show_radii_action", "Show Radii", self.parent.radii_button.isChecked()),
            ("show_axes_action", "Show Axes", self.parent.axes_button.isChecked()),
            ("show_crosshair_action", "Show Crosshair", self.parent.crosshair_button.isChecked()),
            ("show_background_image_action", "Show Background Image", self.parent.background_image_checkbox.isChecked()),
        ):
            act = _action(text, self.parent)
            act.setCheckable(True)
            act.setChecked(checked)
            object.__setattr__(self, attr, act)


@dataclass(frozen=True)
class SectionEditingActions:
    parent: QtWidgets.QWidget
    scale_track: Callback
    open_rotate_track_dialog: Callback
    reverse_track: Callback
    show_section_table: Callback
    show_heading_table: Callback
    show_xsect_table: Callback

    def __post_init__(self) -> None:
        for attr, text, shortcut, button in (
            ("previous_section_action", "Previous Section", "Ctrl+PgUp", self.parent.prev_button),
            ("next_section_action", "Next Section", "Ctrl+PgDown", self.parent.next_button),
            ("new_straight_mode_action", "New Straight", "Ctrl+Alt+S", self.parent.new_straight_button),
            ("new_curve_mode_action", "New Curve", "Ctrl+Alt+C", self.parent.new_curve_button),
            ("split_section_mode_action", "Split Section", None, self.parent.split_section_button),
            ("move_section_mode_action", "Move Section", "Ctrl+Alt+M", self.parent.move_section_button),
            ("delete_section_mode_action", "Delete Section", "Ctrl+Alt+D", self.parent.delete_section_button),
        ):
            act = _action(text, self.parent, shortcut=shortcut, enabled=button.isEnabled())
            if attr not in {"previous_section_action", "next_section_action"}:
                act.setCheckable(True); act.setChecked(button.isChecked())
            object.__setattr__(self, attr, act)
        object.__setattr__(self, "set_start_finish_action", _action("Set Start/Finish", self.parent, enabled=self.parent.set_start_finish_button.isEnabled()))
        object.__setattr__(self, "scale_track_action", _action("Scale Track to Length…", self.parent, self.scale_track, enabled=False))
        object.__setattr__(self, "rotate_track_action", _action("Rotate Track…", self.parent, self.open_rotate_track_dialog, enabled=False))
        object.__setattr__(self, "reverse_track_action", _action("Reverse Track", self.parent, self.reverse_track, enabled=False))
        object.__setattr__(self, "section_table_action", _action("Section Table", self.parent, self.show_section_table, enabled=False))
        object.__setattr__(self, "heading_table_action", _action("Heading Table", self.parent, self.show_heading_table, enabled=False))
        object.__setattr__(self, "xsect_table_action", _action("X-Section Table", self.parent, self.show_xsect_table, enabled=False))


@dataclass(frozen=True)
class FsectActions:
    parent: QtWidgets.QWidget
    open_generate_fsects_dialog: Callback
    open_raise_lower_elevations_dialog: Callback
    open_flatten_all_elevations_and_grade_dialog: Callback
    open_generate_elevation_change_dialog: Callback
    generate_pitwall_txt: Callback

    def __post_init__(self) -> None:
        object.__setattr__(self, "generate_fsects_action", _action("Generate Fsects…", self.parent, self.open_generate_fsects_dialog))
        object.__setattr__(self, "raise_lower_elevations_action", _action("Raise/lower all elevations…", self.parent, self.open_raise_lower_elevations_dialog, enabled=False))
        object.__setattr__(self, "flatten_all_elevations_and_grade_action", _action("Flatten all elevations + grade…", self.parent, self.open_flatten_all_elevations_and_grade_dialog, enabled=False))
        object.__setattr__(self, "generate_elevation_change_action", _action("Generate elevation change…", self.parent, self.open_generate_elevation_change_dialog, enabled=False))
        object.__setattr__(self, "generate_pitwall_action", _action("Generate pitwall.txt…", self.parent, self.generate_pitwall_txt, enabled=False))
        for attr, text, button in (
            ("copy_fsects_prev_action", "Copy Fsects to Previous Section", self.parent.copy_fsects_prev_button),
            ("copy_fsects_next_action", "Copy Fsects to Next Section", self.parent.copy_fsects_next_button),
            ("add_fsect_action", "Insert Fsect", self.parent.add_fsect_button),
            ("delete_fsect_action", "Delete Fsect", self.parent.delete_fsect_button),
            ("move_fsect_up_action", "Move Fsect Up", self.parent.move_fsect_up_button),
            ("move_fsect_down_action", "Move Fsect Down", self.parent.move_fsect_down_button),
            ("swap_fsect_types_action", "Swap Fsect Type Across All Sections…", self.parent.swap_fsect_types_button),
        ):
            object.__setattr__(self, attr, _action(text, self.parent, enabled=button.isEnabled()))


@dataclass(frozen=True)
class MrkActions:
    parent: QtWidgets.QWidget

    def __post_init__(self) -> None:
        for attr, text, button in (
            ("mrk_add_entry_action", "Add MRK Entry", self.parent.mrk_add_entry_button),
            ("mrk_delete_entry_action", "Delete MRK Entry", self.parent.mrk_delete_entry_button),
            ("mrk_move_up_action", "Move MRK Entry Up", self.parent.mrk_move_up_button),
            ("mrk_move_down_action", "Move MRK Entry Down", self.parent.mrk_move_down_button),
            ("mrk_textures_action", "MRK Textures…", self.parent.mrk_textures_button),
            ("mrk_generate_file_action", "Generate .MRK file…", self.parent.mrk_generate_file_button),
            ("mrk_save_entries_action", "Export MRK entries…", self.parent.mrk_save_button),
            ("mrk_load_entries_action", "Import MRK entries…", self.parent.mrk_load_button),
        ):
            object.__setattr__(self, attr, _action(text, self.parent, enabled=button.isEnabled()))


@dataclass(frozen=True)
class TsdActions:
    parent: QtWidgets.QWidget
    show_palette_colors_dialog: Callback

    def __post_init__(self) -> None:
        object.__setattr__(self, "show_palette_colors_action", _action("Show SUNNY Palette Colors…", self.parent, self.show_palette_colors_dialog))


@dataclass(frozen=True)
class TsoActions:
    parent: QtWidgets.QWidget
    launch_tso_generator: Callback
    show_unique_tso_filenames_dialog: Callback

    def __post_init__(self) -> None:
        object.__setattr__(self, "launch_tso_generator_action", _action("Open TSO Generator", self.parent, self.launch_tso_generator))
        object.__setattr__(self, "show_unique_tso_filenames_action", _action("Show list of unique TSOs", self.parent, self.show_unique_tso_filenames_dialog))


@dataclass(frozen=True)
class Track3DActions:
    parent: QtWidgets.QWidget
    calibrate_background: Callback
    open_three_d_tools_dialog: Callback
    run_sg_integrity_checks: Callback

    def __post_init__(self) -> None:
        object.__setattr__(self, "calibrate_background_action", _action("Open Background Calibrator", self.parent, self.calibrate_background))
        object.__setattr__(self, "three_d_tools_action", _action("Run 3D Tools…", self.parent, self.open_three_d_tools_dialog))
        object.__setattr__(self, "run_integrity_checks_action", _action("Run SG Integrity Checks", self.parent, self.run_sg_integrity_checks, enabled=False))


@dataclass(frozen=True)
class HelpActions:
    parent: QtWidgets.QWidget
    show_about_dialog: Callback

    def __post_init__(self) -> None:
        object.__setattr__(self, "about_action", _action("About SG CREATE", self.parent, self.show_about_dialog))


@dataclass(frozen=True)
class ViewerActionGroups:
    file: FileActions
    view: ViewActions
    section_editing: SectionEditingActions
    fsect: FsectActions
    mrk: MrkActions
    tsd: TsdActions
    tso: TsoActions
    track3d: Track3DActions
    help: HelpActions


def build_viewer_menu_bar(window: QtWidgets.QMainWindow, groups: ViewerActionGroups) -> None:
    file_menu = window.menuBar().addMenu("&File")
    file_menu.addAction(groups.file.new_action); file_menu.addAction(groups.file.open_project_action); file_menu.addMenu(groups.file.open_recent_menu)
    import_menu = file_menu.addMenu("Import")
    for act in (groups.file.import_sg_action, groups.file.load_sunny_palette_action, groups.file.import_trk_action, groups.file.import_trk_from_dat_action): import_menu.addAction(act)
    file_menu.addSeparator(); file_menu.addAction(groups.file.save_current_action); file_menu.addAction(groups.file.save_action)
    export_menu = file_menu.addMenu("Export")
    for act in (groups.file.save_project_action, groups.file.convert_trk_action, groups.file.export_csv_action): export_menu.addAction(act)
    file_menu.addSeparator(); file_menu.addAction(groups.file.quit_action)

    view_menu = window.menuBar().addMenu("View")
    for act in (groups.view.open_background_action, groups.view.background_settings_action, groups.view.view_options_action): view_menu.addAction(act)
    view_menu.addSeparator()
    for act in (groups.view.set_project_working_folder_action, groups.view.clear_project_working_folder_action): view_menu.addAction(act)
    view_menu.addSeparator()
    for act in (groups.view.show_section_dlongs_action, groups.view.show_radii_action, groups.view.show_axes_action, groups.view.show_crosshair_action, groups.view.show_background_image_action): view_menu.addAction(act)

    tools_menu = window.menuBar().addMenu("Tools")
    section_menu = tools_menu.addMenu("Section Editing")
    for act in (groups.section_editing.previous_section_action, groups.section_editing.next_section_action): section_menu.addAction(act)
    section_menu.addSeparator()
    for act in (groups.section_editing.new_straight_mode_action, groups.section_editing.new_curve_mode_action, groups.section_editing.split_section_mode_action, groups.section_editing.move_section_mode_action, groups.section_editing.delete_section_mode_action): section_menu.addAction(act)
    section_menu.addSeparator(); section_menu.addAction(groups.section_editing.set_start_finish_action)
    transform_menu = tools_menu.addMenu("Transform")
    for act in (groups.section_editing.scale_track_action, groups.section_editing.rotate_track_action, groups.section_editing.reverse_track_action): transform_menu.addAction(act)
    generate_menu = tools_menu.addMenu("Generate")
    for act in (groups.fsect.generate_fsects_action, groups.fsect.generate_pitwall_action, groups.fsect.generate_elevation_change_action): generate_menu.addAction(act)
    elevation_menu = tools_menu.addMenu("Elevation")
    for act in (groups.fsect.raise_lower_elevations_action, groups.fsect.flatten_all_elevations_and_grade_action): elevation_menu.addAction(act)
    fsects_menu = tools_menu.addMenu("Fsects")
    for act in (groups.fsect.copy_fsects_prev_action, groups.fsect.copy_fsects_next_action): fsects_menu.addAction(act)
    fsects_menu.addSeparator()
    for act in (groups.fsect.add_fsect_action, groups.fsect.delete_fsect_action, groups.fsect.move_fsect_up_action, groups.fsect.move_fsect_down_action): fsects_menu.addAction(act)
    fsects_menu.addSeparator(); fsects_menu.addAction(groups.fsect.swap_fsect_types_action)
    mrk_menu = tools_menu.addMenu("MRK")
    for act in (groups.mrk.mrk_add_entry_action, groups.mrk.mrk_delete_entry_action, groups.mrk.mrk_move_up_action, groups.mrk.mrk_move_down_action): mrk_menu.addAction(act)
    mrk_menu.addSeparator()
    for act in (groups.mrk.mrk_textures_action, groups.mrk.mrk_generate_file_action, groups.mrk.mrk_save_entries_action, groups.mrk.mrk_load_entries_action): mrk_menu.addAction(act)
    tools_menu.addSeparator()
    for act in (groups.tsd.show_palette_colors_action, groups.tso.show_unique_tso_filenames_action, groups.track3d.three_d_tools_action): tools_menu.addAction(act)
    tools_menu.addSeparator(); tools_menu.addAction(groups.track3d.run_integrity_checks_action)
    tools_menu.addSeparator(); tools_menu.addAction(groups.track3d.calibrate_background_action); tools_menu.addAction(groups.tso.launch_tso_generator_action)

    window_menu = window.menuBar().addMenu("Window")
    for act in (groups.section_editing.section_table_action, groups.section_editing.heading_table_action, groups.section_editing.xsect_table_action): window_menu.addAction(act)
    window.set_section_table_action(groups.section_editing.section_table_action)
    window.set_heading_table_action(groups.section_editing.heading_table_action)
    window.set_xsect_table_action(groups.section_editing.xsect_table_action)

    help_menu = window.menuBar().addMenu("Help")
    help_menu.addAction(groups.help.about_action)
