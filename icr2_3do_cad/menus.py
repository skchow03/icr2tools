"""Standard desktop menus for the ICR2 3DO CAD.

Menus call the existing guarded operations; dialogs host former sidebar tools.
They do not introduce a second file-writing or model-loading code path.
"""
from pathlib import Path

from PySide6.QtCore import QSettings
from PySide6.QtGui import QActionGroup, QKeySequence
from PySide6.QtWidgets import QMessageBox


RECENT_LIMIT = 8


def _settings():
    return QSettings("ICR2Tools", "3DOCAD")


def _recent_paths():
    value = _settings().value("recent_models", [])
    if isinstance(value, str):
        value = [value]
    return [str(path) for path in value if isinstance(path, str)]


def refresh_recent_menu(window):
    """Update the menu without attempting to load an unreadable old path."""
    menu = window.recent_models_menu
    menu.clear()
    paths = [p for p in _recent_paths() if Path(p).is_file()]
    if not paths:
        empty = menu.addAction("(No recent models)")
        empty.setEnabled(False)
    for index, path in enumerate(paths, 1):
        model = Path(path)
        action = menu.addAction(f"&{index}  {model.name} — {model.parent}")
        action.setToolTip(path)
        action.setStatusTip(path)
        action.triggered.connect(
            lambda _checked=False, selected=path: window.load(Path(selected)))
    menu.addSeparator()
    clear = menu.addAction("Clear Recent Files")
    clear.setEnabled(bool(_recent_paths()))
    clear.triggered.connect(lambda: clear_recent_files(window))


def remember_recent_model(window, path):
    """Record only successfully loaded models, not canceled/failed opens."""
    recent = str(Path(path).resolve())
    paths = [p for p in _recent_paths() if p != recent and Path(p).is_file()]
    _settings().setValue("recent_models", [recent, *paths][:RECENT_LIMIT])
    refresh_recent_menu(window)


def clear_recent_files(window):
    _settings().remove("recent_models")
    refresh_recent_menu(window)


def update_model_actions(window):
    """Avoid advertising Save, Export, or Reload on an empty viewer."""
    loaded = window.viewer._model is not None
    for name in ("save", "save_as", "export", "reload", "reload_mips",
                 "mip_browser", "appearance_overlay", "tracing_load"):
        window.menu_actions[name].setEnabled(loaded)
    tracing = loaded and window.viewer.tracing_reference is not None
    for name in ("tracing_adjust", "tracing_remove"):
        window.menu_actions[name].setEnabled(tracing)
    window.menu_actions["clear_appearance_overlay"].setEnabled(
        loaded and window.car_appearance_overlay is not None)
    window.apply_car_appearance_button.setEnabled(loaded)
    window.clear_car_appearance_button.setEnabled(
        loaded and window.car_appearance_overlay is not None)


def _add_action(menu, title, callback, shortcut=None):
    action = menu.addAction(title)
    if shortcut is not None:
        action.setShortcut(QKeySequence(shortcut))
    action.triggered.connect(callback)
    return action


def _bind_checkbox(menu, title, widget):
    """Keep a menu check and its existing control state in sync."""
    action = menu.addAction(title)
    action.setCheckable(True)
    action.setChecked(widget.isChecked())
    action.toggled.connect(widget.setChecked)
    widget.toggled.connect(action.setChecked)
    return action


def _reload_model(window):
    if window.model_path is None:
        QMessageBox.information(window, "No model", "Open a model first.")
    else:
        # Window.load performs the existing unsaved-source confirmation.
        window.load(window.model_path)


def _show_controls(window):
    QMessageBox.information(
        window, "3DO CAD Controls",
        "Open: Ctrl+O    Save .3D Source: Ctrl+S    Save .3D Source As: Ctrl+Shift+S\n"
        "Export 3DO: Ctrl+E    Exit: Ctrl+Q\n"
        "Undo/Redo: Ctrl+Z / Ctrl+Y    Find in .3D Source: Ctrl+F\n\n"
        "Orbit: left drag    Pan: Shift+left drag or middle drag\n"
        "Zoom: mouse wheel    Frame All: F (when viewport focused)\n"
        "Reload MIPs: R (when viewport focused)\n\n"
        "Track camera: W/S forward/back, A/D left/right (or arrow keys); "
        "Shift moves 5x faster.\n"
        "Choose View > .3D Source to edit and validate N3 text.")


