import pytest

try:
    import numpy as np
    from PyQt5 import QtWidgets

    from icr2_core.trk.sg_classes import SGFile
    from sg_viewer.ui.preview_widget_qt import PreviewWidgetQt
except ImportError:  # pragma: no cover
    pytest.skip("PyQt5 not available", allow_module_level=True)


@pytest.fixture(scope="module")
def qapp():
    app = QtWidgets.QApplication.instance()
    if app is None:
        app = QtWidgets.QApplication([])
    yield app


def _make_sgfile(num_xsects: int) -> SGFile:
    header = [0x53470000, 1, 1, 0, 1, num_xsects]
    xsect_dlats = np.array([i * 1000 for i in range(num_xsects)], dtype=np.int32)

    # one section; 58 + 2*num_xsects ints
    data = [0] * (58 + 2 * num_xsects)
    data[0] = 1  # straight
    data[1] = 0
    data[2] = 0
    data[8] = 1000
    data[17 + 2 * num_xsects] = 0  # num_fsects

    section = SGFile.Section(data, num_xsects)
    section.alt = [idx for idx in range(num_xsects)]
    section.grade = [0 for _ in range(num_xsects)]

    return SGFile(header, 1, num_xsects, xsect_dlats, [section])


def test_loading_sg_data_updates_runtime_xsections_metadata(qapp):
    preview = PreviewWidgetQt()
    try:
        sgfile = _make_sgfile(5)

        preview.load_sg_data(sgfile, status_message="imported")

        assert preview.sgfile is not None
        assert preview.sgfile.num_xsects == 5
        metadata = preview.get_xsect_metadata()
        assert len(metadata) == 5
        assert [idx for idx, _ in metadata] == [0, 1, 2, 3, 4]
    finally:
        preview.close()


def test_rebuild_elevation_graph_data_discards_stale_profile_caches(qapp):
    preview = PreviewWidgetQt()
    try:
        preview.load_sg_data(_make_sgfile(2), status_message="imported")
        profile = preview.build_elevation_profile(0)
        assert profile is not None

        cache_key = (10, preview._runtime._sg_version)
        preview._runtime._elevation_profile_cache[cache_key] = (
            [999.0],
            [(999.0, 1000.0)],
            [(0, 1)],
        )

        assert preview.rebuild_elevation_graph_data() is True
        rebuilt = preview.build_elevation_profile(0)

        assert rebuilt is not None
        assert rebuilt.dlongs != [999.0]
        assert rebuilt.section_ranges != [(999.0, 1000.0)]
    finally:
        preview.close()
