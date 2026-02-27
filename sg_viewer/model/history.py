from __future__ import annotations

import json
import re
import sys
from configparser import ConfigParser
from pathlib import Path


_HEX_COLOR_RE = re.compile(r"^#[0-9a-fA-F]{6}$")
_ALLOWED_MEASUREMENT_UNITS = {"feet", "meter", "inch", "500ths"}
_PREVIEW_COLOR_STORAGE_KEYS = {
    "fsect_0": "fsect_grass",
    "fsect_1": "fsect_dry_grass",
    "fsect_2": "fsect_dirt",
    "fsect_3": "fsect_sand",
    "fsect_4": "fsect_concrete",
    "fsect_5": "fsect_asphalt",
    "fsect_6": "fsect_paint",
    "fsect_7": "fsect_wall",
    "fsect_8": "fsect_armco",
}


def _normalize_hex_color(value: str) -> str | None:
    candidate = value.strip()
    if not candidate:
        return None
    if not candidate.startswith("#"):
        candidate = f"#{candidate}"
    if not _HEX_COLOR_RE.fullmatch(candidate):
        return None
    return candidate.upper()


def _default_ini_path() -> Path:
    """
    Resolve the default INI path for SG Viewer.

    - Frozen / EXE build: place ini next to the executable
    - Source run: place ini next to this module
    """
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent / "sg_viewer.ini"

    return Path(__file__).resolve().parent / "sg_viewer.ini"


