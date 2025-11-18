"""Backend service helpers used by the Qt control panel.

These classes encapsulate logic that previously lived directly inside
``ControlPanel`` so it can be tested without spinning up the full UI and so the
UI layer can delegate heavy work to plain Python objects.
"""

from __future__ import annotations

import logging
import os
from dataclasses import dataclass
from typing import Callable, Optional, Sequence, Tuple

from PyQt5 import QtCore, QtWidgets

try:  # pragma: no cover - optional dependency for unit tests
    from icr2_core.icr2_memory import MemoryWritesDisabledError
except ModuleNotFoundError:  # pragma: no cover - fallback when pymem missing
    class MemoryWritesDisabledError(RuntimeError):
        pass

from icr2timing.core.telemetry_laps import TelemetryLapLogger
from icr2timing.overlays.constants import CAR_STATE_INDEX_PIT_RELEASE_TIMER
from icr2timing.ui.profile_manager import LAST_SESSION_KEY, Profile, ProfileManager

log = logging.getLogger(__name__)




StatusCallback = Callable[[str, int], None]
StateProvider = Callable[[], Optional[object]]
ConfirmCallback = Callable[[str], bool]


class LapLoggerController:
    """Manages attaching/detaching the telemetry lap logger from the updater."""

    def __init__(
        self,
        updater,
        status_callback: Optional[StatusCallback] = None,
        logger_factory: Optional[Callable[[], TelemetryLapLogger]] = None,
    ):
        self._updater = updater
        self._status = status_callback or (lambda msg, timeout=0: None)
        self._logger_factory = logger_factory or (lambda: TelemetryLapLogger("telemetry_laps"))
        self._lap_logger: Optional[TelemetryLapLogger] = None
        self._enabled = False
        self._recording_file: Optional[str] = None

    @property
    def enabled(self) -> bool:
        return self._enabled

    @property
    def recording_file(self) -> Optional[str]:
        return self._recording_file

    def toggle(self) -> bool:
        if not self._updater:
            self._status("Lap logging unavailable: updater not running", 5000)
            return False

        if self._enabled:
            self.disable()
        else:
            self.enable()
        return self._enabled

    def enable(self) -> bool:
        if self._enabled:
            return True

        if not self._updater:
            self._status("Lap logging unavailable: updater not running", 5000)
            return False

        try:
            logger = self._logger_factory()
            self._updater.state_updated.connect(logger.on_state_updated)
            self._lap_logger = logger
            self._enabled = True
            try:
                self._recording_file = logger.get_filename()
            except AttributeError:
                self._recording_file = None
            if self._recording_file:
                self._status(f"Recording laps → {os.path.basename(self._recording_file)}", 3000)
            else:
                self._status("Lap logging enabled", 3000)
        except Exception as exc:  # pragma: no cover - defensive logging
            log.error("Failed to enable lap logging", exc_info=exc)
            self._status(f"Failed to enable lap logging: {exc}", 5000)
            self._lap_logger = None
            self._enabled = False
            self._recording_file = None

        return self._enabled

    def disable(self) -> bool:
        if not self._enabled:
            return False

        try:
            if self._updater and self._lap_logger:
                self._updater.state_updated.disconnect(self._lap_logger.on_state_updated)
        except Exception:  # pragma: no cover - disconnect best effort
            pass

        if self._lap_logger:
            try:
                self._lap_logger.close()
            except Exception:  # pragma: no cover - defensive close
                log.debug("Lap logger close failed", exc_info=True)

        self._lap_logger = None
        self._enabled = False
        self._recording_file = None
        self._status("Lap logging disabled", 3000)
        return True


