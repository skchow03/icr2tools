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
from texture_tools.sunny_optimizer.chop_horizon import chop_horizon
from texture_tools.sunny_optimizer.ui.main_window import MainWindow as SunnyOptimizerWindow


class MipConversionWidget(QtWidgets.QWidget):
    def __init__(self, parent: QtWidgets.QWidget | None = None) -> None:
        super().__init__(parent)
        self._build_ui()

    def _build_ui(self) -> None:
        layout = QtWidgets.QVBoxLayout(self)

        mode_row = QtWidgets.QHBoxLayout()
        mode_row.addWidget(QtWidgets.QLabel("Mode:"))
        self.mode_combo = QtWidgets.QComboBox()
        self.mode_combo.addItems(["track", "carset"])
        mode_row.addWidget(self.mode_combo)
        mode_row.addStretch(1)
        layout.addLayout(mode_row)

        self.input_edit = self._make_browse_row(layout, "Input image (.bmp/.png) or .mip:", self._browse_input)
        self.palette_edit = self._make_browse_row(layout, "Palette file (.pcx):", self._browse_palette)
        self.output_edit = self._make_browse_row(layout, "Output file:", self._browse_output)

        convert_row = QtWidgets.QHBoxLayout()
        self.to_mip_btn = QtWidgets.QPushButton("Convert Image → MIP")
        self.to_mip_btn.clicked.connect(self._convert_to_mip)
        self.from_mip_btn = QtWidgets.QPushButton("Convert MIP → BMP")
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
        self.input_edit = self._make_browse_row(layout, "Source horizon image (2048x64):", self._browse_input)
        self.output_edit = self._make_browse_row(layout, "Output folder:", self._browse_output)
        run_btn = QtWidgets.QPushButton("Create 256x256 Sheets")
        run_btn.clicked.connect(self._run)
        self.status_label = QtWidgets.QLabel("Ready")
        layout.addWidget(run_btn)
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


class TextureToolsWindow(QtWidgets.QMainWindow):
    def __init__(self) -> None:
        super().__init__()
        self.setWindowTitle("Texture Tools")
        self.resize(960, 700)

        tabs = QtWidgets.QTabWidget()
        tabs.addTab(self._build_sunny_tab(), "Palette Optimizer")
        tabs.addTab(ChopHorizonWidget(), "Chop Horizon")
        tabs.addTab(MipConversionWidget(), "MIP Conversion")
        self.setCentralWidget(tabs)

        self._sunny_windows: list[SunnyOptimizerWindow] = []

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
