from __future__ import annotations

import json
from pathlib import Path


class SGSettingsStore:
    """Persists SG-specific viewer settings to a project file next to the SG."""

    def _settings_path(self, sg_path: Path) -> Path:
        return sg_path.with_suffix(".sgc")

    @staticmethod
    def _sg_file_value(sg_path: Path) -> str:
        return str(Path(sg_path.name))

    def load(self, sg_path: Path) -> dict[str, object]:
        path = self._settings_path(sg_path)
        if not path.exists():
            return {}
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return {}
        if not isinstance(payload, dict):
            return {}
        return payload

    def save(self, sg_path: Path, payload: dict[str, object]) -> None:
        path = self._settings_path(sg_path)
        path.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")

    def update(self, sg_path: Path, **fields: object) -> None:
        payload = self.load(sg_path)
        payload.setdefault("sg_file", self._sg_file_value(sg_path))
        payload.update(fields)
        self.save(sg_path, payload)

    def get_background(self, sg_path: Path) -> tuple[Path, float, tuple[float, float]] | None:
        payload = self.load(sg_path)
        raw = payload.get("background")
        if not isinstance(raw, dict):
            return None
        try:
            image_path = Path(str(raw["image_path"]))
            if not image_path.is_absolute():
                image_path = (sg_path.parent / image_path).resolve()
            scale = float(raw["scale_500ths_per_px"])
            origin = (float(raw["origin_u"]), float(raw["origin_v"]))
            return image_path, scale, origin
        except (KeyError, TypeError, ValueError):
            return None

    def set_background(
        self,
        sg_path: Path,
        image_path: Path,
        scale_500ths_per_px: float,
        origin: tuple[float, float],
    ) -> None:
        stored_path = image_path
        if image_path.is_absolute():
            try:
                stored_path = image_path.resolve().relative_to(sg_path.parent.resolve())
            except ValueError:
                stored_path = image_path.resolve()
        self.update(
            sg_path,
            background={
                "image_path": str(stored_path),
                "scale_500ths_per_px": float(scale_500ths_per_px),
                "origin_u": float(origin[0]),
                "origin_v": float(origin[1]),
            },
        )

    def get_mrk_state(self, sg_path: Path) -> dict[str, object] | None:
        payload = self.load(sg_path)
        state = payload.get("mrk_state")
        return state if isinstance(state, dict) else None

    def set_mrk_state(self, sg_path: Path, state: dict[str, object]) -> None:
        self.update(sg_path, mrk_state=state)

    def get_sunny_palette(self, sg_path: Path) -> Path | None:
        payload = self.load(sg_path)
        value = payload.get("sunny_palette")
        if not isinstance(value, str) or not value.strip():
            return None
        path = Path(value)
        if not path.is_absolute():
            path = (sg_path.parent / path).resolve()
        return path

    def set_sunny_palette(self, sg_path: Path, palette_path: Path) -> None:
        stored_path = palette_path
        if palette_path.is_absolute():
            try:
                stored_path = palette_path.resolve().relative_to(sg_path.parent.resolve())
            except ValueError:
                stored_path = palette_path.resolve()
        self.update(sg_path, sunny_palette=str(stored_path))

    def get_tsd_files(self, sg_path: Path) -> tuple[list[Path], int | None]:
        payload = self.load(sg_path)
        raw = payload.get("tsd")
        if not isinstance(raw, dict):
            return [], None
        raw_paths = raw.get("files")
        result: list[Path] = []
        if isinstance(raw_paths, list):
            for entry in raw_paths:
                if not isinstance(entry, str) or not entry.strip():
                    continue
                candidate = Path(entry)
                if not candidate.is_absolute():
                    candidate = (sg_path.parent / candidate).resolve()
                result.append(candidate)
        active = raw.get("active_index")
        active_index = active if isinstance(active, int) and active >= 0 else None
        return result, active_index

    def set_tsd_files(self, sg_path: Path, files: list[Path], active_index: int | None) -> None:
        serialized: list[str] = []
        base = sg_path.parent.resolve()
        for path in files:
            stored_path = path
            if path.is_absolute():
                try:
                    stored_path = path.resolve().relative_to(base)
                except ValueError:
                    stored_path = path.resolve()
            serialized.append(str(stored_path))
        self.update(
            sg_path,
            tsd={
                "files": serialized,
                "active_index": active_index,
            },
        )

    def get_mrk_wall_heights(self, sg_path: Path) -> tuple[float, float] | None:
        payload = self.load(sg_path)
        raw = payload.get("mrk_wall_heights")
        if not isinstance(raw, dict):
            return None
        try:
            return float(raw["wall_height_500ths"]), float(raw["armco_height_500ths"])
        except (KeyError, TypeError, ValueError):
            return None

    def set_mrk_wall_heights(self, sg_path: Path, wall_height_500ths: float, armco_height_500ths: float) -> None:
        self.update(
            sg_path,
            mrk_wall_heights={
                "wall_height_500ths": float(wall_height_500ths),
                "armco_height_500ths": float(armco_height_500ths),
            },
        )
