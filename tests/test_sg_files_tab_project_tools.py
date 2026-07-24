from pathlib import Path

from sg_viewer.model.history import FileHistory
from sg_viewer.services.template_files import (
    copy_template_files_without_overwrite,
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


def test_copy_template_files_without_overwrite_skips_existing_files(
    tmp_path: Path,
) -> None:
    template = tmp_path / "template"
    project = tmp_path / "project"
    (template / "scripts").mkdir(parents=True)
    project.mkdir()
    (template / "run.bat").write_text("template run\n", encoding="utf-8")
    (template / "scripts" / "build.txt").write_text(
        "template build\n", encoding="utf-8"
    )
    (project / "run.bat").write_text("existing run\n", encoding="utf-8")

    result = copy_template_files_without_overwrite(template, project)

    assert result.copied_files == [Path("scripts/build.txt")]
    assert result.skipped_files == [Path("run.bat")]
    assert result.directory_count == 1
    assert (project / "run.bat").read_text(encoding="utf-8") == "existing run\n"
    assert (project / "scripts" / "build.txt").read_text(
        encoding="utf-8"
    ) == "template build\n"
