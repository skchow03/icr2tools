#!/usr/bin/env python3
"""
ICR2 Building Generator (UI + .3D writer)

PyQt5 application that generates Papyrus/ICR2 .3D building objects.

Supported roof types
- none (no roof)
- flat
- parapet (inset roof cap)
- gable (simple pitched roof)
- pyramid (4-sided pitched roof)
- dome (for circular buildings)
"""

from __future__ import annotations

import configparser
import math
import sys
from pathlib import Path


INI_PATH = Path(__file__).with_suffix(".ini")
TEMPLATE_SECTION_PREFIX = "template:"

TEMPLATE_FIELDS = (
    "building_shape",
    "rect_center_origin",
    "width",
    "depth",
    "height",
    "diameter",
    "num_sides",
    "roof_type",
    "parapet_inset",
    "parapet_height",
    "gable_rise",
    "pyramid_rise",
    "dome_layers",
    "dome_roundness",
    "sunny_pcx",
    "roof_color_bright",
    "roof_color_dark",
    "side_color_bright",
    "side_color_dark",
)


# ------------------------------------------------------------
# Geometry generation
# ------------------------------------------------------------

def generate_base(width, depth, height):
    verts = {}

    verts["a0"] = (0, depth, 0)
    verts["b0"] = (0, 0, 0)
    verts["c0"] = (width, 0, 0)
    verts["d0"] = (width, depth, 0)

    verts["a1"] = (0, depth, height)
    verts["b1"] = (0, 0, height)
    verts["c1"] = (width, 0, height)
    verts["d1"] = (width, depth, height)

    faces = [
        ("ls1", ["a1", "a0", "b0", "b1"]),
        ("fr1", ["b1", "b0", "c0", "c1"]),
        ("rs1", ["c1", "c0", "d0", "d1"]),
        ("bk1", ["d1", "d0", "a0", "a1"]),
    ]

    return verts, faces


def add_flat_roof(faces):
    faces += [
        ("topB", ["a1", "b1", "c1"]),
        ("topD", ["a1", "c1", "d1"]),
    ]


def add_parapet_roof(verts, faces, width, depth, height, inset, roof_height):
    verts["a2"] = (inset, depth - inset, height + roof_height)
    verts["b2"] = (inset, inset, height + roof_height)
    verts["c2"] = (width - inset, inset, height + roof_height)
    verts["d2"] = (width - inset, depth - inset, height + roof_height)

    faces += [
        ("ls2", ["a2", "a1", "b1", "b2"]),
        ("fr2", ["b2", "b1", "c1", "c2"]),
        ("rs2", ["c2", "c1", "d1", "d2"]),
        ("bk2", ["d2", "d1", "a1", "a2"]),
        ("roofB", ["a2", "b2", "c2"]),
        ("roofD", ["a2", "c2", "d2"]),
    ]


