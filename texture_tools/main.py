from __future__ import annotations

import sys
from pathlib import Path

# Ensure repo root is on sys.path when running this file directly
if __package__ is None or __package__ == "":
    sys.path.append(str(Path(__file__).resolve().parent.parent))

from PIL import Image

try:
    from PyQt5 import QtCore, QtWidgets
except ImportError:  # pragma: no cover
    from PySide6 import QtCore, QtWidgets  # type: ignore

from icr2_core.mip.mips import img_to_mip, load_palette, mip_to_img
from texture_tools.pmp import png_to_pmp
from texture_tools.pmp_to_png import convert_pmp_to_png
from texture_tools.sunny_optimizer.chop_horizon import chop_horizon
from texture_tools.sunny_optimizer.ui.main_window import MainWindow as SunnyOptimizerWindow


class MipConversionWidget(QtWidgets.QWidget):
    def __init__(self, parent: QtWidgets.QWidget | None = None) -> None:
        super().__init__(parent)
        self._build_ui()

    def _build_ui(self) -> None:
        layout = QtWidgets.QVBoxLayout(self)
        layout.addWidget(QtWidgets.QLabel("1. Choose input"))

        mode_row = QtWidgets.QHBoxLayout()
        mode_row.addWidget(QtWidgets.QLabel("Mode:"))
        self.mode_combo = QtWidgets.QComboBox()
        self.mode_combo.addItems(["track", "carset"])
        self.mode_combo.setToolTip("Choose target format rules: 'track' for world textures, 'carset' for vehicle textures.")
        mode_row.addWidget(self.mode_combo)
        mode_row.addStretch(1)
        layout.addLayout(mode_row)

        self.input_edit = self._make_browse_row(layout, "Input image (.bmp/.png) or .mip:", self._browse_input)

        layout.addWidget(QtWidgets.QLabel("2. Configure options"))
        self.palette_edit = self._make_browse_row(layout, "Palette file (.pcx):", self._browse_palette)

        layout.addWidget(QtWidgets.QLabel("3. Export"))
        self.output_edit = self._make_browse_row(layout, "Output file:", self._browse_output)

        layout.addStretch(1)
        convert_row = QtWidgets.QHBoxLayout()
        self.to_mip_btn = QtWidgets.QPushButton("Convert")
        self.to_mip_btn.clicked.connect(self._convert_to_mip)
        self.from_mip_btn = QtWidgets.QPushButton("Export")
        self.from_mip_btn.clicked.connect(self._convert_from_mip)
        convert_row.addWidget(self.to_mip_btn)
        convert_row.addWidget(self.from_mip_btn)
        layout.addLayout(convert_row)

        self.status_label = QtWidgets.QLabel("Ready")
        self.status_label.setWordWrap(True)
        layout.addWidget(self.status_label)

    def _make_browse_row(self, parent: QtWidgets.QVBoxLayout, label: str, callback) -> QtWidgets.QLineEdit:
        row = QtWidgets.QHBoxLayout()
        row.addWidget(QtWidgets.QLabel(label))
        edit = QtWidgets.QLineEdit()
        browse = QtWidgets.QPushButton("Browse…")
        browse.clicked.connect(callback)
        row.addWidget(edit, 1)
        row.addWidget(browse)
        parent.addLayout(row)
        return edit

    def _browse_input(self) -> None:
        path, _ = QtWidgets.QFileDialog.getOpenFileName(
            self,
            "Select input file",
            "",
            "Images/MIP (*.bmp *.png *.mip);;All files (*.*)",
        )
        if path:
            self.input_edit.setText(path)

    def _browse_palette(self) -> None:
        path, _ = QtWidgets.QFileDialog.getOpenFileName(self, "Select palette file", "", "PCX (*.pcx);;All files (*.*)")
        if path:
            self.palette_edit.setText(path)

    def _browse_output(self) -> None:
        path, _ = QtWidgets.QFileDialog.getSaveFileName(self, "Select output file")
        if path:
            self.output_edit.setText(path)

    def _convert_to_mip(self) -> None:
        try:
            input_path = Path(self.input_edit.text().strip())
            palette_path = Path(self.palette_edit.text().strip())
            output_path = Path(self.output_edit.text().strip())
            mode = self.mode_combo.currentText()
            image = Image.open(input_path)
            quantized = image.convert("P")
            img_to_mip(quantized, str(output_path), str(palette_path), mode)
            self.status_label.setText(f"Created MIP: {output_path}")
        except Exception as exc:  # pragma: no cover
            QtWidgets.QMessageBox.critical(self, "MIP conversion failed", str(exc))

    def _convert_from_mip(self) -> None:
        try:
            input_path = Path(self.input_edit.text().strip())
            palette_path = Path(self.palette_edit.text().strip())
            output_path = Path(self.output_edit.text().strip())
            palette = load_palette(str(palette_path))
            mip_images = mip_to_img(str(input_path), palette)
            mip_images[0].save(output_path)
            self.status_label.setText(f"Created image: {output_path}")
        except Exception as exc:  # pragma: no cover
            QtWidgets.QMessageBox.critical(self, "MIP extraction failed", str(exc))


