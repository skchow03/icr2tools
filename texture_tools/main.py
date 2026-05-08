from __future__ import annotations

import sys
from pathlib import Path

# Ensure repo root is on sys.path when running this file directly
if __package__ is None or __package__ == "":
    sys.path.append(str(Path(__file__).resolve().parent.parent))

from PIL import Image

try:
    from PyQt5 import QtCore, QtGui, QtWidgets
except ImportError:  # pragma: no cover
    from PySide6 import QtCore, QtGui, QtWidgets  # type: ignore

from icr2_core.mip.mips import img_to_mip, load_palette, mip_to_img
from texture_tools.pmp import png_to_pmp
from texture_tools.pmp_to_png import convert_pmp_to_png
from texture_tools.sunny_optimizer.chop_horizon import chop_horizon
from texture_tools.sunny_optimizer.ui.settings import SunnyOptimizerSettings
from texture_tools.sunny_optimizer.ui.main_window import MainWindow as SunnyOptimizerWindow

ERROR_STYLE = "QLineEdit { border: 1px solid #d93025; border-radius: 3px; }"
STATUS_IDLE = "idle"
STATUS_VALIDATING = "validating"
STATUS_PROCESSING = "processing"
STATUS_SUCCESS = "success"
STATUS_FAILURE = "failure"

UI_LABEL_WIDTH = 220
UI_SECTION_SPACING = 10
UI_PANEL_MARGINS = (12, 12, 12, 12)


def _apply_panel_layout(layout: QtWidgets.QVBoxLayout) -> None:
    layout.setContentsMargins(*UI_PANEL_MARGINS)
    layout.setSpacing(UI_SECTION_SPACING)


def _set_primary_button(button: QtWidgets.QPushButton) -> None:
    button.setProperty("primary", True)


def _set_secondary_button(button: QtWidgets.QPushButton) -> None:
    button.setProperty("secondary", True)


def _make_section_card(title: str, parent: QtWidgets.QWidget | None = None) -> tuple[QtWidgets.QFrame, QtWidgets.QVBoxLayout]:
    card = QtWidgets.QFrame(parent)
    card.setObjectName("sectionCard")
    card_layout = QtWidgets.QVBoxLayout(card)
    card_layout.setContentsMargins(10, 10, 10, 10)
    card_layout.setSpacing(8)
    header = QtWidgets.QLabel(title)
    header.setObjectName("sectionTitle")
    card_layout.addWidget(header)
    return card, card_layout


class SharedStatusMixin:
    STATUS_PREFIX = {
        STATUS_IDLE: "Idle",
        STATUS_VALIDATING: "Validating",
        STATUS_PROCESSING: "Processing",
        STATUS_SUCCESS: "Success",
        STATUS_FAILURE: "Failure",
    }

    def set_status(self, state: str, message: str) -> None:
        self.status_label.setText(f"[{self.STATUS_PREFIX.get(state, 'Status')}] {message}")


class PresettableMixin:
    TOOL_PRESET_KEY = ""

    def _build_preset_controls(self, parent: QtWidgets.QVBoxLayout) -> None:
        row = QtWidgets.QHBoxLayout()
        self.preset_combo = QtWidgets.QComboBox()
        self.preset_combo.setEditable(False)
        self.save_preset_btn = QtWidgets.QPushButton("Save preset")
        self.load_preset_btn = QtWidgets.QPushButton("Load preset")
        self.delete_preset_btn = QtWidgets.QPushButton("Delete preset")
        row.addWidget(QtWidgets.QLabel("Presets:"))
        row.addWidget(self.preset_combo, 1)
        row.addWidget(self.save_preset_btn)
        row.addWidget(self.load_preset_btn)
        row.addWidget(self.delete_preset_btn)
        parent.addLayout(row)

        self.save_preset_btn.clicked.connect(self._save_preset_dialog)
        self.load_preset_btn.clicked.connect(self._load_selected_preset)
        self.delete_preset_btn.clicked.connect(self._delete_selected_preset)
        self._refresh_preset_combo()
        default = self._settings.default_preset_for_tool(self.TOOL_PRESET_KEY)
        if default:
            idx = self.preset_combo.findText(default)
            if idx >= 0:
                self.preset_combo.setCurrentIndex(idx)
                self._apply_preset(self._settings.presets_for_tool(self.TOOL_PRESET_KEY).get(default, {}))

    def _refresh_preset_combo(self) -> None:
        current = self.preset_combo.currentText() if hasattr(self, "preset_combo") else ""
        self.preset_combo.clear()
        self.preset_combo.addItems(sorted(self._settings.presets_for_tool(self.TOOL_PRESET_KEY).keys()))
        if current:
            idx = self.preset_combo.findText(current)
            if idx >= 0:
                self.preset_combo.setCurrentIndex(idx)

    def _save_preset_dialog(self) -> None:
        name, ok = QtWidgets.QInputDialog.getText(self, "Save preset", "Preset name:")
        if not ok or not name.strip():
            return
        preset_name = name.strip()
        self._settings.set_preset_for_tool(self.TOOL_PRESET_KEY, preset_name, self._collect_preset_values())
        self._settings.set_default_preset(self.TOOL_PRESET_KEY, preset_name)
        self._settings.save()
        self._refresh_preset_combo()
        idx = self.preset_combo.findText(preset_name)
        if idx >= 0:
            self.preset_combo.setCurrentIndex(idx)

    def _load_selected_preset(self) -> None:
        preset_name = self.preset_combo.currentText().strip()
        if not preset_name:
            return
        preset = self._settings.presets_for_tool(self.TOOL_PRESET_KEY).get(preset_name)
        if not preset:
            return
        self._apply_preset(preset)
        self._settings.set_default_preset(self.TOOL_PRESET_KEY, preset_name)
        self._settings.save()

    def _delete_selected_preset(self) -> None:
        preset_name = self.preset_combo.currentText().strip()
        if not preset_name:
            return
        self._settings.delete_preset_for_tool(self.TOOL_PRESET_KEY, preset_name)
        if self._settings.default_preset_for_tool(self.TOOL_PRESET_KEY) == preset_name:
            self._settings.default_presets.pop(self.TOOL_PRESET_KEY, None)
        self._settings.save()
        self._refresh_preset_combo()


