from sg_viewer.model.sg_model import SectionPreview
from sg_viewer.services import preview_painter


class _Painter:
    def save(self):
        pass

    def restore(self):
        pass

    def setRenderHint(self, *_args):
        pass

    def setPen(self, *_args):
        pass

    def setBrush(self, *_args):
        pass

    def drawLine(self, *_args):
        pass

    def drawText(self, *_args):
        pass


def test_hi_detail_dividers_span_outermost_track_cross_sections(monkeypatch):
    section = SectionPreview(
        section_id=0,
        source_section_id=0,
        type_name="straight",
        previous_id=-1,
        next_id=-1,
        start=(0.0, 0.0),
        end=(1000.0, 0.0),
        start_dlong=0.0,
        length=1000.0,
        center=None,
        sang1=None,
        sang2=None,
        eang1=None,
        eang2=None,
        radius=None,
        start_heading=(1.0, 0.0),
        end_heading=(1.0, 0.0),
        polyline=[(0.0, 0.0), (1000.0, 0.0)],
    )
    requested_dlats = []

    def point_at_dlong(_sections, dlong, dlat, _track_length, _lookup):
        requested_dlats.append(dlat)
        return dlong, dlat

    monkeypatch.setattr(preview_painter, "_point_on_track_at_dlong", point_at_dlong)
    monkeypatch.setattr(
        preview_painter.sg_rendering,
        "map_point",
        lambda x, y, _transform, _height: preview_painter.QtCore.QPointF(x, y),
    )

    preview_painter._draw_hi_detail_section_dividers(
        _Painter(),
        ((1, 2, 100.0, 200.0),),
        [section],
        (1.0, (0.0, 0.0)),
        500,
        (-275000.0, 410000.0),
    )

    assert requested_dlats == [-275000.0, 410000.0, -275000.0, 410000.0]
