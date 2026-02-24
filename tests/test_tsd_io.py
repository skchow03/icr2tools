from sg_viewer.services.tsd_io import (
    TrackSurfaceDetailFile,
    TrackSurfaceDetailLine,
    parse_tsd,
    serialize_tsd,
)


def test_serialize_tsd_formats_detail_lines() -> None:
    detail_file = TrackSurfaceDetailFile(
        lines=(
            TrackSurfaceDetailLine(36, 4000, 0, -126000, 919091, -126000),
            TrackSurfaceDetailLine(36, 4000, 919091, -126000, 2015740, -126000),
        )
    )

    assert serialize_tsd(detail_file) == (
        "Detail: 36 4000 0 -126000 919091 -126000\n"
        "Detail: 36 4000 919091 -126000 2015740 -126000\n"
    )


def test_serialize_tsd_empty_file_is_empty_string() -> None:
    assert serialize_tsd(TrackSurfaceDetailFile(lines=())) == ""


def test_parse_tsd_reads_detail_lines() -> None:
    parsed = parse_tsd("Detail: 36 4000 0 -126000 919091 -126000\n")
    assert parsed == TrackSurfaceDetailFile(
        lines=(TrackSurfaceDetailLine(36, 4000, 0, -126000, 919091, -126000),)
    )


def test_parse_tsd_rejects_invalid_line() -> None:
    try:
        parse_tsd("Oops: 1 2 3\n")
    except ValueError as exc:
        assert "Detail:" in str(exc)
    else:
        raise AssertionError("Expected ValueError")
