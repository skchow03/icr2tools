# track_viewer Architecture

`track_viewer` is a lightweight PyQt utility for browsing `.TRK` folders and
editing camera data. It mirrors the overlay's cleanup hooks so it can be frozen
into a standalone executable later.

## Discovery flow
- The user selects an IndyCar Racing II installation folder.
- `TrackViewerWindow._tracks_root()` looks for `TRACKS/` (case-insensitive) and
  lists each subfolder as a track option.
- Selecting a track calls `TrackPreviewWidget.load_track()` with the folder path;
  the sidebar shows the inferred track length and enables camera controls.

## Visualization pipeline
1. **Load TRK** – `preview_widget.TrackPreviewWidget.load_track()` calls
   `icr2_core.trk.track_loader.load_trk_from_folder()` to parse the `.TRK`
   contents from the selected folder.
2. **Geometry prep** – The widget samples centreline coordinates via
   `icr2_core.trk.trk_utils.get_cline_pos()` and builds ground-surface strips via
   `icr2_core.trk.surface_mesh.build_ground_surface_mesh()`, caching a pixmap for
   paint events.
3. **View fitting** – Derived bounds and sampled centrelines drive the default
   zoom/center; users can toggle centreline visibility, show/hide camera overlays,
   or pan/zoom interactively.
4. **Camera overlays** – `_load_track_cameras()` loads `.cam`/`.scr` files from
   disk or extracts them from a track DAT, emitting camera lists to the sidebar.
   Users can drag cameras on the preview, edit parameters via `Type6Editor` /
   `Type7Details`, adjust TV segment ranges with `TvModesPanel`, and persist
   changes back to disk (optionally repacking DATs).
5. **Flags & coordinates** – The widget exposes cursor/flag signals so the
   sidebar mirrors the current selection, enabling coordinate tables and camera
   editors to stay in sync with the rendered view.

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
