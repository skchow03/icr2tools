# SG Viewer Architecture

## Overview

`sg_viewer` is an interactive editor and viewer for Papyrus IndyCar Racing II `.SG` track geometry files.  
The application is structured around a strict separation between:

- **Authoritative SG data** (what will be saved to disk)
- **Derived preview geometry** (recomputed, disposable)
- **User interaction logic** (selection, dragging, creation)
- **Rendering and coordinate transforms**
- **Qt UI plumbing**

Preview state is intentionally *lossy and recomputable*. Only SG-backed values are considered canonical.

---

## High-Level Data Flow

.SG file
↓
SG parsing / model creation
↓
SectionPreview objects
↓
Geometry derivation (polylines, headings, bounds)
↓
Preview transform + view state
↓
Interaction controllers (selection, dragging, creation)
↓
Rendering services
↓
Qt widgets


---

## Core Domains

### 1. SG / Track Data (Authoritative)

**Purpose:** Represent real `.SG` semantics and values.

**Primary module:**
- `models/sg_model.py`

**Key type:**
- `SectionPreview`

`SectionPreview` contains:
- SG-backed values:  
  `section_id`, `type_name`, `previous_id`, `next_id`,  
  `start_dlong`, `length`,  
  `sang1/sang2`, `eang1/eang2`, `radius`
- World-space endpoints: `start`, `end`
- Derived values: `polyline`, `start_heading`, `end_heading`

Rules:
- `start_dlong`, `length`, connectivity IDs are authoritative
- Angles and radius follow SG conventions
- Derived geometry may temporarily diverge during editing

---

### 2. Geometry Derivation (Pure, Stateless)

**Purpose:** Convert SG-style parameters into drawable geometry.

**Modules:**
- `geometry/sg_geometry.py`
- `geometry/curve_solver.py`
- `geometry/connect.py`

Responsibilities:
- Build section polylines from SG parameters
- Infer headings when not explicitly stored
- Solve curve geometry from constraints (dragging, fixed heading)
- Flatten sections into a centerline representation

Design constraints:
- No Qt dependencies
- No persistent state
- Safe to recompute at any time
- Deterministic given inputs

---

### 3. Preview State & Coordinate Transforms

**Purpose:** Maintain view state independent of SG data.

**Modules:**
- `models/preview_state.py`
- `geometry/preview_transform.py`
- `preview/transform.py`

Key concepts:
- **World coordinates:** SG space (x right, y up)
- **Screen coordinates:** Qt space (x right, y down)
- **Transform:** `(scale, (offset_x, offset_y))`

`TransformState` tracks:
- `fit_scale` – auto-fit scale from bounds
- `current_scale` – user-modified scale
- `view_center` – world-space center
- `user_transform_active` – disables auto-fit when true

Notes:
- Background image bounds participate in fit calculations
- Auto-fit is suppressed once the user pans or zooms

---

### 4. Selection & Interaction Logic

**Purpose:** Interpret user intent and manage live editing state.

**Modules:**
- `models/selection.py`
- `models/preview_state_utils.py`
- `preview/selection.py`
- `preview/edit_interactions.py`
- `preview/creation_controller.py`
- `preview/connection_detection.py`

Responsibilities:
- Hit-testing against section polylines or centerline
- Mapping screen clicks to world coordinates and DLONGs
- Tracking selected sections and endpoints
- Enforcing connectivity rules (disconnected endpoints only)
- Producing speculative previews during drag or creation

Rules:
- Interaction logic never writes SG values directly
- All edits operate on preview representations first
- Commit happens explicitly after interaction completes

---

### 5. Rendering Services

**Purpose:** Convert preview state into drawing commands.

**Modules:**
- `services/preview_painter.py`
- `services/sg_rendering.py`
- `services/rendering_service.py`
- `services/preview_background.py`

Responsibilities:
- Draw sections, nodes, centerline
- Apply transforms
- Manage draw order and styling
- Render calibrated background images

Rendering is intentionally passive:
- No geometry inference
- No SG mutation
- No interaction decisions

---

### 6. UI Layer (Qt)

**Purpose:** User-facing widgets and application wiring.

**Modules:**
- `ui/preview_widget.py`
- `ui/preview_editor.py`
- `ui/preview_viewport.py`
- `ui/preview_state_controller.py`
- `ui/app.py`
- `ui/*_dialog.py`

Responsibilities:
- Wire mouse/keyboard events to controllers
- Own widgets and layouts
- Display dialogs and status text
- Manage application lifecycle

UI code does **not**:
- Solve geometry
- Interpret SG semantics
- Perform coordinate math beyond delegation

---

## Background Image System

**Modules:**
- `services/preview_background.py`
- `ui/bg_calibrator_minimal.py`
- `models/history.py`

Concepts:
- Images exist in world coordinates
- Scale stored as *500ths per pixel*
- Image origin corresponds to UV (0,0)
- Image bounds are included in auto-fit calculations

Persistence:
- Stored per SG file in history INI
- Relative paths resolved against SG location

---

## Preview vs SG Truth

The following are allowed to diverge temporarily during editing:
- Polylines
- Headings
- Curve center and radius
- Section continuity

The following are always authoritative:
- Section order
- Connectivity (`previous_id`, `next_id`)
- `start_dlong` and `length` once committed

Preview state must always be regenerable from SG data.

---

## Extension Guidelines

Safe extension areas:
- New interaction modes → `preview/*`
- New geometry constraints → `geometry/*`
- New rendering styles → `services/*`
- New dialogs → `ui/*`

Avoid:
- Qt dependencies in `geometry`
- Writing SG values from rendering code
- Treating preview state as authoritative

---

## Non-Goals

The architecture does **not** guarantee:
- Fully valid geometry during active edits
- Continuous section chains mid-interaction
- Normalized angles before save
- Presence of a centerline at all times

These tradeoffs are intentional to support interactive editing.
