# SG Viewer Architecture

This document describes the current architecture of **SG Viewer**, reflecting the recent refactors to reduce module size, improve separation of concerns, and decouple UI widgets from editing logic.

---

## High-Level Overview

This document is written to be consumed by **both humans and LLM-based code assistants**. It is intentionally explicit about ownership, data flow, and dependency direction so that automated refactors do not collapse boundaries or reintroduce large, tightly coupled modules.

When modifying this repository with the help of an LLM:

* Prefer small, local changes
* Never move initialization order inside Qt widgets without understanding dependencies
* Treat architectural boundaries described below as constraints, not suggestions

---

## High-Level Overview

SG Viewer is a Qt-based desktop application for inspecting and editing `.SG` track geometry files used by IndyCar Racing II. The application is structured around a thin UI layer, a preview canvas for visualization and interaction, and a set of domain-focused helpers and controllers that encapsulate geometry, selection, editing, and rendering behavior.

The primary architectural goals are:

* Keep Qt widgets thin and focused on event forwarding and painting
* Isolate math, geometry, and selection logic into pure-Python modules
* Decouple interaction logic from concrete widget classes
* Make incremental refactoring safe by enforcing clear ownership and initialization order

---

## Entry Points and Application Shell

### `sg_viewer/main.py`

**Purpose:** process entry point only.

Responsibilities:

* Parse command-line arguments
* Configure logging
* Create the Qt application instance
* Instantiate and show the main window

Non-responsibilities:

* No preview logic
* No editor logic
* No domain imports beyond `ui.app`

LLM guidance:

> Do not add features or logic here. This file should remain boring and stable.

---

### `sg_viewer/main.py`

Responsibilities:

* Parse command-line arguments
* Configure logging
* Create the Qt application instance
* Instantiate and show the main window

This file intentionally contains no application logic beyond startup and shutdown.

---

### `sg_viewer/ui/app.py`

Defines the main application window and top-level UI composition.

Responsibilities:

* Construct the main window layout
* Instantiate the preview widget
* Own high-level UI controls (buttons, labels, menus)
* Wire signals between UI elements and controllers

The main window treats the preview widget as an opaque component that satisfies the `PreviewContext` interface.

---

## Preview System

The preview system is the core of SG Viewer. It is deliberately split into multiple layers to prevent a single "god widget" from forming.

### `sg_viewer/preview/widget.py` — **SGPreviewWidget**

Role:

* Subclasses `QWidget`
* Owns the Qt paint lifecycle (`paintEvent`)
* Forwards mouse, wheel, and resize events
* Acts as the *concrete runtime provider* of `PreviewContext`

Key invariants:

* All collaborator objects are created in `__init__`
* Initialization order matters and must not be reordered casually
* `_controller`, `_selection`, and `_editor` must exist before use

Non-responsibilities:

* No geometry math
* No hit-testing logic
* No editing state ownership
* No domain decisions

LLM guidance:

> Do not move logic *into* this widget. If code grows here, extract it outward.

---

### `sg_viewer/preview/widget.py` — **SGPreviewWidget**

Role:

* Subclasses `QWidget`
* Owns the Qt paint lifecycle (`paintEvent`)
* Forwards mouse and wheel events
* Acts as the concrete implementation of `PreviewContext`

Non-responsibilities:

* No geometry math
* No selection algorithms
* No editing state ownership
* No direct business logic

The widget’s job is to *coordinate*, not decide.

---

### `sg_viewer/preview/context.py` — **PreviewContext**

`PreviewContext` is a `typing.Protocol` that defines the *minimum surface area* required by non-UI logic.

Design intent:

* Enables duck typing
* Prevents interaction and controller code from depending on Qt widgets
* Allows future replacement or wrapping of the preview widget

Important rules:

* **Never inherit from `PreviewContext`** (especially in Qt classes)
* Only use it for type hints
* Methods must remain simple and side-effect transparent

LLM guidance:

> Adding methods to this interface is a breaking architectural change. Do so only when strictly necessary.

---

### `sg_viewer/preview/context.py` — **PreviewContext**

A `typing.Protocol` defining the minimal interface required by interaction and editing logic.

Responsibilities:

* Abstract access to coordinate transforms
* Provide repaint and status update hooks

