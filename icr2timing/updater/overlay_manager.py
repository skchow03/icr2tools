"""
overlay_manager.py

OverlayManager manages multiple overlays implementing BaseOverlay.
"""
import logging
log = logging.getLogger(__name__)

from typing import List

from overlays.base_overlay import BaseOverlay



class OverlayManager:
    def __init__(self):
        self._overlays: List[BaseOverlay] = []

    def add_overlay(self, overlay: BaseOverlay):
        self._overlays.append(overlay)

    def remove_overlay(self, overlay: BaseOverlay):
        if overlay in self._overlays:
            self._overlays.remove(overlay)

    def show_all(self):
        for o in self._overlays:
            o.widget().show()
            o.widget().raise_()

    def hide_all(self):
        for o in self._overlays:
            o.widget().hide()

    def toggle(self):
        if any(o.widget().isVisible() for o in self._overlays):
            self.hide_all()
        else:
            self.show_all()

    def reset_pbs(self):
        for o in self._overlays:
            if hasattr(o, "reset_pbs"):
                o.reset_pbs()

    def connect_updater(self, updater):
        for o in self._overlays:
            updater.state_updated.connect(o.on_state_updated)
            updater.error.connect(o.on_error)

    def disconnect_updater(self, updater):
        for o in self._overlays:
            try:
                log.info(f"[OverlayManager] Disconnecting updater from overlay: {o}")
                updater.state_updated.disconnect(o.on_state_updated)
                updater.error.disconnect(o.on_error)
            except Exception:
                pass

    def overlays(self) -> List[BaseOverlay]:
        return list(self._overlays)
