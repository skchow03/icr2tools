from PyQt5 import QtCore

from sg_viewer.main import _centered_top_left


def test_centered_top_left_centers_within_available_geometry() -> None:
    available = QtCore.QRect(0, 0, 1920, 1080)
    window_size = QtCore.QSize(960, 720)

    assert _centered_top_left(available, window_size) == (480, 180)


def test_centered_top_left_never_places_window_above_or_left_of_available_origin() -> None:
    available = QtCore.QRect(100, 50, 640, 480)
    window_size = QtCore.QSize(960, 720)

    assert _centered_top_left(available, window_size) == (100, 50)
