# ICR2Tools Architecture

This document is written for new contributors (human or AI) who need context about how the
ICR2Tools repository fits together. It focuses on the two packages that ship in this repo:

* **`icr2_core/`** – a reusable Python package that knows how to talk to IndyCar Racing II
  (memory access, binary formats, track helpers).
* **`icr2timing/`** – the Qt-based live timing overlay application that players see on screen.

Most functionality is pure Python so it can be reused by other tooling and unit tests. The
timing overlay imports heavily from `icr2_core` for memory access, data models, and track
geometry parsing.

---

## 🗺️ Repository Topology

```
icr2tools/
├── icr2_core/               # Shared library imported by all tooling
│   ├── icr2_memory.py       # Process attach + typed memory reads/writes
│   ├── reader.py            # Turns raw memory into structured RaceState objects
│   ├── model.py             # Dataclasses representing drivers, car state, race state
│   ├── trk/                 # Track (.trk) parsing, surface meshes, OBJ/3D exporters
│   └── dat/                 # DAT archive helpers (e.g. unpackdat.py)
├── icr2timing/              # GUI overlay application & supporting scripts
│   ├── main.py              # Entry point; wires memory, updater, and Qt UI together
│   ├── core/                # Config, telemetry loggers, field metadata, recorder utilities
│   ├── analysis/            # Pure helpers for best laps, gaps, and name formatting
│   ├── updater/             # Worker thread + overlay manager coordination
│   ├── overlays/            # Overlay widgets (timing table, radar, track map, etc.)
│   ├── ui/                  # Control panel glue, profile manager, value editors, .ui file
│   ├── utils/               # Shared INI-preserving helpers
│   ├── assets/              # Icon and bundled resources
│   ├── car_data_editor.py   # Stand-alone telemetry editor built on the same pipeline
│   ├── convert_icon.py      # Utility for regenerating the overlay icon
│   ├── build.bat            # PyInstaller build script
│   ├── settings.ini         # Default runtime configuration
│   └── profiles.ini         # Example layout/radar profile bundle
├── tests/                   # Unit tests for analysis helpers and profile handling
├── setup.py / setup.cfg     # Editable install entry for icr2_core
└── README.md                # Project overview & installation instructions
```

---

## 🧠 Package Breakdown

### `icr2_core/`

* **`icr2_memory.ICR2Memory`** attaches to DOSBox/ICR2 processes by scanning window titles and signature bytes, supports all known executables (`REND32A`, `DOS`, `WINDY`), and exposes typed `read`/`write` helpers plus `BulkReader`/`read_blocks` for efficient structured reads. Configuration (window keywords, version) is pulled from `settings.ini` when parameters are omitted, and Windows handles are released cleanly on shutdown.【F:icr2_core/icr2_memory.py†L1-L200】
* **`reader.MemoryReader`** orchestrates the higher-level decoding: it reads counts, driver names, car numbers, and the raw 0x214 telemetry block; computes lap counts, lap times, gaps, and status flags; and assembles immutable `Driver`, `CarState`, and `RaceState` instances. It also fetches track length/name (with WINDY-specific caching logic) and raises `ReadError` on failure so the UI can surface transient issues.【F:icr2_core/reader.py†L1-L206】【F:icr2_core/reader.py†L207-L432】
* **`model.py`** defines frozen dataclasses for `Driver`, `CarState`, and `RaceState`, making snapshots trivially thread-safe and serialisable across Qt signal boundaries.【F:icr2_core/model.py†L1-L54】【F:icr2_core/model.py†L55-L85】
* **Track utilities (`trk/`)** provide `load_trk_from_folder` (detect `.DAT` versus `.TRK` payloads), helpers for sampling centrelines, and `surface_mesh.build_ground_surface_mesh` which emits per-f-section quads plus cached bounds for rendering overlays like the track map and surface visualiser.【F:icr2_core/trk/track_loader.py†L1-L21】【F:icr2_core/trk/surface_mesh.py†L1-L188】
* **`dat/unpackdat.py`** is a stand-alone helper for extracting `.DAT` resource archives shipped with the game or for in-memory extraction when the track loader needs embedded `.TRK` payloads.【F:icr2_core/dat/unpackdat.py†L1-L118】

