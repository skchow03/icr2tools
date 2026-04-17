from pathlib import Path

from icr2_core.three_d.three_d_tools import process_file


def test_process_file_fix_elevation_reports_progress(tmp_path: Path) -> None:
    input_path = tmp_path / "track.3d"
    input_path.write_text(
        "\n".join(
            [
                "Outputing section from dlong",
                "SEC0: example",
                ";",
                "Outputing section from dlong",
                "SEC1: example",
                ";",
                "",
            ]
        ),
        encoding="utf-8",
    )

    updates: list[tuple[int, int, str]] = []
    process_file(
        input_path=input_path,
        output_path=input_path,
        fix_elevation=True,
        on_progress=lambda current, total, message: updates.append((current, total, message)),
    )

    assert updates == [
        (0, 2, "Preparing see-through elevation fix…"),
        (0, 2, "Fixing section 1/2: SEC0"),
        (1, 2, "Fixing section 2/2: SEC1"),
        (2, 2, "See-through elevation fix complete."),
    ]