class PitCommandService:
    """Encapsulates memory write helpers for pit commands."""

    def __init__(
        self,
        mem,
        cfg,
        state_provider: StateProvider,
        confirm_enable_writes: Optional[ConfirmCallback] = None,
        status_callback: Optional[StatusCallback] = None,
    ):
        self._mem = mem
        self._cfg = cfg
        self._state_provider = state_provider
        self._confirm = confirm_enable_writes or (lambda purpose: False)
        self._status = status_callback or (lambda msg, timeout=0: None)

    def update_config(self, cfg):
        self._cfg = cfg

    def release_all_cars(self) -> int:
        """Force pit release countdown to 1 for all cars."""
        if not self._mem:
            self._status("Pit release unavailable: no memory connection", 5000)
            return 0

        if not self._ensure_memory_writes_enabled("set pit release timers to 1"):
            return 0

        state = self._state_provider() if self._state_provider else None
        if state is None:
            self._status("No telemetry state available yet", 3000)
            return 0

        base = getattr(self._cfg, "car_state_base", 0)
        stride = getattr(self._cfg, "car_state_size", 0)
        field_offset = CAR_STATE_INDEX_PIT_RELEASE_TIMER * 4

        updated = 0
        try:
            for struct_idx, car_state in getattr(state, "car_states", {}).items():
                values = getattr(car_state, "values", [])
                if len(values) <= CAR_STATE_INDEX_PIT_RELEASE_TIMER:
                    continue
                exe_offset = base + struct_idx * stride + field_offset
                self._mem.write(exe_offset, "i32", 1)
                updated += 1
        except MemoryWritesDisabledError:
            self._status("Memory writes remain disabled", 5000)
            return 0
        except Exception as exc:  # pragma: no cover - defensive logging
            log.exception("Failed to release all cars from pits", exc_info=exc)
            self._status(f"Failed to release all cars: {exc}", 5000)
            return 0

        if updated:
            self._status(f"Pit release set to 1 for {updated} cars", 3000)
        else:
            self._status("No eligible cars found to release", 3000)
        return updated

    def force_all_cars_to_pit(self) -> int:
        """Force fuel remaining to 1 lap for all cars."""
        if not self._mem:
            self._status("Force pit unavailable: no memory connection", 5000)
            return 0

        if not self._ensure_memory_writes_enabled("set every car's fuel to 1 lap"):
            return 0

        state = self._state_provider() if self._state_provider else None
        if state is None:
            self._status("No telemetry state available yet", 3000)
            return 0

        base = getattr(self._cfg, "car_state_base", 0)
        stride = getattr(self._cfg, "car_state_size", 0)
        field_offset = getattr(self._cfg, "fuel_laps_remaining", 0)
        field_index = field_offset // 4

        updated = 0
        try:
            for struct_idx, car_state in getattr(state, "car_states", {}).items():
                values = getattr(car_state, "values", [])
                if len(values) <= field_index:
                    continue
                exe_offset = base + struct_idx * stride + field_offset
                self._mem.write(exe_offset, "i32", 1)
                updated += 1
        except MemoryWritesDisabledError:
            self._status("Memory writes remain disabled", 5000)
            return 0
        except Exception as exc:  # pragma: no cover - defensive logging
            log.exception("Failed to force all cars to pit", exc_info=exc)
            self._status(f"Failed to force pit stops: {exc}", 5000)
            return 0

        if updated:
            self._status(f"Fuel set to 1 lap for {updated} cars", 3000)
        else:
            self._status("No eligible cars found to adjust fuel", 3000)
        return updated

    def _ensure_memory_writes_enabled(self, purpose: str) -> bool:
        if not self._mem:
            return False
        if getattr(self._mem, "writes_enabled", False):
            return True

        confirmed = self._confirm(purpose)
        if not confirmed:
            self._status("Memory writes remain disabled", 5000)
            return False

        self._mem.enable_writes()
        self._status("Memory writes enabled for this session", 5000)
        return True


@dataclass
class SessionSnapshot:
    ordered_field_keys: Sequence[str]
    custom_fields: Sequence[Tuple[str, int]]
    n_columns: int
    display_mode: str
    sort_by_best: bool
    use_abbrev: bool
    ro_window_x: int
    ro_window_y: int
    radar_x: int
    radar_y: int
    radar_visible: bool
    radar_width: int
    radar_height: int
    radar_range_forward: int
    radar_range_rear: int
    radar_range_side: int
    radar_symbol: str
    radar_show_speeds: bool
    radar_player_color: str
    radar_ai_ahead_color: str
    radar_ai_behind_color: str
    radar_ai_alongside_color: str
    position_indicator_duration: float
    position_indicator_enabled: bool
    available_fields: Sequence = ()


class SessionPersistence:
    """Creates and persists ``Profile`` snapshots for the last session."""

    def __init__(self, profile_manager: ProfileManager):
        self._profiles = profile_manager

    def save_last_session(self, snapshot: SessionSnapshot) -> Profile:
        key_to_label = {field.key: field.label for field in snapshot.available_fields}
        selected_labels = [
            key_to_label[key]
            for key in snapshot.ordered_field_keys
            if key in key_to_label
        ]

        profile = Profile(
            name=LAST_SESSION_KEY,
            columns=selected_labels,
            n_columns=snapshot.n_columns,
            display_mode=snapshot.display_mode,
            sort_by_best=snapshot.sort_by_best,
            use_abbrev=snapshot.use_abbrev,
            window_x=snapshot.ro_window_x,
            window_y=snapshot.ro_window_y,
            radar_x=snapshot.radar_x,
            radar_y=snapshot.radar_y,
            radar_visible=snapshot.radar_visible,
            radar_width=snapshot.radar_width,
            radar_height=snapshot.radar_height,
            radar_range_forward=snapshot.radar_range_forward,
            radar_range_rear=snapshot.radar_range_rear,
            radar_range_side=snapshot.radar_range_side,
            radar_symbol=snapshot.radar_symbol,
            radar_show_speeds=snapshot.radar_show_speeds,
            radar_player_color=snapshot.radar_player_color,
            radar_ai_ahead_color=snapshot.radar_ai_ahead_color,
            radar_ai_behind_color=snapshot.radar_ai_behind_color,
            radar_ai_alongside_color=snapshot.radar_ai_alongside_color,
            position_indicator_duration=snapshot.position_indicator_duration,
            position_indicator_enabled=snapshot.position_indicator_enabled,
            custom_fields=list(snapshot.custom_fields),
        )

        self._profiles.save_last_session(profile)
        return profile


