from __future__ import annotations

from configparser import ConfigParser
import json
from pathlib import Path


class SunnyOptimizerSettings:
    def __init__(self, path: Path) -> None:
        self.path = path
        self.last_texture_folder: str = ""
        self.last_sunny_palette: str = ""
        self.color_budgets: dict[str, dict[str, int]] = {}
        self.tool_presets: dict[str, dict[str, dict[str, str]]] = {}
        self.default_presets: dict[str, str] = {}
        self.recent_paths: dict[str, list[str]] = {}

    @staticmethod
    def default_path() -> Path:
        return Path.home() / ".sunny_optimizer.ini"

    def load(self) -> None:
        parser = ConfigParser()
        if self.path.exists():
            parser.read(self.path, encoding="utf-8")

        self.last_texture_folder = parser.get("recent", "texture_folder", fallback="")
        self.last_sunny_palette = parser.get("recent", "sunny_palette", fallback="")

        budgets: dict[str, dict[str, int]] = {}
        for section in parser.sections():
            if not section.startswith("budgets:"):
                continue
            folder = section[len("budgets:") :]
            folder_budgets: dict[str, int] = {}
            for texture_name, raw_budget in parser.items(section):
                try:
                    budget = int(raw_budget)
                except ValueError:
                    continue
                if budget < 1:
                    continue
                folder_budgets[texture_name] = budget
            if folder_budgets:
                budgets[folder] = folder_budgets
        self.color_budgets = budgets

        presets: dict[str, dict[str, dict[str, str]]] = {}
        for section in parser.sections():
            if not section.startswith("presets:"):
                continue
            tool_name = section[len("presets:") :]
            parsed: dict[str, dict[str, str]] = {}
            for preset_name, raw_json in parser.items(section):
                try:
                    value = json.loads(raw_json)
                except json.JSONDecodeError:
                    continue
                if isinstance(value, dict):
                    parsed[preset_name] = {str(k): str(v) for k, v in value.items()}
            presets[tool_name] = parsed
        self.tool_presets = presets

        self.default_presets = {}
        if parser.has_section("preset_defaults"):
            self.default_presets = {k: v for k, v in parser.items("preset_defaults")}

        self.recent_paths = {}
        if parser.has_section("recent_paths"):
            for key, raw_json in parser.items("recent_paths"):
                try:
                    value = json.loads(raw_json)
                except json.JSONDecodeError:
                    continue
                if isinstance(value, list):
                    self.recent_paths[key] = [str(v) for v in value if str(v).strip()]

    def save(self) -> None:
        parser = ConfigParser()
        parser["recent"] = {
            "texture_folder": self.last_texture_folder,
            "sunny_palette": self.last_sunny_palette,
        }

        for folder, budgets in sorted(self.color_budgets.items()):
            if not budgets:
                continue
            parser[f"budgets:{folder}"] = {name: str(value) for name, value in sorted(budgets.items())}

        for tool_name, presets in sorted(self.tool_presets.items()):
            if not presets:
                continue
            parser[f"presets:{tool_name}"] = {
                name: json.dumps(payload, sort_keys=True) for name, payload in sorted(presets.items())
            }

        if self.default_presets:
            parser["preset_defaults"] = dict(sorted(self.default_presets.items()))

        if self.recent_paths:
            parser["recent_paths"] = {
                name: json.dumps(values)
                for name, values in sorted(self.recent_paths.items())
                if values
            }

        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.path.open("w", encoding="utf-8") as handle:
            parser.write(handle)

    def budgets_for_folder(self, folder: Path) -> dict[str, int]:
        return dict(self.color_budgets.get(str(folder.resolve()), {}))

    def set_budgets_for_folder(self, folder: Path, budgets: dict[str, int]) -> None:
        self.color_budgets[str(folder.resolve())] = dict(budgets)

    def presets_for_tool(self, tool_name: str) -> dict[str, dict[str, str]]:
        return {name: dict(values) for name, values in self.tool_presets.get(tool_name, {}).items()}

    def set_preset_for_tool(self, tool_name: str, preset_name: str, values: dict[str, str]) -> None:
        self.tool_presets.setdefault(tool_name, {})[preset_name] = {str(k): str(v) for k, v in values.items()}

    def delete_preset_for_tool(self, tool_name: str, preset_name: str) -> None:
        presets = self.tool_presets.get(tool_name, {})
        presets.pop(preset_name, None)
        if not presets and tool_name in self.tool_presets:
            del self.tool_presets[tool_name]

    def set_default_preset(self, tool_name: str, preset_name: str) -> None:
        self.default_presets[tool_name] = preset_name

    def default_preset_for_tool(self, tool_name: str) -> str:
        return self.default_presets.get(tool_name, "")


    def get_recent_paths(self, key: str) -> list[str]:
        return list(self.recent_paths.get(key, []))

    def push_recent_path(self, key: str, value: str, *, limit: int = 10) -> None:
        normalized = str(value).strip()
        if not normalized:
            return
        values = [v for v in self.recent_paths.get(key, []) if v != normalized]
        values.insert(0, normalized)
        self.recent_paths[key] = values[: max(1, limit)]
