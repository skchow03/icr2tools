import pytest

pytest.importorskip("PyQt5")

from PyQt5 import QtWidgets

from icr2_core.cam.helpers import CameraPosition, Type6CameraParameters
from track_viewer.model.camera_models import CameraViewEntry, CameraViewListing
from track_viewer.sidebar.coordinate_sidebar import CoordinateSidebar



def _app() -> QtWidgets.QApplication:
    app = QtWidgets.QApplication.instance()
    if app is None:
        app = QtWidgets.QApplication([])
    return app



def _type6_camera(index: int) -> CameraPosition:
    return CameraPosition(
        camera_type=6,
        index=index,
        x=1000 + index,
        y=2000 + index,
        z=3000,
        type6=Type6CameraParameters(
            middle_point=50,
            start_point=0,
            start_zoom=1,
            middle_point_zoom=2,
            end_point=100,
            end_zoom=3,
        ),
        raw_values=(0,) * 9,
    )



def test_add_camera_button_appears_above_camera_list() -> None:
    _app()
    sidebar = CoordinateSidebar()

    layout = sidebar.layout()
    assert layout.itemAt(0).widget().text() == "Track cameras"
    assert layout.itemAt(1).widget().text() == "Add camera"
    assert layout.itemAt(2).widget().text() == "Delete camera"
    assert layout.itemAt(3).widget().text() == "Generate Elevation"
    assert layout.itemAt(4).widget() is sidebar._camera_list



def test_selecting_camera_from_list_updates_tv_panel_selection_state() -> None:
    _app()
    sidebar = CoordinateSidebar()
    cameras = [_type6_camera(0), _type6_camera(1)]
    views = [
        CameraViewListing(
            view=1,
            label="TV1",
            entries=[
                CameraViewEntry(
                    camera_index=0,
                    type_index=0,
                    camera_type=6,
                    start_dlong=0,
                    end_dlong=100,
                )
            ],
        )
    ]
    sidebar.set_cameras(cameras, views)
    sidebar._camera_list.setCurrentRow(1)

    selected_indices: list[int | None] = []

    def _capture(index: int | None) -> None:
        selected_indices.append(index)

    original_select_camera = sidebar._tv_panel.select_camera
    sidebar._tv_panel.select_camera = _capture  # type: ignore[method-assign]
    try:
        sidebar.update_selected_camera_details(1, cameras[1])
    finally:
        sidebar._tv_panel.select_camera = original_select_camera  # type: ignore[method-assign]

    assert selected_indices == [1]
