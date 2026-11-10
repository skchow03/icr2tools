---
name: icr2-3do-modeler
description: Inspect, create, assemble, visually compare, and package low-poly Papyrus ICR2 N3/3DO cars and scenery using the verified icr2tools branch, GitHub Actions, and read-only local game assets.
---

# ICR2 3DO modeler — repository workflow

Work in skchow03/icr2tools. The user's target branch and exact PR head SHA are authoritative. This file documents toolkit phases 1–4, not a new renderer or compiler. Do not produce fake binary bytes, infer unavailable assets, or merge PRs without explicit approval.

## 0. Resolve capabilities and ancestry

1. Read the target ref's icr2_3do_ai/README.md, icr2_3do_ai/AGENTS.md, icr2_3do_ai/__main__.py, actual recipes/tests, and .github/workflows/3do-ai-inspector.yml before authoring commands.
2. Check branch ancestry before selecting a PR base. Phases 1–3 were merged into feature/marmon-wasp-v29-cad-contours-20261109; do not assume they landed on default main. The Wasp V29 compiled assets are a frozen reference until a user requests migration.
3. The Stage 3 job planner (build-job, icr2.n3.job.v1, jobs/) belongs to a SEPARATE branch, feature/3do-ai-stage3-modeling-jobs-20261108, and is NOT in the verified Wasp branch. Do not invoke or recommend build-job unless the exact target ref provides its implementation. On the Wasp branch use generate and explicit recipe edits.
4. Use the existing GitHub connection for edits, PRs, CI logs and artifacts. GitHub Actions has checkout assets only; local unpublished game directories are invisible.

## 1. Research, coordinates and palette

Identify car, year and configuration; distinguish documented measurements from photo-derived estimates and deliberate simplified geometry. The Wasp's design and compiled X axes face opposite ways. Do not silently flip or scale. Source recipes state coordinate_scale explicitly, typically 6000 raw Papyrus units per foot, or 1 for game-raw coordinates. Generated N3 contains ICR2_COORD_SCALE: 1; never scale converted values twice.

Use the verified ICR2 sunny/gamepal palette guide at https://skchow.com/indy/palette/ and actual target PCX swatches. Avoid nonportable indices; index 0 is reserved in some workflows, so use tested black (for example index 49 in the Marmon Wasp) when specified by the target model. Never infer hue from a number alone. Record verified indices/material references. Prefer tens of polygons for simple track furniture and a modest, explicit low-poly budget for cars.

## 2. Geometry correctness (Phase 1)

Create or revise named JSON operations in icr2_3do_ai/recipes/ with schema icr2.n3.recipe.v1. The verified Wasp-branch generator supports loft, extrude, mirror and planar polygon. Use independent caps.start/caps.end for open lofts and zero-thickness polygon for fins/closing faces. Concave flat polygons are triangulated. Reject invalid shape inputs rather than hiding them behind source editing.

Set surface_checks to error for strict new meshes when overlaps should fail. Review duplicate/coplanar/intersection diagnostics. Do not use BSP layers to conceal intersecting shells or unnecessary internal faces. Older recipes without the new options retain original generation behavior.

## 3. Assembly correctness (Phase 2)

For movable subassemblies, set optional assembly.coordinate_system to source or game. Declare anchors, groups, externals, gates and nodes rather than rewriting arbitrary polygon labels in emitted N3.

- Move a driver through one group containing torso, neck, arms, gloves and its HELMET EXTERN; keep a stationary seatback outside the group. Mirror groups should include housing, struts and relevant geometry.
- transform.translate uses recipe coordinate units. rotate_z_quarters permits exact Z quarter turns. Positive uniform scale is permitted only when it yields integer raw coordinates and the group does not contain external DYNAMIC references. Reject arbitrary angles, shear and anisotropic scaling.
- externals record 1–8 character model basenames such as FWHEEL, RWHEEL, HELMET (without .3do). Supply --objects-folder to validate linked .3do files. PMP sprites inside external models require separate visual-asset resolution.
- gates wrap selected polygon indices in FACE records, validated with positive and negative camera halfspaces. nodes represent LIST/BSPN/BSPA painter graphs; every drawable leaf must appear exactly once. Camera halfspace checks are not substitutes for in-game tests.

Use the repository's existing n3_compile and three_do.Model as the ONLY N3 compiler and binary parser. Keep assemble_wasp.py as an unmodified V29 baseline until a deliberate migration is approved and visually compared.

## 4. Visual regression (Phase 3)

Generate filled, camera-specific previews from compiled .3do using:

    python -m icr2_3do_ai preview car/WASP.3do --objects-folder car --texture-folder sprites --strict-assets --cameras front rear left right top front-left rear-right -o output/preview

Supported cameras: front, rear, left, right, top, front-left, front-right, rear-left, rear-right. The CPU renderer reuses CAD FACE/BSP/DYNAMIC traversal, MIP, palette and PMP sprite decoders. Missing sprite files must be reported, not interpreted as absent geometry.

Compare baseline and changed compiled models with one shared camera/scale/palette/asset context:

    python -m icr2_3do_ai compare old/WASP.3do new/WASP.3do --objects-folder new --texture-folder sprites --strict-assets --cameras front rear left right top front-left rear-right --max-diff-ratio 0 -o output/comparison

Review the before, after, highlighted diff and three-panel comparison PNG files plus comparison.json. A threshold of zero requires no changed pixels; justify any relaxed threshold. These are orthographic DIAGNOSTIC previews, not ICR2 scanline-equivalent game screenshots. A successful compiler pass or image match is not proof of in-game correctness.

## 5. Release candidate and artifacts (Phase 4)

The CI workflow compiles recipes, checks headless tests, assembles the Wasp, checks four compiled binaries byte-for-byte against the Phase 1 baseline, renders helmet and Wasp cameras, and demonstrates an intentionally colored model diff. Verify the run that corresponds to the PR's exact head SHA.

The icr2_3do_ai.release_package command creates a review-only deterministic ZIP from validated model sources/binaries, three recipes and Phase 3 reports. Its preflight refuses missing files, N3/binary mismatches, changed assembly SHA hashes, missing PMP sprite renders, warnings and nonzero baseline differences. It emits SHA256SUMS and a release manifest with the exact checked-out build commit and file hashes. CI artifacts: 3do-ai-generated-models and 3do-ai-release-candidate (check current retention; initially 14 days). The candidate does NOT auto-create a public GitHub Release, bundle stock PMP sprite files, or assert that the package is an installable carset.

## 6. Delivery and evidence

For each model task, create a dedicated branch and PR targeting the verified parent branch. Inspect matching CI logs, exact compiler/parser counts and SHA-256 hashes, Phase 1 surface diagnostics, Phase 2 assembly/external dependencies, Phase 3 camera comparisons, and Phase 4 artifact manifest. Preserve existing binaries unless a revision is requested. State missing assets, uncertain historical measures and remaining in-game checks explicitly.

Prefer sharing actual compiled .3do plus editable .3D when a verified binary-transfer path into the chat is available. Otherwise give the successful Actions artifact page and internal paths. Never invent sandbox links, claim to have downloaded a ZIP when only metadata was returned, or treat time-limited artifacts as permanent. Never merge or publish public game assets without explicit user authorization.
