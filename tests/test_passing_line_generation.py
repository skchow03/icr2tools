"""Tests for Samsepi-style PASS1 / PASS2 generation."""
from pathlib import Path
from types import SimpleNamespace

import pytest

from track_viewer.ai.ai_line_service import LpPoint
from track_viewer.model.lp_editing_session import LPChange, LPEditingSession
from track_viewer.model.track_preview_model import TrackPreviewModel


def _point(index: int, dlat_feet: float, speed_mph: float = 100.0) -> LpPoint:
    return LpPoint(
        x=float(index),
        y=dlat_feet * 6000.0,
        dlong=float(index * 6000),
        dlat=dlat_feet * 6000.0,
        speed_raw=int(round(speed_mph * 5280.0 / 9.0)),
        speed_mph=speed_mph,
        lateral_speed=42.0,
    )


def _model(monkeypatch) -> TrackPreviewModel:
    monkeypatch.setattr(
        "track_viewer.model.track_preview_model.getxyz",
        lambda _trk, dlong, dlat, _cline: (float(dlong), float(dlat), 0.0),
    )
    model = TrackPreviewModel()
    model.trk = SimpleNamespace(trklength=6000.0)
    model.centerline = [(0.0, 0.0)]
    model.track_path = Path("/example")
    model.available_lp_files = ["RACE", "MAXRACE", "MINRACE"]
    model._ai_lines = {
        "RACE": [_point(0, 0.0, 120.0), _point(1, 2.0, 80.0)],
        "MAXRACE": [_point(0, 40.0), _point(1, 6.0)],
        "MINRACE": [_point(0, -12.0), _point(1, -10.0)],
    }
    return model


def test_default_generates_both_sides_from_race_even_if_maxrace_selected(
    monkeypatch,
) -> None:
    model = _model(monkeypatch)
    session = LPEditingSession(model)
    session.set_active_lp_line("MAXRACE")
    race_before = [(p.dlat, p.speed_mph) for p in model._ai_lines["RACE"]]
    max_before = [p.dlat for p in model._ai_lines["MAXRACE"]]

    success, message, changes = session.generate_passing_lines()

    assert success, message
    assert changes == {LPChange.DATA, LPChange.VISIBILITY}
    assert session.active_lp_line == "MAXRACE"
    pass1 = model.ai_line_records("PASS1")
    pass2 = model.ai_line_records("PASS2")
    assert [p.dlat / 6000.0 for p in pass1] == pytest.approx([16.0, 4.0])
    assert [p.dlat / 6000.0 for p in pass2] == pytest.approx([-6.0, -4.0])
    assert [p.speed_mph for p in pass1] == pytest.approx([119.75, 79.75])
    assert [p.speed_mph for p in pass2] == pytest.approx([119.75, 79.75])
    # PASS1 approaches RACE while PASS2 moves outward in this test fixture.
    assert all(p.lateral_speed < 0 for p in pass1)
    assert all(p.lateral_speed > 0 for p in pass2)
    assert [(p.dlat, p.speed_mph) for p in model._ai_lines["RACE"]] == race_before
    assert [p.dlat for p in model._ai_lines["MAXRACE"]] == max_before
    assert model._dirty_lp_files == {"PASS1", "PASS2"}
    assert {"PASS1", "PASS2"}.issubset(model.available_lp_files)
    assert {"PASS1", "PASS2"}.issubset(model.visible_lp_files)
    assert len(pass1) == len(pass2) == len(model.ai_line_records("RACE"))


def test_configurable_side_limits_placement_and_speed(monkeypatch) -> None:
    model = _model(monkeypatch)

    success, message = model.generate_passing_lines(
        pass1_max_feet=4.0,
        pass2_max_feet=3.0,
        placement_pct=75.0,
        speed_reduction_mph=2.5,
    )

    assert success, message
    assert [p.dlat / 6000.0 for p in model.ai_line_records("PASS1")] == pytest.approx(
        [4.0, 5.0]
    )
    assert [p.dlat / 6000.0 for p in model.ai_line_records("PASS2")] == pytest.approx(
        [-3.0, -1.0]
    )
    assert model.ai_line_records("PASS1")[0].speed_mph == pytest.approx(117.5)


def test_invalid_hierarchy_does_not_replace_either_existing_target(
    monkeypatch,
) -> None:
    model = _model(monkeypatch)
    original_pass1 = [_point(0, 3.0)]
    original_pass2 = [_point(0, -3.0)]
    model._ai_lines["PASS1"] = original_pass1
    model._ai_lines["PASS2"] = original_pass2
    model.available_lp_files.extend(["PASS1", "PASS2"])
    model._ai_lines["MAXRACE"][1].dlat = model._ai_lines["RACE"][1].dlat

    success, message = model.generate_passing_lines()

    assert not success
    assert "record(s)" in message
    assert model._ai_lines["PASS1"] is original_pass1
    assert model._ai_lines["PASS2"] is original_pass2
    assert not model._dirty_lp_files


def test_mismatched_dlongs_fail_atomically(monkeypatch) -> None:
    model = _model(monkeypatch)
    model._ai_lines["MINRACE"][1].dlong += 6000.0

    success, message = model.generate_passing_lines()

    assert not success
    assert "misaligned" in message
    assert "PASS1" not in model._ai_lines
    assert "PASS2" not in model._ai_lines


def test_missing_source_or_invalid_settings_do_not_create_outputs(
    monkeypatch,
) -> None:
    model = _model(monkeypatch)
    model.available_lp_files.remove("MINRACE")
    success, message = model.generate_passing_lines()
    assert not success
    assert "MINRACE" in message
    model.available_lp_files.append("MINRACE")

    for settings in (
        {"pass1_max_feet": 0.0},
        {"placement_pct": 0.0},
        {"placement_pct": 100.0},
        {"speed_reduction_mph": -1.0},
    ):
        success, _ = model.generate_passing_lines(**settings)
        assert not success
    assert "PASS1" not in model._ai_lines
    assert "PASS2" not in model._ai_lines


def test_integer_lp_precision_must_preserve_hierarchy(monkeypatch) -> None:
    model = _model(monkeypatch)
    model._ai_lines["MAXRACE"][0].dlat = 0.6
    model._ai_lines["MINRACE"][0].dlat = -0.6

    success, message = model.generate_passing_lines()

    assert not success
    assert "integer LP precision" in message
    assert "PASS1" not in model._ai_lines
    assert "PASS2" not in model._ai_lines
