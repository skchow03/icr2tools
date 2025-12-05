# SG Viewer Architecture

This document summarizes how the SG Viewer is structured, how data moves through the
application, and where to look when making changes.

## Entry points and application shell
- **`sg_viewer/main.py`** is the executable entry point. It configures logging and
  instantiates `SGViewerApp` and `SGViewerWindow` before entering the Qt event loop.
- **`SGViewerApp` (`sg_viewer/app.py`)** is a thin `QApplication` wrapper that
  owns a reference to the main window to keep lifetime management explicit.
- **`SGViewerWindow` (`sg_viewer/app.py`)** builds the top-level UI: the preview
  canvas on the left, a sidebar with navigation and selection details, a docked
  `SectionPropertiesPanel`, menus, and toolbar-like buttons for interaction modes.
  It wires signals from the preview widget to both the sidebar labels and the
  properties panel so selection state stays synchronized.

## Data model and editing flow
- **`EditorState` (`sg_viewer/editor_state.py`)** is the authoritative model. It
  owns the mutable `SGFile`, the derived `TRKFile`, and the latest
  `PreviewData`. All editing operations (length, radius, curve center, start
  heading) mutate the `SGFile`, regenerate the `TRKFile`, rebuild `PreviewData`,
  and push snapshots to undo/redo stacks.
- **Loading**: `SGPreviewWidget.load_sg_file()` creates an `EditorState` via
  `EditorState.from_path()`, which calls `preview_loader.load_preview()` to parse
  the SG, build the TRK, sample centreline geometry, and assemble a
  `PreviewData` snapshot.
- **Undo/redo**: `EditorState` keeps deep copies of `SGFile` instances. Undo
  replaces the current snapshot with the previous one and regenerates TRK and
  preview artifacts; redo performs the inverse. Both paths ensure the SG file on
  disk stays in sync.

## Preview rendering pipeline
- **`SGPreviewWidget` (`sg_viewer/preview_widget.py`)** is the interactive canvas.
  It caches references from the bound `EditorState.preview` (SG/TRK objects,
  sampled centreline, bounds, curve markers, section endpoints, and transform
  state). The widget handles:
  - Section selection, broadcasting `selectedSectionChanged` so other widgets can
    update themselves.
  - Camera-like pan/zoom using `TransformState` helpers from
    `preview_loader` to keep view transforms consistent and clamped.
  - Optional "Move Point" mode that lets users detach and drag section end points
    with temporary overrides; redraws are driven by `_section_endpoints` derived
    from the base endpoints plus overrides.
  - Building per-section geometry summaries (`get_section_geometries`), heading
    deltas (`get_section_headings`), x-section metadata, and elevation profile
    samples (`build_elevation_profile`). These feed the tables and elevation plot.
- **`preview_rendering.py`** contains the pure drawing helpers used by the widget
  to render centrelines, curve markers, endpoints, and start/finish lines. It
  delegates common point/line mapping to `track_viewer.rendering`.

## UI composition and secondary views
- **Section properties**: `SectionPropertiesPanel` subscribes to
  `selectedSectionChanged` and exposes editable spinboxes for length, start
  heading, radius, and curve centres when applicable. Edits call back into
  `EditorState` so SG/TRK/preview snapshots stay consistent.
- **Sidebar navigation**: Buttons in `SGViewerWindow` call preview-widget methods
  for section navigation, toggling curve markers, and enabling Move Point mode.
  Selection labels mirror the current `SectionSelection` provided by the preview
  widget.
- **Tables**: `SectionTableWindow` and `HeadingTableWindow` present derived data
  from `SGPreviewWidget.get_section_geometries()` and
  `SGPreviewWidget.get_section_headings()` respectively. They refresh whenever a
  new SG file loads.
- **Elevation profile**: `SGViewerWindow` populates a combo box with available
  x-section indices (via `get_xsect_metadata`) and renders the chosen profile in
  `ElevationProfileWidget`. When a section is selected, the widget highlights the
  corresponding dlong range within the chart.

## Geometry and sampling utilities
- **`preview_loader.py`** centralizes SG/TRK parsing and geometric sampling. It
  builds `PreviewData` containing sampled centrelines, curve markers, section
  endpoints, and a `CenterlineIndex` for point projection. Transform-related
  helpers (fit scale calculation, clamped zooming, and default centring) live
  here so the preview widget can remain a thin view over the immutable snapshot.
- **`sg_geometry.py`** (invoked from `EditorState`) encapsulates SG mutations such
  as updating section length, radius, or curve centres while keeping downstream
  TRK regeneration consistent.

## Typical control flow
1. User launches `main.py`, which creates `SGViewerWindow` and shows the UI.
2. Opening an SG file triggers `SGPreviewWidget.load_sg_file()`, producing an
   `EditorState` and binding it to the preview widget and properties panel.
3. The preview widget paints using cached `PreviewData` and exposes selection and
   analysis helpers. Sidebar labels, tables, and the elevation plot subscribe to
   those helpers for live updates.
4. Edits made through the properties panel call into `EditorState`, which
   rewrites the SG, regenerates the TRK, rebuilds `PreviewData`, and asks the
   preview widget to `refresh_from_state()` so visuals and metadata stay current.
