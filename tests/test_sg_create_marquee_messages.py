import json
from pathlib import Path

import pytest

from sg_viewer.sg_create_marquee_messages import (
    MARQUEE_MESSAGES,
    load_marquee_message_categories,
    random_marquee_message,
    studio_chatter_path,
)


def test_studio_chatter_is_loaded_from_editable_json() -> None:
    assert studio_chatter_path().name == "studio_chatter.json"
    assert studio_chatter_path().is_file()
    assert len(MARQUEE_MESSAGES) > 1


def test_loads_custom_studio_chatter_file(tmp_path: Path) -> None:
    path = tmp_path / "studio_chatter.json"
    path.write_text(json.dumps({"pit_crew": ["  Custom chatter  "]}), encoding="utf-8")

    assert load_marquee_message_categories(path) == {
        "pit_crew": ["Custom chatter"]
    }


def test_rejects_invalid_studio_chatter_messages(tmp_path: Path) -> None:
    path = tmp_path / "studio_chatter.json"
    path.write_text(json.dumps({"pit_crew": [""]}), encoding="utf-8")

    with pytest.raises(ValueError, match="non-empty strings"):
        load_marquee_message_categories(path)


def test_random_message_can_use_a_category() -> None:
    assert random_marquee_message("integrity_check") in load_marquee_message_categories()[
        "integrity_check"
    ]
