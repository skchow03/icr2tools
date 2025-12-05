# sg_viewer/section_properties.py
from __future__ import annotations

import math
from typing import Optional

from PyQt5 import QtCore, QtWidgets

from sg_viewer.editor_state import EditorState
from sg_viewer.preview_widget import SectionSelection


class SectionPropertiesPanel(QtWidgets.QWidget):
    """
    Rich panel for viewing/editing SG section parameters.

    Typical wiring from SGViewerWindow:

        self._properties = SectionPropertiesPanel(self)
        self._properties.set_state(self._state)
        self._preview.selectedSectionChanged.connect(self._properties.on_section_changed)
    """

    def __init__(self, parent=None):
        super().__init__(parent)

        self._state: Optional[EditorState] = None
        self._current_selection: Optional[SectionSelection] = None
        self._building_ui = False  # guard to prevent feedback loops

        self._build_ui()

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def set_state(self, state: Optional[EditorState]) -> None:
        self._state = state
        self._update_enabled_state()

    def on_section_changed(self, selection: Optional[SectionSelection]) -> None:
        """Called by the preview widget when section selection changes."""
        self._current_selection = selection
        self._populate_fields_from_selection()

    # ------------------------------------------------------------------
    # UI construction
    # ------------------------------------------------------------------

    def _build_ui(self) -> None:
        layout = QtWidgets.QVBoxLayout(self)
        layout.setContentsMargins(8, 8, 8, 8)
        layout.setSpacing(6)

        title = QtWidgets.QLabel("<b>Section Properties</b>")
        title.setAlignment(QtCore.Qt.AlignCenter)
        layout.addWidget(title)

        # --- General info (index, type, dlong range) ---
        self.index_field = self._make_readonly_field()
        self.type_field = self._make_readonly_field()
        self.start_dlong_field = self._make_readonly_field()
        self.end_dlong_field = self._make_readonly_field()

        self.length_field = QtWidgets.QDoubleSpinBox()
        self.length_field.setDecimals(2)
        self.length_field.setRange(1.0, 1_000_000_000.0)
        self.length_field.valueChanged.connect(self._on_edit_changed)

        self.start_heading_field = QtWidgets.QDoubleSpinBox()
        self.start_heading_field.setDecimals(4)
        self.start_heading_field.setRange(-360.0, 360.0)
        self.start_heading_field.valueChanged.connect(self._on_edit_changed)

        self.end_heading_field = self._make_readonly_field()

        grid = QtWidgets.QGridLayout()
        r = 0

        def add_row(label: str, widget: QtWidgets.QWidget):
            nonlocal r
            grid.addWidget(QtWidgets.QLabel(label), r, 0)
            grid.addWidget(widget, r, 1)
            r += 1

        add_row("Index:", self.index_field)
        add_row("Type:", self.type_field)
        add_row("Start DLong:", self.start_dlong_field)
        add_row("End DLong:", self.end_dlong_field)
        add_row("Length:", self.length_field)
        add_row("Start Heading (deg):", self.start_heading_field)
        add_row("End Heading (deg):", self.end_heading_field)

        layout.addLayout(grid)

        # --- Curve-only group (radius + center) ---
        self.curve_group = QtWidgets.QGroupBox("Curve Geometry")
        curve_layout = QtWidgets.QGridLayout(self.curve_group)

        self.radius_label = QtWidgets.QLabel("Radius:")
        self.radius_field = QtWidgets.QDoubleSpinBox()
        self.radius_field.setDecimals(2)
        # widen range so it doesn't clamp real values
        self.radius_field.setRange(-1_000_000_000.0, 1_000_000_000.0)
        self.radius_field.valueChanged.connect(self._on_edit_changed)

        self.center_x_label = QtWidgets.QLabel("Center X:")
        self.center_x_field = QtWidgets.QDoubleSpinBox()
        self.center_x_field.setDecimals(2)
        self.center_x_field.setRange(-1_000_000_000.0, 1_000_000_000.0)
        self.center_x_field.valueChanged.connect(self._on_edit_changed)

        self.center_y_label = QtWidgets.QLabel("Center Y:")
        self.center_y_field = QtWidgets.QDoubleSpinBox()
        self.center_y_field.setDecimals(2)
        self.center_y_field.setRange(-1_000_000_000.0, 1_000_000_000.0)
        self.center_y_field.valueChanged.connect(self._on_edit_changed)

        cr = 0
        curve_layout.addWidget(self.radius_label, cr, 0)
        curve_layout.addWidget(self.radius_field, cr, 1)
        cr += 1

        curve_layout.addWidget(self.center_x_label, cr, 0)
        curve_layout.addWidget(self.center_x_field, cr, 1)
        cr += 1

        curve_layout.addWidget(self.center_y_label, cr, 0)
        curve_layout.addWidget(self.center_y_field, cr, 1)

        layout.addWidget(self.curve_group)

        # --- Buttons: apply / undo / redo / navigation ---
        apply_btn = QtWidgets.QPushButton("Apply Changes")
        apply_btn.clicked.connect(self._apply_changes)

        undo_btn = QtWidgets.QPushButton("Undo")
        undo_btn.clicked.connect(self._on_undo)

        redo_btn = QtWidgets.QPushButton("Redo")
        redo_btn.clicked.connect(self._on_redo)

        nav_row = QtWidgets.QHBoxLayout()
        prev_btn = QtWidgets.QPushButton("Previous Section")
        next_btn = QtWidgets.QPushButton("Next Section")
        prev_btn.clicked.connect(lambda: self._navigate(-1))
        next_btn.clicked.connect(lambda: self._navigate(+1))
        nav_row.addWidget(prev_btn)
        nav_row.addWidget(next_btn)

        btn_row = QtWidgets.QHBoxLayout()
        btn_row.addWidget(apply_btn)
        btn_row.addWidget(undo_btn)
        btn_row.addWidget(redo_btn)

        layout.addLayout(btn_row)
        layout.addLayout(nav_row)
        layout.addStretch(1)

        self._update_enabled_state()

    @staticmethod
    def _make_readonly_field() -> QtWidgets.QLineEdit:
        field = QtWidgets.QLineEdit()
        field.setReadOnly(True)
        return field

    # ------------------------------------------------------------------
    # State helpers
    # ------------------------------------------------------------------

    def _update_enabled_state(self) -> None:
        enabled = self._state is not None and self._current_selection is not None

        for w in [
            self.length_field,
            self.start_heading_field,
            self.radius_field,
            self.center_x_field,
            self.center_y_field,
        ]:
            w.setEnabled(enabled)

        # hide curve group if not a curve
        is_curve = (
            self._current_selection is not None
            and self._current_selection.type_name == "Curve"
        )
        self.curve_group.setVisible(enabled and is_curve)

    def _clear_fields(self) -> None:
        self.index_field.clear()
        self.type_field.clear()
        self.start_dlong_field.clear()
        self.end_dlong_field.clear()
        self.end_heading_field.clear()

        self.length_field.setValue(0.0)
        self.start_heading_field.setValue(0.0)
        self.radius_field.setValue(0.0)
        self.center_x_field.setValue(0.0)
        self.center_y_field.setValue(0.0)

        self.curve_group.setVisible(False)
        self._update_enabled_state()

    # ------------------------------------------------------------------
    # Populate from current selection
    # ------------------------------------------------------------------

    def _populate_fields_from_selection(self) -> None:
        self._building_ui = True

        sel = self._current_selection
        if sel is None or self._state is None:
            self._clear_fields()
            self._building_ui = False
            return

        sg = self._state.sg
        if sel.index < 0 or sel.index >= sg.num_sects:
            self._clear_fields()
            self._building_ui = False
            return

        sect = sg.sects[sel.index]

        # Index / type / dlong
        self.index_field.setText(str(sel.index))
        self.type_field.setText(sel.type_name)
        self.start_dlong_field.setText(f"{sel.start_dlong:.0f}")
        self.end_dlong_field.setText(f"{sel.end_dlong:.0f}")

        # Length
        self.length_field.setValue(float(sect.length))

        # Start/end heading from SG sin/cos fields
        start_theta_deg = math.degrees(math.atan2(float(sect.sang1), float(sect.sang2)))
        end_theta_deg = math.degrees(math.atan2(float(sect.eang1), float(sect.eang2)))
        self.start_heading_field.setValue(start_theta_deg)
        self.end_heading_field.setText(f"{end_theta_deg:.4f}")

        # Curve-only fields
        is_curve = getattr(sect, "type", 1) == 2
        self.curve_group.setVisible(is_curve)

        if is_curve:
            self.radius_field.setValue(float(sect.radius))
            self.center_x_field.setValue(float(sect.center_x))
            self.center_y_field.setValue(float(sect.center_y))

        self._update_enabled_state()
        self._building_ui = False

    # ------------------------------------------------------------------
    # Field change handling
    # ------------------------------------------------------------------

    def _on_edit_changed(self, *args) -> None:
        # Currently we don't do live updates; this just avoids recursion.
        if self._building_ui:
            return

    # ------------------------------------------------------------------
    # Apply / Undo / Redo / Navigation
    # ------------------------------------------------------------------

    def _apply_changes(self) -> None:
        if self._state is None or self._current_selection is None:
            return

        idx = self._current_selection.index
        sg = self._state.sg
        if idx < 0 or idx >= sg.num_sects:
            return

        sect = sg.sects[idx]

        # Length
        new_length = self.length_field.value()
        if abs(new_length - float(sect.length)) > 1e-6:
            self._state.set_section_length(idx, new_length)

        # Start heading (degrees)
        new_head_deg = self.start_heading_field.value()
        old_head_deg = math.degrees(
            math.atan2(float(sect.sang1), float(sect.sang2))
        )
        if abs(new_head_deg - old_head_deg) > 1e-6:
            self._state.set_section_start_heading_deg(idx, new_head_deg)

        # Curve-specific updates
        if getattr(sect, "type", 1) == 2:
            new_radius = self.radius_field.value()
            if abs(new_radius - float(sect.radius)) > 1e-6:
                self._state.set_section_radius(idx, new_radius)

            new_cx = self.center_x_field.value()
            new_cy = self.center_y_field.value()
            if (
                abs(new_cx - float(sect.center_x)) > 1e-6
                or abs(new_cy - float(sect.center_y)) > 1e-6
            ):
                self._state.set_curve_center(idx, new_cx, new_cy)

        # Refresh preview
        parent = self.parent()
        if parent is not None and hasattr(parent, "_preview"):
            parent._preview.refresh_from_state()

    def _on_undo(self) -> None:
        if self._state is None:
            return
        self._state.undo()
        parent = self.parent()
        if parent is not None and hasattr(parent, "_preview"):
            parent._preview.refresh_from_state()

    def _on_redo(self) -> None:
        if self._state is None:
            return
        self._state.redo()
        parent = self.parent()
        if parent is not None and hasattr(parent, "_preview"):
            parent._preview.refresh_from_state()

    def _navigate(self, direction: int) -> None:
        """
        direction = +1 → next section
        direction = -1 → previous section
        """
        parent = self.parent()
        if parent is None or not hasattr(parent, "_preview"):
            return

        preview = parent._preview
        if direction < 0:
            preview.select_previous_section()
        else:
            preview.select_next_section()
