"""Nonmodal reference-image calibration dialog for the CAD tracing layer.

Click A and B directly on a preview, then enter the physical AB distance in
raw model units. Live scale, angle and placement never touch N3 source.
"""
from __future__ import annotations

from dataclasses import replace

from PySide6.QtCore import Qt, QRectF, QPointF, Signal
from PySide6.QtGui import QColor, QPainter, QPen, QPixmap
from PySide6.QtWidgets import (
    QCheckBox, QComboBox, QDialog, QDoubleSpinBox, QFormLayout, QGroupBox,
    QHBoxLayout, QLabel, QPushButton, QSlider, QVBoxLayout, QWidget,
)

from tracing_reference import PLANES, calibrate_two_points


class CalibrationCanvas(QWidget):
    pointPicked = Signal(str, object)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.image_width = 0
        self.image_height = 0
        self.pixmap = QPixmap()
        self.point_a = None
        self.point_b = None
        self.pick_target = None
        self.setMinimumSize(400, 300)
        self.setMouseTracking(True)

    def set_image(self, image):
        # Keep the interactive preview bounded even for a large photograph.
        preview = image.scaled(
            1600, 1200, Qt.AspectRatioMode.KeepAspectRatio,
            Qt.TransformationMode.SmoothTransformation)
        self.pixmap = QPixmap.fromImage(preview)
        self.image_width = image.width()
        self.image_height = image.height()
        self.update()

    def set_markers(self, a, b):
        self.point_a, self.point_b = a, b
        self.update()

    def set_pick_target(self, name):
        self.pick_target = name
        self.setCursor(Qt.CursorShape.CrossCursor if name else
                       Qt.CursorShape.ArrowCursor)
        self.update()

    def image_rect(self):
        if not self.image_width or not self.image_height:
            return QRectF()
        scale = min(
            (self.width() - 20) / self.image_width,
            (self.height() - 20) / self.image_height)
        scale = max(0, scale)
        width = self.image_width * scale
        height = self.image_height * scale
        return QRectF((self.width()-width)/2, (self.height()-height)/2,
                      width, height)

    def canvas_to_image(self, point):
        rect = self.image_rect()
        if not rect.contains(point) or rect.width() <= 0 or rect.height() <= 0:
            return None
        return (max(0.0, min(float(self.image_width),
                               (point.x()-rect.left()) / rect.width()
                               * self.image_width)),
                max(0.0, min(float(self.image_height),
                               (point.y()-rect.top()) / rect.height()
                               * self.image_height)))

    def mousePressEvent(self, event):
        if (event.button() == Qt.MouseButton.LeftButton
                and self.pick_target is not None):
            pixel = self.canvas_to_image(event.position())
            if pixel is not None:
                self.pointPicked.emit(self.pick_target, pixel)
                event.accept()
                return
        super().mousePressEvent(event)

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.fillRect(self.rect(), QColor("#17202b"))
        if self.pixmap.isNull():
            return
        painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
        rect = self.image_rect()
        painter.drawPixmap(rect, self.pixmap, QRectF(self.pixmap.rect()))
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        for name, point, color in (
                ("A", self.point_a, QColor("#ffff55")),
                ("B", self.point_b, QColor("#ff8899"))):
            if point is None:
                continue
            x = rect.left() + point[0] / self.image_width * rect.width()
            y = rect.top() + point[1] / self.image_height * rect.height()
            painter.setPen(QPen(color, 2))
            painter.drawLine(QPointF(x-9, y), QPointF(x+9, y))
            painter.drawLine(QPointF(x, y-9), QPointF(x, y+9))
            painter.drawEllipse(QPointF(x, y), 5, 5)
            painter.drawText(QPointF(x+11, y-10), name)
        if self.point_a and self.point_b:
            a, b = self.point_a, self.point_b
            ar = QPointF(rect.left()+a[0]/self.image_width*rect.width(),
                         rect.top()+a[1]/self.image_height*rect.height())
            br = QPointF(rect.left()+b[0]/self.image_width*rect.width(),
                         rect.top()+b[1]/self.image_height*rect.height())
            painter.setPen(QPen(QColor("#fafafa"), 1,
                                Qt.PenStyle.DashLine))
            painter.drawLine(ar, br)
        if self.pick_target:
            painter.setPen(QPen(QColor("#ffffff"), 1))
            painter.drawText(
                QRectF(12, 8, self.width()-24, 30),
                Qt.AlignmentFlag.AlignTop | Qt.AlignmentFlag.AlignLeft,
                f"Click point {self.pick_target} in the image")