class RecentPathMixin:
    TOOL_RECENT_KEY = ""

    def _recent_paths_key(self, field_name: str) -> str:
        return f"{self.TOOL_RECENT_KEY}:{field_name}"

    def _record_recent_path(self, field_name: str, path: str) -> None:
        if not getattr(self, "_settings", None):
            return
        self._settings.push_recent_path(self._recent_paths_key(field_name), path)
        self._settings.save()

    def _apply_recent_menu(self, menu_btn: QtWidgets.QToolButton, edit: QtWidgets.QLineEdit, field_name: str) -> None:
        if not getattr(self, "_settings", None):
            menu_btn.setEnabled(False)
            return
        menu_btn.setPopupMode(QtWidgets.QToolButton.InstantPopup)

        def _refresh_menu() -> None:
            menu = QtWidgets.QMenu(menu_btn)
            recents = self._settings.get_recent_paths(self._recent_paths_key(field_name))
            if not recents:
                action = menu.addAction("No recent paths")
                action.setEnabled(False)
            for value in recents:
                action = menu.addAction(value)
                action.triggered.connect(lambda _checked=False, v=value: edit.setText(v))
            menu_btn.setMenu(menu)

        menu_btn.pressed.connect(_refresh_menu)

class DropPathLineEdit(QtWidgets.QLineEdit):
    def __init__(self, *, acceptor, on_accept, on_reject=None, parent: QtWidgets.QWidget | None = None) -> None:
        super().__init__(parent)
        self._acceptor = acceptor
        self._on_accept = on_accept
        self._on_reject = on_reject
        self.setAcceptDrops(True)

    def _paths_from_event(self, event) -> list[Path]:
        mime = event.mimeData()
        if not mime.hasUrls():
            return []
        return [Path(url.toLocalFile()) for url in mime.urls() if url.isLocalFile()]

    def dragEnterEvent(self, event) -> None:
        paths = self._paths_from_event(event)
        accepted, _ = self._acceptor(paths)
        if accepted:
            event.acceptProposedAction()
        else:
            event.ignore()

    def dropEvent(self, event) -> None:
        paths = self._paths_from_event(event)
        accepted, message = self._acceptor(paths)
        if accepted:
            self._on_accept(paths)
            event.acceptProposedAction()
            return
        if self._on_reject is not None:
            self._on_reject(message or 'Dropped item is not valid for this field.')
        event.ignore()


def _set_field_error(field: QtWidgets.QLineEdit, error_label: QtWidgets.QLabel, message: str | None) -> None:
    has_error = bool(message)
    field.setStyleSheet(ERROR_STYLE if has_error else "")
    error_label.setText(message or "")
    error_label.setVisible(has_error)


def _validate_path(
    raw_path: str,
    *,
    label: str,
    expected_suffixes: tuple[str, ...],
    must_exist: bool = True,
    folder_only: bool = False,
) -> str | None:
    if not raw_path:
        return f"{label} is required."
    path = Path(raw_path)
    if must_exist and not path.exists():
        return f"{label} does not exist."
    if folder_only:
        if path.exists() and not path.is_dir():
            return f"{label} must be a folder."
        return None
    if expected_suffixes and path.suffix.lower() not in expected_suffixes:
        return f"{label} must end with {', '.join(expected_suffixes)}."
    return None




def _fmt_dimensions(image: Image.Image) -> str:
    return f"{image.width}x{image.height}"


def _confirm_summary(parent: QtWidgets.QWidget, *, dimensions: str, output_format: str, palette_source: str, destination: Path) -> bool:
    message = (
        "Output summary:\n"
        f"• Dimensions: {dimensions}\n"
        f"• Format: {output_format}\n"
        f"• Palette: {palette_source}\n"
        f"• Destination: {destination}"
    )
    result = QtWidgets.QMessageBox.question(
        parent,
        "Confirm output",
        message,
        QtWidgets.QMessageBox.Yes | QtWidgets.QMessageBox.No,
        QtWidgets.QMessageBox.Yes,
    )
    return result == QtWidgets.QMessageBox.Yes


def _offer_preview(parent: QtWidgets.QWidget, image: Image.Image, title: str) -> bool:
    preview_message = QtWidgets.QMessageBox(parent)
    preview_message.setIcon(QtWidgets.QMessageBox.Question)
    preview_message.setWindowTitle("Preview output")
    preview_message.setText("Preview output before final write?")
    preview_message.setStandardButtons(
        QtWidgets.QMessageBox.Yes | QtWidgets.QMessageBox.No | QtWidgets.QMessageBox.Cancel
    )
    choice = preview_message.exec_()
    if choice == QtWidgets.QMessageBox.Cancel:
        return False
    if choice == QtWidgets.QMessageBox.Yes:
        rgb_image = image.convert("RGBA")
        data = rgb_image.tobytes("raw", "RGBA")
        qimage = QtGui.QImage(data, rgb_image.width, rgb_image.height, QtGui.QImage.Format_RGBA8888)
        pixmap = QtGui.QPixmap.fromImage(qimage.copy())
        dialog = QtWidgets.QDialog(parent)
        dialog.setWindowTitle(title)
        vbox = QtWidgets.QVBoxLayout(dialog)
        scroll = QtWidgets.QScrollArea()
        label = QtWidgets.QLabel()
        label.setPixmap(pixmap)
        scroll.setWidget(label)
        scroll.setWidgetResizable(True)
        vbox.addWidget(scroll)
        buttons = QtWidgets.QDialogButtonBox(QtWidgets.QDialogButtonBox.Ok | QtWidgets.QDialogButtonBox.Cancel)
        vbox.addWidget(buttons)
        buttons.accepted.connect(dialog.accept)
        buttons.rejected.connect(dialog.reject)
        return dialog.exec_() == QtWidgets.QDialog.Accepted
    return True


def _pil_to_pixmap(image: Image.Image) -> QtGui.QPixmap:
    rgba = image.convert("RGBA")
    data = rgba.tobytes("raw", "RGBA")
    qimage = QtGui.QImage(data, rgba.width, rgba.height, QtGui.QImage.Format_RGBA8888)
    return QtGui.QPixmap.fromImage(qimage.copy())