class ChopHorizonWidget(QtWidgets.QWidget):
    def __init__(self, parent: QtWidgets.QWidget | None = None) -> None:
        super().__init__(parent)
        self._build_ui()

    def _build_ui(self) -> None:
        layout = QtWidgets.QVBoxLayout(self)
        layout.addWidget(QtWidgets.QLabel("1. Choose input"))
        self.input_edit = self._make_browse_row(layout, "Source horizon image (2048x64):", self._browse_input)

        layout.addWidget(QtWidgets.QLabel("2. Configure options"))

        layout.addWidget(QtWidgets.QLabel("3. Export"))
        self.output_edit = self._make_browse_row(layout, "Output folder:", self._browse_output)

        layout.addStretch(1)
        run_btn = QtWidgets.QPushButton("Run")
        run_btn.clicked.connect(self._run)
        self.status_label = QtWidgets.QLabel("Ready")
        action_row = QtWidgets.QHBoxLayout()
        action_row.addStretch(1)
        action_row.addWidget(run_btn)
        layout.addLayout(action_row)
        layout.addWidget(self.status_label)

    def _make_browse_row(self, parent: QtWidgets.QVBoxLayout, label: str, callback) -> QtWidgets.QLineEdit:
        row = QtWidgets.QHBoxLayout()
        row.addWidget(QtWidgets.QLabel(label))
        edit = QtWidgets.QLineEdit()
        browse = QtWidgets.QPushButton("Browse…")
        browse.clicked.connect(callback)
        row.addWidget(edit, 1)
        row.addWidget(browse)
        parent.addLayout(row)
        return edit

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
        try:
            out1, out2 = chop_horizon(self.input_edit.text().strip(), self.output_edit.text().strip())
            self.status_label.setText(f"Created: {out1.name}, {out2.name}")
        except Exception as exc:  # pragma: no cover
            QtWidgets.QMessageBox.critical(self, "Chop Horizon failed", str(exc))


class PmpConversionWidget(QtWidgets.QWidget):
    def __init__(self, parent: QtWidgets.QWidget | None = None) -> None:
        super().__init__(parent)
        self._build_ui()

    def _build_ui(self) -> None:
        layout = QtWidgets.QVBoxLayout(self)
        layout.addWidget(QtWidgets.QLabel("1. Choose input"))
        self.input_edit = self._make_browse_row(layout, "Input image (.png):", self._browse_input)

        layout.addWidget(QtWidgets.QLabel("2. Configure options"))
        self.palette_edit = self._make_browse_row(layout, "Palette file (.pcx):", self._browse_palette)
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

        layout.addStretch(1)
        convert_btn = QtWidgets.QPushButton("Convert")
        convert_btn.clicked.connect(self._convert)
        self.status_label = QtWidgets.QLabel("Ready")
        self.status_label.setWordWrap(True)
        action_row = QtWidgets.QHBoxLayout()
        action_row.addStretch(1)
        action_row.addWidget(convert_btn)
        layout.addLayout(action_row)
        layout.addWidget(self.status_label)

    def _make_browse_row(self, parent: QtWidgets.QVBoxLayout, label: str, callback) -> QtWidgets.QLineEdit:
        row = QtWidgets.QHBoxLayout()
        row.addWidget(QtWidgets.QLabel(label))
        edit = QtWidgets.QLineEdit()
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
            raw = self.size_field.text().strip()
            if raw.lower().startswith("0x"):
                raw = raw[2:]
            size_field = int(raw, 16)
            if not 0 <= size_field <= 0xFFFF:
                raise ValueError("Header size field must be in range 0000..FFFF")
            palette_raw = self.palette_edit.text().strip()
            palette_path = palette_raw if palette_raw else None
            out = png_to_pmp(
                self.input_edit.text().strip(),
                self.output_edit.text().strip(),
                size_field=size_field,
                palette_path=palette_path,
                alpha_transparent_threshold=self.alpha_threshold_spin.value(),
            )
            self.status_label.setText(f"Created PMP: {out}")
        except Exception as exc:  # pragma: no cover
            QtWidgets.QMessageBox.critical(self, "PMP conversion failed", str(exc))


