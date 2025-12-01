# ICR2Tools Architecture

This document gives new contributors a map of the repository and how the
packages interact. The project ships three main deliverables:

* **`icr2_core/`** – shared Python library for reading IndyCar Racing II process
  memory, decoding telemetry into dataclasses, and parsing track/camera
  resources.
* **`icr2timing/`** – Qt-based live timing overlay used while driving.
* **`track_viewer/`** – experimental Qt utility for browsing `.TRK` files and
  editing camera placements outside the game.

Most functionality is pure Python so it can be exercised by tests or reused by
other tooling.

---

## 🗺️ Repository Topology

```
icr2tools/
├── icr2_core/               # Shared library imported by all tooling
│   ├── icr2_memory.py       # Process attach + typed memory reads/writes
│   ├── reader.py            # Turns raw memory into structured RaceState objects
│   ├── model.py             # Dataclasses representing drivers, car state, race state
│   ├── cam/                 # Camera parsers/helpers shared with the track viewer
│   ├── trk/                 # Track (.trk) parsing, surface meshes, OBJ/3D exporters
│   └── dat/                 # DAT archive helpers (e.g. unpackdat.py)
├── icr2timing/              # GUI overlay application & supporting scripts
│   ├── main.py              # Entry point; wires memory, updater, and Qt UI together
│   ├── core/                # Config, telemetry loggers, field metadata, recorder utilities
│   ├── analysis/            # Helpers for best laps, gaps, and name formatting
│   ├── updater/             # Worker thread + overlay manager coordination
│   ├── overlays/            # Overlay widgets (timing table, radar, track map, etc.)
│   ├── ui/                  # Control panel glue, profile manager, value editors, .ui file
│   ├── utils/               # Shared INI-preserving helpers
│   ├── assets/              # Icon and bundled resources
│   ├── car_data_editor.py   # Stand-alone telemetry editor built on the same pipeline
│   ├── convert_icon.py      # Utility for regenerating the overlay icon
│   └── build.bat            # PyInstaller build script
├── track_viewer/            # Standalone TRK + camera inspector/editor
│   ├── app.py               # QApplication shell + main window wiring
│   ├── preview_widget.py    # TRK surface renderer and camera/flag interactions
│   ├── tv_modes_panel.py    # Type 6 TV mode editor
│   ├── type6_editor.py      # Camera parameter editor for type 6
│   ├── type7_details.py     # Read-only view of type 7 camera data
│   └── camera_table.py      # Coordinate grid for manual camera edits
├── tests/                   # Unit tests for analysis helpers and profile handling
├── setup.py / setup.cfg     # Editable install entry for icr2_core
└── README.md                # Project overview & installation instructions
```

---

## 🧠 Package Breakdown

### `icr2_core/`

* **`icr2_memory.ICR2Memory`** attaches to DOSBox/ICR2 processes by scanning
  window titles and signature bytes, supports all known executables, exposes
  typed `read`/`write` helpers, and offers bulk reads for efficient polling. It
  loads defaults from `settings.ini` when parameters are omitted and cleans up
  handles on shutdown.
* **`reader.MemoryReader`** drives the higher-level decoding: it reads counts,
  names, car numbers, and the raw telemetry block; computes lap counts/times,
  gaps, and retirement flags; fetches track metadata; and returns immutable
  `RaceState` snapshots safe to share across threads.
* **`model.py`** defines frozen dataclasses for drivers, car state, and the
  overall race state, including the full 133-field telemetry array so overlays
  and editors can surface custom columns.
* **Track utilities (`trk/`)** provide TRK loading helpers, centreline sampling,
  and ground-surface mesh generation used by the map overlays and track viewer.
* **Camera utilities (`cam/`)** parse `.CAM` files and segment tables so the
  track viewer can load, edit, and save camera placements.
* **DAT helpers (`dat/`)** allow extracting files from `.DAT` archives or
  writing new bundles when repacking camera edits.

### `icr2timing/`

#### Entry point & bootstrap
* **`main.py`** configures logging, boots the Qt application, retries
  `ICR2Memory` attachment via message boxes, and wires a shared `MemoryReader`
  and `RaceUpdater` into the `ControlPanel` before starting the worker thread.