def add_gable_roof(verts, faces, width, depth, height, rise):
    verts["r0"] = (width // 2, 0, height + rise)
    verts["r1"] = (width // 2, depth, height + rise)

    faces += [
        ("roofL", ["a1", "b1", "r0", "r1"]),
        ("roofR", ["c1", "d1", "r1", "r0"]),
        ("gableF", ["b1", "c1", "r0"]),
        ("gableB", ["d1", "a1", "r1"]),
    ]


def add_pyramid_roof(verts, faces, width, depth, height, rise):
    verts["p0"] = (width // 2, depth // 2, height + rise)

    faces += [
        ("pyrF", ["b1", "c1", "p0"]),
        ("pyrR", ["c1", "d1", "p0"]),
        ("pyrB", ["d1", "a1", "p0"]),
        ("pyrL", ["a1", "b1", "p0"]),
    ]


def generate_circular_base(diameter, sides, height):
    verts = {}
    faces = []
    radius = diameter / 2.0
    for i in range(sides):
        angle = (2.0 * math.pi * i) / sides
        x = radius * math.cos(angle)
        y = radius * math.sin(angle)
        verts[f"cb{i}"] = (int(round(x)), int(round(y)), 0)
        verts[f"ct{i}"] = (int(round(x)), int(round(y)), height)

    for i in range(sides):
        nxt = (i + 1) % sides
        theta = (2.0 * math.pi * (i + 0.5)) / sides
        side_prefix = "sideB" if (math.cos(theta) - math.sin(theta)) >= 0 else "sideD"
        faces.append((f"{side_prefix}{i}", [f"ct{i}", f"cb{i}", f"cb{nxt}", f"ct{nxt}"]))

    return verts, faces


def add_circular_flat_roof(verts, faces, sides, diameter, height):
    verts["ctp"] = (0, 0, height)
    for i in range(sides):
        nxt = (i + 1) % sides
        theta = (2.0 * math.pi * (i + 0.5)) / sides
        roof_prefix = "roofB" if (math.cos(theta) - math.sin(theta)) >= 0 else "roofD"
        faces.append((f"{roof_prefix}{i}", [f"ct{i}", f"ct{nxt}", "ctp"]))


def add_circular_dome_roof(verts, faces, diameter, sides, height, dome_layers, dome_roundness):
    radius = diameter / 2.0
    roundness = max(0.0, min(100.0, float(dome_roundness))) / 100.0
    dome_height = radius * roundness
    prev_ring = [f"ct{i}" for i in range(sides)]

    for layer in range(1, dome_layers + 1):
        t = layer / (dome_layers + 1)
        # Use a quarter-circle profile so dome sides curve upward like a capitol dome,
        # instead of tapering linearly into a cone.
        profile_angle = (math.pi / 2.0) * t
        # Keep the profile curved all the way to the top, while lowering total
        # dome height for flatter stadium-like roofs.
        ring_radius = radius * math.cos(profile_angle)
        ring_z = height + (dome_height * math.sin(profile_angle))
        ring_names = []
        for i in range(sides):
            angle = (2.0 * math.pi * i) / sides
            x = ring_radius * math.cos(angle)
            y = ring_radius * math.sin(angle)
            name = f"dr{layer}_{i}"
            verts[name] = (int(round(x)), int(round(y)), int(round(ring_z)))
            ring_names.append(name)

        for i in range(sides):
            nxt = (i + 1) % sides
            theta = (2.0 * math.pi * (i + 0.5)) / sides
            roof_prefix = "roofB" if (math.cos(theta) - math.sin(theta)) >= 0 else "roofD"
            faces.append((f"{roof_prefix}L{layer}_{i}", [prev_ring[i], prev_ring[nxt], ring_names[nxt], ring_names[i]]))

        prev_ring = ring_names

    top_z = height + int(round(dome_height))
    verts["dome_top"] = (0, 0, top_z)
    for i in range(sides):
        nxt = (i + 1) % sides
        theta = (2.0 * math.pi * (i + 0.5)) / sides
        roof_prefix = "roofB" if (math.cos(theta) - math.sin(theta)) >= 0 else "roofD"
        faces.append((f"{roof_prefix}Top{i}", [prev_ring[i], prev_ring[nxt], "dome_top"]))


def generate_building(
    width,
    depth,
    height,
    roof_type,
    inset,
    roof_height,
    gable_rise,
    pyramid_rise,
    building_shape="rectangular",
    diameter=320,
    num_sides=12,
    dome_layers=4,
    dome_roundness=100,
    rect_center_origin=False,
):
    if building_shape == "circular":
        verts, faces = generate_circular_base(diameter, num_sides, height)
        if roof_type == "flat":
            add_circular_flat_roof(verts, faces, num_sides, diameter, height)
        elif roof_type == "dome":
            if int(dome_roundness) <= 0:
                add_circular_flat_roof(verts, faces, num_sides, diameter, height)
            else:
                add_circular_dome_roof(verts, faces, diameter, num_sides, height, dome_layers, dome_roundness)
        return verts, faces

    verts, faces = generate_base(width, depth, height)

    if rect_center_origin:
        x_offset = -(width // 2)
        y_offset = -(depth // 2)
        for name, (x, y, z) in list(verts.items()):
            verts[name] = (x + x_offset, y + y_offset, z)

    if roof_type == "flat":
        add_flat_roof(faces)
    elif roof_type == "parapet":
        add_parapet_roof(verts, faces, width, depth, height, inset, roof_height)
    elif roof_type == "gable":
        add_gable_roof(verts, faces, width, depth, height, gable_rise)
    elif roof_type == "pyramid":
        add_pyramid_roof(verts, faces, width, depth, height, pyramid_rise)

    return verts, faces


# ------------------------------------------------------------
# .3D writer
# ------------------------------------------------------------

def write_3d(path, verts, faces, parameters):
    roof_bright = int(parameters["roof_color_bright"])
    roof_dark = int(parameters["roof_color_dark"])
    side_bright = int(parameters["side_color_bright"])
    side_dark = int(parameters["side_color_dark"])
    roof_type = str(parameters.get("roof_type", ""))

    if roof_type == "flat":
        roof_dark = roof_bright

    def color_for_face(name):
        roof_bright_faces = {"topB", "roofB", "roofL", "pyrF", "pyrL"}
        roof_dark_faces = {"topD", "roofD", "roofR", "pyrR", "pyrB"}
        side_bright_faces = {"ls1", "fr1", "ls2", "fr2", "gableF"}
        side_dark_faces = {"rs1", "bk1", "rs2", "bk2", "gableB"}

        if name in roof_bright_faces or name.startswith("roofB"):
            return roof_bright
        if name in roof_dark_faces or name.startswith("roofD"):
            return roof_dark
        if name in side_bright_faces or name.startswith("sideB"):
            return side_bright
        if name in side_dark_faces or name.startswith("sideD"):
            return side_dark
        return side_bright

    lines = []
    lines.append("3D VERSION 3.0;")
    lines.append("% Generated by ICR2 Building Generator")
    for key, value in parameters.items():
        lines.append(f"% {key}: {value}")
    lines.append("")
    lines.append("nil: NIL;")

    for name in verts:
        x, y, z = verts[name]
        lines.append(f"{name}: [<{x}, {y}, {z}>];")

    lines.append("")

    for name, vs in faces:
        v = ", ".join(vs)
        lines.append(f"{name}: POLY <{color_for_face(name)}> {{{v}}};")

    lines.append("")

    prev = "nil"

    for i, (name, vs) in enumerate(faces):
        v1, v2, v3 = vs[:3]
        node = f"o{i}"
        lines.append(f"{node}: BSPF ({v1}, {v2}, {v3}), nil, {name}, {prev};")
        prev = node

    v1, v2, v3 = faces[-1][1][:3]
    lines.append(f"root: BSPF ({v1}, {v2}, {v3}), nil, {faces[-1][0]}, {prev};")

    with open(path, "w", encoding="utf-8") as f:
        f.write("\n".join(lines))


# ------------------------------------------------------------
# UI helpers
# ------------------------------------------------------------

def load_settings():
    config = configparser.ConfigParser()
    config.read(INI_PATH)
    return config


def save_settings(config: configparser.ConfigParser):
    with open(INI_PATH, "w", encoding="utf-8") as ini_file:
        config.write(ini_file)


def set_sunny_path(config: configparser.ConfigParser, sunny_pcx_path: str):
    if not config.has_section("paths"):
        config.add_section("paths")
    config["paths"]["sunny_pcx"] = sunny_pcx_path


def list_template_names(config: configparser.ConfigParser):
    return sorted(
        section[len(TEMPLATE_SECTION_PREFIX):]
        for section in config.sections()
        if section.startswith(TEMPLATE_SECTION_PREFIX)
    )


def get_template_values(config: configparser.ConfigParser, name: str):
    section = f"{TEMPLATE_SECTION_PREFIX}{name}"
    if not config.has_section(section):
        return None
    return {field: config.get(section, field, fallback="") for field in TEMPLATE_FIELDS}


def save_template(config: configparser.ConfigParser, name: str, values):
    section = f"{TEMPLATE_SECTION_PREFIX}{name}"
    if not config.has_section(section):
        config.add_section(section)
    for field in TEMPLATE_FIELDS:
        config[section][field] = str(values.get(field, ""))


def remove_template(config: configparser.ConfigParser, name: str):
    config.remove_section(f"{TEMPLATE_SECTION_PREFIX}{name}")


def load_sunny_palette(path: str | Path):
    data = Path(path).read_bytes()
    if len(data) < 769 or data[-769] != 0x0C:
        raise ValueError("Invalid or missing 256-color PCX palette marker")
    raw = data[-768:]
    return [(raw[i], raw[i + 1], raw[i + 2]) for i in range(0, 768, 3)]


def _ui_imports():
    from PyQt5 import QtCore, QtGui, QtWidgets

    return QtCore, QtGui, QtWidgets


def build_window():
    QtCore, QtGui, QtWidgets = _ui_imports()

    class PaletteMatrixDialog(QtWidgets.QDialog):
        def __init__(self, parent, palette, selected_index: int):
            super().__init__(parent)
            self.setWindowTitle("Pick Palette Color")
            self.selected_index = int(max(0, min(255, selected_index)))

            layout = QtWidgets.QVBoxLayout(self)
            info = QtWidgets.QLabel("Select a palette index (0-255):")
            layout.addWidget(info)

            grid = QtWidgets.QGridLayout()
            grid.setSpacing(2)
            self._tiles = {}

            for index, (r, g, b) in enumerate(palette[:256]):
                tile = QtWidgets.QPushButton(f"{index}")
                tile.setFixedSize(34, 24)
                tile.setToolTip(f"Index {index}: rgb({r}, {g}, {b})")
                tile.setStyleSheet(
                    "QPushButton {"
                    f"background-color: rgb({r}, {g}, {b});"
                    "color: #000;"
                    "border: 1px solid #444;"
                    "font-size: 10px;"
                    "padding: 0px;"
                    "}"
                )
                tile.clicked.connect(lambda _checked=False, idx=index: self._choose(idx))
                grid.addWidget(tile, index // 16, index % 16)
                self._tiles[index] = tile

            layout.addLayout(grid)
            self._apply_selection_outline()

        def _apply_selection_outline(self):
            for index, tile in self._tiles.items():
                if index == self.selected_index:
                    tile.setStyleSheet(tile.styleSheet() + "QPushButton { border: 2px solid #fff; }")

        def _choose(self, index: int):
            self.selected_index = int(index)
            self.accept()

    class PaletteIndexPicker(QtWidgets.QWidget):
        def __init__(self, parent, palette, initial_index: int):
            super().__init__(parent)
            self._palette = list(palette)
            self._index = int(max(0, min(255, initial_index)))

            layout = QtWidgets.QHBoxLayout(self)
            layout.setContentsMargins(0, 0, 0, 0)

            self._preview = QtWidgets.QLabel()
            self._preview.setFixedWidth(90)
            self._button = QtWidgets.QPushButton("Pick...")
            self._button.clicked.connect(self._open_picker)

            layout.addWidget(self._preview)
            layout.addWidget(self._button)
            self._refresh_preview()

        def _refresh_preview(self):
            r, g, b = self._palette[self._index]
            self._preview.setText(f"{self._index:>3} ({r},{g},{b})")
            self._preview.setStyleSheet(
                "QLabel {"
                f"background-color: rgb({r}, {g}, {b});"
                "border: 1px solid #222;"
                "padding: 2px;"
                "}"
            )

        def _open_picker(self):
            dialog = PaletteMatrixDialog(self, self._palette, self._index)
            if dialog.exec_() != QtWidgets.QDialog.Accepted:
                return
            self._index = dialog.selected_index
            self._refresh_preview()

        def set_palette(self, palette):
            self._palette = list(palette)
            self._refresh_preview()

        def set_color_index(self, index: int):
            self._index = int(max(0, min(255, index)))
            self._refresh_preview()

        def color_index(self):
            return self._index

    class MainWindow(QtWidgets.QMainWindow):
        def __init__(self):
            super().__init__()
            self.setWindowTitle("ICR2 Building Generator")
            self.palette = [(0, 0, 0)] * 256
            self.settings = load_settings()
            self._build_ui()

        def _build_ui(self):
            central = QtWidgets.QWidget(self)
            self.setCentralWidget(central)
            root_layout = QtWidgets.QHBoxLayout(central)

            self.template_list = QtWidgets.QListWidget()
            self.template_list.setMinimumWidth(220)
            self.save_template_btn = QtWidgets.QPushButton("Save Template")
            self.load_template_btn = QtWidgets.QPushButton("Load Selected")
            self.remove_template_btn = QtWidgets.QPushButton("Remove Selected")

            self.save_template_btn.clicked.connect(self.save_template_clicked)
            self.load_template_btn.clicked.connect(self.load_template_clicked)
            self.remove_template_btn.clicked.connect(self.remove_template_clicked)

            template_layout = QtWidgets.QVBoxLayout()
            template_layout.addWidget(QtWidgets.QLabel("Templates"))
            template_layout.addWidget(self.template_list, 1)
            template_layout.addWidget(self.save_template_btn)
            template_layout.addWidget(self.load_template_btn)
            template_layout.addWidget(self.remove_template_btn)

            form_widget = QtWidgets.QWidget()
            layout = QtWidgets.QGridLayout(form_widget)
            root_layout.addLayout(template_layout)
            root_layout.addWidget(form_widget, 1)

            self.width_spin = QtWidgets.QSpinBox()
            self.width_spin.setRange(1, 50000)
            self.width_spin.setValue(320)

            self.depth_spin = QtWidgets.QSpinBox()
            self.depth_spin.setRange(1, 50000)
            self.depth_spin.setValue(1042)

            self.height_spin = QtWidgets.QSpinBox()
            self.height_spin.setRange(1, 50000)
            self.height_spin.setValue(100)

            self.shape_combo = QtWidgets.QComboBox()
            self.shape_combo.addItems(["rectangular", "circular"])
            self.shape_combo.currentTextChanged.connect(self.update_shape_field_visibility)

            self.roof_combo = QtWidgets.QComboBox()
            self.roof_combo.currentTextChanged.connect(self.update_roof_field_visibility)

            self.inset_spin = QtWidgets.QSpinBox()
            self.inset_spin.setRange(0, 50000)
            self.inset_spin.setValue(30)

            self.roof_height_spin = QtWidgets.QSpinBox()
            self.roof_height_spin.setRange(0, 50000)
            self.roof_height_spin.setValue(15)

            self.gable_spin = QtWidgets.QSpinBox()
            self.gable_spin.setRange(0, 50000)
            self.gable_spin.setValue(50)

            self.pyramid_spin = QtWidgets.QSpinBox()
            self.pyramid_spin.setRange(0, 50000)
            self.pyramid_spin.setValue(50)

            self.diameter_spin = QtWidgets.QSpinBox()
            self.diameter_spin.setRange(1, 50000)
            self.diameter_spin.setValue(320)

            self.sides_spin = QtWidgets.QSpinBox()
            self.sides_spin.setRange(3, 256)
            self.sides_spin.setValue(16)

            self.dome_layers_spin = QtWidgets.QSpinBox()
            self.dome_layers_spin.setRange(1, 256)
            self.dome_layers_spin.setValue(4)

            self.dome_roundness_spin = QtWidgets.QSpinBox()
            self.dome_roundness_spin.setRange(0, 100)
            self.dome_roundness_spin.setSuffix("%")
            self.dome_roundness_spin.setValue(100)

            self.rect_center_check = QtWidgets.QCheckBox("Center rectangular building at (0,0)")

            self.roof_bright_picker = PaletteIndexPicker(self, self.palette, 200)
            self.roof_dark_picker = PaletteIndexPicker(self, self.palette, 201)
            self.side_bright_picker = PaletteIndexPicker(self, self.palette, 202)
            self.side_dark_picker = PaletteIndexPicker(self, self.palette, 203)
            self.color_pickers = [
                self.roof_bright_picker,
                self.roof_dark_picker,
                self.side_bright_picker,
                self.side_dark_picker,
            ]

            self.sunny_edit = QtWidgets.QLineEdit(self.settings.get("paths", "sunny_pcx", fallback=""))
            self.sunny_browse = QtWidgets.QPushButton("Browse...")
            self.sunny_browse.clicked.connect(self.load_sunny_pcx_clicked)

            self.generate_btn = QtWidgets.QPushButton("Generate .3D")
            self.generate_btn.clicked.connect(self.generate_clicked)

            self.form_rows = {}

            def add_form_row(row, field_name, label_text, widget):
                label = QtWidgets.QLabel(label_text)
                layout.addWidget(label, row, 0)
                layout.addWidget(widget, row, 1)
                self.form_rows[field_name] = (label, widget)

            row_specs = [
                ("building_shape", "Building Shape", self.shape_combo),
                ("rect_center_origin", "Rect Origin", self.rect_center_check),
                ("width", "Width", self.width_spin),
                ("depth", "Depth", self.depth_spin),
                ("diameter", "Diameter", self.diameter_spin),
                ("num_sides", "Number of Sides", self.sides_spin),
                ("height", "Height", self.height_spin),
                ("roof_type", "Roof Type", self.roof_combo),
                ("parapet_inset", "Parapet Inset", self.inset_spin),
                ("parapet_height", "Parapet Height", self.roof_height_spin),
                ("gable_rise", "Gable Rise", self.gable_spin),
                ("pyramid_rise", "Pyramid Rise", self.pyramid_spin),
                ("dome_layers", "Dome Layers", self.dome_layers_spin),
                ("dome_roundness", "Dome Roundness", self.dome_roundness_spin),
                ("roof_color_bright", "Roof Color (Bright)", self.roof_bright_picker),
                ("roof_color_dark", "Roof Color (Dark)", self.roof_dark_picker),
                ("side_color_bright", "Side Color (Bright)", self.side_bright_picker),
                ("side_color_dark", "Side Color (Dark)", self.side_dark_picker),
            ]
            for row, (field_name, label, widget) in enumerate(row_specs):
                add_form_row(row, field_name, label, widget)

            sunny_row = len(row_specs)
            layout.addWidget(QtWidgets.QLabel("sunny.pcx"), sunny_row, 0)
            path_layout = QtWidgets.QHBoxLayout()
            path_layout.addWidget(self.sunny_edit)
            path_layout.addWidget(self.sunny_browse)
            layout.addLayout(path_layout, sunny_row, 1)
            layout.addWidget(self.generate_btn, sunny_row + 1, 0, 1, 2)

            file_menu = self.menuBar().addMenu("File")
            load_action = QtWidgets.QAction("Load sunny.pcx...", self)
            load_action.triggered.connect(self.load_sunny_pcx_clicked)
            file_menu.addAction(load_action)

            self.refresh_color_combos(defaults=(200, 201, 202, 203))
            if self.sunny_edit.text().strip():
                self.try_load_palette(self.sunny_edit.text().strip(), preserve_selection=True)
            self.refresh_templates()
            self.update_shape_field_visibility(self.shape_combo.currentText())

        def _set_row_visible(self, field_name, is_visible: bool):
            label, widget = self.form_rows[field_name]
            label.setVisible(is_visible)
            widget.setVisible(is_visible)

        def _set_roof_options_for_shape(self, shape: str):
            shape = str(shape)
            options = ["none", "flat", "parapet", "gable", "pyramid"] if shape == "rectangular" else ["none", "flat", "dome"]
            current = self.roof_combo.currentText()
            self.roof_combo.blockSignals(True)
            self.roof_combo.clear()
            self.roof_combo.addItems(options)
            self.roof_combo.setCurrentText(current if current in options else options[0])
            self.roof_combo.blockSignals(False)

        def update_shape_field_visibility(self, shape: str):
            shape = str(shape)
            is_rectangular = shape == "rectangular"
            self._set_roof_options_for_shape(shape)
            self._set_row_visible("width", is_rectangular)
            self._set_row_visible("depth", is_rectangular)
            self._set_row_visible("rect_center_origin", is_rectangular)
            self._set_row_visible("diameter", not is_rectangular)
            self._set_row_visible("num_sides", not is_rectangular)
            self.update_roof_field_visibility(self.roof_combo.currentText())

        def update_roof_field_visibility(self, roof_type: str):
            roof_type = str(roof_type)
            shape = self.shape_combo.currentText()
            is_rectangular = shape == "rectangular"
            self._set_row_visible("roof_color_dark", roof_type not in {"none", "flat"})
            self._set_row_visible("parapet_inset", is_rectangular and roof_type == "parapet")
            self._set_row_visible("parapet_height", is_rectangular and roof_type == "parapet")
            self._set_row_visible("gable_rise", is_rectangular and roof_type == "gable")
            self._set_row_visible("pyramid_rise", is_rectangular and roof_type == "pyramid")
            is_dome = (not is_rectangular) and roof_type == "dome"
            self._set_row_visible("dome_layers", is_dome)
            self._set_row_visible("dome_roundness", is_dome)

        def collect_current_values(self):
            return {
                "building_shape": self.shape_combo.currentText(),
                "width": self.width_spin.value(),
                "depth": self.depth_spin.value(),
                "rect_center_origin": self.rect_center_check.isChecked(),
                "diameter": self.diameter_spin.value(),
                "num_sides": self.sides_spin.value(),
                "height": self.height_spin.value(),
                "roof_type": self.roof_combo.currentText(),
                "parapet_inset": self.inset_spin.value(),
                "parapet_height": self.roof_height_spin.value(),
                "gable_rise": self.gable_spin.value(),
                "pyramid_rise": self.pyramid_spin.value(),
                "dome_layers": self.dome_layers_spin.value(),
                "dome_roundness": self.dome_roundness_spin.value(),
                "sunny_pcx": self.sunny_edit.text().strip(),
                "roof_color_bright": self.roof_bright_picker.color_index(),
                "roof_color_dark": self.roof_dark_picker.color_index(),
                "side_color_bright": self.side_bright_picker.color_index(),
                "side_color_dark": self.side_dark_picker.color_index(),
            }

        def apply_values(self, values):
            self.shape_combo.setCurrentText(values.get("building_shape", self.shape_combo.currentText()))
            self.width_spin.setValue(int(values.get("width", self.width_spin.value())))
            self.depth_spin.setValue(int(values.get("depth", self.depth_spin.value())))
            self.rect_center_check.setChecked(str(values.get("rect_center_origin", "False")).lower() in {"1", "true", "yes", "on"})
            self.diameter_spin.setValue(int(values.get("diameter", self.diameter_spin.value())))
            self.sides_spin.setValue(int(values.get("num_sides", self.sides_spin.value())))
            self.height_spin.setValue(int(values.get("height", self.height_spin.value())))
            self.roof_combo.setCurrentText(values.get("roof_type", self.roof_combo.currentText()))
            self.inset_spin.setValue(int(values.get("parapet_inset", self.inset_spin.value())))
            self.roof_height_spin.setValue(int(values.get("parapet_height", self.roof_height_spin.value())))
            self.gable_spin.setValue(int(values.get("gable_rise", self.gable_spin.value())))
            self.pyramid_spin.setValue(int(values.get("pyramid_rise", self.pyramid_spin.value())))
            self.dome_layers_spin.setValue(int(values.get("dome_layers", self.dome_layers_spin.value())))
            self.dome_roundness_spin.setValue(int(values.get("dome_roundness", self.dome_roundness_spin.value())))
            self.sunny_edit.setText(values.get("sunny_pcx", self.sunny_edit.text().strip()))

            self.roof_bright_picker.set_color_index(int(values.get("roof_color_bright", 0)))
            self.roof_dark_picker.set_color_index(int(values.get("roof_color_dark", 0)))
            self.side_bright_picker.set_color_index(int(values.get("side_color_bright", 0)))
            self.side_dark_picker.set_color_index(int(values.get("side_color_dark", 0)))

            path = self.sunny_edit.text().strip()
            if path:
                self.try_load_palette(path, preserve_selection=True)

        def refresh_templates(self):
            current_name = self.template_list.currentItem().text() if self.template_list.currentItem() else ""
            names = list_template_names(self.settings)
            self.template_list.clear()
            self.template_list.addItems(names)
            if current_name in names:
                matches = self.template_list.findItems(current_name, QtCore.Qt.MatchExactly)
                if matches:
                    self.template_list.setCurrentItem(matches[0])

        def save_template_clicked(self):
            name, ok = QtWidgets.QInputDialog.getText(self, "Save Template", "Template name:")
            template_name = name.strip()
            if not ok or not template_name:
                return
            save_template(self.settings, template_name, self.collect_current_values())
            save_settings(self.settings)
            self.refresh_templates()

        def load_template_clicked(self):
            item = self.template_list.currentItem()
            if not item:
                return
            values = get_template_values(self.settings, item.text())
            if values is None:
                QtWidgets.QMessageBox.warning(self, "Template", "Template not found in settings file.")
                return
            self.apply_values(values)

        def remove_template_clicked(self):
            item = self.template_list.currentItem()
            if not item:
                return
            remove_template(self.settings, item.text())
            save_settings(self.settings)
            self.refresh_templates()

        def refresh_color_combos(self, defaults=None):
            defaults = defaults or (0, 1, 2, 3)
            for picker, selected in zip(self.color_pickers, defaults):
                picker.set_palette(self.palette)
                picker.set_color_index(int(selected))

        def load_sunny_pcx_clicked(self):
            path, _ = QtWidgets.QFileDialog.getOpenFileName(
                self,
                "Select sunny.pcx",
                self.sunny_edit.text().strip(),
                "PCX files (*.pcx);;All files (*.*)",
            )
            if not path:
                return
            self.try_load_palette(path, preserve_selection=True)
            self.sunny_edit.setText(path)
            set_sunny_path(self.settings, path)
            save_settings(self.settings)

        def try_load_palette(self, path: str, preserve_selection: bool):
            selections = [picker.color_index() for picker in self.color_pickers]
            try:
                self.palette = load_sunny_palette(path)
                self.refresh_color_combos(defaults=selections if preserve_selection else None)
            except Exception as exc:
                QtWidgets.QMessageBox.warning(self, "Palette Load Error", str(exc))

        def generate_clicked(self):
            try:
                roof = self.roof_combo.currentText()
                path = self.sunny_edit.text().strip()
                if path:
                    self.try_load_palette(path, preserve_selection=True)
                    set_sunny_path(self.settings, path)
                    save_settings(self.settings)

                values = self.collect_current_values()
                verts, faces = generate_building(
                    values["width"],
                    values["depth"],
                    values["height"],
                    roof,
                    values["parapet_inset"],
                    values["parapet_height"],
                    values["gable_rise"],
                    values["pyramid_rise"],
                    values["building_shape"],
                    values["diameter"],
                    values["num_sides"],
                    values["dome_layers"],
                    values["dome_roundness"],
                    values["rect_center_origin"],
                )

                out_path, _ = QtWidgets.QFileDialog.getSaveFileName(
                    self,
                    "Save .3D",
                    "",
                    "3D files (*.3D)",
                )
                if not out_path:
                    return

                params = dict(values)
                params["roof_type"] = roof

                write_3d(out_path, verts, faces, params)
                QtWidgets.QMessageBox.information(self, "Success", "Building generated successfully.")
            except Exception as exc:
                QtWidgets.QMessageBox.critical(self, "Error", str(exc))

    app = QtWidgets.QApplication(sys.argv)
    window = MainWindow()
    window.show()
    app.exec_()


if __name__ == "__main__":
    build_window()
