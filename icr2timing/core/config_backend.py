"""Low-level INI parsing helpers for configuration management."""

from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, Mapping, Optional
import configparser
import os
import sys

from icr2timing.utils.ini_preserver import update_ini_file

EXE_INFO_SECTION = "exe_info"

# Known EXE file sizes and their associated ICR2 versions.
EXE_VERSIONS = {
    1142371: "DOS100",
    1142387: "DOS102",
    1247899: "REND102",
    1916928: "WINDY101",
    1109095: "REND32A",
}

# Some INI configurations use more specific build tags that map onto the
# canonical memory maps above. These aliases keep backwards compatibility.
VERSION_ALIASES = {
    "WINDY101": "WINDY101",
}


class ConfigBackend:
    """Encapsulates discovery, parsing, and persistence of settings.ini."""

    def __init__(self, ini_path: Optional[str] = None) -> None:
        base_dir = os.path.dirname(sys.argv[0])
        self._path = Path(ini_path or (Path(base_dir) / "settings.ini"))

    @property
    def path(self) -> Path:
        return self._path

    def load(self) -> Dict[str, Dict[str, str]]:
        parser = configparser.ConfigParser(inline_comment_prefixes=(";", "#"))
        parser.read(self._path)
        data: Dict[str, Dict[str, str]] = {}
        for section in parser.sections():
            data[section] = dict(parser.items(section))
        return data

    def save(self, section_updates: Mapping[str, Mapping[str, Any]]) -> None:
        """Persist *section_updates* to disk, preserving unrelated comments."""

        if not section_updates:
            return
        normalized = {
            section: {key: str(value) for key, value in values.items()}
            for section, values in section_updates.items()
        }
        update_ini_file(str(self._path), normalized)

    def get_option(
        self,
        data: Mapping[str, Mapping[str, str]],
        section: str,
        option: str,
        fallback: str = "",
    ) -> str:
        section_map = data.get(section)
        if section_map is None:
            return fallback
        return section_map.get(option, fallback)

    def get_exe_info_option(
        self,
        data: Mapping[str, Mapping[str, str]],
        option: str,
        fallback: str = "",
    ) -> str:
        for section in (EXE_INFO_SECTION, "memory"):
            if section in data and option in data[section]:
                return data[section][option]
        if option == "game_exe" and "paths" in data and option in data["paths"]:
            return data["paths"][option]
        return fallback

    def validate_executable(self, data: Mapping[str, Mapping[str, str]], normalized_version: str) -> None:
        exe_path = self.get_exe_info_option(data, "game_exe", fallback="")
        if not exe_path:
            return

        try:
            size = os.path.getsize(exe_path)
        except OSError as exc:  # pragma: no cover - exercised in integration tests
            raise ValueError(
                f"Configured game_exe '{exe_path}' is not accessible: {exc.strerror or exc}"
            ) from exc

        exe_version = EXE_VERSIONS.get(size)
        if exe_version is None:
            known = ", ".join(
                f"{name} ({bytes_} bytes)" for bytes_, name in sorted(EXE_VERSIONS.items())
            )
            raise ValueError(
                f"Unrecognized game_exe '{exe_path}' size {size} bytes. Known versions: {known}"
            )

        normalized_exe_version = VERSION_ALIASES.get(exe_version.upper(), exe_version.upper())
        if normalized_exe_version != normalized_version:
            raise ValueError(
                "settings.ini version "
                f"'{normalized_version}' does not match executable '{exe_path}' "
                f"({exe_version} build, {size} bytes)"
            )
