"""Utilities for editing INI files without stripping comments.

The standard :mod:`configparser` module rewrites the entire file when
``write()`` is called, discarding user comments in the process.  These
helpers perform targeted updates so that comments and untouched settings
remain intact.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, List, Mapping, Optional


@dataclass
class _SectionRange:
    name: str
    start: int
    end: int


class _IniEditor:
    def __init__(self, lines: List[str], newline: str, trailing_newline: bool) -> None:
        self._lines = lines
        self._newline = newline
        self._trailing_newline = trailing_newline

    @property
    def lines(self) -> List[str]:
        return self._lines

    def set(self, section: str, key: str, value: str) -> None:
        section_range = self._find_section(section)
        assignment = f"{key} = {value}"

        if section_range is None:
            if self._lines and self._lines[-1].strip():
                self._lines.append("")
            self._lines.append(f"[{section}]")
            self._lines.append(assignment)
            return

        start, end = section_range.start, section_range.end
        key_lower = key.lower()

        for idx in range(start + 1, end):
            line = self._lines[idx]
            stripped = line.strip()
            if not stripped or stripped.startswith(("#", ";")):
                continue
            if "=" not in line:
                continue

            current_key = stripped.split("=", 1)[0].strip().lower()
            if current_key != key_lower:
                continue

            prefix, suffix = _split_comment(line)
            self._lines[idx] = f"{_rebuild_assignment(prefix, key, value)}{suffix}"
            return

        insert_at = end
        while insert_at > start + 1 and self._lines[insert_at - 1].strip() == "":
            insert_at -= 1
        self._lines.insert(insert_at, assignment)

    def remove_section(self, section: str) -> None:
        section_range = self._find_section(section)
        if section_range is None:
            return

        start, end = section_range.start, section_range.end
        del self._lines[start:end]
        # Trim a single trailing blank line to avoid leaving large gaps.
        if start < len(self._lines) and self._lines[start].strip() == "":
            del self._lines[start]

    def to_string(self) -> str:
        text = self._newline.join(self._lines)
        if self._lines and (self._trailing_newline or text):
            text += self._newline
        return text

    def _find_section(self, name: str) -> Optional[_SectionRange]:
        header = f"[{name}]"
        current_name = None
        current_start = None
        for idx, line in enumerate(self._lines):
            stripped = line.strip()
            if stripped.startswith("[") and stripped.endswith("]"):
                if current_name is not None:
                    if current_name == name:
                        return _SectionRange(current_name, current_start, idx)
                current_name = stripped[1:-1]
                current_start = idx
        if current_name == name and current_start is not None:
            return _SectionRange(current_name, current_start, len(self._lines))
        return None


def _split_comment(line: str) -> (str, str):
    for marker in (";", "#"):
        pos = line.find(marker)
        if pos != -1:
            return line[:pos], line[pos:]
    return line, ""


def _rebuild_assignment(prefix: str, key: str, value: str) -> str:
    if "=" not in prefix:
        leading = prefix[: len(prefix) - len(prefix.lstrip())]
        return f"{leading}{key} = {value}"

    eq_index = prefix.find("=")
    before_eq = prefix[:eq_index]
    after_eq = prefix[eq_index + 1 :]

    leading = before_eq[: len(before_eq) - len(before_eq.lstrip())]
    key_core = before_eq.strip()
    trailing_key_ws = before_eq[len(leading) + len(key_core) :]

    value_prefix = after_eq[: len(after_eq) - len(after_eq.lstrip())]
    value_suffix = after_eq[len(after_eq.rstrip()) :]

    return f"{leading}{key}{trailing_key_ws}={value_prefix}{value}{value_suffix}"


def _create_editor(path: Path, encoding: str) -> _IniEditor:
    if path.exists():
        raw = path.read_text(encoding=encoding)
        newline = "\r\n" if "\r\n" in raw else "\n"
        trailing_newline = raw.endswith(("\n", "\r\n"))
        lines = raw.splitlines()
    else:
        newline = "\n"
        trailing_newline = True
        lines = []
    return _IniEditor(lines, newline, trailing_newline)


def update_ini_file(
    path: str,
    updates: Mapping[str, Mapping[str, str]] | None = None,
    remove_sections: Iterable[str] | None = None,
    *,
    encoding: str = "utf-8",
) -> None:
    """Apply *updates* to *path* while preserving unrelated comments.

    Args:
        path: The INI file to update.
        updates: Mapping of section names to ``{key: value}`` dictionaries.
        remove_sections: Iterable of section names to remove entirely.
        encoding: File encoding.
    """

    ini_path = Path(path)
    editor = _create_editor(ini_path, encoding)

    if remove_sections:
        for section in remove_sections:
            editor.remove_section(section)

    if updates:
        for section, values in updates.items():
            for key, value in values.items():
                editor.set(section, key, value)

    ini_path.parent.mkdir(parents=True, exist_ok=True)
    ini_path.write_text(editor.to_string(), encoding=encoding)