class TracingReferenceDialog(QDialog):
    def __init__(self, reference, image, *, mesh, on_change, on_align,
                 on_browse, on_remove, on_save_profile=None,
                 on_load_profile=None, on_delete_profile=None,
                 profile_names=None, parent=None):
        super().__init__(parent)
        self.setObjectName("tracingReferenceDialog")
        self.setWindowTitle("Tracing Reference Image — 3DO CAD")
        self.setModal(False)
        self.resize(1000, 610)
        self.reference = reference
        self.mesh = mesh
        self._on_change = on_change
        self._on_align = on_align
        self._on_browse = on_browse
        self._on_remove = on_remove
        self._on_save_profile = on_save_profile
        self._on_load_profile = on_load_profile
        self._on_delete_profile = on_delete_profile
        self._profile_names = profile_names
        self._setting_controls = False

        outer = QVBoxLayout(self)
        title = QLabel("Calibrate a photo, drawing or blueprint behind the editable model")
        title.setWordWrap(True)
        outer.addWidget(title)
        body = QHBoxLayout()
        outer.addLayout(body, stretch=1)
        left = QVBoxLayout()
        body.addLayout(left, stretch=2)
        self.canvas = CalibrationCanvas()
        self.canvas.set_image(image)
        self.canvas.pointPicked.connect(self._point_picked)
        left.addWidget(self.canvas, stretch=1)
        point_bar = QHBoxLayout()
        self.pick_a = QPushButton("Pick A")
        self.pick_b = QPushButton("Pick B")
        self.pick_a.clicked.connect(lambda: self.canvas.set_pick_target("A"))
        self.pick_b.clicked.connect(lambda: self.canvas.set_pick_target("B"))
        point_bar.addWidget(self.pick_a)
        point_bar.addWidget(self.pick_b)
        self.clear_points = QPushButton("Clear points")
        self.clear_points.clicked.connect(self._clear_points)
        point_bar.addWidget(self.clear_points)
        left.addLayout(point_bar)
        self.points_label = QLabel()
        self.points_label.setWordWrap(True)
        left.addWidget(self.points_label)

        right = QVBoxLayout()
        body.addLayout(right, stretch=1)
        self.path_label = QLabel()
        self.path_label.setWordWrap(True)
        self.path_label.setTextInteractionFlags(
            Qt.TextInteractionFlag.TextSelectableByMouse)
        right.addWidget(self.path_label)
        self.browse = QPushButton("Load another image…")
        self.browse.clicked.connect(self._on_browse)
        right.addWidget(self.browse)
        form = QFormLayout()
        right.addLayout(form)
        self.plane = QComboBox()
        for name, axes in (("Side", "Y / Z"), ("Front", "X / Z"),
                           ("Top", "X / Y")):
            self.plane.addItem(f"{name} ({axes})", name)
        self.plane.currentIndexChanged.connect(self._plane_changed)
        form.addRow("Tracing plane", self.plane)

        self.distance = self._spin(0.000001, 1e12, 4)
        # A useful first guess is the opened model's bounding-box width;
        # Qt's QDoubleSpinBox otherwise starts at the tiny minimum value.
        self.distance.setValue(max(float(mesh.scale) * 2.0, 1.0))
        self.distance.setToolTip(
            "Raw model units between the two photo points, e.g. wheelbase "
            "measured in the model; this is not automatically feet/meters.")
        self.distance.valueChanged.connect(self._calibrate)
        form.addRow("A–B distance (model units)", self.distance)

        self.units = self._spin(0.00000001, 1e12, 8)
        self.units.valueChanged.connect(self._manual_scale)
        form.addRow("Raw units / image pixel", self.units)
        self.rotation = self._spin(-360, 360, 3)
        self.rotation.valueChanged.connect(
            lambda value: self._change(rotation_degrees=value,
                                       calibration_distance=None))
        form.addRow("Image rotation (degrees)", self.rotation)

        self.world_u = self._spin(-1e12, 1e12, 2)
        self.world_v = self._spin(-1e12, 1e12, 2)
        self.world_u.valueChanged.connect(self._position_changed)
        self.world_v.valueChanged.connect(self._position_changed)
        form.addRow("Point A / center world U", self.world_u)
        form.addRow("Point A / center world V", self.world_v)

        self.visible = QCheckBox("Show tracing image")
        self.visible.stateChanged.connect(
            lambda _: self._change(visible=self.visible.isChecked()))
        right.addWidget(self.visible)
        right.addWidget(QLabel("Opacity"))
        self.opacity = QSlider(Qt.Orientation.Horizontal)
        self.opacity.setRange(0, 100)
        self.opacity.valueChanged.connect(
            lambda value: self._change(opacity=value / 100.0))
        right.addWidget(self.opacity)
        self.opacity_text = QLabel()
        right.addWidget(self.opacity_text)
        self.align = QPushButton("Align viewport to this plane (orthographic)")
        self.align.clicked.connect(lambda: self._on_align(self.reference.plane))
        right.addWidget(self.align)
        self.fit = QPushButton("Reset scale and center to model")
        self.fit.clicked.connect(self._fit_model)
        right.addWidget(self.fit)

        # Named references persist outside any particular model. Restoring a
        # profile retains physical calibration while reanchoring its image to
        # the current model's center (or optionally exact saved world U/V).
        profiles_group = QGroupBox("Saved reference profiles")
        profiles_box = QVBoxLayout(profiles_group)
        self.profile_combo = QComboBox()
        self.profile_combo.setObjectName("savedTracingProfiles")
        self.profile_combo.setToolTip(
            "Saved profiles retain image path, calibration markers, physical "
            "scale, rotation, opacity and placement across CAD sessions.")
        profiles_box.addWidget(self.profile_combo)
        self.profile_placement = QComboBox()
        self.profile_placement.addItem(
            "Place relative to current model center", "relative")
        self.profile_placement.addItem(
            "Keep exact saved model coordinates", "absolute")
        self.profile_placement.setToolTip(
            "Relative placement keeps the same raw offset from the model "
            "center on different models; exact placement uses saved U/V.")
        profiles_box.addWidget(self.profile_placement)
        profile_actions = QHBoxLayout()
        self.profile_save_button = QPushButton("Save as…")
        self.profile_save_button.clicked.connect(
            lambda: self._on_save_profile()
            if self._on_save_profile is not None else None)
        profile_actions.addWidget(self.profile_save_button)
        self.profile_load_button = QPushButton("Restore")
        self.profile_load_button.clicked.connect(
            lambda: self._on_load_profile(
                self.profile_combo.currentData(),
                self.profile_placement.currentData())
            if self._on_load_profile is not None and
            self.profile_combo.currentData() else None)
        profile_actions.addWidget(self.profile_load_button)
        self.profile_delete_button = QPushButton("Delete")
        self.profile_delete_button.clicked.connect(
            lambda: self._on_delete_profile(self.profile_combo.currentData())
            if self._on_delete_profile is not None and
            self.profile_combo.currentData() else None)
        profile_actions.addWidget(self.profile_delete_button)
        profiles_box.addLayout(profile_actions)
        right.addWidget(profiles_group)
        self.refresh_profiles()
        right.addStretch(1)

        instructions = QLabel(
            "Click Pick A and a feature in the image, then Pick B and a second "
            "feature. Enter the real distance between them in raw model units. "
            "A is placed at the world U/V coordinates above; B becomes that "
            "distance to the right. You can then adjust position, scale, "
            "rotation and opacity. For a car profile, use the wheel centers; "
            "for a building, use a measured facade width.")
        instructions.setWordWrap(True)
        outer.addWidget(instructions)
        footer = QHBoxLayout()
        remove = QPushButton("Remove image")
        remove.clicked.connect(self._on_remove)
        footer.addWidget(remove)
        footer.addStretch(1)
        close = QPushButton("Close (keep reference)")
        close.clicked.connect(self.close)
        footer.addWidget(close)
        outer.addLayout(footer)
        self._sync_controls()

    def refresh_profiles(self, preferred=None):
        """Refresh without discarding the selected profile/placement mode."""
        if not hasattr(self, "profile_combo"):
            return
        previous = preferred or self.profile_combo.currentData()
        try:
            names = list(self._profile_names()) if self._profile_names else []
        except (OSError, ValueError) as exc:
            names = []
            self.profile_combo.setToolTip(
                f"Cannot read tracing profiles: {exc}")
        self.profile_combo.blockSignals(True)
        self.profile_combo.clear()
        for name in names:
            self.profile_combo.addItem(name, name)
        index = self.profile_combo.findData(previous)
        if index >= 0:
            self.profile_combo.setCurrentIndex(index)
        self.profile_combo.blockSignals(False)
        self.profile_load_button.setEnabled(bool(names))
        self.profile_delete_button.setEnabled(bool(names))
        self.profile_save_button.setEnabled(self._on_save_profile is not None)

    @staticmethod
    def _spin(minimum, maximum, decimals):
        spin = QDoubleSpinBox()
        spin.setDecimals(decimals)
        spin.setRange(minimum, maximum)
        spin.setSingleStep(100 if decimals <= 3 else 0.1)
        spin.setKeyboardTracking(False)
        return spin

    def _sync_controls(self):
        self._setting_controls = True
        try:
            ref = self.reference
            self.path_label.setText(
                f"{ref.path.name} — {ref.width} × {ref.height} pixels")
            self.path_label.setToolTip(str(ref.path))
            self.plane.setCurrentIndex(self.plane.findData(ref.plane))
            self.distance.setValue(
                ref.calibration_distance or self.distance.value() or
                max(self.mesh.scale, 1.0))
            self.units.setValue(ref.units_per_pixel)
            self.rotation.setValue(ref.rotation_degrees)
            self.world_u.setValue(ref.world_anchor[0])
            self.world_v.setValue(ref.world_anchor[1])
            self.visible.setChecked(ref.visible)
            self.opacity.setValue(round(ref.opacity * 100))
            self.opacity_text.setText(f"{round(ref.opacity * 100)}% visible")
            self.canvas.set_markers(ref.point_a, ref.point_b)
            desc = lambda p: (
                f"({p[0]:.1f}, {p[1]:.1f}) px" if p else "not selected")
            self.points_label.setText(
                f"A: {desc(ref.point_a)}    B: {desc(ref.point_b)}")
        finally:
            self._setting_controls = False

    def set_reference(self, reference, image, mesh):
        self.mesh = mesh
        self.reference = reference
        self.canvas.set_image(image)
        self.canvas.set_pick_target(None)
        self._sync_controls()

    def _change(self, **changes):
        if self._setting_controls:
            return
        self.reference = replace(self.reference, **changes)
        self._sync_controls()
        self._on_change(self.reference)

    def _point_picked(self, which, point):
        ref = self.reference
        if which == "A":
            ref = replace(ref, point_a=point, anchor_pixel=point)
            self.canvas.set_pick_target("B")
        else:
            ref = replace(ref, point_b=point)
            self.canvas.set_pick_target(None)
        self.reference = ref
        self._calibrate()
        self._sync_controls()
        self._on_change(self.reference)

    def _calibrate(self, *_):
        if self._setting_controls:
            return
        a, b = self.reference.point_a, self.reference.point_b
        if a is None or b is None:
            return
        try:
            units, angle = calibrate_two_points(a, b, self.distance.value())
        except ValueError:
            self.points_label.setText("Choose two distinct points and a positive distance")
            return
        self.reference = replace(
            self.reference, anchor_pixel=a, units_per_pixel=units,
            rotation_degrees=angle,
            calibration_distance=self.distance.value())
        self._sync_controls()
        self._on_change(self.reference)

    def _clear_points(self):
        self.canvas.set_pick_target(None)
        self._change(point_a=None, point_b=None, calibration_distance=None,
                     anchor_pixel=(self.reference.width / 2,
                                   self.reference.height / 2))

    def _manual_scale(self, value):
        self._change(units_per_pixel=value, calibration_distance=None)

    def _position_changed(self, *_):
        self._change(world_anchor=(self.world_u.value(), self.world_v.value()))

    def _plane_changed(self, *_):
        if self._setting_controls:
            return
        plane = self.plane.currentData()
        u_axis, v_axis, _, _ = PLANES[plane]
        self._change(
            plane=plane,
            world_anchor=(float(self.mesh.center[u_axis]),
                          float(self.mesh.center[v_axis])))

    def _fit_model(self):
        from tracing_reference import initial_reference
        new_ref = initial_reference(
            self.reference.path, self.reference.width,
            self.reference.height, self.mesh, plane=self.reference.plane)
        self.canvas.set_pick_target(None)
        self._change(
            anchor_pixel=new_ref.anchor_pixel,
            world_anchor=new_ref.world_anchor,
            units_per_pixel=new_ref.units_per_pixel,
            rotation_degrees=0, point_a=None, point_b=None,
            calibration_distance=None)