### `icr2timing/`

#### Entry point & bootstrap

* **`main.py`** configures logging (with a capped on-disk handler), boots the Qt application, retries `ICR2Memory` attachment via message boxes, and wires a shared `MemoryReader` and `RaceUpdater` into the `ControlPanel` before starting the worker thread. The app icon is loaded from `assets/icon.ico` for both frozen and development builds.【F:icr2timing/main.py†L1-L133】

#### Core utilities (`core/`)

* `config.Config` – thin facade over the shared `ConfigStore`, letting legacy callers fetch the current settings, subscribe to change signals, or persist overrides without holding a direct reference to the store.【F:icr2timing/core/config.py†L1-L37】
* `config_store.ConfigStore` – a `QObject` singleton that loads `settings.ini`, applies the correct memory offsets for the detected executable, exposes a `ConfigModel` with overlay defaults (fonts, colours, radar geometry, column widths), and emits `config_changed`/`overlay_setting_changed` when `reload()`/`save()` mutates runtime state so overlays can hot-reload UI tweaks.【F:icr2timing/core/config_store.py†L1-L200】【F:icr2timing/core/config_store.py†L201-L304】
* `config_backend.ConfigBackend` – handles INI parsing/persistence, version alias resolution, executable validation, and comment-preserving saves via the shared INI writer so that `settings.ini` edits never discard user annotations.【F:icr2timing/core/config_backend.py†L1-L113】
* `car_field_definitions.py` – metadata for the 133 telemetry integers powering custom table columns and editors (indexes, names, and descriptions).【F:icr2timing/core/car_field_definitions.py†L1-L78】
* `car_data_recorder.py` – CSV recorder for per-car telemetry slices, keeping metadata files alongside logs for later analysis and exposing methods to rotate car targets mid-session.【F:icr2timing/core/telemetry/car_data_recorder.py†L1-L163】
* `telemetry_laps.py` – session-wide lap logger that appends to a timestamped CSV whenever a car completes a lap, deduplicating laps via `lap_end_clock` tracking.【F:icr2timing/core/telemetry/telemetry_laps.py†L1-L73】
* `version.py` – single-source version string for the overlay executable.【F:icr2timing/core/version.py†L1-L1】

#### Analysis helpers (`analysis/`)

* `best_laps.BestLapTracker` tracks per-driver and global best laps, formats outputs as time or speed, and colour-codes purple/green for global/personal records.【F:icr2timing/analysis/best_laps.py†L1-L78】
* `gap_utils` renders gap/interval strings, highlights pitting/retired cars, and caches previous intervals to prevent flicker at the line.【F:icr2timing/analysis/gap_utils.py†L1-L191】
* `name_utils` splits driver names into first/last components, generates compact displays, and builds 3-letter abbreviations with collision handling for overlays and telemetry CSVs.【F:icr2timing/analysis/name_utils.py†L1-L147】

#### Updater & worker infrastructure (`updater/`)

* `RaceUpdater` lives in a worker `QThread`, runs a precise `QTimer`, emits `state_updated` and `error` signals, dynamically adjusts polling frequency, and shuts down when the DOSBox process exits.【F:icr2timing/updater/updater.py†L1-L150】
* `OverlayManager` maintains the overlay registry, wires/disconnects updater signals, handles `show_all`/`hide_all`/`toggle`, and propagates personal-best resets across overlays.【F:icr2timing/updater/overlay_manager.py†L1-L60】

#### Overlay suite (`overlays/`)

