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