class PreviewPane(QtWidgets.QGroupBox):
    def __init__(self, title: str = "Preview", parent: QtWidgets.QWidget | None = None) -> None:
        super().__init__(title, parent)
        layout = QtWidgets.QVBoxLayout(self)
        controls = QtWidgets.QHBoxLayout()
        controls.addStretch(1)
        self.fit_btn = QtWidgets.QPushButton("Fit to pane")
        self.fit_btn.clicked.connect(self._fit_to_pane)
        controls.addWidget(self.fit_btn)
        layout.addLayout(controls)

        self._scene = QtWidgets.QGraphicsScene(self)
        self._pixmap_item = QtWidgets.QGraphicsPixmapItem()
        self._scene.addItem(self._pixmap_item)

        self.image_view = QtWidgets.QGraphicsView(self._scene)
        self.image_view.setMinimumHeight(160)
        self.image_view.setStyleSheet("border: 1px solid #d1d5db; background: #fff;")
        self.image_view.setRenderHint(QtGui.QPainter.SmoothPixmapTransform, True)
        self.image_view.setRenderHint(QtGui.QPainter.Antialiasing, True)
        self.image_view.setTransformationAnchor(QtWidgets.QGraphicsView.AnchorUnderMouse)
        self.image_view.setResizeAnchor(QtWidgets.QGraphicsView.AnchorViewCenter)
        self.image_view.setDragMode(QtWidgets.QGraphicsView.ScrollHandDrag)
        self.image_view.setInteractive(False)
        self.image_view.viewport().installEventFilter(self)
        self._zoom_factor = 1.0

        self.image_label = QtWidgets.QLabel("No preview available.")
        self.image_label.setAlignment(QtCore.Qt.AlignCenter)
        self.image_label.setStyleSheet("color: #6b7280; background: transparent;")
        self.image_label.setAttribute(QtCore.Qt.WA_TransparentForMouseEvents, True)
        self._scene.addWidget(self.image_label)

        self.meta_label = QtWidgets.QLabel("")
        self.meta_label.setStyleSheet("color: #6b7280;")
        layout.addWidget(self.image_view)
        layout.addWidget(self.meta_label)

    def set_preview(self, image: Image.Image, *, caption: str = "") -> None:
        pixmap = _pil_to_pixmap(image)
        self._pixmap_item.setPixmap(pixmap)
        self.image_label.hide()
        self.image_view.viewport().setCursor(QtCore.Qt.OpenHandCursor)
        self._fit_to_pane()
        self.meta_label.setText(caption or _fmt_dimensions(image))

    def clear_preview(self, message: str = "No preview available.") -> None:
        self._pixmap_item.setPixmap(QtGui.QPixmap())
        self.image_label.setText(message)
        self.image_label.show()
        self.image_view.viewport().unsetCursor()
        self._fit_to_pane()
        self.meta_label.setText("")

    def _fit_to_pane(self) -> None:
        self.image_view.resetTransform()
        self._zoom_factor = 1.0
        pixmap = self._pixmap_item.pixmap()
        if pixmap.isNull():
            return
        self.image_view.fitInView(self._pixmap_item, QtCore.Qt.KeepAspectRatio)
        self._zoom_factor = self.image_view.transform().m11()

    def eventFilter(self, watched: QtCore.QObject, event: QtCore.QEvent) -> bool:
        if watched is self.image_view.viewport():
            if event.type() == QtCore.QEvent.Wheel and not self._pixmap_item.pixmap().isNull():
                delta = event.angleDelta().y()
                if delta:
                    factor = 1.15 if delta > 0 else 1 / 1.15
                    new_zoom = self._zoom_factor * factor
                    if 0.02 <= new_zoom <= 80:
                        self.image_view.scale(factor, factor)
                        self._zoom_factor = new_zoom
                return True
            if event.type() == QtCore.QEvent.MouseButtonPress and event.button() == QtCore.Qt.LeftButton:
                self.image_view.setCursor(QtCore.Qt.ClosedHandCursor)
            elif event.type() == QtCore.QEvent.MouseButtonRelease and event.button() == QtCore.Qt.LeftButton:
                self.image_view.setCursor(QtCore.Qt.OpenHandCursor)
        return super().eventFilter(watched, event)