def install_menus(window):
    """Install menus after all viewer and settings-dialog controls exist."""
    bar = window.menuBar()
    file_menu = bar.addMenu("&File")
    _add_action(file_menu, "&Open Model…", window.open_dialog,
                QKeySequence.StandardKey.Open)
    window.recent_models_menu = file_menu.addMenu("Open &Recent")
    refresh_recent_menu(window)
    window.menu_actions = {}
    window.menu_actions["reload"] = _add_action(
        file_menu, "&Reload Model from Disk", lambda: _reload_model(window))
    file_menu.addSeparator()
    window.menu_actions["save"] = _add_action(
        file_menu, "&Save .3D Source", lambda:
        window._source_toolbar_action(window._save_source),
        QKeySequence.StandardKey.Save)
    window.menu_actions["save_as"] = _add_action(
        file_menu, "Save .3D Source &As…", lambda:
        window._source_toolbar_action(
            lambda: window._save_source(save_as=True)),
        QKeySequence.StandardKey.SaveAs)
    window.menu_actions["export"] = _add_action(
        file_menu, "&Export Compiled 3DO…", lambda:
        window._source_toolbar_action(window._export_compiled_source),
        QKeySequence("Ctrl+E"))
    file_menu.addSeparator()
    _add_action(file_menu, "E&xit", window.close,
                QKeySequence.StandardKey.Quit)

    edit = bar.addMenu("&Edit")
    window.menu_actions["undo"] = _add_action(
        edit, "&Undo", lambda: window._edit_source_command("undo"),
        QKeySequence.StandardKey.Undo)
    window.menu_actions["redo"] = _add_action(
        edit, "&Redo", lambda: window._edit_source_command("redo"),
        QKeySequence.StandardKey.Redo)
    edit.addSeparator()
    _add_action(edit, "Cu&t", lambda: window._edit_source_command("cut"),
                QKeySequence.StandardKey.Cut)
    _add_action(edit, "&Copy", lambda: window._edit_source_command("copy"),
                QKeySequence.StandardKey.Copy)
    _add_action(edit, "&Paste", lambda: window._edit_source_command("paste"),
                QKeySequence.StandardKey.Paste)
    _add_action(edit, "Select &All",
                lambda: window._edit_source_command("selectAll"),
                QKeySequence.StandardKey.SelectAll)
    edit.addSeparator()
    _add_action(edit, "&Find in .3D Source…", window._find_source,
                QKeySequence.StandardKey.Find)
    _add_action(edit, "Find &Next", lambda: window._find_source(next_match=True),
                QKeySequence.StandardKey.FindNext)
    edit.addSeparator()
    _add_action(edit, "Rename Selected &Pointer…",
                lambda: window.source_pane.rename_selected_pointer())
    _add_action(edit, "&Scale Model…", window._scale_model)
    _add_action(edit, "Split selected &Polygon…",
                lambda: window.split_button.setChecked(True))
    _add_action(edit, "Apply .3D Source Now",
                lambda: window._source_toolbar_action(
                    window.source_pane.apply_now))

    view = bar.addMenu("&View")
    _add_action(view, "Frame &All (F)", window.viewer.frame_all)
    for title in ("3D", "Top", "Front", "Side"):
        _add_action(view, title, lambda checked=False, mode=title:
                    window.viewer.set_view(mode))
    view.addSeparator()
    perspective = _bind_checkbox(view, "&Perspective", window.perspective_toggle)
    window.perspective_menu_action = perspective
    _bind_checkbox(view, "&Fixed Camera", window.fixed_camera_button)
    _bind_checkbox(view, "Show &.3D Source", window.source_toggle)
    view.addSeparator()
    rendering = view.addMenu("&Rendering Mode")
    render_group = QActionGroup(window)
    render_group.setExclusive(True)
    for index in range(window.mode_combo.count()):
        label = window.mode_combo.itemText(index)
        action = rendering.addAction(label)
        action.setCheckable(True)
        action.setChecked(index == window.mode_combo.currentIndex())
        render_group.addAction(action)
        action.triggered.connect(
            lambda checked=False, mode=index:
                window.mode_combo.setCurrentIndex(mode))
    window.mode_combo.currentIndexChanged.connect(
        lambda index: (render_group.actions()[index].setChecked(True)
                       if 0 <= index < len(render_group.actions()) else None))
    _add_action(view, "&Display Settings…",
                lambda: window.open_settings_dialog("display"))
    _add_action(view, "Customize &Colors…", window.customize_colors)
    _add_action(view, "Advanced &Diagnostics…",
                lambda: window.open_settings_dialog("advanced"))
    view.addAction(window.load_activity_dock.toggleViewAction())
    _add_action(view, "Load &Error Log…", window.open_load_error_log)
    options = view.addMenu("Display &Options")
    _bind_checkbox(options, "Textures", window.show_textures)
    _bind_checkbox(options, "PMP sprites", window.show_sprites)
    _bind_checkbox(options, "Repeat UV (tile MIPs)", window.repeat_uv)

    model = bar.addMenu("&Model")
    workspace = model.addMenu("&Workspace")
    group = QActionGroup(window)
    group.setExclusive(True)
    for index in range(window.workspace_tabs.count()):
        action = workspace.addAction(window.workspace_tabs.tabText(index))
        action.setCheckable(True)
        action.setChecked(index == window.workspace_tabs.currentIndex())
        group.addAction(action)
        action.triggered.connect(
            lambda checked=False, mode=index: window.workspace_tabs.setCurrentIndex(mode))
    window.workspace_tabs.currentChanged.connect(
        lambda index: [action.setChecked(i == index)
                       for i, action in enumerate(group.actions())])
    model.addSeparator()
    _add_action(model, "&Model Settings…",
                lambda: window.open_settings_dialog("model"))
    for index, title in enumerate(("Car", "Track", "Object")):
        _add_action(model, f"{title} &Settings…",
                    lambda checked=False, mode=index:
                    window.open_settings_dialog("model", workspace=mode))

    assets = bar.addMenu("&Assets")
    _add_action(assets, "Asset &Settings…",
                lambda: window.open_settings_dialog("assets"))
    assets.addSeparator()
    window.menu_actions["appearance_overlay"] = _add_action(
        assets, "Apply Individual-Car &RECOLOR / MIP…",
        window.choose_car_appearance_overlay)
    window.menu_actions["clear_appearance_overlay"] = _add_action(
        assets, "Clear Car Appearance Overlay",
        window.clear_car_appearance_overlay)
    assets.addSeparator()
    window.menu_actions["tracing_load"] = _add_action(
        assets, "Load &Tracing Reference Image…",
        window.load_tracing_reference_image)
    window.menu_actions["tracing_adjust"] = _add_action(
        assets, "Adjust Tracing Reference…",
        window.adjust_tracing_reference_image)
    window.menu_actions["tracing_remove"] = _add_action(
        assets, "Remove Tracing Reference",
        window.clear_tracing_reference_image)
    assets.addSeparator()
    window.menu_actions["mip_browser"] = _add_action(
        assets, "Browse Model &MIPs / U,V…", window.open_mip_browser)
    assets.addSeparator()
    _add_action(assets, "Open PCX &Palette…", window.open_palette_dialog)
    _add_action(assets, "&Default Palette", window.restore_palette)
    assets.addSeparator()
    _add_action(assets, "Select &MIP Folder…", window.choose_mip_folder)
    _add_action(assets, "Select External &3DO Folder…",
                window.choose_objects_folder)
    _add_action(assets, "Select &Fallback MIP…", window.choose_fallback_mip)
    _add_action(assets, "C&lear Fallback MIP", window.clear_fallback_mip)
    assets.addSeparator()
    window.menu_actions["reload_mips"] = _add_action(
        assets, "&Reload MIPs (R)", window.reload_mips)

    help_menu = bar.addMenu("&Help")
    _add_action(help_menu, "&Keyboard and Mouse Controls",
                lambda: _show_controls(window))
    _add_action(help_menu, "&About ICR2 3DO CAD", lambda:
                QMessageBox.about(
                    window, "About ICR2 3DO CAD",
                    "ICR2 3DO CAD — 3DO CAD\n"
                    "Papyrus .3D/.3DO model inspection and N3 editing.\n\n"
                    "Save Source writes an editable .3D file. "
                    "Export Compiled 3DO writes a separate binary, "
                    "without replacing the original model."))

    def sync_perspective_availability(*_):
        perspective.setEnabled(
            not window.viewer.fixed_camera_mode and
            not window.viewer.track_drive_enabled)

    # Fixed/TRK camera modes require perspective; the menu must not offer
    # an unavailable toggle while the corresponding checkbox is disabled.
    window.viewer.fixedCameraModeChanged.connect(sync_perspective_availability)
    window.viewer.trackDriveModeChanged.connect(sync_perspective_availability)
    sync_perspective_availability()
    update_model_actions(window)
