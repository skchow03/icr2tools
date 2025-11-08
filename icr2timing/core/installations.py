"""Installation management utilities.

This module keeps a list of known ICR2 installations inside ``settings.ini``.
Each installation stores a user-facing name, the path to the executable, the
memory version (``DOS``, ``REND32A`` or ``WINDY``) and a list of window title
keywords.  The active installation controls which executable/path/version the
rest of the application uses.

The structure persisted to ``settings.ini`` looks like::

    [installations]
    active = default
    order = default, rend32

    [installation:default]
    name = DOSBox Default
    exe = C:/Games/ICR2/indycar.exe
    version = REND32A
    keywords = dosbox, cart

    [installation:rend32]
    name = Rendition
    exe = D:/ICR2_Rendition/cart.exe
    version = REND32A
    keywords = dosbox, cart

``InstallationManager`` handles reading/writing this data and also keeps the
legacy ``[memory]``/``[paths]`` sections in sync so that existing code paths
continue to work without modification.
"""

from __future__ import annotations

from dataclasses import dataclass
import configparser
import os
import re
import sys
from typing import Iterable, List, Optional


@dataclass
class Installation:
    """Dataclass describing a single ICR2 installation entry."""

    key: str
    name: str
    exe_path: str
    version: str
    keywords: List[str]

    def keywords_string(self) -> str:
        return ", ".join(self.keywords)


