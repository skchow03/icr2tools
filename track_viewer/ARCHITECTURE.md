# Track Viewer Architecture

This package is a standalone Qt-based viewer/editor for IndyCar Racing II (ICR2) track resources, focused on:
- Loading a track folder (`.TRK`, optional DAT containers, `.LP`, `.cam/.scr`, `.txt`)
- Rendering a 2D preview of the track surface/centerline plus overlays (AI lines, cameras, flags, pit markers)
- Editing camera positions (including TV modes / type 6 & 7 cameras), flag placement, and selected track.txt PIT parameters
- Saving camera edits back to `.cam/.scr` and (when applicable) repacking to DAT

Current package version: `0.1.1`. :contentReference[oaicite:1]{index=1}

---

## Package entrypoints

- `python -m track_viewer` runs `track_viewer.__main__`, which calls `controllers.main.main()`. :contentReference[oaicite:2]{index=2}

The primary UI is implemented in `widget/app.py` (Qt `QMainWindow` shell + wiring), with the preview canvas in `widget/track_preview_widget.py`. :contentReference[oaicite:3]{index=3}

---

## Top-level folder structure

- `ai/`
  - AI line (LP) loading + derived metrics (heading, speed conversions, lateral speed, etc.).
  - Defines `LpPoint` records and an async/worker-ish load task pattern. :contentReference[oaicite:4]{index=4}

- `common/`
  - Shared constants and versioning.
  - Includes LP file name ordering + default colors used across the UI. :contentReference[oaicite:5]{index=5}

- `controllers/`
  - “Orchestration” logic that coordinates higher-level operations and produces user-facing results.
  - Example: `CameraActions` wraps preview widget operations and emits info/warn messages. :contentReference[oaicite:6]{index=6}
  - `CameraController` implements camera CRUD-like mutations (add type6/type7, renumbering, TV-mode coordination). :contentReference[oaicite:7]{index=7}

- `geometry.py`
  - Centerline sampling and indexing utilities used to map dlong->world coords and to support cursor/marker logic.
  - The `TrackPreviewModel` builds and stores a `CenterlineIndex` for fast lookups. :contentReference[oaicite:8]{index=8}

- `model/`
  - Data models + state containers shared across the widget and sidebar.
  - `TrackPreviewModel` is the primary loaded-data cache (TRK, centerline, surface mesh/bounds, detected LP files, track length). :contentReference[oaicite:9]{index=9}
  - `PitParameters` represents parsed track.txt PIT line values. :contentReference[oaicite:10]{index=10}
  - `TrackPreviewViewState` holds interactive view flags (selected camera, selected LP record, cursor position, toggles, etc.). :contentReference[oaicite:11]{index=11}

- `rendering/`
  - Pure drawing helpers that render the model+view-state onto a `QPainter`.
  - `TrackPreviewRenderer` is the composition point: it draws base geometry then overlays (AI lines, cameras, flags, pit markers, zoom points). :contentReference[oaicite:12]{index=12}:contentReference[oaicite:13]{index=13}

- `services/`
  - IO and persistence boundary.
  - `TrackIOService` loads track data (TRK + mesh + bounds), loads cameras (from `.cam/.scr` or DAT), and loads/parses track.txt PIT/metadata. :contentReference[oaicite:14]{index=14}
  - `CameraService` is a stateful wrapper around camera IO + mutation (delegates to `CameraController`, persists via `TrackIOService`). :contentReference[oaicite:15]{index=15}

- `sidebar/`
  - “Inspector/editor” UI that mirrors selection from the preview and offers structured editing controls.
  - `CoordinateSidebar` hosts camera lists, TV mode panel, editable coordinate table, and type-specific editors.
  - A dedicated view-model `CoordinateSidebarViewModel` keeps UI updating logic isolated from rendering code. :contentReference[oaicite:16]{index=16}:contentReference[oaicite:17]{index=17}

- `widget/`
  - Qt widgets and the app shell:
    - `TrackViewerWindow` creates the main layout and owns the `TrackIOService` (and track-folder selection state). :contentReference[oaicite:18]{index=18}
    - `TrackPreviewWidget` is the interactive canvas (mouse/keyboard), and is the main bridge between UI events and model/service calls.
    - Auxiliary UI wiring lives here as well (menus, buttons, dialogs, etc.).

---

## Core runtime objects and responsibilities

### 1) Data/model layer

**`TrackPreviewModel` (model/track_preview_model.py)**
- Loads and caches:
  - `trk` (`TRKFile`)
  - `centerline` (list of world points)
  - `surface_mesh` + computed bounds
  - available LP file names in the folder
  - `track_length`
- Owns AI-line caching and triggers background loads; emits `aiLineLoaded(lp_name)` when an LP finishes loading. :contentReference[oaicite:19]{index=19}

**`TrackPreviewViewState` (model/view_state.py)**
- Stores UI-driven transient state (toggles and current selection), for example:
  - selected camera index, selected flag, selected LP line/record
  - visibility toggles (cameras, zoom points, section dividers, etc.)
  - AI line color mode (solid vs gradients) and rendering params (line width, accel window)
- This state is read by the renderer, and mutated by widget interaction methods. :contentReference[oaicite:20]{index=20}

### 2) IO/service layer

**`TrackIOService` (services/io_service.py)**
- Track loading:
  - `load_track(folder)` loads TRK, computes centerline, builds surface mesh, bounds, detects LPs. :contentReference[oaicite:21]{index=21}
- Cameras loading:
  - `load_cameras(folder)` resolves `.cam/.scr` first, otherwise tries a matching DAT; returns camera list + derived TV views and metadata about source. :contentReference[oaicite:22]{index=22}
