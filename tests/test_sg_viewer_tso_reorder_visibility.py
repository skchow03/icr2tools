import pytest

pytest.importorskip("PyQt5")

from PyQt5 import QtWidgets

from sg_viewer.io.track3d_parser import Track3DObjectList
from sg_viewer.model.sg_model import SectionPreview
from sg_viewer.services.trackside_elevation import TsoBoundaryElevationContext
from sg_viewer.services.trackside_objects import TracksideObject
from sg_viewer.ui.main_window import SGViewerWindow
from sg_viewer.ui.viewer_controller import SGViewerController
from track_viewer.geometry import build_centerline_index


@pytest.fixture
def qapp():
    app = QtWidgets.QApplication.instance()
    if app is None:
        app = QtWidgets.QApplication([])
    return app


def test_moving_tso_updates_visibility_assignments(qapp) -> None:
    _ = qapp
    window = SGViewerWindow()
    controller = SGViewerController(window)
    try:
        controller._trackside_objects = [
            TracksideObject(
                filename="A", x=0, y=0, z=0, yaw=0, pitch=0, tilt=0, description="first"
            ),
            TracksideObject(
                filename="B",
                x=0,
                y=0,
                z=0,
                yaw=0,
                pitch=0,
                tilt=0,
                description="second",
            ),
            TracksideObject(
                filename="C", x=0, y=0, z=0, yaw=0, pitch=0, tilt=0, description="third"
            ),
        ]
        window.tso_visibility_sidebar.set_object_lists(
            [Track3DObjectList(side="L", section=0, sub_index=0, tso_ids=[0, 2])]
        )
        controller._refresh_tso_table()
        window.tso_table.selectRow(0)

        controller._on_tso_move_down_requested()

        assert [obj.filename for obj in controller._trackside_objects] == [
            "B",
            "A",
            "C",
        ]
        assert window.tso_visibility_sidebar.object_lists[0].tso_ids == [1, 2]
    finally:
        window.close()


def _hairpin_context() -> TsoBoundaryElevationContext:
    points = [(0.0, 0.0), (100.0, 0.0), (100.0, 10.0), (0.0, 10.0), (0.0, 0.0)]
    dlongs = [0.0, 100.0, 110.0, 210.0, 220.0]
    sections = []
    for index, (start, end) in enumerate(zip(points, points[1:])):
        sections.append(
            SectionPreview(
                section_id=index,
                source_section_id=index,
                type_name="straight",
                previous_id=(index - 1) % 4,
                next_id=(index + 1) % 4,
                start=start,
                end=end,
                start_dlong=dlongs[index],
                length=dlongs[index + 1] - dlongs[index],
                center=None,
                sang1=None,
                sang2=None,
                eang1=None,
                eang2=None,
                radius=None,
                start_heading=None,
                end_heading=None,
                polyline=[start, end],
            )
        )
    bounds = (0.0, 100.0, 0.0, 10.0)
    return TsoBoundaryElevationContext(
        centerline_index=build_centerline_index(points, bounds),
        sampled_dlongs=dlongs,
        sections=sections,
        track_length=220.0,
        get_section_fsects=lambda _index: [],
        sample_elevation_at_dlat=lambda _index, _progress, _dlat: None,
    )


def test_auto_add_projects_against_selected_hairpin_interval(qapp, monkeypatch) -> None:
    _ = qapp
    window = SGViewerWindow()
    controller = SGViewerController(window)
    try:
        controller._trackside_objects = [
            TracksideObject(filename="shared", x=50, y=2, z=0),
            TracksideObject(filename="wrong-side", x=40, y=12, z=0),
            TracksideObject(filename="far", x=30, y=-1, z=0),
            TracksideObject(filename="existing", x=60, y=1, z=0),
        ]
        sidebar = window.tso_visibility_sidebar
        sidebar.set_object_lists(
            [
                Track3DObjectList(side="L", section=0, sub_index=0, tso_ids=[0]),
                Track3DObjectList(side="L", section=2, sub_index=0, tso_ids=[3]),
            ]
        )
        sidebar._subsection_dlong_ranges = {(2, 0): (110.0, 210.0)}
        monkeypatch.setattr(
            controller,
            "_build_tso_boundary_elevation_context",
            _hairpin_context,
        )

        added = controller._auto_add_tsos_to_object_list(1, 9.0)

        assert added == 1
        assert sidebar.object_lists[0].tso_ids == [0]
        assert set(sidebar.object_lists[1].tso_ids) == {0, 3}
    finally:
        window.close()


def test_auto_add_handles_wrapped_range_side_distance_and_existing_id(
    qapp, monkeypatch
) -> None:
    _ = qapp
    window = SGViewerWindow()
    controller = SGViewerController(window)
    try:
        controller._trackside_objects = [
            TracksideObject(filename="shared", x=70, y=8, z=0),
            TracksideObject(filename="wrong-side", x=60, y=-2, z=0),
            TracksideObject(filename="far", x=50, y=12, z=0),
            TracksideObject(filename="existing", x=80, y=7, z=0),
        ]
        sidebar = window.tso_visibility_sidebar
        sidebar.set_object_lists(
            [
                Track3DObjectList(side="L", section=2, sub_index=0, tso_ids=[0]),
                Track3DObjectList(side="L", section=3, sub_index=0, tso_ids=[3]),
            ]
        )
        sidebar._subsection_dlong_ranges = {(3, 0): (210.0, 100.0)}
        monkeypatch.setattr(
            controller,
            "_build_tso_boundary_elevation_context",
            _hairpin_context,
        )

        added = controller._auto_add_tsos_to_object_list(1, 9.0)

        assert added == 1
        assert sidebar.object_lists[0].tso_ids == [0]
        assert set(sidebar.object_lists[1].tso_ids) == {0, 3}
    finally:
        window.close()
