# Phase 4: ICR2 3DO model-review and release process

This page documents the **real** repository workflow after Phases 1–3, and how to deliver a validated model safely. This is not an automatic public release or an ICR2 game installer.

## Branch and ownership

- Main model-source branch at introduction: feature/marmon-wasp-v29-cad-contours-20261109. Phase 1 PR #1960, Phase 2 PR #1961 and Phase 3 PR #1962 merged into **that feature branch**, not necessarily main.
- The canonical repository agent skill is .agents/skills/icr2-3do-modeler/SKILL.md. The installed private ChatGPT skill may be a separately packaged release; do not assume editing a GitHub file updates an installed plugin. Resolve plugin release identity and verify read-back after explicit updates.
- An older, separate experimental modeling-job implementation (build-job) is on feature/3do-ai-stage3-modeling-jobs-20261108. Do not invoke it on the Wasp branch unless the branch is explicitly integrated and the CLI is verified.
- Assembly of the historical Wasp V29 remains intentionally frozen. Building a release candidate must **not** migrate the model's old N3 source operations.

## Production sequence

1. Research the particular car/part and identify documented vs approximate dimensions. Confirm coordinate frame and colors in the intended palette. Avoid index 0 where reserved; for the current Wasp the tested dark palette index is 49.
2. Create or revise an icr2.n3.recipe.v1 JSON under icr2_3do_ai/recipes. Use Phase 1 independent loft caps, planar polygons and geometry-integrity diagnostics. Set surface_checks=error for strict clean new geometry.
3. Use the optional Phase 2 assembly block for named anchors, movable groups, external DYNAMIC references, FACE halfspace gates, and BSP/LIST painter graph. Do not hide overlapping or redundant geometry through draw-order tricks.
4. Compile with the *existing* N3 compiler and reparse the 3DO. Validate actual EXTERN assets through --objects-folder, then render camera-specific filled previews with --strict-assets and compare before/after images with a shared palette and framing. Review the PNGs: diagnostic orthographic views are not game screenshots.
5. In a dedicated GitHub PR, check the **exact head SHA** and matching successful Actions run. The 3do-ai-inspector workflow compiles all checked-in recipes, tests geometry/assembly/visual regression, assembles the original V29 Wasp, checks four compiled models against the exact Phase 1 merge baseline, and generates seven Wasp camera views with stock PMP images resolved from the fixture directory.
6. The workflow creates an isolated, review-only ZIP. Review the SHA256SUMS, release_manifest.json, 3D source, compiled 3DO files, previews and diffs. Do not merge or publish anything without user authorization. Phase 3 camera comparison alone is **not** an in-game validation.

## Headless commands

Install the toolchain's existing requirements first:

    python -m pip install numpy Pillow

Compile a new recipe to a new output directory:

    python -m icr2_3do_ai generate icr2_3do_ai/recipes/phase2_assembly_demo.json --objects-folder icr2_3do_cad/fixtures -o output/demo

Render camera-specific image evidence from compiled geometry, including referenced sprites:

    python -m icr2_3do_ai preview car/WASP.3do --objects-folder car --texture-folder local_pmp_assets --strict-assets --cameras front rear left right top front-left rear-right -o output/wasp_views

Compare compiled versions under the same palette, camera/framing and local asset set:

    python -m icr2_3do_ai compare baseline/WASP.3do candidate/WASP.3do --objects-folder candidate --texture-folder local_pmp_assets --strict-assets --max-diff-ratio 0 --cameras front rear left right top front-left rear-right -o output/wasp_diff

Package a *verified* V29 review candidate from the three recipe builds, assembled source/binary folder, and complete Phase 3 evidence:

    python -m icr2_3do_ai.release_package \
      --models output/marmon_wasp_complete \
      --previews output/phase3_wasp_v29 \
      --comparison output/phase3_wasp_identical_diff \
      --recipes icr2_3do_ai/recipes \
      --source-commit <full-40-hex-commit-of-the-checked-out-build> \
      -o output/phase4_release_candidate

It refuses existing output paths. Nothing modifies the original binaries or earlier generated packages. The packaging preflight recompiles Wasp/FWHEEL/RWHEEL N3 and checks their binary SHA-256, verifies compiled HELMET and assembly_manifest SHA-256, confirms every preview PNG hash and helmet sprite count, and requires a zero-difference camera comparison without missing asset warnings.

The deterministic ZIP uses stable entry order and timestamps and contains model files, the three upstream Wasp recipes, all seven filled-camera previews, all seven comparison groups, SHA256SUMS and release_manifest.json with per-file SHA-256 and source commit. A matching artifact built twice from the same inputs has identical bytes.

## GitHub Actions artifacts and promotion

The repository's .github/workflows/3do-ai-inspector.yml runs on relevant pushes and PRs and supports workflow_dispatch for manual reruns. It **does not** publish releases or modify any branch after building.

Two distinct 14-day download artifacts are uploaded after passing validation:

- 3do-ai-generated-models — full per-recipe build packages, assembled Wasp, geometry reports, sprite preview images and deliberate/identity image comparison groups
- 3do-ai-release-candidate — release-candidate.zip with release_manifest.json and SHA256SUMS, and a copy of the release manifest outside the ZIP

These are *review* artifacts, not redistribution approval or guaranteed game-ready carset installers. The supplied stock helmet PMP assets are used only as locally resolved validation resources; stock PMP files are not added to the candidate ZIP. Preserve ownership/license restrictions for stock binaries and textures before distributing to anyone else. A separate user-approved game compatibility test and actual game asset assembly are needed before any public release.

Release acceptance checklist:

- All 3DOs parse; N3 sources recompile byte-for-byte; SHA-256 hashes match stored manifests.
- Current run's compiled Wasp/FWHEEL/RWHEEL/HELMET remain byte-identical to Phase 1 V29 baseline unless a documented migration is intentional.
- Every selected camera renders the expected PMP helmet with no warning; before/after plots and per-camera changed-pixel counts are reviewed.
- A deliberate changed-polygon test proves the difference detector can report a nonzero change.
- Artifact ZIP checksum/contents and exact Git SHA are recorded; retention period and accessibility are checked.
- Human approval is recorded before merge or publishing. Any game-only visibility findings remain open instead of claiming fidelity.

## Limitations and follow-up

The compiler is structurally faithful but does not prove in-game face culling or pixel-exact painter behavior. The Phase 3 software renderer is orthographic and its sprite/MIP rasterization is approximate. Phase 2 does not automatically migrate the existing Wasp script or perform arbitrary transforms. Phase 4 packaging intentionally does **not** embed licensed external PMP artwork or publish public GitHub Releases. Changes to those constraints require explicit design, licensing consideration and regression tests.