class InstallationManager:
    """Read/write helper for installation metadata stored in ``settings.ini``."""

    SECTION_ROOT = "installations"
    SECTION_PREFIX = "installation:"

    def __init__(self):
        self._cfgdir = os.path.dirname(sys.argv[0])
        self._cfgfile = os.path.join(self._cfgdir, "settings.ini")
        self._parser = configparser.ConfigParser()
        self._load()

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------
    def list_installations(self) -> List[Installation]:
        self._load()
        keys = self._ordered_keys()
        installs: List[Installation] = []
        seen = set()
        for key in keys:
            inst = self._read_installation(key)
            if inst:
                installs.append(inst)
                seen.add(key)

        # Include stray sections not present in order list
        for section in self._parser.sections():
            if section.startswith(self.SECTION_PREFIX):
                key = section.split(":", 1)[1]
                if key not in seen:
                    inst = self._read_installation(key)
                    if inst:
                        installs.append(inst)
        return installs

    def get_installation(self, key: str) -> Optional[Installation]:
        self._load()
        return self._read_installation(key)

    def get_active_key(self) -> Optional[str]:
        self._load()
        if not self._parser.has_section(self.SECTION_ROOT):
            return None
        active = self._parser.get(self.SECTION_ROOT, "active", fallback="").strip()
        if active:
            return active
        keys = self._ordered_keys()
        return keys[0] if keys else None

    def set_active(self, key: str) -> Optional[Installation]:
        self._load()
        if not key:
            return None
        inst = self._read_installation(key)
        if not inst:
            return None

        if not self._parser.has_section(self.SECTION_ROOT):
            self._parser.add_section(self.SECTION_ROOT)
        self._parser.set(self.SECTION_ROOT, "active", key)
        self._apply_active_defaults(inst)
        self._save()
        return inst

    def add_installation(
        self,
        name: str,
        exe_path: str,
        version: str,
        keywords: Iterable[str],
    ) -> Installation:
        self._load()
        key = self._generate_key(name)
        section = f"{self.SECTION_PREFIX}{key}"
        if not self._parser.has_section(section):
            self._parser.add_section(section)

        normalized_version = (version or "REND32A").upper()
        keyword_list = [k.strip() for k in keywords if k and k.strip()]

        self._parser.set(section, "name", name.strip() or key)
        self._parser.set(section, "exe", exe_path.strip())
        self._parser.set(section, "version", normalized_version)
        self._parser.set(section, "keywords", ", ".join(keyword_list))

        if not self._parser.has_section(self.SECTION_ROOT):
            self._parser.add_section(self.SECTION_ROOT)

        order = self._ordered_keys()
        order.append(key)
        self._parser.set(self.SECTION_ROOT, "order", ", ".join(order))
        self._parser.set(self.SECTION_ROOT, "active", key)

        inst = Installation(key, name.strip() or key, exe_path.strip(), normalized_version, keyword_list)
        self._apply_active_defaults(inst)
        self._save()
        return inst

    def update_installation(
        self,
        key: str,
        *,
        name: Optional[str] = None,
        exe_path: Optional[str] = None,
        version: Optional[str] = None,
        keywords: Optional[Iterable[str]] = None,
    ) -> Optional[Installation]:
        self._load()
        section = f"{self.SECTION_PREFIX}{key}"
        if not self._parser.has_section(section):
            return None

        if name is not None:
            self._parser.set(section, "name", name.strip() or key)
        if exe_path is not None:
            self._parser.set(section, "exe", exe_path.strip())
        if version is not None:
            self._parser.set(section, "version", (version or "REND32A").upper())
        if keywords is not None:
            keyword_list = [k.strip() for k in keywords if k and k.strip()]
            self._parser.set(section, "keywords", ", ".join(keyword_list))

        inst = self._read_installation(key)
        active_key = self.get_active_key()
        if inst and active_key == key:
            self._apply_active_defaults(inst)
        self._save()
        return inst

    def remove_installation(self, key: str) -> bool:
        self._load()
        section = f"{self.SECTION_PREFIX}{key}"
        if not self._parser.has_section(section):
            return False

        self._parser.remove_section(section)
        order = [k for k in self._ordered_keys() if k != key]
        if not self._parser.has_section(self.SECTION_ROOT):
            self._parser.add_section(self.SECTION_ROOT)
        self._parser.set(self.SECTION_ROOT, "order", ", ".join(order))

        active_key = self.get_active_key()
        if active_key == key:
            new_key = order[0] if order else None
            if new_key:
                inst = self._read_installation(new_key)
                if inst:
                    self._parser.set(self.SECTION_ROOT, "active", new_key)
                    self._apply_active_defaults(inst)
            else:
                self._parser.remove_option(self.SECTION_ROOT, "active")
        self._save()
        return True

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------
    def _load(self) -> None:
        self._parser.read(self._cfgfile)
        self._migrate_legacy_if_needed()

    def _save(self) -> None:
        with open(self._cfgfile, "w", encoding="utf-8") as fh:
            self._parser.write(fh)

    def _ordered_keys(self) -> List[str]:
        if not self._parser.has_section(self.SECTION_ROOT):
            return []
        order = self._parser.get(self.SECTION_ROOT, "order", fallback="")
        return [k.strip() for k in order.split(",") if k.strip()]

    def _read_installation(self, key: str) -> Optional[Installation]:
        section = f"{self.SECTION_PREFIX}{key}"
        if not self._parser.has_section(section):
            return None
        name = self._parser.get(section, "name", fallback=key).strip()
        exe = self._parser.get(section, "exe", fallback="").strip()
        version = self._parser.get(section, "version", fallback="REND32A").upper().strip()
        keywords_raw = self._parser.get(section, "keywords", fallback="")
        keywords = [k.strip() for k in keywords_raw.split(",") if k.strip()]
        return Installation(key, name, exe, version, keywords)

    def _generate_key(self, name: str) -> str:
        base = re.sub(r"[^a-z0-9]+", "-", name.strip().lower()) or "install"
        base = base.strip("-") or "install"
        existing = {inst.key for inst in self.list_installations()}
        candidate = base
        counter = 2
        while candidate in existing:
            candidate = f"{base}-{counter}"
            counter += 1
        return candidate

    def _apply_active_defaults(self, inst: Installation) -> None:
        if not self._parser.has_section("memory"):
            self._parser.add_section("memory")
        if not self._parser.has_section("paths"):
            self._parser.add_section("paths")

        self._parser.set("memory", "version", inst.version.upper())
        self._parser.set("memory", "window_keywords", inst.keywords_string())
        self._parser.set("paths", "game_exe", inst.exe_path)

    def _migrate_legacy_if_needed(self) -> None:
        has_install_sections = any(
            section.startswith(self.SECTION_PREFIX) for section in self._parser.sections()
        )
        if has_install_sections:
            return

        legacy_exe = self._parser.get("paths", "game_exe", fallback="").strip()
        legacy_version = self._parser.get("memory", "version", fallback="REND32A").strip() or "REND32A"
        keywords_raw = self._parser.get("memory", "window_keywords", fallback="")
        legacy_keywords = [k.strip() for k in keywords_raw.split(",") if k.strip()]

        if not (legacy_exe or legacy_keywords or legacy_version):
            return

        if not self._parser.has_section(self.SECTION_ROOT):
            self._parser.add_section(self.SECTION_ROOT)

        key = "default"
        section = f"{self.SECTION_PREFIX}{key}"
        if not self._parser.has_section(section):
            self._parser.add_section(section)

        self._parser.set(section, "name", "Default Installation")
        self._parser.set(section, "exe", legacy_exe)
        self._parser.set(section, "version", legacy_version.upper())
        self._parser.set(section, "keywords", ", ".join(legacy_keywords))
        self._parser.set(self.SECTION_ROOT, "order", key)
        self._parser.set(self.SECTION_ROOT, "active", key)

        inst = self._read_installation(key)
        if inst:
            self._apply_active_defaults(inst)
        self._save()