class MipConversionWidget(QtWidgets.QWidget, SharedStatusMixin, PresettableMixin, RecentPathMixin):
    TOOL_PRESET_KEY = "mip_conversion"
    TOOL_RECENT_KEY = "mip_conversion"
    def _set_status_warning(self, message: str) -> None:
        self.status_label.setText(message)

    def __init__(self, settings: SunnyOptimizerSettings, parent: QtWidgets.QWidget | None = None) -> None:
        super().__init__(parent)
        self._settings = settings
        self._build_ui()

    def _build_ui(self) -> None:
        layout = QtWidgets.QVBoxLayout(self)
        _apply_panel_layout(layout)
        section, section_layout = _make_section_card("1. Choose input")
        section_layout.addWidget(QtWidgets.QLabel("Mode and input files"))
        layout.addWidget(section)

        mode_row = QtWidgets.QHBoxLayout()
        mode_row.addWidget(QtWidgets.QLabel("Mode:"))
        self.mode_combo = QtWidgets.QComboBox()
        self.mode_combo.addItems(["track", "carset"])
        self.mode_combo.setToolTip("Choose target format rules: 'track' for world textures, 'carset' for vehicle textures.")
        mode_row.addWidget(self.mode_combo)
        mode_row.addStretch(1)
        layout.addLayout(mode_row)

        self.input_edit, self.input_error = self._make_browse_row(layout, "Input image (.bmp/.png) or .mip:", self._browse_input, "input")
        self.input_edit._acceptor = lambda p: (len(p)==1 and p[0].is_file() and p[0].suffix.lower() in {".bmp", ".png", ".mip"}, "Drop a .bmp, .png, or .mip file.")
        self.input_edit._on_accept = lambda p: self.input_edit.setText(str(p[0]))

        layout.addWidget(QtWidgets.QLabel("2. Configure options"))
        self.palette_edit, self.palette_error = self._make_browse_row(layout, "Palette file (.pcx):", self._browse_palette, "palette")
        self.palette_edit._acceptor = lambda p: (len(p)==1 and p[0].is_file() and p[0].suffix.lower()==".pcx", "Drop a .pcx palette file.")
        self.palette_edit._on_accept = lambda p: self.palette_edit.setText(str(p[0]))

        layout.addWidget(QtWidgets.QLabel("3. Export"))
        self.output_edit, self.output_error = self._make_browse_row(layout, "Output file:", self._browse_output, "output")
        self.output_edit._acceptor = lambda p: (len(p)==1 and ((p[0].suffix.lower() in {".bmp", ".png", ".mip"}) or not p[0].exists()), "Drop a target file path ending in .bmp, .png, or .mip.")
        self.output_edit._on_accept = lambda p: self.output_edit.setText(str(p[0]))

        layout.addStretch(1)
        self._build_preset_controls(layout)
        convert_row = QtWidgets.QHBoxLayout()
        self.to_mip_btn = QtWidgets.QPushButton("Convert")
        _set_primary_button(self.to_mip_btn)
        self.to_mip_btn.clicked.connect(self._convert_to_mip)
        self.from_mip_btn = QtWidgets.QPushButton("Export")
        _set_secondary_button(self.from_mip_btn)
        self.from_mip_btn.clicked.connect(self._convert_from_mip)
        convert_row.addWidget(self.to_mip_btn)
        convert_row.addWidget(self.from_mip_btn)
        layout.addLayout(convert_row)
        self.preview_pane = PreviewPane("Output preview")
        layout.addWidget(self.preview_pane)

        self.status_label = QtWidgets.QLabel()
        self.status_label.setWordWrap(True)
        layout.addWidget(self.status_label)
        for edit in (self.input_edit, self.palette_edit, self.output_edit):
            edit.textChanged.connect(self._update_validation_state)
        self.input_edit.textChanged.connect(self._refresh_preview)
        self.palette_edit.textChanged.connect(self._refresh_preview)
        self.mode_combo.currentTextChanged.connect(self._refresh_preview)
        self._update_validation_state()
        self._refresh_preview()

    def _refresh_preview(self) -> None:
        input_raw = self.input_edit.text().strip()
        if not input_raw:
            self.preview_pane.clear_preview()
            return
        try:
            input_path = Path(input_raw)
            if input_path.suffix.lower() == ".mip":
                palette_path = self.palette_edit.text().strip()
                if not palette_path:
                    self.preview_pane.clear_preview("Palette file required for .mip preview.")
                    return
                preview = mip_to_img(str(input_path), load_palette(palette_path))[0]
                self.preview_pane.set_preview(preview, caption=f"{_fmt_dimensions(preview)} • Decoded from MIP")
                return
            source = Image.open(input_path)
            preview = source.convert("P")
            self.preview_pane.set_preview(preview, caption=f"{_fmt_dimensions(preview)} • Quantized preview")
        except Exception as exc:
            self.preview_pane.clear_preview(f"Preview unavailable: {exc}")

    def _collect_preset_values(self) -> dict[str, str]:
        return {"mode": self.mode_combo.currentText(), "palette_path": self.palette_edit.text().strip(), "output_path": self.output_edit.text().strip()}

    def _apply_preset(self, preset: dict[str, str]) -> None:
        self.mode_combo.setCurrentText(preset.get("mode", self.mode_combo.currentText()))
        self.palette_edit.setText(preset.get("palette_path", self.palette_edit.text()))
        self.output_edit.setText(preset.get("output_path", self.output_edit.text()))

    def _make_browse_row(self, parent: QtWidgets.QVBoxLayout, label: str, callback, field_name: str) -> tuple[QtWidgets.QLineEdit, QtWidgets.QLabel]:
        wrap = QtWidgets.QVBoxLayout()
        row = QtWidgets.QHBoxLayout()
        field_label = QtWidgets.QLabel(label)
        field_label.setMinimumWidth(UI_LABEL_WIDTH)
        row.addWidget(field_label)
        edit = DropPathLineEdit(acceptor=lambda _p: (False, None), on_accept=lambda _p: None, on_reject=self._set_status_warning)
        browse = QtWidgets.QPushButton("Browse…")
        browse.clicked.connect(callback)
        recent = QtWidgets.QToolButton()
        recent.setText("▼")
        recent.setToolTip("Recent paths")
        row.addWidget(edit, 1)
        row.addWidget(browse)
        row.addWidget(recent)
        self._apply_recent_menu(recent, edit, field_name)
        error = QtWidgets.QLabel()
        error.setStyleSheet("color: #d93025; font-size: 11px;")
        error.setVisible(False)
        wrap.addLayout(row)
        wrap.addWidget(error)
        parent.addLayout(wrap)
        return edit, error

    def _update_validation_state(self) -> bool:
        errors = {
            "input": _validate_path(self.input_edit.text().strip(), label="Input", expected_suffixes=(".bmp", ".png", ".mip")),
            "palette": _validate_path(self.palette_edit.text().strip(), label="Palette", expected_suffixes=(".pcx",)),
            "output": _validate_path(self.output_edit.text().strip(), label="Output", expected_suffixes=(".bmp", ".png", ".mip"), must_exist=False),
        }
        _set_field_error(self.input_edit, self.input_error, errors["input"])
        _set_field_error(self.palette_edit, self.palette_error, errors["palette"])
        _set_field_error(self.output_edit, self.output_error, errors["output"])
        problems = [name for name, err in errors.items() if err]
        valid = not problems
        self.to_mip_btn.setEnabled(valid)
        self.from_mip_btn.setEnabled(valid)
        self.set_status(STATUS_IDLE if valid else STATUS_VALIDATING, "Ready" if valid else f"Missing/invalid: {', '.join(problems)}")
        return valid

    def _browse_input(self) -> None:
        path, _ = QtWidgets.QFileDialog.getOpenFileName(
            self,
            "Select input file",
            "",
            "Images/MIP (*.bmp *.png *.mip);;All files (*.*)",
        )
        if path:
            self.input_edit.setText(path)
            self._record_recent_path("input", path)

    def _browse_palette(self) -> None:
        path, _ = QtWidgets.QFileDialog.getOpenFileName(self, "Select palette file", "", "PCX (*.pcx);;All files (*.*)")
        if path:
            self.palette_edit.setText(path)
            self._record_recent_path("palette", path)

    def _browse_output(self) -> None:
        path, _ = QtWidgets.QFileDialog.getSaveFileName(self, "Select output file")
        if path:
            self.output_edit.setText(path)
            self._record_recent_path("output", path)

    def _convert_to_mip(self) -> None:
        if not self._update_validation_state():
            return
        try:
            input_path = Path(self.input_edit.text().strip())
            palette_path = Path(self.palette_edit.text().strip())
            output_path = Path(self.output_edit.text().strip())
            mode = self.mode_combo.currentText()
            image = Image.open(input_path)
            quantized = image.convert("P")
            if not _confirm_summary(
                self,
                dimensions=_fmt_dimensions(quantized),
                output_format="MIP",
                palette_source=str(palette_path),
                destination=output_path,
            ):
                self.set_status(STATUS_IDLE, "Conversion cancelled.")
                return
            img_to_mip(quantized, str(output_path), str(palette_path), mode)
            self.set_status(STATUS_SUCCESS, f"Created MIP: {output_path}")
        except Exception as exc:  # pragma: no cover
            self.set_status(STATUS_FAILURE, f"MIP conversion failed: {exc}")
            QtWidgets.QMessageBox.critical(self, "MIP conversion failed", str(exc))

    def _convert_from_mip(self) -> None:
        if not self._update_validation_state():
            return
        try:
            input_path = Path(self.input_edit.text().strip())
            palette_path = Path(self.palette_edit.text().strip())
            output_path = Path(self.output_edit.text().strip())
            palette = load_palette(str(palette_path))
            mip_images = mip_to_img(str(input_path), palette)
            preview_image = mip_images[0]
            if not _confirm_summary(
                self,
                dimensions=_fmt_dimensions(preview_image),
                output_format=output_path.suffix.lstrip(".").upper() or "Image",
                palette_source=str(palette_path),
                destination=output_path,
            ):
                self.set_status(STATUS_IDLE, "Export cancelled.")
                return
            preview_image.save(output_path)
            self.set_status(STATUS_SUCCESS, f"Created image: {output_path}")
        except Exception as exc:  # pragma: no cover
            self.set_status(STATUS_FAILURE, f"MIP extraction failed: {exc}")
            QtWidgets.QMessageBox.critical(self, "MIP extraction failed", str(exc))