Key property:

* **Duck-typed** only
* Never inherited from by Qt widgets

This allows interactions and controllers to remain widget-agnostic.

---

## Controllers and State

Controllers are long-lived objects that own mutable application state. They are created by `SGPreviewWidget` and outlive individual user interactions.

Controllers:

* Never import Qt widgets
* May depend on `PreviewContext`
* May depend on pure helper modules

They represent the *behavioral core* of the preview system.

---

## Controllers and State

### Preview State Controllers

These classes own mutable preview/editor state and are created by `SGPreviewWidget` during initialization.

Typical responsibilities include:

* Track state
* Selection state
* Edit mode and creation state

Strict rule:

> Controllers may depend on `PreviewContext`, but never on concrete widget classes.

---

### Creation / Interaction Controllers

Creation logic (new straight, new curve, delete, etc.) is implemented via dedicated controllers and interaction classes.

Responsibilities:

* Interpret mouse input into domain actions
* Maintain temporary creation state
* Generate preview geometry
* Emit status text

They do **not**:

* Paint
* Access widget internals
* Perform geometry math directly

---

## Helper Modules

Helper modules are intentionally boring. They should contain pure, testable logic with no side effects.

LLM guidance:

> If a helper module needs Qt, it probably belongs in a painter or widget instead.

---

## Helper Modules

### Geometry

**Location:** `sg_viewer/preview/geometry.py`

Contains all math-only helpers:

* Heading calculations
* Tangent / normal computation
* Curve angle math
* Coordinate reconstruction

Pure Python. No Qt imports.

---

### Selection

**Location:** `sg_viewer/preview/selection.py`

Responsibilities:

* Hit testing
* Nearest-section lookup
* Selection resolution

Pure Python. No Qt imports.

---

### Transforms

**Location:** `sg_viewer/preview/transform.py`

Responsibilities:

* World ↔ screen coordinate transforms
* Pan / zoom math

Pure Python. No Qt imports.

---

### Rendering

**Location:** `sg_viewer/services/preview_painter.py`

Responsibilities:

* All QPainter-based drawing
* Background imagery
* Centerline and section drawing
* Selection highlights
* Creation previews

Qt-dependent by design, but stateless and function-based.

---

## Dependency Rules (Important)

These rules are **hard constraints**, not stylistic preferences. Violating them will reintroduce the problems this architecture was designed to eliminate.

Allowed dependencies:

* Widgets → Controllers → Helpers
* Widgets → Painters
* Controllers → Helpers

Forbidden dependencies:

* Helpers → Qt
* Controllers → Widgets
* Painters → Controllers
* Cross-imports between helpers

Initialization rules:

* Widgets must fully construct collaborators before passing references
* Controllers must not assume widget attributes beyond the `PreviewContext` interface

LLM guidance:

> If you are about to add an import that violates these rules, stop and reconsider the design.

---

## Dependency Rules (Important)

The following rules are enforced by convention:

* Qt widgets do **not** import geometry, selection, or math helpers directly
* Geometry / selection helpers never import Qt
* Controllers depend on `PreviewContext`, not widgets
* Widgets create controllers; controllers never create widgets
* Initialization order in widgets is explicit and guarded

These rules prevent circular dependencies and make future refactors predictable.

---

## Known Extension Points

Designed extension areas:

* New edit modes (via new interaction/controller classes)
* Additional overlays in the painter layer
* Alternative background imagery sources
* Additional export or analysis tools

Areas intentionally frozen:

* Preview widget public surface
* Context interface shape

---

## Summary

This architecture exists to protect the project from two common failure modes:

1. **God widgets** that mix UI, math, and domain logic
2. **Uncontrolled LLM refactors** that accidentally collapse boundaries

By enforcing explicit ownership, clear dependency direction, and minimal interfaces, SG Viewer remains evolvable even as features grow.

LLM guidance:

> Prefer extracting new modules over extending existing ones. Small files are a feature, not a problem.

---

## Summary

SG Viewer’s architecture prioritizes long-term maintainability over short-term convenience. By enforcing strict separation between UI, interaction, math, and rendering, the project remains flexible even as feature complexity grows.

Further structural refactors should only be undertaken deliberately, as the current layout represents a stable and extensible baseline.
