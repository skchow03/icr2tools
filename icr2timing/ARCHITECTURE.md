# icr2timing Architecture

`icr2timing` is the live telemetry overlay that sits on top of IndyCar Racing II.
It boots a Qt control panel, polls process memory through `icr2_core`, and
renders overlays in a worker-safe way.

## Control flow at a glance
1. **Bootstrap (`main.py`)** – Configures logging, spins up the Qt application,
   and loops until `ICR2Memory` can attach. It wires `Config`,
   `MemoryReader.read_race_state`, and a `RaceUpdater` worker into the
   `ControlPanel`.
2. **Polling (`updater/RaceUpdater`)** – Lives in a `QThread`, fires a precise
   `QTimer`, and on each tick calls `read_race_state()`. Emits `state_updated`
   with a frozen `RaceState`, or `error` when polling fails. Stops gracefully if
   DOSBox exits.
3. **Presentation (`ui/control_panel.py`)** – Hosts overlay toggles, profile
   management, logging/recording controls, and delegates overlay lifecycle to
   `OverlayManager`. Also exposes pit/command helpers and hot-reload of UI
   settings so most logic stays testable.
4. **Overlays (`overlays/`)** – Widgets such as the running-order table,
   proximity radar, and TRK-based track map subscribe to updater signals and use
   `analysis/` helpers (`best_laps`, `gap_utils`, etc.) to turn telemetry into
   formatted strings and colours.
5. **Hooks & services** – `utils/ini_preserver.py` and `core/config_backend.py`
   keep INI comments intact; `core/telemetry/*` modules record per-car CSVs;
   `analysis/` keeps best-lap/gap caches; `updater/overlay_manager.py` brokers
   show/hide/reset commands for the overlay suite.

## UI building blocks
- **Control panel** – The main window that starts/stops polling, shows overlay
  toggles, profile selectors, and errors from the updater.
- **Overlay widgets** – `overlays/running_order_overlay.py`,
  `overlays/proximity_overlay.py`, `overlays/track_map_overlay.py`, and
  experimental surface/map layers share a `BaseOverlay` interface for consistent
  `on_state_updated`/`on_error` hooks and window handles.
- **Editors** – `car_data_editor.py` and `ui/car_value_helpers.py` reuse the same
  telemetry pipeline to edit or export values without the overlay chrome.

## Integration with `icr2_core`
- Uses `icr2_core.icr2_memory.ICR2Memory` for typed reads/writes and cleanup.
- `icr2_core.reader.MemoryReader` translates raw memory into immutable models
  that can be sent across Qt threads safely.
- TRK helpers in `icr2_core.trk.*` supply centreline samples and surface meshes
  for the track-map overlays.
