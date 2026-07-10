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


def test_tso_attributes_dialog_notes_matching_filename_fields_and_has_no_manual_apply_button(qapp):
    dialog = TracksideObjectAttributesDialog()
    try:
        assert (
            dialog._matching_filename_note.text()
            == "BBox, sprite, and rotation point fields apply to all TSOs with the same filename."
        )
        assert not any(
            button.text() == "Apply BBox/Pivot to matches"
            for button in dialog.findChildren(QtWidgets.QPushButton)
        )
    finally:
        dialog.close()

def test_track3d_bbox_import_converts_from_selected_source_unit(qapp):
    from sg_viewer.io.track3d_parser import Track3DBoundingBox

    dialog = TracksideObjectAttributesDialog()
    try:
        bbox = Track3DBoundingBox(min_x=0, min_y=0, max_x=2, max_y=3)

        dialog.set_measurement_unit("500ths")
        assert dialog._track3d_bbox_values_for_source_unit(bbox, "feet") == (
            12000,
            18000,
        )
        assert dialog._track3d_bbox_values_for_source_unit(bbox, "inch") == (
            1000,
            1500,
        )

        dialog.set_measurement_unit("feet")
        length, width = dialog._track3d_bbox_values_for_source_unit(bbox, "meter")
        assert length == pytest.approx(6.5616666667)
        assert width == pytest.approx(9.8425)
    finally:
        dialog.close()