class PmpToPngWidget(QtWidgets.QWidget):
    def __init__(self, parent: QtWidgets.QWidget | None = None) -> None:
        super().__init__(parent)
        self._build_ui()

    def _build_ui(self) -> None:
        layout = QtWidgets.QVBoxLayout(self)
        layout.addWidget(QtWidgets.QLabel("1. Choose input"))
        self.input_edit = self._make_browse_row(layout, "Input file (.pmp):", self._browse_input)

        layout.addWidget(QtWidgets.QLabel("2. Configure options"))
        self.palette_edit = self._make_browse_row(layout, "Palette file (.pcx):", self._browse_palette)
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

        layout.addStretch(1)
        convert_btn = QtWidgets.QPushButton("Export")
        convert_btn.clicked.connect(self._convert)
        self.status_label = QtWidgets.QLabel("Ready")
        self.status_label.setWordWrap(True)
        action_row = QtWidgets.QHBoxLayout()
        action_row.addStretch(1)
        action_row.addWidget(convert_btn)
        layout.addLayout(action_row)
        layout.addWidget(self.status_label)

    def _make_browse_row(self, parent: QtWidgets.QVBoxLayout, label: str, callback) -> QtWidgets.QLineEdit:
        row = QtWidgets.QHBoxLayout()
        row.addWidget(QtWidgets.QLabel(label))
        edit = QtWidgets.QLineEdit()
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
            convert_pmp_to_png(
                self.input_edit.text().strip(),
                self.output_edit.text().strip(),
                self.palette_edit.text().strip(),
                crop=self.crop_checkbox.isChecked(),
            )
            self.status_label.setText(f"Created PNG: {self.output_edit.text().strip()}")
        except Exception as exc:  # pragma: no cover
            QtWidgets.QMessageBox.critical(self, "PMP conversion failed", str(exc))


class TextureToolsWindow(QtWidgets.QMainWindow):
    def __init__(self) -> None:
        super().__init__()
        self.setWindowTitle("Texture Tools")
        self.resize(960, 700)

        tabs = QtWidgets.QTabWidget()
        tabs.setCornerWidget(self._build_overview_button(), QtCore.Qt.TopRightCorner)
        tabs.addTab(self._build_sunny_tab(), "Palette Optimizer")
        tabs.addTab(ChopHorizonWidget(), "Chop Horizon")
        tabs.addTab(MipConversionWidget(), "MIP Conversion")
        tabs.addTab(PmpConversionWidget(), "PNG → PMP")
        tabs.addTab(PmpToPngWidget(), "PMP → PNG")
        self.setCentralWidget(tabs)

        self._sunny_windows: list[SunnyOptimizerWindow] = []
        QtCore.QTimer.singleShot(0, self._show_overview_dialog)

    def _build_overview_button(self) -> QtWidgets.QPushButton:
        button = QtWidgets.QPushButton("Welcome / Overview")
        button.clicked.connect(self._show_overview_dialog)
        return button

    def _show_overview_dialog(self) -> None:
        message = (
            "Welcome to Texture Tools.\n\n"
            "Tabs:\n"
            "• Palette Optimizer: launch Sunny Optimizer for multi-texture palette balancing.\n"
            "• Chop Horizon: split a 2048x64 horizon strip into game-ready sheets.\n"
            "• MIP Conversion: convert image ↔ MIP using a palette.\n"
            "• PNG → PMP: encode indexed PMP sprites.\n"
            "• PMP → PNG: decode PMP back to PNG for editing.\n\n"
            "Recommended start:\n"
            "1) Build or tune palette in Palette Optimizer.\n"
            "2) Convert assets with PNG ↔ PMP or MIP tools.\n"
            "3) Use Chop Horizon for sky/horizon sheets when needed."
        )
        QtWidgets.QMessageBox.information(self, "Texture Tools Overview", message)

    def _build_sunny_tab(self) -> QtWidgets.QWidget:
        container = QtWidgets.QWidget()
        layout = QtWidgets.QVBoxLayout(container)
        text = QtWidgets.QLabel(
            "Launch the full Sunny Optimizer window from here. "
            "This keeps all texture-focused tools grouped under Texture Tools."
        )
        text.setWordWrap(True)
        button = QtWidgets.QPushButton("Open Sunny Optimizer")
        button.clicked.connect(self._open_sunny_optimizer)
        layout.addWidget(text)
        layout.addWidget(button)
        layout.addStretch(1)
        return container

    def _open_sunny_optimizer(self) -> None:
        window = SunnyOptimizerWindow()
        window.setAttribute(QtCore.Qt.WA_DeleteOnClose, True)
        window.setWindowTitle("Texture Tools - Sunny Optimizer")
        window.destroyed.connect(lambda *_: self._sunny_windows.remove(window) if window in self._sunny_windows else None)
        self._sunny_windows.append(window)
        window.show()


def main() -> None:
    app = QtWidgets.QApplication.instance() or QtWidgets.QApplication(sys.argv)
    window = TextureToolsWindow()
    window.show()
    app.exec_()


if __name__ == "__main__":
    main()