* All overlays implement the `BaseOverlay` ABC, guaranteeing a widget handle plus `on_state_updated`/`on_error` hooks.【F:icr2timing/overlays/base_overlay.py†L1-L27】
* `running_order_overlay.py` drives the flagship timing table: it keeps column metadata, tracks best laps, manages Δ position indicators with expirations, honours custom `CarState.values` fields, and optionally sorts by personal bests while ensuring the player car stays visible.【F:icr2timing/overlays/running_order_overlay.py†L1-L200】
* `proximity_overlay.py` renders a configurable radar with persistent config-backed size, ranges, symbol styles, colours, and optional speed readouts; setters persist changes via `Config.save` so the UI controls can drive it live.【F:icr2timing/overlays/proximity_overlay.py†L1-L200】
* `track_map_overlay.py` loads TRK files via the shared loader, samples centrelines, autosizes the window, and paints cars/racing lines in sync with telemetry snapshots.【F:icr2timing/overlays/track_map_overlay.py†L1-L200】
* `experimental_track_surface_overlay.py` caches ground-surface meshes built from TRK sections and renders them as filled polygons, reloading whenever the track name changes.【F:icr2timing/overlays/experimental_track_surface_overlay.py†L1-L200】
* `individual_car_overlay.py` exposes a draggable, editable table of all 133 car-state fields, reuses the shared value recorder/range tracking helpers, and can write values back to memory (with confirmation) for live experimentation.【F:icr2timing/overlays/individual_car_overlay.py†L1-L200】

#### UI layer & services (`ui/`)

* `control_panel.py` (Qt Designer `.ui` driven) orchestrates overlay lifecycles, radar controls, telemetry utilities, updater connections, and profile persistence, wiring each subsection to the relevant PyQt widgets and hooking into the updater signals.【F:icr2timing/ui/control_panel.py†L1-L200】
* Section helpers (`control_sections.py`) encapsulate button groups for overlays, radar settings, and telemetry controls, emitting intent-specific signals and syncing with the config store so UI feedback stays coherent.【F:icr2timing/ui/control_sections.py†L1-L200】
* `profile_manager.py` models saved layouts (columns, radar placement, custom telemetry fields), injects the position-indicator column when enabled, and persists updates through the INI preserver so user comments survive saves.【F:icr2timing/ui/profile_manager.py†L1-L195】
* Backend helpers in `services.py` now include `LapLoggerController`, `PitCommandService`, `SessionPersistence`, and the high-level `TelemetryServiceController`. Together they attach/detach the lap logger, gate pit-release/fuel writes behind confirmations, persist the "last session" profile, and wire telemetry controls to updater signals while handling shutdown prompts in one place – keeping heavy logic out of the Qt widgets for easier testing.【F:icr2timing/ui/services.py†L1-L220】【F:icr2timing/ui/services.py†L244-L440】
* `car_value_helpers.py` provides the reusable recording controller, value-range tracker, frozen value store, delegate painting, and parsing helpers used by the individual car overlay and the stand-alone editor.【F:icr2timing/ui/car_value_helpers.py†L1-L200】
* `track_selector.py` surfaces game tracks based on `settings.ini`'s `game_exe` path, emitting a signal whenever a user chooses a new folder for tooling that needs to open TRK files.【F:icr2timing/ui/track_selector.py†L1-L69】

#### Persistence & utilities

* `utils/ini_preserver.py` performs targeted INI edits without clobbering comments, inserting or removing sections/assignments in-place for both `settings.ini` and `profiles.ini`. This helper underpins `ConfigBackend` and `ProfileManager`.【F:icr2timing/utils/ini_preserver.py†L1-L170】
* `profiles.ini` and `settings.ini` are therefore kept readable even when overlays or services constantly update runtime parameters.

#### Stand-alone tooling & editors

* `car_data_editor.py` boots the same memory reader/updater pipeline inside a dedicated widget, presents car selection + editable 133-field table, and streams recordings via the shared recorder helpers so users can tweak memory without running the main overlay.【F:icr2timing/car_data_editor.py†L1-L200】
* `convert_icon.py` and `build.bat` support packaging the PyInstaller executable.

#### Tests (`tests/`)

