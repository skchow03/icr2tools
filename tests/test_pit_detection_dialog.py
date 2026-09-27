"""Qt smoke test for the pit detection review/confirmation dialog."""
from __future__ import annotations

from types import SimpleNamespace

from PyQt5 import QtWidgets

from track_viewer.model.pit_models import PitParameters
from track_viewer.pit.pit_lane_detector import detect_pit_lanes
from track_viewer.widget import pit_detection_dialog as dialog_module

FT = 6000


def _simple_trk():
    sections = []
    for i in range(4):
        split = i in (1, 2)
        sec = SimpleNamespace(
            start_dlong=i * 300 * FT,
            length=300 * FT,
            num_bounds=2,
            bound_dlat_start=([-90, 50] if split else [-50, 50]),
            bound_dlat_end=([-90, 50] if split else [-50, 50]),
            ground_fsects=3 if split else 1,
            ground_type=[40, 0, 40] if split else [40],
            ground_dlat_start=[-90, -30, -25] if split else [-50],
            ground_dlat_end=[-90, -30, -25] if split else [-50],
        )
        for key in ("bound_dlat_start", "bound_dlat_end",
                    "ground_dlat_start", "ground_dlat_end"):
            setattr(sec, key, [x * FT for x in getattr(sec, key)])
        sections.append(sec)
    return SimpleNamespace(sects=sections, trklength=1200 * FT)


def test_review_dialog_shows_candidates_and_only_applies_after_accept(monkeypatch):
    trk = _simple_trk()
    detection = detect_pit_lanes(trk)
    monkeypatch.setattr(dialog_module, "get_cline_pos", lambda _trk: [(0, 0)])
    monkeypatch.setattr(
        dialog_module, "getxyz",
        lambda _trk, dlong, dlat, _cline: (dlong / FT, dlat / FT, 0.0),
    )
    app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
    dialog = dialog_module.PitDetectionDialog(
        trk, detection, PitParameters.empty(), {},
    )
    assert dialog._choices.count() == 1
    assert dialog.suggestion is not None
    assert dialog._table.item(0, 0).text() == "Pit wall DLAT"
    assert dialog.result() == 0  # construction does not apply anything
    dialog._side.setCurrentIndex(2)  # force left, which has no pit
    assert dialog._choices.count() == 0
    assert not dialog._apply.isEnabled()
    dialog._side.setCurrentIndex(1)  # force right
    assert dialog._apply.isEnabled()
    dialog.accept()
    assert dialog.result() == QtWidgets.QDialog.Accepted
    assert dialog.suggestion is not None
    dialog.deleteLater()
    del app
