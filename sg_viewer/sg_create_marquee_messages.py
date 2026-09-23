"""Load SG CREATE's studio chatter from a user-editable data file."""

from __future__ import annotations

import json
import sys
from pathlib import Path
from random import choice
from typing import Mapping


STUDIO_CHATTER_FILENAME = "studio_chatter.json"


def studio_chatter_path() -> Path:
    """Return the studio chatter file used by this SG CREATE installation.

    A frozen build first looks beside the executable, where users can edit the
    file.  The bundled copy remains a fallback for distributions that omit the
    external file.
    """
    if getattr(sys, "frozen", False):
        external_path = Path(sys.executable).resolve().parent / STUDIO_CHATTER_FILENAME
        if external_path.is_file():
            return external_path
        bundle_dir = getattr(sys, "_MEIPASS", None)
        if bundle_dir:
            return Path(bundle_dir) / STUDIO_CHATTER_FILENAME
    return Path(__file__).resolve().with_name(STUDIO_CHATTER_FILENAME)


def load_marquee_message_categories(
    path: str | Path | None = None,
) -> dict[str, list[str]]:
    """Load and validate categorized messages from ``studio_chatter.json``."""
    chatter_path = Path(path) if path is not None else studio_chatter_path()
    with chatter_path.open(encoding="utf-8") as chatter_file:
        raw_categories = json.load(chatter_file)

    if not isinstance(raw_categories, Mapping):
        raise ValueError("Studio chatter must be a JSON object of message lists.")

    categories: dict[str, list[str]] = {}
    for category, raw_messages in raw_categories.items():
        if not isinstance(category, str) or not isinstance(raw_messages, list):
            raise ValueError("Each studio chatter category must contain a list.")
        messages = [
            message.strip()
            for message in raw_messages
            if isinstance(message, str) and message.strip()
        ]
        if len(messages) != len(raw_messages):
            raise ValueError("Studio chatter messages must be non-empty strings.")
        categories[category] = messages

    if not any(categories.values()):
        raise ValueError("Studio chatter must contain at least one message.")
    return categories


MARQUEE_MESSAGE_CATEGORIES = load_marquee_message_categories()
MARQUEE_MESSAGES = [
    message
    for category_messages in MARQUEE_MESSAGE_CATEGORIES.values()
    for message in category_messages
]


def random_marquee_message(category: str | None = None) -> str:
    """Return a random message, optionally from one named category."""
    if category is None:
        return choice(MARQUEE_MESSAGES)
    return choice(MARQUEE_MESSAGE_CATEGORIES[category])