class ChopHorizonWidget(QtWidgets.QWidget, SharedStatusMixin):
    def _set_status_warning(self, message: str) -> None:
        self.status_label.setText(message)

    def __init__(self, parent: QtWidgets.QWidget | None = None) -> None:
        super().__init__(parent)
        self._build_ui()

    def _build_ui(self) -> None:
        layout = QtWidgets.QVBoxLayout(self)
        _apply_panel_layout(layout)
        section, section_layout = _make_section_card("1. Choose input")
        section_layout.addWidget(QtWidgets.QLabel("Mode and input files"))
        layout.addWidget(section)
        self.input_edit, self.input_error = self._make_browse_row(layout, "Source horizon image (2048x64):", self._browse_input)
        self.input_edit._acceptor = lambda p: (len(p)==1 and p[0].is_file() and p[0].suffix.lower() in {".png", ".bmp"}, "Drop a .png or .bmp image.")
        self.input_edit._on_accept = lambda p: self.input_edit.setText(str(p[0]))

        layout.addWidget(QtWidgets.QLabel("2. Configure options"))

        layout.addWidget(QtWidgets.QLabel("3. Export"))
        self.output_edit, self.output_error = self._make_browse_row(layout, "Output folder:", self._browse_output)
        self.output_edit._acceptor = lambda p: (len(p)==1 and p[0].is_dir(), "Drop a folder path.")
        self.output_edit._on_accept = lambda p: self.output_edit.setText(str(p[0]))

        layout.addStretch(1)
        self.run_btn = QtWidgets.QPushButton("Run")
        _set_primary_button(self.run_btn)
        self.run_btn.clicked.connect(self._run)
        self.status_label = QtWidgets.QLabel()
        action_row = QtWidgets.QHBoxLayout()
        action_row.addStretch(1)
        action_row.addWidget(self.run_btn)
        layout.addLayout(action_row)
        layout.addWidget(self.status_label)
        self.input_edit.textChanged.connect(self._update_validation_state)
        self.output_edit.textChanged.connect(self._update_validation_state)
        self._update_validation_state()

    def _make_browse_row(self, parent: QtWidgets.QVBoxLayout, label: str, callback) -> tuple[QtWidgets.QLineEdit, QtWidgets.QLabel]:
        wrap = QtWidgets.QVBoxLayout()
        row = QtWidgets.QHBoxLayout()
        field_label = QtWidgets.QLabel(label)
        field_label.setMinimumWidth(UI_LABEL_WIDTH)
        row.addWidget(field_label)
        edit = DropPathLineEdit(acceptor=lambda _p: (False, None), on_accept=lambda _p: None, on_reject=self._set_status_warning)
        browse = QtWidgets.QPushButton("Browse…")
        browse.clicked.connect(callback)
        row.addWidget(edit, 1)
        row.addWidget(browse)
        error = QtWidgets.QLabel()
        error.setStyleSheet("color: #d93025; font-size: 11px;")
        error.setVisible(False)
        wrap.addLayout(row)
        wrap.addWidget(error)
        parent.addLayout(wrap)
        return edit, error

    def _update_validation_state(self) -> bool:
        input_error = _validate_path(self.input_edit.text().strip(), label="Input", expected_suffixes=(".png", ".bmp"))
        output_error = _validate_path(
            self.output_edit.text().strip(),
            label="Output folder",
            expected_suffixes=(),
            folder_only=True,
        )
        _set_field_error(self.input_edit, self.input_error, input_error)
        _set_field_error(self.output_edit, self.output_error, output_error)
        problems = [name for name, err in (("input", input_error), ("output", output_error)) if err]
        valid = not problems
        self.run_btn.setEnabled(valid)
        self.set_status(STATUS_IDLE if valid else STATUS_VALIDATING, "Ready" if valid else f"Missing/invalid: {', '.join(problems)}")
        return valid

    def _browse_input(self) -> None:
        path, _ = QtWidgets.QFileDialog.getOpenFileName(self, "Select source image", "", "Images (*.png *.bmp)")
        if path:
            self.input_edit.setText(path)
            if not self.output_edit.text().strip():
                self.output_edit.setText(str(Path(path).parent))

    def _browse_output(self) -> None:
        folder = QtWidgets.QFileDialog.getExistingDirectory(self, "Select output folder")
        if folder:
            self.output_edit.setText(folder)

    def _run(self) -> None:
        if not self._update_validation_state():
            return
        try:
            out1, out2 = chop_horizon(self.input_edit.text().strip(), self.output_edit.text().strip())
            self.set_status(STATUS_SUCCESS, f"Created: {out1.name}, {out2.name}")
        except Exception as exc:  # pragma: no cover
            self.set_status(STATUS_FAILURE, f"Chop Horizon failed: {exc}")
            QtWidgets.QMessageBox.critical(self, "Chop Horizon failed", str(exc))


