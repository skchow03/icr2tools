from pathlib import Path

from sg_viewer.ui.window_title import build_window_title


def test_window_title_includes_project_and_sg_names() -> None:
    title = build_window_title(
        path=Path('/tracks/monza.sg'),
        project_path=Path('/tracks/monza.sgc'),
        is_dirty=False,
    )
    assert title == 'monza.sgc [monza.sg] — SG CREATE'


def test_window_title_marks_dirty_with_project_and_sg_names() -> None:
    title = build_window_title(
        path=Path('/tracks/monza.sg'),
        project_path=Path('/tracks/monza.sgc'),
        is_dirty=True,
    )
    assert title == 'monza.sgc [monza.sg]* — SG CREATE'
