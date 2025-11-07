# ICR2Tools Architecture

This document is written for new contributors (human or AI) who need context about how the
ICR2Tools repository fits together. It focuses on the two packages that ship in this repo:

* **`icr2_core/`** – a reusable Python package that knows how to talk to IndyCar Racing II
  (memory access, binary formats, track helpers).
* **`icr2timing/`** – the Qt-based live timing overlay application that players see on screen.

---

## 🗺️ Repository Topology

```
icr2tools/
├── icr2_core/               # Shared library imported by all tooling
│   ├── icr2_memory.py       # Process attach + typed memory reads
│   ├── reader.py            # Turns raw memory into structured RaceState objects
│   ├── model.py             # Dataclasses representing drivers, cars, races
│   ├── trk/                 # Track (.trk) parsing, geometry helpers, exporters
│   └── dat/                 # DAT archive helpers (e.g. unpackdat.py)
├── icr2timing/              # GUI overlay application
│   ├── main.py              # Entry point; wires memory + updater + UI
│   ├── core/                # Config, version metadata, telemetry helpers
│   ├── updater/             # Worker thread + overlay manager coordination
│   ├── overlays/            # Individual overlay widgets (timing table, radar, track map, etc.)
│   ├── analysis/            # Pure functions for formatting gaps, best laps, name transforms
│   └── ui/                  # Qt Designer .ui file, control panel glue, profile manager
└── setup.py / setup.cfg     # Editable install entry for icr2_core
```

The overlay imports heavily from `icr2_core`. Most code lives in plain Python modules so that it can be
reused by other tools (for example, the track-map overlay reuses the general-purpose `icr2_core.trk` loader).

---

## 🔄 End-to-End Flow (Timing Overlay)

1. **Application bootstrap (`icr2timing/main.py`)**
   * Configures logging, creates a `QApplication`, and repeatedly tries to create `ICR2Memory` until DOSBox is found.
   * Initializes `Config` (memory map + UI defaults) and constructs the shared `MemoryReader` and `RaceUpdater`.
   * Builds the `ControlPanel` main window, wires Qt signals, and starts the updater worker thread.

2. **Process attachment & raw reads (`icr2_core/icr2_memory.py`)**
   * Uses Win32 window enumeration + signature scanning to discover the DOSBox process and calculate the base address
     for the active ICR2 executable (supports `REND32A`, `DOS`, and `WINDY`).
   * Exposes a typed `read(offset, type, count)` API and helpers like `BulkReader` for efficient block reads.
   * Cleans up Windows handles when the app exits.

3. **Configuration (`icr2timing/core/config.py`)**
   * Loads `settings.ini` alongside the executable for overrides (memory version, colors, fonts, radar sizes, poll rate).
   * Provides memory offsets for each supported game build and column sizing defaults for overlays.

4. **State decoding (`icr2_core/reader.py`)**
   * Pulls raw bytes through `ICR2Memory` and translates them into immutable dataclasses from `icr2_core/model.py`:
     * `Driver` – identity data such as name and car number.
     * `CarState` – lap counts, deltas, DLAT/DLONG coordinates, fuel, retirement status, raw 0x214 block, etc.
     * `RaceState` – aggregate snapshot (order, totals, driver/car maps, track length & name).
   * Handles quirks like unsigned clock wraparound when calculating lap times and sentinel values for invalid data.

5. **Polling loop (`icr2timing/updater/updater.py`)**
   * `RaceUpdater` lives in its own `QThread` and owns a high-precision `QTimer`.
   * On every tick it calls `MemoryReader.read_race_state()` and emits Qt signals:
     * `state_updated(RaceState)` – consumed by overlays and the control panel.
     * `error(str)` – routed to UI so the user can see transient read failures.

