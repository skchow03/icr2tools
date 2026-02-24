from sg_viewer.services.tsd_io import TrackSurfaceDetailFile, TrackSurfaceDetailLine, serialize_tsd


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
