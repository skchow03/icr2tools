from __future__ import annotations

from sg_viewer.sg_document_fsects import normalize_fsections


def test_normalize_fsections_orders_and_filters() -> None:
    fsects = [
        {"start_dlat": 12.0, "end_dlat": 4.0, "surface_type": 1, "type2": 0},
        {"start_dlat": 6.0, "end_dlat": 14.0, "surface_type": 2, "type2": 0},
        {"start_dlat": 5.0, "end_dlat": 5.0, "surface_type": 3, "type2": 0},
    ]

    normalized = normalize_fsections(fsects)

    assert len(normalized) == 2
    assert normalized[0]["start_dlat"] == 4.0
    assert normalized[0]["end_dlat"] == 12.0
    assert normalized[1]["start_dlat"] == 6.0
    assert normalized[1]["end_dlat"] == 14.0

    assert sorted(
        [(item["start_dlat"], item["end_dlat"]) for item in normalized]
    ) == [(item["start_dlat"], item["end_dlat"]) for item in normalized]

    assert {
        (item["start_dlat"], item["end_dlat"]) for item in normalized
    } == {(4.0, 12.0), (6.0, 14.0)}
