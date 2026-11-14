---
name: icr2-3do-modeler
description: Create or revise low-poly Papyrus ICR2 N3/3DO geometry for the icr2tools CAD editor using semantic inspection, parametric recipes, validated modeling jobs, and GitHub Actions. Use for IndyCar, historical open-wheel, trackside object and car-part modeling tasks.
---

# ICR2 3DO modeling workflow

Use this skill for requests to create an editable ICR2 3DO/N3 model, prepare a simple low-poly blockout, refine a Stage 2 component, or investigate a problematic existing model. The **repository code** does geometry generation and compilation; this skill supplies workflow guidance. Do not generate a binary by inventing bytes.

## Before modeling

1. Read `icr2_3do_ai/AGENTS.md` and `icr2_3do_ai/README.md`. Identify whether the user wants **inspection**, a **new model/blockout**, or a **revision**.
2. For an existing 3DO, run or invoke `python -m icr2_3do_ai inspect` on the available source and its local referenced objects. Cite exact instance/record IDs, rather than guessing component names from binary offsets.
3. For a historically specific car (e.g., the 1911 Marmon Wasp), research reliable photographs, technical drawings and dimensions when available. Separate verified dimensions from approximations. Explicitly label template geometry as illustrative.
4. Use simple geometric descriptions (length, width, height, wheel centers, cross-sections, silhouette), and name every significant component.

## Create a model

- For a generic early racer, create a job in `icr2_3do_ai/jobs/` using schema `icr2.n3.job.v1` with `mode="blockout"`, `template="vintage_open_wheel"`, and `parameters`. Review the existing `vintage_racer_blockout.json` example.
- For a bespoke object, author a Stage 2 recipe in `icr2_3do_ai/recipes/` using `loft`, `extrude` and `mirror`, with explicit coordinate scale, palette indices and optional planar UVs. Review `recipes/example_indycar_nose.json`.
- Treat `goal` as descriptive metadata, not a natural-language programming interface. The modeling assistant is responsible for translating the request into valid structured geometry.
- Prefer multiple meaningful source components over one massive unmanageable mesh. Leave individual parts easy to select in the CAD editor.

## Revise a model

- If the model was generated from a Stage 2 recipe, create a `mode="revise"` job with an existing repository-relative `base_recipe`. Use `add`, `replace` or `remove` edits targeting **named components**.
- Use `base_recipe_sha256` for stale-source protection when feasible. Populate `quality.must_preserve` with components that must not change and bound `max_abs_polygon_delta`.
- **Do not claim arbitrary binary 3DOs or hand-edited BSP trees are supported by Stage 3's revision mode.** They require explicit analysis and a separate source-editing approach.
- Do not silently overwrite source files, carsets, MIPs or previous model outputs.

## Validate and present

1. Run `python -m icr2_3do_ai build-job <job.json> -o <new_output>`, optionally with `--repository-root .`; never reuse an existing output directory.
2. Confirm the N3 compiler and binary parser accept the output, the quality gates pass, and the Stage 1 geometry diagnostics are available. Compare the baseline and candidate for revisions.
3. Review `generated/model.3D`, `generated/model.3do`, `change_report.json`, and any `generated/analysis/views/*.png`. The wireframes are diagnostic only; they do not prove BSP/LOD or in-game drawing.
4. In a GitHub-connected workflow, create a branch/PR with the job or recipe and inspect the GitHub Actions run and its `3do-ai-stage3-modeling-jobs` or `3do-ai-generated-models` artifact. Do not merge the PR without the user's instruction.
5. Report what was modeled, which dimensions were estimated, what was validated, where the N3 source and compiled model are, and what must still be refined in CAD.

## Important limitations

This first Stage 3 implementation does not interpret reference images automatically, generate complete BSP ordering, cut true cockpit holes, model faithful mechanical internals, or verify a historical vehicle's exact shape. Treat those as future capabilities. When the user asks for a famous real car, build a recognizably proportioned editable starting shape when possible, but never imply that an illustrative template is a faithful replica.
