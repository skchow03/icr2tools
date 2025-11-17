from __future__ import annotations

from typing import Callable, Optional

from PyQt5 import QtCore

from icr2timing.overlays.running_order_overlay import RunningOrderOverlayTable
from icr2timing.overlays.proximity_overlay import ProximityOverlay
from icr2timing.overlays.track_map_overlay import TrackMapOverlay
from icr2timing.overlays.experimental_track_surface_overlay import (
    ExperimentalTrackSurfaceOverlay,
)
from icr2timing.overlays.individual_car_overlay import IndividualCarOverlay
from icr2timing.updater.overlay_manager import OverlayManager


class OverlayController:
    """Encapsulates overlay setup, updater wiring, and visibility toggles."""

    def __init__(
        self,
        *,
        updater,
        config_store,
        running_order_overlay: RunningOrderOverlayTable,
        radar_overlay: ProximityOverlay,
        track_overlay: TrackMapOverlay,
        surface_overlay: ExperimentalTrackSurfaceOverlay,
        individual_overlay: IndividualCarOverlay,
        running_order_state_handler: Optional[Callable] = None,
    ):
        self._updater = updater
        self._config_store = config_store
        self.running_order_overlay = running_order_overlay
        self.radar_overlay = radar_overlay
        self.track_overlay = track_overlay
        self.surface_overlay = surface_overlay
        self.individual_overlay = individual_overlay
        self._running_order_state_handler = (
            running_order_state_handler or running_order_overlay.on_state_updated
        )

        self.manager = OverlayManager()
        self.manager.add_overlay(self.running_order_overlay)

        if self._updater:
            self._connect_static_overlays()
            self._connect_running_order_overlay()

    # ------------------------------------------------------------------
    # Updater wiring
    # ------------------------------------------------------------------
    def _connect_static_overlays(self):
        updater = self._updater
        updater.state_updated.connect(self.radar_overlay.on_state_updated)
        updater.error.connect(self.radar_overlay.on_error)

        updater.state_updated.connect(self.track_overlay.on_state_updated)
        updater.error.connect(self.track_overlay.on_error)

        updater.state_updated.connect(self.surface_overlay.on_state_updated)
        updater.error.connect(self.surface_overlay.on_error)

        updater.state_updated.connect(self.individual_overlay.on_state_updated)
        updater.error.connect(self.individual_overlay.on_error)

    def _connect_running_order_overlay(self):
        updater = self._updater
        updater.state_updated.connect(self._running_order_state_handler)
        updater.error.connect(self.running_order_overlay.on_error)

    def _disconnect_running_order_overlay(
        self,
        overlay: RunningOrderOverlayTable,
        handler: Callable,
    ):
        updater = self._updater
        try:
            updater.state_updated.disconnect(handler)
        except Exception:
            pass
        try:
            updater.error.disconnect(overlay.on_error)
        except Exception:
            pass

    # ------------------------------------------------------------------
    # Overlay management helpers
    # ------------------------------------------------------------------
    def replace_running_order_overlay(
        self,
        overlay: RunningOrderOverlayTable,
        *,
        state_handler: Optional[Callable] = None,
    ):
        old_overlay = self.running_order_overlay
        old_handler = self._running_order_state_handler
        if self._updater:
            self._disconnect_running_order_overlay(old_overlay, old_handler)

        self.manager.remove_overlay(old_overlay)
        self.running_order_overlay = overlay
        self.manager.add_overlay(overlay)
        self._running_order_state_handler = state_handler or overlay.on_state_updated

        if self._updater:
            self._connect_running_order_overlay()

    def reset_personal_bests(self):
        self.manager.reset_pbs()

    # ------------------------------------------------------------------
    # Toggle helpers
    # ------------------------------------------------------------------
    def toggle_running_order(self) -> bool:
        widget = self.running_order_overlay.widget()
        return self._toggle_widget(widget)

    def toggle_radar(self) -> bool:
        return self._toggle_widget(self.radar_overlay)

    def toggle_track_map(self) -> bool:
        return self._toggle_widget(self.track_overlay)

    def toggle_surface_overlay(self) -> bool:
        return self._toggle_widget(self.surface_overlay)

    def toggle_individual_overlay(self, car_index_data) -> Optional[bool]:
        if car_index_data is None:
            return None

        self.individual_overlay.set_car_index(car_index_data)
        return self._toggle_widget(self.individual_overlay)

    def _toggle_widget(self, widget) -> bool:
        if widget.isVisible():
            widget.hide()
            return False
        widget.show()
        widget.raise_()
        if hasattr(widget, "activateWindow"):
            widget.activateWindow()
        return True

    # ------------------------------------------------------------------
    # OBS capture mode
    # ------------------------------------------------------------------
    def set_obs_capture_mode(self, enabled: bool):
        """Toggle overlays between translucent overlay mode and OBS capture mode."""
        overlays = [
            self.running_order_overlay.widget(),
            self.radar_overlay,
            self.track_overlay,
        ]

        for overlay in overlays:
            if overlay is None:
                continue

            was_visible = overlay.isVisible()
            geom = overlay.geometry()
            overlay.hide()

            if enabled:
                flags = QtCore.Qt.FramelessWindowHint | QtCore.Qt.Window
                translucent = False
            else:
                flags = (
                    QtCore.Qt.FramelessWindowHint
                    | QtCore.Qt.Tool
                    | QtCore.Qt.WindowStaysOnTopHint
                )
                translucent = True

            overlay.setWindowFlags(flags)
            overlay.setAttribute(QtCore.Qt.WA_TranslucentBackground, translucent)

            if enabled:
                if overlay is self.running_order_overlay.widget():
                    overlay.setWindowTitle("ICR2 Timing - Running Order")
                elif overlay is self.track_overlay:
                    overlay.setWindowTitle("ICR2 Timing - Track Map")
                elif overlay is self.radar_overlay:
                    overlay.setWindowTitle("ICR2 Timing - Radar")
            else:
                overlay.setWindowTitle("")

            if hasattr(overlay, "cfg"):
                try:
                    overlay.cfg = self._config_store.config
                    overlay._update_ranges_from_cfg()
                    if translucent:
                        overlay.background.setAlpha(128)
                    else:
                        overlay.background.setAlpha(255)
                except Exception:
                    pass

            overlay.setGeometry(geom)
            if was_visible:
                overlay.show()
                overlay.raise_()

