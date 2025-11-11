from pathlib import Path

from icr2timing.utils.ini_preserver import update_ini_file


def _read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def test_update_preserves_comments(tmp_path: Path):
    ini = tmp_path / "settings.ini"
    ini.write_text(
        """; global comment\n[exe_info]\n; keep me\ngame_exe = OLD.EXE ; trailing\n\n[overlay]\n# numbers\npoll_ms = 250\n""",
        encoding="utf-8",
    )

    update_ini_file(
        str(ini),
        {
            "exe_info": {"game_exe": "NEW.EXE"},
            "overlay": {"poll_ms": "333", "font_size": "10"},
        },
    )

    content = _read(ini)
    assert "; keep me" in content
    assert "# numbers" in content
    assert "game_exe = NEW.EXE ; trailing" in content
    assert "font_size = 10" in content


def test_remove_section(tmp_path: Path):
    ini = tmp_path / "profiles.ini"
    ini.write_text(
        """[keep]\nvalue = 1\n\n[remove]\nvalue = bye\n""",
        encoding="utf-8",
    )

    update_ini_file(str(ini), remove_sections=["remove"])

    assert "[remove]" not in _read(ini)
    assert "value = 1" in _read(ini)


def test_create_new_file(tmp_path: Path):
    ini = tmp_path / "new.ini"

    update_ini_file(str(ini), {"section": {"key": "value"}})

    assert _read(ini) == "[section]\nkey = value\n"