class TelemetryServiceController(QtCore.QObject):
    """Coordinates telemetry-related services and UI wiring."""

    individual_overlay_toggle_requested = QtCore.pyqtSignal(object)
    individual_car_selected = QtCore.pyqtSignal(int)

    def __init__(
        self,
        *,
        updater,
        mem,
        cfg,
        telemetry_controls,
        profile_manager: ProfileManager,
        state_provider: Optional[StateProvider] = None,
        status_callback: Optional[StatusCallback] = None,
        parent: Optional[QtCore.QObject] = None,
    ) -> None:
        super().__init__(parent)
        self._updater = updater
        self._mem = mem
        self._cfg = cfg
        self._status = status_callback or (lambda msg, timeout=0: None)
        self._telemetry_controls = telemetry_controls
        self._state_provider = state_provider or (lambda: None)
        self._profile_manager = profile_manager
        self._session_persistence = SessionPersistence(profile_manager)
        self._lap_logger = LapLoggerController(
            updater=self._updater,
            status_callback=self._status,
        )
        self._pit_command_service = PitCommandService(
            mem=self._mem,
            cfg=self._cfg,
            state_provider=self._state_provider,
            confirm_enable_writes=self._prompt_enable_writes,
            status_callback=self._status,
        )

        telemetry_controls.lap_logger_toggle_requested.connect(
            self._on_toggle_lap_logger
        )
        telemetry_controls.release_all_cars_requested.connect(
            self._pit_command_service.release_all_cars
        )
        telemetry_controls.force_all_cars_requested.connect(
            self._pit_command_service.force_all_cars_to_pit
        )
        telemetry_controls.individual_overlay_toggle_requested.connect(
            self._on_individual_overlay_toggle_requested
        )
        telemetry_controls.individual_car_selected.connect(
            self.individual_car_selected.emit
        )

    # ------------------------------------------------------------------
    def update_config(self, cfg) -> None:
        self._cfg = cfg
        self._pit_command_service.update_config(cfg)

    # ------------------------------------------------------------------
    def load_last_session(self) -> Optional[Profile]:
        return self._profile_manager.load_last_session()

    def save_last_session(self, snapshot: SessionSnapshot) -> Profile:
        return self._session_persistence.save_last_session(snapshot)

    # ------------------------------------------------------------------
    def set_individual_overlay_visible(self, visible: bool) -> None:
        self._telemetry_controls.set_individual_overlay_visible(visible)

    @property
    def lap_logger_recording_file(self) -> Optional[str]:
        return self._lap_logger.recording_file

    # ------------------------------------------------------------------
    def shutdown(self) -> None:
        try:
            self._lap_logger.disable()
        except Exception:  # pragma: no cover - defensive
            pass
        self._stop_updater_thread()

    def _stop_updater_thread(self) -> None:
        if not self._updater:
            return
        try:
            QtCore.QMetaObject.invokeMethod(
                self._updater,
                "stop",
                QtCore.Qt.QueuedConnection,
            )
        except Exception as exc:  # pragma: no cover - log but keep closing
            log.warning("Failed to stop updater cleanly: %s", exc)

    # ------------------------------------------------------------------
    def _on_toggle_lap_logger(self) -> None:
        enabled = self._lap_logger.toggle()
        self._telemetry_controls.set_lap_logger_enabled(enabled)

    def _on_individual_overlay_toggle_requested(self) -> None:
        idx_data = self._telemetry_controls.current_car_index()
        if idx_data is None:
            self._status("Select a car before toggling telemetry overlay", 3000)
            return
        self.individual_overlay_toggle_requested.emit(idx_data)

    def _prompt_enable_writes(self, purpose: str) -> bool:
        message = (
            "Memory writes are currently disabled for this session.\n\n"
            f"Enabling writes will allow the tool to {purpose}. "
            "Only proceed if you understand the risks."
        )
        parent_widget = self.parent() if isinstance(self.parent(), QtWidgets.QWidget) else None
        reply = QtWidgets.QMessageBox.warning(
            parent_widget,
            "Enable memory writes?",
            message,
            QtWidgets.QMessageBox.Yes | QtWidgets.QMessageBox.No,
            QtWidgets.QMessageBox.No,
        )
        return reply == QtWidgets.QMessageBox.Yes
