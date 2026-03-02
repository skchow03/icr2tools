from __future__ import annotations

from configparser import ConfigParser
from pathlib import Path


class SunnyOptimizerSettings:
    def __init__(self, path: Path) -> None:
        self.path = path
        self.last_texture_folder: str = ""
        self.last_sunny_palette: str = ""
        self.color_budgets: dict[str, dict[str, int]] = {}

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

        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.path.open("w", encoding="utf-8") as handle:
            parser.write(handle)

    def budgets_for_folder(self, folder: Path) -> dict[str, int]:
        return dict(self.color_budgets.get(str(folder.resolve()), {}))

    def set_budgets_for_folder(self, folder: Path, budgets: dict[str, int]) -> None:
        self.color_budgets[str(folder.resolve())] = dict(budgets)

