# SG Viewer Architecture

The SG Viewer is a Qt-based desktop utility for inspecting and editing SG track files. It provides a single-window workspace with preview canvas, editing controls, background imagery options, and supporting dialogs. The sections below outline how the app is wired together after the latest refactors.

## Entry Points and Application Shell
- `sg_viewer/main.py` configures logging, parses CLI flags (including `--debug`, `--log-level`, and `--log-file`/`SG_VIEWER_LOG_PATH`), creates the Qt application, and shows the main window before entering the event loop.【F:sg_viewer/main.py†L1-L85】
- `sg_viewer/ui/app.py` defines `SGViewerApp` and the `SGViewerWindow` layout. The window hosts the preview canvas, elevation profile, background/selection controls, and action buttons for navigation, creation, and deletion. It initializes the controller to wire behaviors and keeps selection labels in sync with preview events.【F:sg_viewer/ui/app.py†L1-L209】

## Controller and Window Coordination
- `SGViewerController` (constructed by the window) owns menu actions, button state, and dialog lifecycles. It drives file open/save, recent-file history, background image handling, and toggling of creation/deletion modes while relaying preview signals back into the UI.【F:sg_viewer/ui/viewer_controller.py†L19-L198】
- The controller boots with a fresh track, enables menu shortcuts, and keeps recent files and per-SG background settings persisted via `FileHistory`. Loading a file seeds the preview widget, updates dialog data, populates cross-section choices, and restores any remembered background overlay for that SG path.【F:sg_viewer/ui/viewer_controller.py†L32-L115】【F:sg_viewer/models/history.py†L8-L109】

## Preview State, Editing, and Interactions
- `SGPreviewWidget` maintains the loaded SG/TRK data, sampled centerline geometry, background overlay, transform state (pan/zoom), and selection manager. It emits signals for section selection changes, scale changes, and mode toggles so the controller can style buttons and update labels.【F:sg_viewer/ui/preview_widget.py†L75-L210】【F:sg_viewer/ui/preview_widget.py†L293-L344】
- State storage and transform math are delegated to `PreviewStateController`, which wraps the current SG/TRK payload, sampled bounds, track length, and view transforms. It provides helpers for fitting the view, mapping widget coordinates to track space, and reloading SG data via `preview_loader_service`.【F:sg_viewer/ui/preview_state_controller.py†L19-L156】
- The widget wires interaction helpers for selection, panning/zooming, and creation (`PreviewInteraction`, `PreviewCreationAdapter`) into a `PreviewEditor` that finalizes new straights/curves, updates section sets, and marks unsaved edits. New track creation clears state, while load/save/reset paths rebuild signatures and selection context to keep the preview, tables, and status messages aligned.【F:sg_viewer/ui/preview_widget.py†L96-L210】【F:sg_viewer/ui/preview_widget.py†L319-L439】

## Data Loading and Modeling
- `preview_loader_service.load_preview` is a thin façade over `services/preview_loader.load_preview`, keeping UI code decoupled from the loader implementation.【F:sg_viewer/services/preview_loader_service.py†L1-L9】
- `preview_loader.load_preview` parses the SG/TRK pair, samples the centerline, builds a spatial index, derives start/finish normals, and constructs `SectionPreview` records (with polylines, headings, and radius metadata). Results come back as `PreviewData` for direct consumption by the preview widget and editor.【F:sg_viewer/services/preview_loader.py†L1-L63】【F:sg_viewer/services/preview_loader.py†L66-L115】
- Immutable data carriers for preview and sections live in `models/sg_model.py`, defining `SectionPreview` and `PreviewData` structures shared among loaders, interactions, and renderers.【F:sg_viewer/models/sg_model.py†L1-L42】

## Background Imagery and Rendering
- Background images are managed by `PreviewBackground`, which loads the image, tracks its origin/scale in SG units, combines bounds with track geometry, and exposes fit helpers used when an overlay is present.【F:sg_viewer/services/preview_background.py†L13-L70】
- Users can add or adjust a background via the controller’s menu actions and `BackgroundImageDialog`; the controller also saves/restores per-file background configuration through `FileHistory` so overlays reapply on reopen.【F:sg_viewer/ui/viewer_controller.py†L67-L198】【F:sg_viewer/models/history.py†L36-L68】

## Supporting Dialogs, Profiles, and Tables
- Section and heading details are exposed through `SectionTableWindow` and `HeadingTableWindow`, which the controller instantiates on demand and refreshes from the preview widget’s current section set and heading vectors. Buttons and menus enable these dialogs only after a track is loaded.【F:sg_viewer/ui/viewer_controller.py†L32-L145】【F:sg_viewer/ui/viewer_controller.py†L117-L169】
- Elevation profiles are drawn by `ElevationProfileWidget`, fed by cross-section choices from the preview and selection updates from the window to keep the profile range aligned with the active section.【F:sg_viewer/ui/app.py†L51-L209】【F:sg_viewer/ui/viewer_controller.py†L135-L169】

## Typical Editing Workflow
1. Launch with `python -m sg_viewer.main`; logging initializes and the window opens.【F:sg_viewer/main.py†L62-L85】
2. Use **File → Open SG…** or **Open Recent** to load a track. The controller populates preview geometry, enables editing buttons/tables, restores any background image, and refreshes elevation profile options.【F:sg_viewer/ui/viewer_controller.py†L41-L115】
3. Pan/zoom the preview, toggle curve markers, or click near the centerline to select sections. Signals update sidebar metadata, elevation profile bounds, and button styling for creation/deletion modes.【F:sg_viewer/ui/preview_widget.py†L75-L210】【F:sg_viewer/ui/viewer_controller.py†L117-L173】
4. Create or edit content: start a new track, add straights/curves, or delete sections. The preview editor recomputes signatures, track length, and selection while flagging unsaved changes and repainting the canvas.【F:sg_viewer/ui/preview_widget.py†L319-L439】
5. Optional dialogs (section/heading tables, background settings) stay synchronized with the preview state, while elevation profiles reflect the current cross-section and selection range.【F:sg_viewer/ui/viewer_controller.py†L117-L198】【F:sg_viewer/ui/app.py†L51-L209】
