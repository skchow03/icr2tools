# SG CREATE (sg_viewer) Architecture

## Overview

`sg_viewer` (“SG CREATE” in the UI) is an interactive editor/viewer for Papyrus IndyCar Racing II `.SG` track geometry files.

The app is organized around strict separation of:
- **Authoritative SG data** (the only truth that is saved to disk)
- **Derived preview geometry** (recomputed and disposable)
- **Interaction logic** (selection, dragging, creation modes)
- **Transforms + mapping** (screen ↔ world, fit/zoom/pan)
- **Rendering** (pure drawing from current state)
- **Qt UI plumbing** (widgets, dialogs, menu actions)

Key principle:
> Preview state is intentionally lossy and recomputable. Only SG-backed values are canonical.

---

## Package Map (where to look)

- `model/`
  - Authoritative document wrapper: `SGDocument`
  - Preview/derived state structs (e.g., `PreviewData`, `SectionPreview`, `PreviewFSection`, view/transform state)
  - Undo/redo command framework
- `preview/`
  - `PreviewRuntime`: orchestrates preview data, geometry derivation, interaction, creation, overlays, transforms
  - `preview/runtime_ops/` + `preview/runtime_ops_editing/`: mixin “ops” layers used by `PreviewRuntime`
- `geometry/`
  - Pure geometry/topology math (dlong/topology/centerline/picking/transforms/derived geometry)
- `rendering/`
  - Style maps and rendering helpers (surface/boundary/fence styles, colors)
- `services/`
  - Background image model + calibration helpers
  - Export helpers (SG→CSV, SG→TRK subprocess wrappers)
  - Simple generators (e.g., f-section templates)
- `ui/`
  - Main window, dialogs, widgets
  - Feature controllers (“Document”, “Sections”, “Elevation panel”, “Background”)
  - Preview widget wrapper (`PreviewWidgetQt`) that owns a `PreviewRuntime`

---

## Data Ownership and Canonical State

### 1) Authoritative SG: `SGDocument` (canonical)

**Canonical SG state is owned by `SGDocument`**, which holds an `icr2_core.trk.sg_classes.SGFile` instance and emits signals when it changes.

Responsibilities:
- Own the loaded `.SG` data (`SGFile`) and validate it
- Apply edits that should persist (section elevation/grade, x-sections, f-sections, metadata)
- Emit signals so the preview/runtime and UI can refresh

Key signals:
- `section_changed(section_id)`
- `geometry_changed()`
- `elevation_changed(section_id)`
- `metadata_changed()`

Rule:
- Anything that must survive save/load belongs here (or must be committed here).

### 2) Preview model: `SectionPreview`, `PreviewFSection`, `PreviewData` (disposable)

The preview/runtime layer works with lightweight preview objects:
- `SectionPreview`: a preview-friendly representation of a section (including endpoints and derived headings/polyline)
- `PreviewFSection`: preview representation of f-section spans/types used by the diagram/editor
- `PreviewData`: “current snapshot” used by rendering (sections + derived geometry + overlays + messages)

Rules:
- Preview structures can be rebuilt from `SGDocument.sg_data` at any time.
- During active editing, preview may be temporarily “invalid” (non-closed loop, inconsistent headings, etc.).
- “Commit” operations translate from preview edits back into `SGDocument` / `SGFile`.

---

## High-Level Runtime Flow

### App bootstrap → window wiring

Entry points:
- `python -m sg_viewer` calls `main()`
- `ui/app_bootstrap.py` builds the main window and wires a `SGViewerController` to attach feature controllers.

### Preview widget owns the runtime

`PreviewWidgetQt` owns:
- an `SGDocument` instance
- a `PreviewRuntime` instance (constructed with the widget as context)
- Qt signals that reflect runtime state (selection changes, mode toggles, scale changes, etc.)

The widget delegates:
- mouse/keyboard events → runtime interaction
- paint events → runtime rendering/presenter
- UI actions/modes → runtime ops/state

---

## PreviewRuntime: the “orchestrator”

`PreviewRuntime` is the center of the interactive editor:
- Pulls data from `SGDocument` and constructs preview sections/fsections
- Computes derived geometry via `geometry/*` utilities
- Maintains view state + transforms (fit/zoom/pan)
- Coordinates selection/hit-testing and drag logic
- Handles creation modes (new straight/curve, split, delete, connect)
- Integrates optional TRK overlay logic
- Produces `PreviewData` used by rendering/painter/presenter