#### Core utilities (`core/`)
* `config.Config` and `config_store.ConfigStore` load `settings.ini`, apply the
  correct offsets for the detected executable, expose overlay defaults, and emit
  change signals so widgets hot-reload UI tweaks.
* `config_backend.ConfigBackend` parses/persists INI files while preserving
  comments. Shared helpers in `utils/ini_preserver.py` underpin comment-friendly
  writes for both `settings.ini` and `profiles.ini`.
* Telemetry helpers include `car_field_definitions.py` (metadata for the
  133-value telemetry block), `telemetry_laps.py` (lap logger), and
  `telemetry/car_data_recorder.py` (per-car CSV recorder with rotation support).

#### Analysis helpers (`analysis/`)
* `best_laps` tracks per-driver and global best laps/speeds with formatting and
  colour-coding helpers.
* `gap_utils` renders gap/interval strings and highlights pitting/retired cars.
* `name_utils` builds driver abbreviations and compact display names.

#### Updater & worker infrastructure (`updater/`)
* `RaceUpdater` runs inside a worker `QThread`, fires a precise `QTimer`, polls
  `MemoryReader`, and emits snapshots/errors to the UI.
* `OverlayManager` maintains overlay widgets, wires/disconnects updater signals,
  and handles show/hide/reset operations for the overlay suite.

#### Overlay suite (`overlays/`)
* All overlays implement `BaseOverlay` to provide consistent widget handles and
  `on_state_updated`/`on_error` hooks.
* `running_order_overlay.py` drives the timing table: column metadata,
  best-lap tracking, position-change indicators, optional sorting by personal
  best, and support for custom telemetry columns.
* `proximity_overlay.py` renders the radar with config-backed ranges, symbol
  styles, colours, and optional speed readouts.
* `track_map_overlay.py` loads TRK files, samples centrelines, autosizes the
  window, and paints cars/racing lines in sync with telemetry snapshots.
* `experimental_track_surface_overlay.py` caches ground-surface meshes built
  from TRK sections and renders them as filled polygons.

#### UI glue (`ui/`)
* `control_panel.py` hosts the main window, wires overlay toggles, telemetry
  controls, profile management, and updater lifecycle handling.
* `services.py` contains headless helpers for lap logging, pit command writes,
  session persistence, and telemetry control orchestration so tests can exercise
  logic without a full Qt stack.
* `profile_manager.py` loads/saves `profiles.ini`, including custom telemetry
  columns and radar placement/settings.
* Reusable editors like `car_value_helpers.py` and `car_data_editor.py` share
  rendering/recording helpers with the main overlay.

### `track_viewer/`

* `TrackViewerApp` keeps shared state (installation path, track list, selected
  window) and mirrors the overlay's cleanup hooks for future packaging.
* `TrackViewerWindow` hosts the track list, camera sidebars, and preview widget,
  wiring Qt signals so the sidebar edits cameras while the preview shows the
  surface mesh and cursor/flag positions.
* `TrackPreviewWidget` renders TRK ground surfaces, centreline samples, and
  camera geometry; it can load data from `.TRK`/`.DAT` bundles, supports flag
  placement, and emits camera updates for editors.
* `TvModesPanel`, `Type6Editor`, `Type7Details`, and `CameraCoordinateTable`
  collectively handle TV mode ranges and camera coordinate adjustments so users
  can inspect and export revised `.CAM` data.

### Tests (`tests/`)

The `tests/` package exercises config loading, INI preservation, overlay control
sections, and service classes without spinning up Qt.

---

## 🔄 End-to-End Flow (Timing Overlay)

1. **Bootstrap (`icr2timing/main.py`)** – Configure logging, create the
   `QApplication`, set the window icon, and loop until `ICR2Memory` attaches or
   the user cancels. Instantiate `Config`, `MemoryReader`, and `RaceUpdater`,
   then create and show the `ControlPanel`. A worker `QThread` is started and
   `RaceUpdater.start()` begins polling.