class PmpConversionWidget(QtWidgets.QWidget, SharedStatusMixin, PresettableMixin):
    TOOL_PRESET_KEY = "png_to_pmp"
    def _set_status_warning(self, message: str) -> None:
        self.status_label.setText(message)

    def __init__(self, settings: SunnyOptimizerSettings, parent: QtWidgets.QWidget | None = None) -> None:
        super().__init__(parent)
        self._settings = settings
        self._build_ui()

    def _build_ui(self) -> None:
        layout = QtWidgets.QVBoxLayout(self)
        _apply_panel_layout(layout)
        section, section_layout = _make_section_card("1. Choose input")
        section_layout.addWidget(QtWidgets.QLabel("Mode and input files"))
        layout.addWidget(section)
        self.input_edit = self._make_browse_row(layout, "Input image (.png):", self._browse_input)
        self.input_edit._acceptor = lambda p: (len(p)==1 and p[0].is_file() and p[0].suffix.lower()==".png", "Drop a .png image.")
        self.input_edit._on_accept = lambda p: self.input_edit.setText(str(p[0]))

        layout.addWidget(QtWidgets.QLabel("2. Configure options"))
        self.palette_edit = self._make_browse_row(layout, "Palette file (.pcx):", self._browse_palette)
        self.palette_edit._acceptor = lambda p: (len(p)==1 and p[0].is_file() and p[0].suffix.lower()==".pcx", "Drop a .pcx palette file.")
        self.palette_edit._on_accept = lambda p: self.palette_edit.setText(str(p[0]))
        self.palette_edit.setText("SUNNY.PCX")

        advanced_box = QtWidgets.QGroupBox("Advanced")
        advanced_box.setCheckable(True)
        advanced_box.setChecked(False)
        advanced_layout = QtWidgets.QVBoxLayout(advanced_box)

        settings_row = QtWidgets.QHBoxLayout()
        settings_row.addWidget(QtWidgets.QLabel("Header bytes 002-003 override (hex):"))
        self.size_field = QtWidgets.QLineEdit("0000")
        self.size_field.setMaxLength(4)
        self.size_field.setFixedWidth(100)
        self.size_field.setToolTip(
            "Optional hex override for PMP header bytes 002-003. Leave 0000 to use auto-generated origin offsets."
        )
        settings_row.addWidget(self.size_field)
        settings_row.addSpacing(16)
        settings_row.addWidget(QtWidgets.QLabel("Treat alpha ≤ as transparent:"))
        self.alpha_threshold_spin = QtWidgets.QSpinBox()
        self.alpha_threshold_spin.setRange(0, 255)
        self.alpha_threshold_spin.setValue(51)
        self.alpha_threshold_spin.setToolTip("51 means pixels that are at least 80% transparent are dropped.")
        settings_row.addWidget(self.alpha_threshold_spin)
        settings_row.addStretch(1)
        advanced_layout.addLayout(settings_row)

        note = QtWidgets.QLabel(
            "Note: bytes 000-001 are bbox width/height. By default bytes 002-003 "
            "store signed Int8 values for -left/-top bbox origin offsets; non-zero "
            "override value writes raw bytes 002-003."
        )
        note.setWordWrap(True)
        advanced_layout.addWidget(note)
        layout.addWidget(advanced_box)

        layout.addWidget(QtWidgets.QLabel("3. Export"))
        self.output_edit = self._make_browse_row(layout, "Output file (.pmp):", self._browse_output)
        self.output_edit._acceptor = lambda p: (len(p)==1 and (p[0].suffix.lower()==".pmp" or not p[0].exists()), "Drop a .pmp output file path.")
        self.output_edit._on_accept = lambda p: self.output_edit.setText(str(p[0]))

        layout.addStretch(1)
        self._build_preset_controls(layout)
        convert_btn = QtWidgets.QPushButton("Convert")
        _set_primary_button(convert_btn)
        convert_btn.clicked.connect(self._convert)
        self.status_label = QtWidgets.QLabel()
        self.status_label.setWordWrap(True)
        action_row = QtWidgets.QHBoxLayout()
        action_row.addStretch(1)
        action_row.addWidget(convert_btn)
        layout.addLayout(action_row)
        self.preview_pane = PreviewPane("Output preview")
        layout.addWidget(self.preview_pane)
        layout.addWidget(self.status_label)
        self.set_status(STATUS_IDLE, "Ready")
        self.input_edit.textChanged.connect(self._refresh_preview)
        self._refresh_preview()

    def _refresh_preview(self) -> None:
        raw = self.input_edit.text().strip()
        if not raw:
            self.preview_pane.clear_preview()
            return
        try:
            preview = Image.open(raw)
            self.preview_pane.set_preview(preview, caption=f"{_fmt_dimensions(preview)} • PNG source")
        except Exception as exc:
            self.preview_pane.clear_preview(f"Preview unavailable: {exc}")

    def _collect_preset_values(self) -> dict[str, str]:
        return {"palette_path": self.palette_edit.text().strip(), "output_path": self.output_edit.text().strip(), "alpha_threshold": str(self.alpha_threshold_spin.value()), "header_size": self.size_field.text().strip()}

    def _apply_preset(self, preset: dict[str, str]) -> None:
        self.palette_edit.setText(preset.get("palette_path", self.palette_edit.text()))
        self.output_edit.setText(preset.get("output_path", self.output_edit.text()))
        self.size_field.setText(preset.get("header_size", self.size_field.text()))
        try:
            self.alpha_threshold_spin.setValue(int(preset.get("alpha_threshold", str(self.alpha_threshold_spin.value()))))
        except ValueError:
            pass

    def _make_browse_row(self, parent: QtWidgets.QVBoxLayout, label: str, callback) -> QtWidgets.QLineEdit:
        row = QtWidgets.QHBoxLayout()
        row.addWidget(QtWidgets.QLabel(label))
        edit = DropPathLineEdit(acceptor=lambda _p: (False, None), on_accept=lambda _p: None, on_reject=self._set_status_warning)
        browse = QtWidgets.QPushButton("Browse…")
        browse.clicked.connect(callback)
        row.addWidget(edit, 1)
        row.addWidget(browse)
        parent.addLayout(row)
        return edit

    def _browse_input(self) -> None:
        path, _ = QtWidgets.QFileDialog.getOpenFileName(self, "Select PNG input", "", "PNG (*.png);;All files (*.*)")
        if path:
            self.input_edit.setText(path)
            if not self.output_edit.text().strip():
                self.output_edit.setText(str(Path(path).with_suffix(".pmp")))

    def _browse_output(self) -> None:
        path, _ = QtWidgets.QFileDialog.getSaveFileName(self, "Select PMP output", "", "PMP (*.pmp);;All files (*.*)")
        if path:
            self.output_edit.setText(path)

    def _browse_palette(self) -> None:
        path, _ = QtWidgets.QFileDialog.getOpenFileName(self, "Select palette file", "", "PCX (*.pcx *.PCX);;All files (*.*)")
        if path:
            self.palette_edit.setText(path)

    def _convert(self) -> None:
        try:
            self.set_status(STATUS_PROCESSING, "Converting PNG to PMP...")
            raw = self.size_field.text().strip()
            if raw.lower().startswith("0x"):
                raw = raw[2:]
            size_field = int(raw, 16)
            if not 0 <= size_field <= 0xFFFF:
                raise ValueError("Header size field must be in range 0000..FFFF")
            palette_raw = self.palette_edit.text().strip()
            palette_path = palette_raw if palette_raw else None
            input_image = Image.open(self.input_edit.text().strip())
            if not _confirm_summary(
                self,
                dimensions=_fmt_dimensions(input_image),
                output_format="PMP",
                palette_source=palette_path or "default internal palette",
                destination=Path(self.output_edit.text().strip()),
            ):
                self.set_status(STATUS_IDLE, "Conversion cancelled.")
                return
            out = png_to_pmp(
                self.input_edit.text().strip(),
                self.output_edit.text().strip(),
                size_field=size_field,
                palette_path=palette_path,
                alpha_transparent_threshold=self.alpha_threshold_spin.value(),
            )
            self.set_status(STATUS_SUCCESS, f"Created PMP: {out}")
        except Exception as exc:  # pragma: no cover
            self.set_status(STATUS_FAILURE, f"PMP conversion failed: {exc}")
            QtWidgets.QMessageBox.critical(self, "PMP conversion failed", str(exc))


