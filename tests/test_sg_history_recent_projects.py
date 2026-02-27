from sg_viewer.model.history import FileHistory


def test_recent_paths_convert_sg_to_sgc(tmp_path):
    history = FileHistory(tmp_path / "history.ini")
    sg_path = tmp_path / "track.sg"
    sg_path.write_bytes(b"")

    history.record_open(sg_path)

    assert history.get_recent_paths() == [sg_path.with_suffix('.sgc').resolve()]
