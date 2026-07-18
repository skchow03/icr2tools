from pathlib import Path

from sg_viewer.model.history import FileHistory


def test_file_history_persists_template_folder(tmp_path: Path) -> None:
    ini_path = tmp_path / "sg_viewer.ini"
    template = tmp_path / "template"
    template.mkdir()

    history = FileHistory(ini_path)
    history.set_template_folder(template)

    assert FileHistory(ini_path).get_template_folder() == template.resolve()