class PmpToPngWidget(QtWidgets.QWidget, SharedStatusMixin, PresettableMixin):
    TOOL_PRESET_KEY = "pmp_to_png"
    def _set_status_warning(self, message: str) -> None:
        self.status_label.setText(message)

    def __init__(self, settings: SunnyOptimizerSettings, parent: QtWidgets.QWidget | None = None) -> None:
        super().__init__(parent)
        self._settings = settings
        self._build_ui()

    def _build_ui(self) -> None:
        layout = QtWidgets.QVBoxLayout(self)
        _apply_panel_layout(layout)
        section, section_layout = _make_section_card("1. Choose input")
        section_layout.addWidget(QtWidgets.QLabel("Mode and input files"))
        layout.addWidget(section)
        self.input_edit = self._make_browse_row(layout, "Input file (.pmp):", self._browse_input)
        self.input_edit._acceptor = lambda p: (len(p)==1 and p[0].is_file() and p[0].suffix.lower()==".pmp", "Drop a .pmp file.")
        self.input_edit._on_accept = lambda p: self.input_edit.setText(str(p[0]))

        layout.addWidget(QtWidgets.QLabel("2. Configure options"))
        self.palette_edit = self._make_browse_row(layout, "Palette file (.pcx):", self._browse_palette)
        self.palette_edit._acceptor = lambda p: (len(p)==1 and p[0].is_file() and p[0].suffix.lower()==".pcx", "Drop a .pcx palette file.")
        self.palette_edit._on_accept = lambda p: self.palette_edit.setText(str(p[0]))
        self.palette_edit.setText("SUNNY.PCX")

        advanced_box = QtWidgets.QGroupBox("Advanced")
        advanced_box.setCheckable(True)
        advanced_box.setChecked(False)
        advanced_layout = QtWidgets.QVBoxLayout(advanced_box)
        self.crop_checkbox = QtWidgets.QCheckBox("Crop transparent border")
        advanced_layout.addWidget(self.crop_checkbox)
        layout.addWidget(advanced_box)

        layout.addWidget(QtWidgets.QLabel("3. Export"))
        self.output_edit = self._make_browse_row(layout, "Output image (.png):", self._browse_output)
        self.output_edit._acceptor = lambda p: (len(p)==1 and (p[0].suffix.lower()==".png" or not p[0].exists()), "Drop a .png output file path.")
        self.output_edit._on_accept = lambda p: self.output_edit.setText(str(p[0]))

        layout.addStretch(1)
        self._build_preset_controls(layout)
        convert_btn = QtWidgets.QPushButton("Export")
        _set_primary_button(convert_btn)
        convert_btn.clicked.connect(self._convert)
        self.status_label = QtWidgets.QLabel()
        self.status_label.setWordWrap(True)
        action_row = QtWidgets.QHBoxLayout()
        action_row.addStretch(1)
        action_row.addWidget(convert_btn)
        layout.addLayout(action_row)
        self.preview_pane = PreviewPane("Output preview")
        layout.addWidget(self.preview_pane)
        layout.addWidget(self.status_label)
        self.set_status(STATUS_IDLE, "Ready")
        self.input_edit.textChanged.connect(self._refresh_preview)
        self.palette_edit.textChanged.connect(self._refresh_preview)
        self.crop_checkbox.toggled.connect(self._refresh_preview)
        self._refresh_preview()

    def _refresh_preview(self) -> None:
        input_path = self.input_edit.text().strip()
        palette_path = self.palette_edit.text().strip()
        if not input_path:
            self.preview_pane.clear_preview()
            return
        if not palette_path:
            self.preview_pane.clear_preview("Palette file required for preview.")
            return
        try:
            preview = mip_to_img(input_path, load_palette(palette_path))[0]
            if self.crop_checkbox.isChecked():
                preview = preview.crop(preview.getbbox()) if preview.getbbox() else preview
            self.preview_pane.set_preview(preview, caption=f"{_fmt_dimensions(preview)} • PNG output preview")
        except Exception as exc:
            self.preview_pane.clear_preview(f"Preview unavailable: {exc}")

    def _collect_preset_values(self) -> dict[str, str]:
        return {"palette_path": self.palette_edit.text().strip(), "output_path": self.output_edit.text().strip(), "crop_transparent_border": str(self.crop_checkbox.isChecked())}

    def _apply_preset(self, preset: dict[str, str]) -> None:
        self.palette_edit.setText(preset.get("palette_path", self.palette_edit.text()))
        self.output_edit.setText(preset.get("output_path", self.output_edit.text()))
        self.crop_checkbox.setChecked(preset.get("crop_transparent_border", "False").lower() == "true")

    def _make_browse_row(self, parent: QtWidgets.QVBoxLayout, label: str, callback) -> QtWidgets.QLineEdit:
        row = QtWidgets.QHBoxLayout()
        row.addWidget(QtWidgets.QLabel(label))
        edit = DropPathLineEdit(acceptor=lambda _p: (False, None), on_accept=lambda _p: None, on_reject=self._set_status_warning)
        browse = QtWidgets.QPushButton("Browse…")
        browse.clicked.connect(callback)
        row.addWidget(edit, 1)
        row.addWidget(browse)
        parent.addLayout(row)
        return edit

    def _browse_input(self) -> None:
        path, _ = QtWidgets.QFileDialog.getOpenFileName(self, "Select PMP input", "", "PMP (*.pmp);;All files (*.*)")
        if path:
            self.input_edit.setText(path)
            if not self.output_edit.text().strip():
                self.output_edit.setText(str(Path(path).with_suffix(".png")))

    def _browse_output(self) -> None:
        path, _ = QtWidgets.QFileDialog.getSaveFileName(self, "Select PNG output", "", "PNG (*.png);;All files (*.*)")
        if path:
            self.output_edit.setText(path)

    def _browse_palette(self) -> None:
        path, _ = QtWidgets.QFileDialog.getOpenFileName(self, "Select palette file", "", "PCX (*.pcx *.PCX);;All files (*.*)")
        if path:
            self.palette_edit.setText(path)

    def _convert(self) -> None:
        try:
            self.set_status(STATUS_PROCESSING, "Exporting PNG from PMP...")
            palette_path = self.palette_edit.text().strip()
            input_path = self.input_edit.text().strip()
            output_path = Path(self.output_edit.text().strip())
            preview_palette = load_palette(palette_path)
            preview_image = mip_to_img(input_path, preview_palette)[0]
            if not _confirm_summary(
                self,
                dimensions=_fmt_dimensions(preview_image),
                output_format="PNG",
                palette_source=palette_path,
                destination=output_path,
            ):
                self.set_status(STATUS_IDLE, "Export cancelled.")
                return
            convert_pmp_to_png(
                input_path,
                str(output_path),
                palette_path,
                crop=self.crop_checkbox.isChecked(),
            )
            self.set_status(STATUS_SUCCESS, f"Created PNG: {output_path}")
        except Exception as exc:  # pragma: no cover
            self.set_status(STATUS_FAILURE, f"PMP conversion failed: {exc}")
            QtWidgets.QMessageBox.critical(self, "PMP conversion failed", str(exc))