* The `tests/` package exercises config loading, INI preservation, overlay control sections, and service classes; for example, `tests/test_ui_services.py` verifies the lap logger controller, pit commands, and session persistence glue without spinning up Qt.【F:tests/test_ui_services.py†L1-L200】

---

## 🔄 End-to-End Flow (Timing Overlay)

1. **Bootstrap (`icr2timing/main.py`)** – Configure logging, create the `QApplication`, set the
   window icon, and loop until `ICR2Memory` attaches or the user cancels. Instantiate
   `Config`, `MemoryReader`, and `RaceUpdater`, then create and show the `ControlPanel`. A
   worker `QThread` is started and `RaceUpdater.start()` is invoked via `QMetaObject` to begin
   polling.【F:icr2timing/main.py†L39-L115】
2. **Memory access (`icr2_core/icr2_memory.py`)** – Attach to the target process based on
   `settings.ini` keywords, locate the executable base via signature scanning, and expose
   typed reads/writes plus efficient bulk readers. Handles cleanup in `close()`/context
   managers so file descriptors and process handles are never leaked.【F:icr2_core/icr2_memory.py†L41-L129】【F:icr2_core/icr2_memory.py†L222-L333】
3. **Decoding (`icr2_core/reader.py`)** – Each poll reads car counts, names, numbers, and the
   telemetry blob; computes lap times with wraparound-aware arithmetic; detects pit/retirement
   status; fetches track metadata; and returns a frozen `RaceState` snapshot. Track lookup for
   WINDY builds scans `.TXT` files once and caches them for subsequent polls.【F:icr2_core/reader.py†L49-L206】【F:icr2_core/reader.py†L267-L432】
4. **Worker loop (`icr2timing/updater/updater.py`)** – `RaceUpdater` runs inside the worker
   thread, firing a high-precision `QTimer` at `Config.poll_ms`. On each timeout it calls
   `read_race_state()`, emits snapshots, deduplicates error messages, and stops polling when
   the DOSBox process exits.【F:icr2timing/updater/updater.py†L13-L125】
5. **Presentation (`icr2timing/ui/control_panel.py` + overlays)** – The control panel connects
   overlay widgets, toggles, radar controls, and telemetry utilities. It proxies updater
   signals to the overlay manager (for table/surface/map) and directly to widgets like the
   proximity radar or individual telemetry panel. Profiles, lap logging, and car release/pit
   commands live here.【F:icr2timing/ui/control_panel.py†L1-L149】
6. **Analysis helpers (`icr2timing/analysis/`)** – Overlays call `best_laps`, `gap_utils`, and
   other helpers to translate raw snapshots into formatted strings, colour codes, and tooltips.

---

## 🧵 Threading & Signal Model

* `RaceUpdater` is a `QObject` that lives in a worker `QThread`; its `start/stop` slots and
  `state_updated`/`error` signals are invoked via queued connections from the GUI thread.
* `OverlayManager` keeps overlay widgets in sync by connecting them to the updater and exposing
  bulk `show_all`, `hide_all`, and `reset_pbs` operations, while specialised overlays (radar,
  individual car telemetry) manage their own connections for additional UI controls.【F:icr2timing/updater/overlay_manager.py†L1-L77】【F:icr2timing/ui/control_panel.py†L29-L117】
* `RaceState`/`CarState` instances are immutable, so they can be safely shared across Qt
  threads without locking.

---

## ⚙️ Configuration, Persistence & Assets

* **`settings.ini`** (in `icr2timing/`) controls memory version, polling interval, fonts, colour
  palette, radar geometry, and optional paths like `game_exe`. `ConfigStore` loads the file via
  `ConfigBackend`, verifies the configured executable, applies the right offsets, and emits
  change notifications so overlays update instantly, while `ICR2Memory` still honours the same
  version/path hints during attachment.【F:icr2timing/core/config_store.py†L197-L304】【F:icr2timing/core/config_backend.py†L31-L113】【F:icr2_core/icr2_memory.py†L14-L39】
