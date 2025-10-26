# ICR2 Timing Overlay – Architecture

This document explains how the app is structured and how the pieces fit together.

---

## 🔄 High-Level Flow

1. **Game running in DOSBox**  
   - ICR2 (DOS or Rendition build) is launched in DOSBox.  
   - The app will attach to the DOSBox process by searching window titles (`window_keywords`).

2. **Attach + Memory base detection (`core/icr2_memory.py`)**  
   - The app finds DOSBox’s PID and opens it with `pymem`.  
   - In Rendition mode: scans process memory for the string `"license with Bob"`, subtracts a fixed offset to compute the EXE base.  
   - In DOS mode: uses flat offsets (exe_base = 0).  
   - Provides a typed `read()` API (e.g. `i32`, `u16`, `bytes`).

3. **Offsets + Config (`core/config.py`)**  
   - `Config` loads settings from `settings.ini`.  
   - Selects the correct offset map for either `DOS` or `REND32A`.  
   - Also supplies UI defaults (fonts, colors, radar size, etc.).

4. **Reading structured state (`core/reader.py`)**  
   - Wraps `ICR2Memory` to interpret raw bytes into structured objects:  
     - `Driver` (name, number)  
     - `CarState` (lap count, gaps, DLAT/DLONG, fuel, pit/retire status)  
     - `RaceState` (order, bests, all cars combined)

5. **Updating loop (`updater/updater.py`)**  
   - `RaceUpdater` runs in its own Qt thread.  
   - Polls `MemoryReader` at a configurable interval (`poll_ms`).  
   - Emits Qt signals with updated `RaceState`.  
   - On error, emits error signals to overlays/control panel.

6. **Overlays (various in `overlays/`)**  
   - Subclass `BaseOverlay` (abstract interface with `on_state_updated`).  
   - Examples:  
     - `running_order_overlay.py` → timing table overlay  
     - `proximity_overlay.py` → radar  
     - `track_map_overlay.py` → track bubble map  
   - Each overlay paints itself using `RaceState` snapshots.  
   - Best laps and gap formatting handled by helpers (`best_laps.py`, `gap_utils.py`).

7. **Control Panel (`ui/control_panel.py`)**  
   - Qt main window created in `main.py`.  
   - Loads `.ui` layout file from Qt Designer.  
   - Provides buttons to toggle overlays (show/hide), radar, and track map.  
   - Manages profiles (via `profile_manager.py`) to persist layout and last session state.

---

## 📂 Folders & Responsibilities

### Root
- **main.py**: Application entry point. Creates `ICR2Memory`, `MemoryReader`, `RaceUpdater`, `ControlPanel`.

### core/
- **config.py**: Loads offsets, colors, fonts, INI paths. Chooses offsets by version.  
- **icr2_memory.py**: Process attach + low-level typed memory reader.  
- **reader.py**: High-level API to produce `RaceState` objects.  
- **model.py**: Data containers for drivers, cars, race.

### updater/
- **updater.py**: Background Qt thread to poll memory → emit updates.

### overlays/
- **base_overlay.py**: Abstract base interface for all overlays.  
- **overlay_table_window.py**: Generic table window with styling.  
- **running_order_overlay.py**: Timing overlay (positions, gaps, laps, PBs).  
- **proximity_overlay.py**: Radar overlay (nearby cars).  
- **track_map_overlay.py**: Track outline overlay with moving car bubbles.  
- **overlay_manager.py**: Manages all overlays together (show/hide/reset).

### ui/
- **control_panel.py**: Main Qt window with buttons + profile integration.  
- **control_panel.ui**: Designer XML layout.

### utils/
- **gap_utils.py**: Formats gaps/intervals/pitting/retirement text.  
- **name_utils.py**: Splits names, generates abbreviations.  
- **trk_utils.py**: DLONG/DLAT to world coordinates, geometry helpers.  
- **trk_classes.py**: Parser for `.trk` binary track files.  
- **utils.py**: Misc math/helpers.

### other/
- **best_laps.py**: Tracks best laps per-driver and global best.  
- **profile_manager.py**: Load/save overlay profiles.  
- **settings.ini**: Central config file.  
- **unpackdat.py**: Extracts `.dat` game archives.  
- **track_loader.py**: Loads track data for overlays.

---

## 🧩 How It All Fits Together

- **main.py** starts → attaches memory → spawns updater thread.  
- **RaceUpdater** runs continuously:  
  - Reads offsets → builds `RaceState` → emits signals.  
- **Overlays** subscribe to signals → repaint themselves live.  
- **Control Panel** toggles overlays and stores preferences.  
- **Config** + `settings.ini` unify version offsets, UI, and file paths.

---

## ⚙️ Current Supported Modes

- **REND32A** (Rendition ICR2, cart.exe)  
  - Uses signature scan + offset correction.  
- **DOS** (DOS ICR2, indycar.exe)  
  - Uses flat offsets from Ghidra analysis.  
  - No signature scan needed (exe_base = 0).

---

This layered architecture keeps **memory handling**, **UI overlays**, and **persistence** separated, making it easier to add new overlays, adjust offsets for new builds, or customize the UI without breaking the rest of the system.