class TextureToolsWindow(QtWidgets.QMainWindow):
    def __init__(self) -> None:
        super().__init__()
        self.setWindowTitle("Texture Tools")
        self.resize(980, 720)
        self.setStyleSheet(
            """
            QFrame#sectionCard { background: #f8f9fb; border: 1px solid #d9dce3; border-radius: 8px; }
            QLabel#sectionTitle { font-weight: 700; }
            QPushButton[primary="true"] { background: #2b6de6; color: white; font-weight: 700; padding: 6px 12px; border-radius: 6px; }
            QPushButton[secondary="true"] { background: #f1f3f6; color: #374151; border: 1px solid #d1d5db; padding: 5px 10px; border-radius: 6px; }
            """
        )
        self._settings = SunnyOptimizerSettings(SunnyOptimizerSettings.default_path())
        self._settings.load()

        self.intent_tabs = QtWidgets.QTabWidget()
        self.intent_tabs.setCornerWidget(self._build_overview_button(), QtCore.Qt.TopRightCorner)
        self.intent_tabs.addTab(self._build_optimize_palette_tab(), "Optimize palette")
        self.intent_tabs.addTab(self._build_convert_formats_tab(), "Convert formats")
        self.intent_tabs.addTab(self._build_split_prepare_tab(), "Split/prepare textures")
        self.setCentralWidget(self.intent_tabs)

        QtCore.QTimer.singleShot(0, self._show_overview_dialog)

    def _build_overview_button(self) -> QtWidgets.QPushButton:
        button = QtWidgets.QPushButton("Welcome / Overview")
        button.clicked.connect(self._show_overview_dialog)
        return button

    def _show_overview_dialog(self) -> None:
        message = (
            "Welcome to Texture Tools.\n\n"
            "Workflows by intent:\n"
            "• Optimize palette: Sunny Optimizer (embedded in this window).\n"
            "• Convert formats: MIP and PMP encode/decode tools.\n"
            "• Split/prepare textures: Chop Horizon helper.\n\n"
            "Sunny Optimizer now lives directly in the Optimize palette tab for a single-window workflow."
        )
        QtWidgets.QMessageBox.information(self, "Texture Tools Overview", message)

    def _build_optimize_palette_tab(self) -> QtWidgets.QWidget:
        sunny = SunnyOptimizerWindow()
        sunny.setWindowFlags(QtCore.Qt.Widget)
        sunny.setWindowTitle("Sunny Optimizer")
        return sunny

    def _build_convert_formats_tab(self) -> QtWidgets.QWidget:
        tabs = QtWidgets.QTabWidget()
        tabs.addTab(MipConversionWidget(self._settings), "MIP Conversion")
        tabs.addTab(PmpConversionWidget(self._settings), "PNG → PMP")
        tabs.addTab(PmpToPngWidget(self._settings), "PMP → PNG")
        return tabs

    def _build_split_prepare_tab(self) -> QtWidgets.QWidget:
        tabs = QtWidgets.QTabWidget()
        tabs.addTab(ChopHorizonWidget(), "Chop Horizon")
        return tabs


def main() -> None:
    app = QtWidgets.QApplication.instance() or QtWidgets.QApplication(sys.argv)
    window = TextureToolsWindow()
    window.show()
    app.exec_()


if __name__ == "__main__":
    main()