2. **Memory access (`icr2_core/icr2_memory.py`)** – Attach to the target process
   based on `settings.ini` keywords, locate the executable base via signature
   scanning, and expose typed reads/writes plus efficient bulk readers. Handles
   cleanup in `close()`/context managers so file descriptors and process handles
   are never leaked.
3. **Decoding (`icr2_core/reader.py`)** – Each poll reads car counts, names,
   numbers, and the telemetry blob; computes lap times with wraparound-aware
   arithmetic; detects pit/retirement status; fetches track metadata; and
   returns a frozen `RaceState` snapshot.
4. **Worker loop (`icr2timing/updater/updater.py`)** – `RaceUpdater` runs inside
   the worker thread, firing a high-precision `QTimer` at `Config.poll_ms`. On
   each timeout it calls `read_race_state()`, emits snapshots, deduplicates
   error messages, and stops polling when the DOSBox process exits.
5. **Presentation (`icr2timing/ui/control_panel.py` + overlays)** – The control
   panel connects overlay widgets, toggles, radar controls, and telemetry
   utilities. It proxies updater signals to the overlay manager (for table,
   surface, map) and directly to widgets like the proximity radar or individual
   telemetry panel. Profiles, lap logging, and car release/pit commands live
   here.
6. **Analysis helpers (`icr2timing/analysis/`)** – Overlays call `best_laps`,
   `gap_utils`, and other helpers to translate raw snapshots into formatted
   strings, colour codes, and tooltips.

---

## 🧵 Threading & Signal Model

* `RaceUpdater` is a `QObject` that lives in a worker `QThread`; its
  `start/stop` slots and `state_updated`/`error` signals are invoked via queued
  connections from the GUI thread.
* `OverlayManager` keeps overlay widgets in sync by connecting them to the
  updater and exposing bulk `show_all`, `hide_all`, and `reset_pbs` operations,
  while specialised overlays manage their own connections for additional UI
  controls (e.g., the radar or individual car telemetry panel).
* `RaceState`/`CarState` instances are immutable, so they can be safely shared
  across Qt threads without locking.

---

## ⚙️ Configuration, Persistence & Assets

* **`settings.ini`** controls memory version, polling interval, fonts, colour
  palette, radar geometry, and optional paths like `game_exe`. `ConfigStore`
  loads the file via `ConfigBackend`, verifies the configured executable, and
  emits change notifications so overlays update instantly, while `ICR2Memory`
  honours the same version/path hints during attachment.
* **`profiles.ini`** stores overlay layouts. `ProfileManager` loads/saves
  entries, injects the position-change indicator column when enabled, persists
  radar/overlay placement, and keeps per-profile custom telemetry columns bound
  to `CarState.values` indices.
* **INI persistence (`icr2timing/utils/ini_preserver.py`)** centralises
  comment-friendly writes for both configuration files, allowing targeted
  key/section edits without clobbering user annotations.
* **Telemetry logging** – The telemetry service toggles the lap logger and car
  data recorder, each keeping CSV handles open with optional `flush_every`
  thresholds so long runs can trade durability vs. throughput.
* **Assets/packaging** – `assets/icon.ico` is loaded by the Qt app; `build.bat`
  wraps PyInstaller, and `convert_icon.py` regenerates icons from source
  artwork.

---

## ➕ Extending the System

### Adding a new memory field
1. Add offsets or index metadata to `icr2timing/core/config.py` (and optionally
   `car_field_definitions.py` for display labels).
2. Update `MemoryReader` to decode the value into `CarState` and surface any
   derived properties.
3. Reference the field from overlays/analysis helpers via the
   `RaceState.car_states` map.

### Creating a new overlay widget
1. Subclass `BaseOverlay` (`icr2timing/overlays/base_overlay.py`) and implement
   `widget()`, `on_state_updated`, and `on_error`.
2. Register the overlay with `ControlPanel` (direct connection) or
   `OverlayManager` (for global toggle/reset support).
3. If the overlay needs UI controls, extend `control_panel.ui` and wire
   slots/signals in `control_panel.py`.

### Reusing core helpers in other tools
* Run `pip install -e .` to import `icr2_core` in external scripts – the package
  has no Qt dependency and works headlessly for automation, track conversion, or
  telemetry capture.
