from __future__ import annotations

import json
from configparser import ConfigParser
from pathlib import Path


class FileHistory:
    """Persistent history for SG viewer activity and background settings."""

    DEFAULT_PATH = Path.home() / ".icr2tools_sg_viewer.ini"
    MAX_RECENT = 10

    def __init__(self, path: Path | None = None) -> None:
        self._path = path or self.DEFAULT_PATH
        self._config = ConfigParser()
        self._load()

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
                "background_origin_u": origin[0],
                "background_origin_v": origin[1],
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
            scale = float(data["background_scale"])
            origin = (float(data["background_origin_u"]), float(data["background_origin_v"]))
            return image, scale, origin
        except KeyError:
            return None

    # ------------------------------------------------------------------
    # Internals
    # ------------------------------------------------------------------
    def _touch_recent(self, sg_path: Path) -> None:
        normalized = str(sg_path.resolve())
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