class FileHistory:
    """Persistent history for SG viewer activity and background settings."""

    DEFAULT_PATH = _default_ini_path()
    MAX_RECENT = 10
    PREVIEW_COLORS_SECTION = "preview_colors"
    VIEW_SECTION = "view"

    def __init__(self, path: Path | None = None) -> None:
        # Path resolves differently for source vs frozen executable
        self._path = path or self.DEFAULT_PATH
        self._config = ConfigParser(strict=False, delimiters=("=",))
        self._config.optionxform = str
        self._load()

    def ensure_preview_colors(self, defaults: dict[str, str]) -> dict[str, str]:
        """Ensure preview colors exist in config, writing defaults when missing."""
        if not self._config.has_section(self.PREVIEW_COLORS_SECTION):
            self._config.add_section(self.PREVIEW_COLORS_SECTION)

        changed = False
        resolved: dict[str, str] = {}
        section = self._config[self.PREVIEW_COLORS_SECTION]
        for key, fallback in defaults.items():
            storage_key = self._preview_color_storage_key(key)
            raw = section.get(storage_key, "").strip()
            if not raw and storage_key != key:
                raw = section.get(key, "").strip()
            normalized = _normalize_hex_color(raw)
            if normalized is not None:
                resolved[key] = normalized
                if raw != resolved[key] or section.get(storage_key) != resolved[key]:
                    section[storage_key] = resolved[key]
                    changed = True
                if storage_key != key and key in section:
                    del section[key]
                    changed = True
                continue

            default_color = _normalize_hex_color(fallback) or "#000000"
            resolved[key] = default_color
            section[storage_key] = resolved[key]
            if storage_key != key and key in section:
                del section[key]
            changed = True

        if changed:
            self._save()
        return resolved

    def set_preview_color(self, key: str, color: str) -> None:
        """Persist one preview color in ``#RRGGBB`` form."""
        normalized = _normalize_hex_color(color)
        if normalized is None:
            return
        if not self._config.has_section(self.PREVIEW_COLORS_SECTION):
            self._config.add_section(self.PREVIEW_COLORS_SECTION)
        section = self._config[self.PREVIEW_COLORS_SECTION]
        storage_key = self._preview_color_storage_key(key)
        if section.get(storage_key) == normalized and (
            storage_key == key or key not in section
        ):
            return
        section[storage_key] = normalized
        if storage_key != key and key in section:
            del section[key]
        self._save()

    def get_measurement_unit(self) -> str | None:
        if not self._config.has_section(self.VIEW_SECTION):
            return None
        candidate = self._config[self.VIEW_SECTION].get("uom", "").strip().lower()
        if candidate not in _ALLOWED_MEASUREMENT_UNITS:
            return None
        return candidate

    def set_measurement_unit(self, unit: str) -> None:
        normalized = str(unit).strip().lower()
        if normalized not in _ALLOWED_MEASUREMENT_UNITS:
            return
        if not self._config.has_section(self.VIEW_SECTION):
            self._config.add_section(self.VIEW_SECTION)
        if self._config[self.VIEW_SECTION].get("uom") == normalized:
            return
        self._config[self.VIEW_SECTION]["uom"] = normalized
        self._save()

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------
    def record_open(self, sg_path: Path) -> None:
        self._touch_recent(sg_path)

    def record_save(self, sg_path: Path) -> None:
        self._touch_recent(sg_path)

    def get_recent_paths(self) -> list[Path]:
        if not self._config.has_section("recent"):
            return []

        raw = self._config.get("recent", "files", fallback="")
        return [Path(p) for p in raw.splitlines() if p]

    def set_background(
        self,
        sg_path: Path,
        image_path: Path,
        scale_500ths_per_px: float,
        origin: tuple[float, float],
    ) -> None:
        data = self._load_file_entry(sg_path)
        data.update(
            {
                "background_image": str(image_path),
                "background_scale": scale_500ths_per_px,
                "background_upperleft_x": origin[0],
                "background_upperleft_y": origin[1],
            }
        )
        self._store_file_entry(sg_path, data)

    def get_background(
        self, sg_path: Path
    ) -> tuple[Path, float, tuple[float, float]] | None:
        data = self._load_file_entry(sg_path)
        if not data:
            return None

        try:
            image = Path(data["background_image"])
            if not image.is_absolute():
                image = (sg_path.parent / image).resolve()
            scale = float(data["background_scale"])
            origin = (float(data["background_upperleft_x"]), float(data["background_upperleft_y"]))
            return image, scale, origin
        except KeyError:
            return None

    def set_sunny_palette(self, sg_path: Path, palette_path: Path) -> None:
        data = self._load_file_entry(sg_path)
        data["sunny_palette"] = str(palette_path)
        self._store_file_entry(sg_path, data)

    def get_sunny_palette(self, sg_path: Path) -> Path | None:
        data = self._load_file_entry(sg_path)
        palette_value = data.get("sunny_palette")
        if not palette_value:
            return None
        palette_path = Path(palette_value)
        if not palette_path.is_absolute():
            palette_path = (sg_path.parent / palette_path).resolve()
        return palette_path

    def set_mrk_state(self, sg_path: Path, state: dict[str, object]) -> None:
        data = self._load_file_entry(sg_path)
        data["mrk_state"] = state
        self._store_file_entry(sg_path, data)

    def get_mrk_state(self, sg_path: Path) -> dict[str, object] | None:
        data = self._load_file_entry(sg_path)
        raw_state = data.get("mrk_state")
        if not isinstance(raw_state, dict):
            return None
        return raw_state

    # ------------------------------------------------------------------
    # Internals
    # ------------------------------------------------------------------
    def _touch_recent(self, sg_path: Path) -> None:
        resolved_path = sg_path.resolve()
        if resolved_path.suffix.lower() == ".sg":
            resolved_path = resolved_path.with_suffix(".sgc")
        normalized = str(resolved_path)
        recent = [p for p in self.get_recent_paths() if str(p) != normalized]
        recent.insert(0, Path(normalized))
        if not self._config.has_section("recent"):
            self._config.add_section("recent")
        self._config["recent"]["files"] = "\n".join(
            [str(p) for p in recent[: self.MAX_RECENT]]
        )
        self._save()

    def _load(self) -> None:
        if self._path.exists():
            self._config.read(self._path)

    def _save(self) -> None:
        self._path.parent.mkdir(parents=True, exist_ok=True)
        with self._path.open("w", encoding="utf-8") as fp:
            self._config.write(fp)

    def _load_file_entry(self, sg_path: Path) -> dict:
        if not self._config.has_section("files"):
            self._config.add_section("files")
        serialized = self._config["files"].get(str(sg_path.resolve()))
        if not serialized:
            return {}

        try:
            return json.loads(serialized)
        except json.JSONDecodeError:
            return {}

    def _store_file_entry(self, sg_path: Path, data: dict) -> None:
        if not self._config.has_section("files"):
            self._config.add_section("files")
        self._config["files"][str(sg_path.resolve())] = json.dumps(data)
        self._save()

    @staticmethod
    def _preview_color_storage_key(key: str) -> str:
        return _PREVIEW_COLOR_STORAGE_KEYS.get(key, key)
