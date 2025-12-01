from icr2timing.core.config_backend import ConfigBackend


def test_load_strips_inline_comments(tmp_path):
    ini_path = tmp_path / "settings.ini"
    ini_path.write_text(
        """
[radar]
symbol = rectangle   ; options: rectangle, circle, arrow
""".strip()
    )

    backend = ConfigBackend(str(ini_path))
    data = backend.load()

    assert data["radar"]["symbol"] == "rectangle"

    backend.save({"radar": {"symbol": "circle"}})

    contents = ini_path.read_text()
    assert contents.count("options: rectangle, circle, arrow") == 1
    assert "symbol = circle" in contents
