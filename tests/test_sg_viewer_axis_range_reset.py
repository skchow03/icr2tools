from __future__ import annotations

from PyQt5 import QtWidgets

from sg_viewer.model.preview_fsection import PreviewFSection
from sg_viewer.ui.fsect_diagram_widget import FsectDiagramWidget
from sg_viewer.ui.elevation_profile import ElevationProfileData, elevation_profile_alt_bounds
from sg_viewer.ui.xsect_elevation import XsectElevationData, XsectElevationWidget


def qapp():
    app = QtWidgets.QApplication.instance()
    if app is None:
        app = QtWidgets.QApplication([])
    return app


def test_xsect_elevation_resets_y_view_range_for_new_track_bounds() -> None:
    _ = qapp()
    widget = XsectElevationWidget()
    first = XsectElevationData(
        section_index=0,
        altitudes=[100.0, 100.5, 101.0],
        xsect_dlats=[-5000.0, 0.0, 5000.0],
        y_range=(95.0, 105.0),
    )
    widget.set_xsect_data(first)
    widget._y_view_range = (99.0, 101.0)

    second = XsectElevationData(
        section_index=0,
        altitudes=[10.0, 70.0, 130.0],
        xsect_dlats=[-5000.0, 0.0, 5000.0],
        y_range=(0.0, 140.0),
    )
    widget.set_xsect_data(second)

    assert widget._y_view_range is None


def test_fsect_diagram_resets_range_when_data_changes() -> None:
    _ = qapp()
    widget = FsectDiagramWidget()
    widget.set_fsects(
        0,
        [PreviewFSection(start_dlat=-100.0, end_dlat=100.0, surface_type=0, type2=0)],
    )
    widget._range = (-10.0, 10.0)

    widget.set_fsects(
        0,
        [PreviewFSection(start_dlat=-1000.0, end_dlat=1000.0, surface_type=0, type2=0)],
    )

    assert widget._range != (-10.0, 10.0)


def test_xsect_elevation_enforces_minimum_one_foot_range() -> None:
    _ = qapp()
    widget = XsectElevationWidget()
    widget.resize(600, 200)
    widget.set_xsect_data(
        XsectElevationData(
            section_index=0,
            altitudes=[100.0, 100.0, 100.0],
            xsect_dlats=[-1.0, 0.0, 1.0],
            y_range=(100.0, 101.0),
        )
    )

    _, min_alt, max_alt = widget._plot_context()

    assert (max_alt - min_alt) >= 6000


def test_elevation_profile_bounds_enforce_minimum_one_foot_range() -> None:
    data = ElevationProfileData(
        dlongs=[0.0, 1.0],
        sg_altitudes=[10.0, 10.0],
        trk_altitudes=None,
        section_ranges=[(0.0, 1.0)],
        track_length=1.0,
        xsect_label="X0",
        y_range=(10.0, 20.0),
    )

    min_alt, max_alt = elevation_profile_alt_bounds(data)

    assert (max_alt - min_alt) >= 6000
