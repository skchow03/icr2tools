from icr2_core.cam.helpers import CameraPosition, Type6CameraParameters, Type7CameraParameters

from track_viewer.controllers.camera_controller import CameraController
from track_viewer.model.camera_models import CameraViewEntry, CameraViewListing


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


def _type7_camera(index: int) -> CameraPosition:
    return CameraPosition(
        camera_type=7,
        index=index,
        x=4000 + index,
        y=5000 + index,
        z=6000,
        type7=Type7CameraParameters(
            z_axis_rotation=1,
            vertical_rotation=2,
            tilt=3,
            zoom=4,
            unknown1=5,
            unknown2=6,
            unknown3=7,
            unknown4=8,
        ),
        raw_values=(0,) * 12,
    )


def test_delete_last_pan_camera_removes_tv_entries_and_renumbers_indices() -> None:
    controller = CameraController()
    cameras = [_type6_camera(0), _type7_camera(0), _type6_camera(1)]
    views = [
        CameraViewListing(
            view=1,
            label="TV1",
            entries=[
                CameraViewEntry(camera_index=0, type_index=0, camera_type=6, start_dlong=0, end_dlong=50),
                CameraViewEntry(camera_index=2, type_index=1, camera_type=6, start_dlong=50, end_dlong=100),
            ],
        ),
        CameraViewListing(
            view=2,
            label="TV2",
            entries=[
                CameraViewEntry(camera_index=2, type_index=1, camera_type=6, start_dlong=100, end_dlong=150),
                CameraViewEntry(camera_index=1, type_index=0, camera_type=7, start_dlong=150, end_dlong=200),
            ],
        ),
    ]

    result = controller.delete_last_camera_of_type(cameras, views, 6, camera_label="pan")

    assert result.success is True
    assert result.message == "Pan camera deleted."
    assert [camera.camera_type for camera in cameras] == [6, 7]
    assert [camera.index for camera in cameras] == [0, 0]
    assert [entry.camera_index for entry in views[0].entries] == [0]
    assert [entry.camera_index for entry in views[1].entries] == [1]
    assert views[1].entries[0].camera_type == 7
    assert views[1].entries[0].type_index == 0
    assert result.selected_camera == 1


def test_delete_last_fixed_camera_reports_missing_camera() -> None:
    controller = CameraController()
    cameras = [_type6_camera(0)]
    views = [
        CameraViewListing(
            view=1,
            label="TV1",
            entries=[
                CameraViewEntry(camera_index=0, type_index=0, camera_type=6, start_dlong=0, end_dlong=100),
            ],
        )
    ]

    result = controller.delete_last_camera_of_type(cameras, views, 7, camera_label="fixed")

    assert result.success is False
    assert result.message == "No fixed cameras are available to delete."
    assert len(cameras) == 1
    assert len(views[0].entries) == 1


def test_delete_camera_removes_it_from_all_tv_modes_and_renumbers() -> None:
    controller = CameraController()
    cameras = [_type6_camera(0), _type7_camera(0), _type6_camera(1), _type7_camera(1)]
    views = [
        CameraViewListing(
            view=1,
            label="TV1",
            entries=[
                CameraViewEntry(camera_index=0, type_index=0, camera_type=6, start_dlong=0, end_dlong=50),
                CameraViewEntry(camera_index=2, type_index=1, camera_type=6, start_dlong=50, end_dlong=100),
                CameraViewEntry(camera_index=3, type_index=1, camera_type=7, start_dlong=100, end_dlong=150),
            ],
        ),
        CameraViewListing(
            view=2,
            label="TV2",
            entries=[
                CameraViewEntry(camera_index=1, type_index=0, camera_type=7, start_dlong=150, end_dlong=200),
                CameraViewEntry(camera_index=3, type_index=1, camera_type=7, start_dlong=200, end_dlong=250),
            ],
        ),
    ]

    result = controller.delete_camera(cameras, views, 1)

    assert result.success is True
    assert result.message == "Camera deleted."
    assert [camera.camera_type for camera in cameras] == [6, 6, 7]
    assert [camera.index for camera in cameras] == [0, 1, 0]
    assert [(entry.camera_index, entry.type_index, entry.camera_type) for entry in views[0].entries] == [
        (0, 0, 6),
        (1, 1, 6),
        (2, 0, 7),
    ]
    assert [(entry.camera_index, entry.type_index, entry.camera_type) for entry in views[1].entries] == [
        (2, 0, 7),
    ]
    assert result.selected_camera == 1