* **`profiles.ini`** stores overlay layouts. `ProfileManager` loads/saves entries, injects the
  position-change indicator column when enabled, persists radar/overlay placement, and keeps
  per-profile custom telemetry columns bound to `CarState.values` indices.【F:icr2timing/ui/profile_manager.py†L1-L194】
* **INI persistence (`icr2timing/utils/ini_preserver.py`)** centralises comment-friendly writes
  for both configuration files, allowing targeted key/section edits without clobbering user
  annotations – the helper is reused by `ConfigBackend` and `ProfileManager`.【F:icr2timing/utils/ini_preserver.py†L1-L170】【F:icr2timing/core/config_backend.py†L31-L60】【F:icr2timing/ui/profile_manager.py†L13-L194】
* **Telemetry logging** – The telemetry service toggles the lap logger (`TelemetryLapLogger`)
  and car data recorder (`CarDataRecorder`), each keeping CSV handles open with optional
  `flush_every` thresholds so long runs can trade durability vs. throughput while still
  emitting timestamped logs and metadata for offline analysis.【F:icr2timing/ui/services.py†L319-L418】【F:icr2timing/core/telemetry/telemetry_laps.py†L18-L116】【F:icr2timing/core/telemetry/car_data_recorder.py†L18-L190】
* **Assets/packaging** – `assets/icon.ico` is loaded by the Qt app; `build.bat` wraps PyInstaller,
  and `convert_icon.py` regenerates icons from source artwork.

---

## ➕ Extending the System

### Adding a new memory field
1. Add offsets or index metadata to `icr2timing/core/config.py` (and optionally
   `car_field_definitions.py` for display labels).
2. Update `MemoryReader._read_laps_full` (or a new helper) to decode the value into
   `CarState` and surface any derived properties.
3. Reference the field from overlays/analysis helpers via the `RaceState.car_states` map.

### Creating a new overlay widget
1. Subclass `BaseOverlay` (`icr2timing/overlays/base_overlay.py`) and implement `widget()`,
   `on_state_updated`, and `on_error`.
2. Register the overlay with `ControlPanel` (direct connection) or `OverlayManager` (for global
   toggle/reset support).
3. If the overlay needs UI controls, extend `control_panel.ui` and wire slots/signals in
   `control_panel.py`.

### Reusing core helpers in other tools
* Run `pip install -e .` to import `icr2_core` in external scripts – the package has no Qt
  dependency and works headlessly for automation, track conversion, or telemetry capture.
* Track utilities under `icr2_core/trk/` expose loaders and exporters that can be called from
  notebooks or command-line scripts without touching the GUI.

---

## 🧪 Tests & Developer Notes

* Unit tests live under `tests/` and currently exercise gap/interval formatting plus profile
  encoding to catch regressions in overlay output and persistence expectations.【F:tests/test_gap_utils.py†L1-L88】【F:tests/test_profile_manager_encoding.py†L1-L120】
* `tests/test_ui_services.py` covers `LapLoggerController`, `PitCommandService`, and
  `SessionPersistence`, so telemetry toggles, pit commands, and session snapshots stay
  correct without spinning up Qt widgets.【F:tests/test_ui_services.py†L1-L200】
* The repository is Windows-centric (uses Win32 APIs and PyQt5). Non-Windows environments can
  still run pure-Python helpers and tests, but memory attachment requires Windows with DOSBox.

---

## 🧭 Key Entry Points for ChatGPT

* Launching the overlay: `icr2timing/main.py` → `main()`.
* Memory attach/read pipeline: `icr2_core/icr2_memory.py` → `ICR2Memory`,
  `icr2_core/reader.py` → `MemoryReader.read_race_state()`.
* UI control hub: `icr2timing/ui/control_panel.py` → `ControlPanel`.
* Extensible overlays: `icr2timing/overlays/` (start with `running_order_overlay.py`).
* Configuration knobs: `icr2timing/core/config.py`, `icr2timing/settings.ini`,
  `icr2timing/profiles.ini`.

Use this map to orient yourself before making changes; most features span both the memory
reader (`icr2_core`) and the presentation layer (`icr2timing`).
