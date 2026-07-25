import pytest

pytest.importorskip("PyQt5")

from PyQt5 import QtWidgets

from sg_viewer.io.track3d_parser import Track3DObjectList
from sg_viewer.services.trackside_objects import TracksideObject
from sg_viewer.ui.main_window import SGViewerWindow
from sg_viewer.ui.viewer_controller import SGViewerController


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


def test_auto_add_to_section_filters_side_and_distance_and_sorts(
    qapp, monkeypatch
) -> None:
    _ = qapp
    window = SGViewerWindow()
    controller = SGViewerController(window)
    try:
        controller._trackside_objects = [
            TracksideObject(filename=name, x=index, y=0, z=0)
            for index, name in enumerate(("existing", "near", "wrong-side", "far"))
        ]
        sidebar = window.tso_visibility_sidebar
        sidebar.set_object_lists(
            [Track3DObjectList(side="R", section=2, sub_index=0, tso_ids=[0])]
        )
        sidebar._subsection_dlong_ranges = {(2, 0): (100.0, 200.0)}
        projections = {
            0: (120.0, -5.0, 4.0),
            1: (150.0, -8.0, 10.0),
            2: (140.0, 7.0, 8.0),
            3: (160.0, -30.0, 12.0),
        }
        monkeypatch.setattr(
            controller,
            "_build_tso_boundary_elevation_context",
            lambda: object(),
        )
        monkeypatch.setattr(
            controller,
            "_project_tso_for_object_list",
            lambda obj, _context: projections[int(obj.x)],
        )

        added = controller._auto_add_tsos_to_object_list(0, 20.0)

        assert added == 1
        assert sidebar.object_lists[0].tso_ids == [1, 0]
    finally:
        window.close()
