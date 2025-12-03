# track_viewer Architecture

`track_viewer` is a multi-pane PyQt desktop utility for browsing `.TRK` folders,
overlaying AI lines, and editing camera data. It mirrors the overlay's cleanup
hooks so it can be frozen into a standalone executable later.

## Discovery flow
- The user chooses an IndyCar Racing II installation folder; `WindowController`
  resolves the `TRACKS/` directory (case-insensitive) and builds the track
  listing.
- Picking a track calls `TrackPreviewWidget.load_track()` with the folder path;
  the window updates track length readouts, toggles the TRK-gap action, and
  refreshes AI-line options.

## Visualization pipeline
1. **Load TRK & metadata** – `TrackPreviewWidget.load_track()` pulls centreline,
   surface mesh, available AI-line files, and track length from
   `TrackIOService.load_track()`. Bounds and a cached pixmap back the core paint
   routine.
2. **View fitting** – Sampled centreline points and surface bounds determine the
   default zoom/center; users can pan/zoom, toggle centreline visibility, and
   hide/show camera overlays or zoom markers.
3. **AI lines** – When `*.LP` files are present, toggling them calls
   `_get_ai_line_points()` which lazily loads the requested file via
   `geometry.load_ai_line()` and renders polylines on the preview.
4. **TRK gaps** – The widget exposes `run_trk_gaps()` that mirrors the standalone
   script, surfacing per-section gap lengths and summary stats in a dialog.
5. **Flags & coordinates** – Cursor/flag state propagates through signals so the
   sidebar mirrors the current selection and keeps the coordinate table in sync
   with the rendered view.

## Camera lifecycle
- `CameraService.load_for_track()` discovers cameras from `.cam`/`.scr` files or
  matching DAT archives, tracking whether files were extracted from the archive
  so saves can repack (and optionally remove) temporary files.
- `CameraController` and `CameraService` handle interactive mutations: adding
  Type 6/7 cameras relative to the current selection, renumbering, and adjusting
  TV mode counts while archiving excess views.
- `TrackPreviewWidget` emits camera lists to the sidebar, supports dragging
  camera handles on the canvas, and writes the final state through
  `CameraService.save()` which backs up existing files and repacks the DAT when
  needed.

## UI structure
- **TrackViewerApp** stores shared state (install path, track list) and ensures
  cleanup when the last window closes.
- **TrackViewerWindow** builds the layout: track list on the left, preview in the
  center, and the coordinate/camera sidebar on the right. Buttons allow adding
  Type 6/7 cameras, toggling centreline/camera overlays, and saving edits.
- **TrackPreviewWidget** owns all rendering and camera/flag interaction logic,
  emitting signals to drive the sidebar widgets.
- **CoordinateSidebar** hosts track metadata, camera list, TV mode panel,
  coordinate grid (`CameraCoordinateTable`), and camera editors so UI updates
  stay isolated from the preview rendering.
