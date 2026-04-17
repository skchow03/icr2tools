import pytest

try:
    from PyQt5 import QtWidgets
    from sg_viewer.services.trackside_objects import TracksideObject
    from sg_viewer.ui.tso_attributes_dialog import TracksideObjectAttributesDialog
except ImportError:  # pragma: no cover
    pytest.skip("PyQt5 not available", allow_module_level=True)


@pytest.fixture(scope="module")
def qapp():
    app = QtWidgets.QApplication.instance()
    if app is None:
        app = QtWidgets.QApplication([])
    yield app


def test_yaw_slider_emits_preview_update_and_close_resets_preview(qapp):
    dialog = TracksideObjectAttributesDialog()
    try:
        obj = TracksideObject(
            filename="tower.3do",
            x=1,
            y=2,
            z=3,
            yaw=0,
            pitch=0,
            tilt=0,
            description="",
            bbox_length=0,
            bbox_width=0,
            rotation_point="center",
        )
        preview_updates: list[tuple[int, TracksideObject]] = []
        preview_ended = []
        dialog.objectPreviewUpdated.connect(lambda row, updated: preview_updates.append((row, updated)))
        dialog.previewEnded.connect(lambda: preview_ended.append(True))

        dialog.edit_object(4, obj)

        dialog._yaw_slider.setValue(123)

        assert preview_updates
        row, updated = preview_updates[-1]
        assert row == 4
        assert isinstance(updated, TracksideObject)
        assert updated.yaw == 123

        dialog.close()

        assert preview_ended == [True]
    finally:
        dialog.close()


def test_bbox_values_follow_current_measurement_unit(qapp):
    dialog = TracksideObjectAttributesDialog()
    try:
        obj = TracksideObject(
            filename="tower.3do",
            x=1,
            y=2,
            z=3,
            yaw=0,
            pitch=0,
            tilt=0,
            description="",
            bbox_length=6000,
            bbox_width=12000,
            rotation_point="center",
        )
        updates: list[tuple[int, TracksideObject]] = []
        dialog.objectUpdated.connect(lambda row, updated: updates.append((row, updated)))

        dialog.set_measurement_unit("feet")
        dialog.edit_object(0, obj)

        assert dialog._bbox_length_label.text() == "BBox Length (ft)"
        assert dialog._bbox_width_label.text() == "BBox Width (ft)"
        assert dialog._bbox_length_spin.value() == pytest.approx(1.0)
        assert dialog._bbox_width_spin.value() == pytest.approx(2.0)

        dialog._bbox_length_spin.setValue(1.5)
        dialog._bbox_width_spin.setValue(2.25)
        dialog._apply_changes()

        assert updates
        _row, updated = updates[-1]
        assert updated.bbox_length == 9000
        assert updated.bbox_width == 13500
    finally:
        dialog.close()


def test_apply_bbox_pivot_to_matches_confirms_before_emitting(qapp, monkeypatch):
    dialog = TracksideObjectAttributesDialog()
    try:
        obj = TracksideObject(
            filename="tower.3do",
            x=1,
            y=2,
            z=3,
            yaw=0,
            pitch=0,
            tilt=0,
            description="",
            bbox_length=6000,
            bbox_width=12000,
            rotation_point="center",
        )
        dialog.edit_object(2, obj)
        dialog._bbox_length_spin.setValue(3.0)
        dialog._bbox_width_spin.setValue(4.0)
        dialog._rotation_point_combo.setCurrentIndex(dialog._rotation_point_combo.findData("top_left"))

        emitted: list[tuple[int, TracksideObject]] = []
        dialog.matchingFilenameBBoxRotationApplyRequested.connect(lambda row, updated: emitted.append((row, updated)))

        monkeypatch.setattr(QtWidgets.QMessageBox, "question", lambda *args, **kwargs: QtWidgets.QMessageBox.No)
        dialog._apply_bbox_rotation_to_matching_filename()
        assert emitted == []

        monkeypatch.setattr(QtWidgets.QMessageBox, "question", lambda *args, **kwargs: QtWidgets.QMessageBox.Yes)
        dialog._apply_bbox_rotation_to_matching_filename()
        assert len(emitted) == 1
        row, updated = emitted[0]
        assert row == 2
        assert updated.filename == "tower"
        assert updated.bbox_length == 18000
        assert updated.bbox_width == 24000
        assert updated.rotation_point == "top_left"
    finally:
        dialog.close()
