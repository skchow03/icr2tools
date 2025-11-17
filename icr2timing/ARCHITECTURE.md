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

* **`icr2_memory.ICR2Memory`** attaches to DOSBox/ICR2 processes by scanning window titles and
  signature bytes, supports all known executables (`REND32A`, `DOS`, `WINDY`), and exposes
  typed `read`/`write` helpers plus `BulkReader`/`read_blocks` for efficient structured reads.
  Configuration (window keywords, version) is pulled from `settings.ini` when parameters are
  omitted, and Windows handles are released cleanly on shutdown.【F:icr2_core/icr2_memory.py†L1-L129】【F:icr2_core/icr2_memory.py†L130-L221】
* **`reader.MemoryReader`** orchestrates the higher-level decoding: it reads counts, driver
  names, car numbers, and the raw 0x214 telemetry block; computes lap counts, lap times, gaps,
  and status flags; and assembles immutable `Driver`, `CarState`, and `RaceState` instances.
  It also fetches track length/name (with WINDY-specific caching logic) and raises `ReadError`
  on failure so the UI can surface transient issues.【F:icr2_core/reader.py†L1-L206】【F:icr2_core/reader.py†L207-L432】
* **`model.py`** defines frozen dataclasses for `Driver`, `CarState`, and `RaceState`, making
  snapshots trivially thread-safe and serialisable across Qt signal boundaries.【F:icr2_core/model.py†L1-L54】【F:icr2_core/model.py†L55-L85】
* **Track utilities (`trk/`)** expose loaders (`track_loader.py`), geometry classes, surface mesh
  generators, and exporters used by overlays like the track map and surface visualiser.
* **`dat/unpackdat.py`** is a stand-alone helper for extracting `.DAT` resource archives shipped
  with the game.

### `icr2timing/`

* **Entry point (`main.py`)** configures logging (with a capped on-disk handler), boots the
  Qt application, retries `ICR2Memory` attachment via message boxes, and wires a shared
  `MemoryReader`/`RaceUpdater` into the `ControlPanel` before starting the worker thread.
  The app icon is loaded from `assets/icon.ico` for both frozen and development builds.【F:icr2timing/main.py†L1-L115】
* **Core utilities (`core/`)** include:
  * `config.Config` – thin facade over the shared `ConfigStore`, letting legacy callers fetch the
    current settings, subscribe to change signals, or persist overrides without holding a direct
    reference to the store.【F:icr2timing/core/config.py†L1-L34】
  * `config_store.ConfigStore` – a `QObject` singleton that loads `settings.ini`, applies the
    correct memory offsets for the detected executable, exposes a `ConfigModel` with overlay
    defaults (fonts, colours, radar geometry, column widths), and emits
    `config_changed`/`overlay_setting_changed` when `reload()`/`save()` mutates runtime state so
    overlays can hot-reload UI tweaks.【F:icr2timing/core/config_store.py†L1-L200】【F:icr2timing/core/config_store.py†L242-L304】
  * `config_backend.ConfigBackend` – handles INI parsing/persistence, version alias resolution,
    executable validation, and comment-preserving saves via the shared INI writer so that
    `settings.ini` edits never discard user annotations.【F:icr2timing/core/config_backend.py†L1-L113】
  * `car_field_definitions.py` – metadata for the 133 telemetry integers powering custom table
    columns and editors.【F:icr2timing/core/car_field_definitions.py†L1-L78】
  * `car_data_recorder.py` – CSV recorder for per-car telemetry slices, keeping metadata files
    alongside logs for later analysis.【F:icr2timing/core/car_data_recorder.py†L1-L120】
  * `telemetry_laps.py` – session-wide lap logger that appends to a timestamped CSV whenever
    a car completes a lap.【F:icr2timing/core/telemetry_laps.py†L1-L63】
  * `version.py` – single-source version string for the overlay executable.【F:icr2timing/core/version.py†L1-L1】
* **Analysis helpers (`analysis/`)** provide deterministic formatting and classification logic:
  `best_laps.py` tracks personal/global bests, `gap_utils.py` renders gaps/intervals while
  handling retirements and pit status, and `name_utils.py` applies display tweaks.【F:icr2timing/analysis/best_laps.py†L1-L54】【F:icr2timing/analysis/gap_utils.py†L1-L131】
* **Updater (`updater/`)** houses `RaceUpdater`, the worker-side `QObject` that runs a precise
  `QTimer`, emits `state_updated`/`error`, and stops itself if the process disappears, plus
  `OverlayManager` for show/hide/reset orchestration across overlays.【F:icr2timing/updater/updater.py†L1-L125】【F:icr2timing/updater/overlay_manager.py†L1-L77】
* **Overlays (`overlays/`)** share a `BaseOverlay` contract and optional helpers in
  `overlay_table_window.py`. `running_order_overlay.py` drives the flagship timing table: it
  maintains a configurable column list (including the Δ position indicator), tracks best laps,
  honours profile-defined custom telemetry fields, and listens to `ConfigStore` signals so
  fonts/colours/resize throttling update live.【F:icr2timing/overlays/running_order_overlay.py†L1-L200】
  Additional overlays (proximity radar, track map, experimental surface visualiser, individual
  telemetry panel) respond to updater signals and use the shared geometry/analysis helpers.
* **UI layer (`ui/`)** contains:
  * `control_panel.py` – the main window built from `control_panel.ui`. It owns overlay
    instances, hooks up radar controls, manages the lap logger and profile persistence, and
    forwards updater signals to overlays that are not centrally managed (e.g. radar, individual
    telemetry).【F:icr2timing/ui/control_panel.py†L1-L149】
  * `profile_manager.py` – reads/writes `profiles.ini`, handles custom telemetry columns, and
    preserves radar/window placement per layout.【F:icr2timing/ui/profile_manager.py†L1-L120】
  * `car_value_helpers.py` – shared widgets/controllers for recording and editing raw telemetry
    values (reused by the individual-car overlay and the car data editor).
  * `track_selector.py` – helper widget listing track folders based on the configured game
    executable path, emitting signals on selection.【F:icr2timing/ui/track_selector.py†L1-L52】
* **Standalone tooling**:
  * `car_data_editor.py` spins up the same memory reader/updater pipeline in a dedicated
    widget, letting users inspect and overwrite individual telemetry values with live writes
    back to the game process.【F:icr2timing/car_data_editor.py†L1-L104】
  * `convert_icon.py` and `build.bat` support packaging the PyInstaller executable.

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
* **Telemetry logging** – The control panel can toggle the lap logger (`TelemetryLapLogger`)
  and car data recorder (`CarDataRecorder`), producing timestamped CSV + metadata files for
  offline analysis.【F:icr2timing/ui/control_panel.py†L77-L149】【F:icr2timing/core/car_data_recorder.py†L13-L120】
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