- Track TXT loading:
  - `load_track_txt(folder)` parses `<trackname>.txt`, collecting PIT parameters and metadata lines while preserving raw lines. :contentReference[oaicite:23]{index=23}

**`CameraService` (services/camera_service.py)**
- Maintains the currently loaded camera state (cameras + view listings), and tracks camera provenance:
  - whether cameras came from `.cam/.scr` files or from DAT
  - whether temporary files were extracted from DAT and may need repacking on save. :contentReference[oaicite:24]{index=24}
- Provides `save()` to persist camera edits through `TrackIOService.save_cameras(...)`. :contentReference[oaicite:25]{index=25}

### 3) Controller/orchestration layer

**`CameraController` (controllers/camera_controller.py)**
- Implements camera mutation operations as pure-ish transformations:
  - add type 6 camera based on current selection, splitting surrounding TV ranges and cloning zoom parameters
  - add type 7 camera similarly
  - renumber per-type indices to match ICR2 expectations
  - adjust TV mode count by archiving/restoring view listings. :contentReference[oaicite:26]{index=26}:contentReference[oaicite:27]{index=27}

**`CameraActions` (controllers/camera_actions.py)**
- Small UI-facing wrapper: calls preview widget functions and emits info/warn signals so the window can show dialogs/toasts without duplicating logic. :contentReference[oaicite:28]{index=28}

### 4) UI layer (window, preview, sidebar)

**`TrackViewerWindow` (widget/app.py)**
- Owns:
  - `TrackIOService` instance and current folder selection
  - Layout: track list, preview widget, coordinate sidebar
  - Buttons for camera add/save and other toggles. :contentReference[oaicite:29]{index=29}

**`TrackPreviewWidget`**
- Owns:
  - `TrackPreviewModel`, `CameraService`, and `TrackPreviewViewState`
  - The render loop (via `TrackPreviewRenderer`) and the interaction logic:
    - mouse selection/dragging of cameras and flags
    - cursor inspection
    - keyboard-based LP editing toggles (when enabled)
  - Emits signals to update the sidebar (selection changes, lists, etc.).
- When state changes, the widget invalidates caches and calls `update()` to repaint. :contentReference[oaicite:30]{index=30}:contentReference[oaicite:31]{index=31}

**`CoordinateSidebar` + `CoordinateSidebarViewModel`**
- Sidebar is responsible for structured inspection/editing:
  - camera list + camera details
  - TV mode editor panel
  - coordinate table editor (X/Y/Z)
  - type6/type7 parameter editors
- The view-model computes labels/status text and keeps widget updates consistent with selection. :contentReference[oaicite:32]{index=32}

---

## Primary data flow

### Track load flow
1. User selects a track folder.
2. `TrackIOService.load_track()` loads TRK + centerline + surface mesh + bounds + LP availability. :contentReference[oaicite:33]{index=33}
3. `CameraService.load_for_track()` calls `TrackIOService.load_cameras()` to resolve camera sources and build TV view listings. :contentReference[oaicite:34]{index=34}:contentReference[oaicite:35]{index=35}
4. `TrackIOService.load_track_txt()` parses track TXT and PIT parameters. :contentReference[oaicite:36]{index=36}
5. UI updates:
   - preview widget refreshes model and state
   - sidebar receives camera lists/views and renders editors accordingly. :contentReference[oaicite:37]{index=37}

### Paint/render flow
1. Qt calls `paintEvent`.
2. `TrackPreviewRenderer.paint()`:
   - draws surface mesh and boundaries
   - overlays:
     - cameras (if enabled)
     - AI lines (solid or gradient modes)
     - selection markers (selected LP record segment, selected camera, etc.)
     - flags and optional radii
     - pit lines / section dividers
     - zoom points markers. :contentReference[oaicite:38]{index=38}

### Camera edit/save flow
1. User edits via:
   - dragging in preview widget (camera positions / selections)
   - sidebar coordinate table (direct X/Y/Z edits)
   - add type6/type7 camera actions (buttons).
2. Mutations:
   - `CameraController` computes updated camera lists and updated TV view entries. :contentReference[oaicite:39]{index=39}
   - `CameraService` caches results and exposes them to the UI. :contentReference[oaicite:40]{index=40}
3. Save:
   - Preview widget calls `CameraService.save()`.
   - `TrackIOService` writes `.cam/.scr` and repacks DAT when needed, with backups. :contentReference[oaicite:41]{index=41}:contentReference[oaicite:42]{index=42}

---

## Key invariants

- `TrackPreviewModel` is the source of truth for loaded track geometry and cached AI line records.
- `TrackPreviewViewState` is the source of truth for what the user is currently looking at/selecting and which overlays are enabled.
- `CameraService` is the source of truth for camera persistence state and provenance (files vs DAT).
- Rendering modules (`rendering/*`) should remain side-effect free: they read model/state and draw only.
- Sidebar widgets should not reach into the renderer directly; they communicate via signals and the view-model.

---

## Extension points (recommended)

- Add new overlay types:
  - implement drawing in `rendering/*`
  - add state toggle(s) to `TrackPreviewViewState`
  - add UI controls in sidebar/window and wire to widget setters

- Add new file-backed editors:
  - parsing/loading: extend `TrackIOService`
  - state/model: new `model/*` structures
  - UI: sidebar panel + view-model updates
  - saving: add corresponding save method(s) to `TrackIOService`

---

## Notes on dependencies

- Core TRK/LP/camera parsing utilities come from `icr2_core` (e.g., `load_trk_from_folder`, `getxyz`, LP loader, camera helper classes). :contentReference[oaicite:43]{index=43}:contentReference[oaicite:44]{index=44}
- Qt: PyQt5 is used throughout UI, models, painting, and signals. :contentReference[oaicite:45]{index=45}
