from __future__ import annotations

import pytest

pytest.importorskip("PyQt5")

from PyQt5 import QtGui

from sg_viewer.services import sg_rendering


class _CapturingPainter:
    def __init__(self) -> None:
        self.drawn_rect: QtGui.QRectF | None = None

    def save(self) -> None:  # pragma: no cover - interface compatibility
        pass

    def restore(self) -> None:  # pragma: no cover - interface compatibility
        pass

    def setRenderHint(self, *_args, **_kwargs) -> None:  # pragma: no cover
        pass

    def drawImage(self, rect: QtGui.QRectF, _image: QtGui.QImage) -> None:
        self.drawn_rect = rect


def test_draw_background_image_respects_origin_direction() -> None:
    image = QtGui.QImage(10, 20, QtGui.QImage.Format_ARGB32)
    painter = _CapturingPainter()
    origin = (100.0, 200.0)
    scale = 2.0
    transform: sg_rendering.Transform = (1.0, (0.0, 0.0))
    widget_height = 400

    sg_rendering.draw_background_image(
        painter,
        image,
        origin,
        scale,
        transform,
        widget_height,
    )

    assert painter.drawn_rect is not None
    expected_top_left = sg_rendering.map_point(*origin, transform, widget_height)
    expected_bottom_right = sg_rendering.map_point(
        origin[0] + image.width() * scale,
        origin[1] - image.height() * scale,
        transform,
        widget_height,
    )

    assert painter.drawn_rect.left() == expected_top_left.x()
    assert painter.drawn_rect.top() == expected_top_left.y()
    assert painter.drawn_rect.right() == expected_bottom_right.x()
    assert painter.drawn_rect.bottom() == expected_bottom_right.y()