Important collaborators commonly held/used by `PreviewRuntime`:
- `PreviewStateController` (tracks view + selection + mode-ish state)
- `PreviewSectionManager` (current list of `SectionPreview`, selection index)
- `PreviewEditor` (edit rules/constraints, higher-level operations)
- `PreviewInteraction` (mouse intent, drag state, hit testing)
- `CreationController` (new-straight/new-curve workflows)
- `TransformController` + `PreviewViewport` (view transform state)
- `TrkOverlayController` (TRK overlay, centerline sampling/indexing)
- `DerivedGeometry` (cached/recomputed centerline/bounds, etc.)

---

## Runtime Ops Layer (mixin-based)

`PreviewRuntime` subclasses an ops bundle (`PreviewRuntimeOps`) that is split into multiple mixins under:
- `preview/runtime_ops/`
- `preview/runtime_ops_editing/`

Intent:
- Keep `PreviewRuntime` readable by pushing “verbs” into cohesive mixins:
  - commit/finalize creation
  - connect/disconnect endpoints
  - edit transforms / dragging rules
  - snap/project operations
  - constraints shared by editing actions

Guideline:
- If you are adding a new runtime feature that is an “operation” (not a persistent state field), it usually belongs in `runtime_ops_*`.

---

## Editing Model and Undo/Redo

### Sections: command-based undo/redo

For section edits, the codebase uses:
- `model/edit_commands.py` (command objects)
- `model/edit_manager.py` (undo/redo stacks, invariants validation)

Typical pattern:
1. Capture “before”
2. Build “after”
3. Execute via `EditManager` (push undo stack)
4. Update preview sections
5. Optionally commit to SG on save/export

### F-sections: edit sessions

F-section editing uses an explicit session object:
- `runtime_ops/fsection_edit_session.py`

Pattern:
- `begin()` → snapshot original f-sections into preview form
- mutate the preview list during UI edits
- `commit()` → apply normalized f-sections into `SGDocument` for persistence
- `cancel()` → revert to original snapshot

Rule:
- F-sections are SG-owned; preview f-sections are a temporary working copy.

---

## Geometry Layer (pure math)

The `geometry/` package is intentionally UI-free and runtime-free.

Common responsibilities:
- Centerline rebuild/sample utilities
- Track topology checks (closed loop, length)
- DLONG and start/finish normalization
- Picking/projection to polylines/segments
- Transform helpers (world bounds, fit scale, view center)

Rule:
- Geometry utilities should accept plain data (tuples, lists, preview objects) and return plain results.
- No Qt, no widget assumptions.

---

## Rendering Layer

Rendering is split between:
- “Style resolution” (what color/width/type to use) in `rendering/`
- “Painter/presenter” style drawing code in UI/preview components

Goal:
- The renderer consumes the current `PreviewData` snapshot and draws without mutating model state.

---

## Services Layer (I/O and side effects)

### Background image support
- `services/preview_background.py` holds the background image model, scale, and world↔image mapping.
- UI feature controller(s) manage dialogs and calibration flows.

### Export helpers
- `services/export_service.py` builds subprocess commands and wraps results for:
  - SG→CSV
  - SG→TRK

Rule:
- Services are allowed to touch filesystem/subprocess.
- Runtime/model layers should call services, not embed subprocess logic.

### Generators
- `services/fsect_generation_service.py` builds common template f-section layouts (“street”, “oval”, etc.) as `PreviewFSection` lists.

---

## UI Layer (Qt)

### Main window and feature controllers

The UI is organized with:
- `ui/main_window.py` (menus, docks, widgets)
- `ui/viewer_controller.py` + `ui/controllers/features/*` (feature-specific controllers)

Feature controllers typically:
- own menu actions / dialogs for a feature
- call into runtime/document/services to do the work
- keep Qt wiring isolated from core logic

### Preview widget

`ui/preview_widget_qt.py` is the key widget binding:
- constructs `SGDocument`
- constructs `PreviewRuntime`
- forwards input events to runtime
- emits UI-friendly signals for selection/mode/scale changes

---

## Design Rules (guardrails)

- **SGDocument is canonical**: anything saved must be reflected into `SGDocument.sg_data`.
- **Preview is disposable**: if a preview structure is hard to keep consistent, recompute it.
- **Geometry is pure**: no Qt dependencies in `geometry/`.
- **Ops are verbs**: prefer placing complex “actions” in `runtime_ops_*` rather than bloating the runtime or UI.
- **UI calls, doesn’t decide**: controllers/widgets should delegate policy-heavy logic to runtime/editor/geometry.

---

## Non-Goals

The architecture does **not** guarantee:
- Fully valid geometry during active edits
- Continuous section chains mid-interaction
- Normalized angles before save
- Presence of a centerline at all times

These tradeoffs are intentional to support interactive editing.
