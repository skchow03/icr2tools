from types import SimpleNamespace

from sg_viewer.model.sg_model import SectionPreview
from sg_viewer.model.preview_fsection import PreviewFSection
from sg_viewer.preview.runtime import PreviewRuntime
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


def test_hi_detail_dividers_interpolate_outermost_fsection_boundaries(monkeypatch):
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

    fsections = (
        (
            PreviewFSection(-100.0, -300.0, 0, 0),
            PreviewFSection(25.0, 50.0, 1, 0),
            PreviewFSection(400.0, 200.0, 2, 0),
        ),
    )

    preview_painter._draw_hi_detail_section_dividers(
        _Painter(),
        ((1, 2, 250.0, 750.0),),
        [section],
        (1.0, (0.0, 0.0)),
        500,
        fsections,
    )

    assert requested_dlats == [-150.0, 350.0, -250.0, 250.0]


def test_runtime_exposes_fsections_instead_of_extreme_xsect_dlats():
    runtime = PreviewRuntime.__new__(PreviewRuntime)
    runtime._document = SimpleNamespace(
        sg_data=SimpleNamespace(xsect_dlats=[-999999.0, 888888.0])
    )
    runtime._fsects_by_section = [
        [PreviewFSection(-100.0, -300.0, 0, 0), PreviewFSection(400.0, 200.0, 0, 0)]
    ]

    assert runtime.preview_fsections_by_section == (
        (
            PreviewFSection(-100.0, -300.0, 0, 0),
            PreviewFSection(400.0, 200.0, 0, 0),
        ),
    )
    assert not hasattr(runtime, "track_dlat_bounds")
