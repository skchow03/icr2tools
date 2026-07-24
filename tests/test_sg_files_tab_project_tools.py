from pathlib import Path

from sg_viewer.model.history import FileHistory
from sg_viewer.services.template_files import (
    parse_template_trackname_files,
    replace_template_trackname_placeholders,
)


def test_file_history_persists_template_folder(tmp_path: Path) -> None:
    ini_path = tmp_path / "sg_viewer.ini"
    template = tmp_path / "template"
    template.mkdir()

    history = FileHistory(ini_path)
    history.set_template_folder(template)

    assert FileHistory(ini_path).get_template_folder() == template.resolve()


def test_file_history_persists_template_trackname_files(tmp_path: Path) -> None:
    ini_path = tmp_path / "sg_viewer.ini"

    history = FileHistory(ini_path)
    history.set_template_trackname_files("run.bat, scripts/build.txt")

    assert (
        FileHistory(ini_path).get_template_trackname_files()
        == "run.bat, scripts/build.txt"
    )


def test_template_trackname_replacement_updates_nested_copied_files(
    tmp_path: Path,
) -> None:
    project = tmp_path / "project"
    nested = project / "scripts"
    nested.mkdir(parents=True)
    (project / "run.bat").write_text("sg2trk <<trackname>>\n", encoding="utf-8")
    (nested / "build.txt").write_text("build <<trackname>>\n", encoding="utf-8")

    replaced_count = replace_template_trackname_placeholders(
        project,
        parse_template_trackname_files("run.bat, scripts/build.txt"),
        "monza",
    )

    assert replaced_count == 2
    assert (project / "run.bat").read_text(encoding="utf-8") == "sg2trk monza\n"
    assert (nested / "build.txt").read_text(encoding="utf-8") == "build monza\n"