6. **Presentation layer**
   * **Control panel (`icr2timing/ui/control_panel.py`)**
     * Hosts buttons/toggles, wiring to `OverlayManager`, radar settings, lap logger controls, and profile persistence.
     * Manages the lifetime of non-table overlays (radar, track map, individual car telemetry) and the lap logger.
   * **Overlay manager (`icr2timing/updater/overlay_manager.py`)**
     * Keeps a registry of `BaseOverlay` implementations and handles global show/hide/reset commands.
   * **Overlays (`icr2timing/overlays/`)**
     * `running_order_overlay.py` – table overlay rendering the timing grid via `OverlayTableWindow`.
     * `proximity_overlay.py` – radar view that visualises car proximity using DLAT/DLONG deltas and Config radar options.
     * `track_map_overlay.py` – draws the track outline by loading `.trk` geometry through `icr2_core.trk.track_loader`.
     * `experimental_track_surface_overlay.py` – experimental window that expands each TRK ground f-section into a filled
       polygon coloured by surface type (asphalt, concrete, grass, sand, etc.).
     * `individual_car_overlay.py` – single-car telemetry panel that surfaces extended `CarState.values` columns.
     * Each overlay implements `BaseOverlay` (`widget()`, `on_state_updated`, `on_error`).

7. **Supporting services**
   * **Analysis helpers (`icr2timing/analysis/`)**: pure functions for lap classification (`best_laps.py`), gap formatting
     (`gap_utils.py`), and name formatting (`name_utils.py`).
   * **Profiles (`icr2timing/ui/profile_manager.py`)**: saves overlay layout, column choices, and radar preferences to
     `profiles.ini`, including support for custom columns (label + raw memory index).
   * **Telemetry lap logger (`icr2timing/core/telemetry_laps.py`)**: optional CSV writer triggered from the control panel
     that logs each completed lap using `RaceState` data.

---

## 🧱 Core Data Model (`icr2_core/model.py`)

* `Driver`: struct index, HTML-escaped name, and optional car number.
* `CarState`: exposes lap counts, last-lap timing, fuel, DLAT/DLONG, status, and the entire 0x214 raw block so overlays
  can extract extra metrics without altering the reader.
* `RaceState`: contains counts, running order, driver/car maps, and optional track metadata (length and name). This object
  is considered immutable; overlays should treat each emission as a snapshot.

Because `RaceState` is serialisable (pure Python types), it is safe to emit across Qt threads or persist for later analysis.

---

## ⚙️ Configuration & Assets

* **`settings.ini`** – shipped next to the binary; controls memory version, polling interval, UI theme, radar dimensions,
  and default executable path. Both `ICR2Memory` and `Config` read from this file.
* **`profiles.ini`** – stored beside the executable; `ProfileManager` maintains sections per layout and a `__last_session__`
  snapshot restored at boot.
* **`assets/`** – contains the overlay icon (`icon.ico`) and any additional resources packaged with the PyInstaller build.

---

## ➕ Extending the System

### Adding a new memory field
1. Add constants or offsets to `icr2timing/core/config.py` if the field is version-dependent.
2. Update `MemoryReader` to populate the field into `CarState` (or a new dataclass).
3. Surface the data in overlays by reading from `RaceState.car_states[struct_idx]`.

### Creating a new overlay widget
1. Subclass `BaseOverlay` (see `overlays/base_overlay.py`) and implement `widget()`, `on_state_updated`, and `on_error`.
2. Instantiate the overlay in `ControlPanel` (or register with `OverlayManager` if it should participate in global toggles).
3. Wire `RaceUpdater.state_updated` and `.error` signals to the new overlay.
4. Optionally expose controls in the control panel UI (Qt Designer file + associated slots).

### Reusing core helpers in other tools
* Any standalone script can `pip install -e .` from the repo root to import `icr2_core` directly.
* Track processing utilities live under `icr2_core/trk/` and do not depend on Qt, making them safe for headless scripts.

---

## 🧭 Key Entry Points for ChatGPT

* Launching the overlay: `icr2timing/main.py` → `main()`.
* Memory attach/read pipeline: `icr2_core/icr2_memory.py` → `ICR2Memory`, `icr2_core/reader.py` → `MemoryReader.read_race_state()`.
* UI control hub: `icr2timing/ui/control_panel.py` → `ControlPanel`.
* Extensible overlays: `icr2timing/overlays/` (start with `running_order_overlay.py`).
* Configuration knobs: `icr2timing/core/config.py`, `icr2timing/settings.ini`, `icr2timing/profiles.ini`.

Use this map to orient yourself before making changes; most features span both the memory reader (`icr2_core`) and the
presentation layer (`icr2timing`).
