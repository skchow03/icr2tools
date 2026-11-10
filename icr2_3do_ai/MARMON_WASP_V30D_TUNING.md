# Marmon Wasp V30d — tapered tail shadow and pilot collar clearance

Follow-up to V30c on the integrated Wasp modeling branch. Script: `icr2_3do_ai/wasp_v30d_tuning.py`. The V29/V30c sources and compiled outputs remain unchanged. Build from the validated V30c output:

```sh
python -m icr2_3do_ai.wasp_v30d_tuning --baseline /tmp/3do-ai-recipes/marmon_wasp_v30 --output /tmp/3do-ai-recipes/marmon_wasp_v30d
```

## Ground shadow

The previous separate tail shadow was a rectangular four-vertex POLY, palette 27, at Z=-8501, spanning X=-41500 to -32500 and ±6000 Y. It extended beyond the modeled tail tip and gave the shadow a square rear edge.

V30d changes **only its four vertices** to (-38248,-150,-8501), (-33000,-5100,-8501), (-33000,5100,-8501), (-38248,150,-8501). This creates a pointed-looking taper matching the modeled tail's X=-38248 tip and approximately ±150 half-width. The broad end joins the existing body shadow precisely at X=-33000, Y=±5100. The other seven shadow polygons, palette index 27, Z=-8501, and overall eight-polygon shadow budget remain unchanged.

## Driver torso and neck

Keep helmet DYNAMIC at (-600,0,12824), same stock `HELMET.3do` and eight `helm0001..helm0008.pmp` references. Do not move the seat, arms, gloves or alter palette.

- Torso middle cross-section vertices 4–7: +180 raw Z (0.36 inch)
- Torso top cross-section vertices 8–11: +480 raw Z (0.96 inch), final Z=11404
- Neck bottom vertices 0–3: +240 raw Z (0.48 inch), final Z=10024
- Neck top vertices 4–7: +840 raw Z (1.68 inch), final Z=12304

These small local extensions overlap the neck with the upper torso and push the neck closer to the unchanged sprite helmet chin without raising the helmet or widening the cockpit.

## Verification and limits

Compile via the existing N3 backend and reparse. Confirm eight shadow POLYs at palette 27 and Z=-8501, 56 independent outward-facing V30c roof/cockpit FACE gates, unchanged helmet anchor, 32 low/side painter-order samples, byte-identical external wheel and helmet binaries, ten matched filled-camera previews and nonzero V30c→V30d image differences. Generated source and compiled binaries are under `marmon_wasp_v30d/` in the `3do-ai-generated-models` GitHub Actions artifact.

The dimensions above are **user-requested visual tuning**, not new historical measurement claims. The CPU preview's ground shadow shape and sprite rendering may differ from the ICR2 game engine. In-game visual testing is required to confirm the gap is fully hidden and the tail patch aligns with engine shadow compositing.
