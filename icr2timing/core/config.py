"""Facade for the shared :class:`ConfigStore` singleton."""

from __future__ import annotations

from typing import Callable

from icr2timing.core.config_store import ConfigModel, ConfigStore, get_config_store


class Config:
    """Convenience facade providing legacy Config() semantics."""

    def __new__(cls):
        return cls.current()

    @staticmethod
    def current() -> ConfigModel:
        return get_config_store().config

    @staticmethod
    def store() -> ConfigStore:
        return get_config_store()

    @staticmethod
    def subscribe(callback: Callable[[ConfigModel], None]) -> None:
        get_config_store().config_changed.connect(callback)

    @staticmethod
    def subscribe_overlay(callback: Callable[[str], None]) -> None:
        get_config_store().overlay_setting_changed.connect(callback)

    @staticmethod
    def save(section_updates):
        return get_config_store().save(section_updates)


__all__ = ["Config", "ConfigModel"]
