# Marmon Wasp V25 — raised scuttle and brown driving suit

## Source interpretation
The user-provided side-view image shows the hood top turning upward toward a raised, sloped scuttle/front cockpit bulkhead, with the sidewall falling away toward the open cockpit behind. This is an **illustrative model photograph**, not a verified 1911 manufacturing drawing or dimensional specification. Shape/height choices below are deliberately approximate.

## Geometry (Stage 2, raw scale 6,000 units/foot)
- Preserve the existing main rear-facing bonnet dashboard cap at **design X=6.15 ft**, game X=8,100.
- Add a second, separate **raised dashboard cowl** (`dashboard_cowl_riser`) from design X=5.82 to 6.09 ft. The upstream surface follows the existing bonnet crown near Z=3.402 ft, rising along a short ramp into a center crown at Z=4.03 ft and side shoulder at Z=3.65 ft. It follows the bonnet's six-point cross section. Its fore-facing cap is removed rather than leaving a hidden internal bulkhead; its *rear-facing* cross section is retained as the requested new raised firewall.
- Cowl rear cap: design X=6.09, game X=8,460, palette 159; wrapped in a rear-facing `FACE` gate so it paints into the cockpit and from behind, but not from the front of the car.
- Cowl upper triangles: palette 158, alongside bonnet upper skin. Draw the cowl **after** the bonnet/tail roof skins and **before** mirror housing/struts and helmet sprite.
- Raise the first cockpit-side segment's leading top edge to complement the high scuttle so the upper sidewall falls back toward the driver's opening rather than dropping abruptly at the original dashboard.
- Preserve existing mirror/strut assembly, open seat, windshield sprite draw order, rear fin, shadow, black palette 33, wheels and helmet location Z=12824.

## Color (verified shared palette indices)
Colors verified from the repository `icr2_3do_cad/gamepal.pcx` blob SHA `8784dc6278cb7c057cd717c7b786301a8aa8890a`; see https://skchow.com/indy/palette/ for the shared gamepal/sunny index policy.

| Material | Palette index | RGB |
| --- | ---: | --- |
| Driver brown suit, arms, neck | 148 | (163, 103, 63) |
| Driver darker brown gloves | 149 | (127, 79, 47) |
| Black seat, chassis, tires | 33 | Retained fixed-black selection |
| Upper yellow body/cowl | 158 | (255, 223, 35) |
| Side yellow / transverse bulkhead | 159 | (235, 203, 0) |
| Gray reflective mirror | 40 | (167, 167, 167) |

No newly introduced black 49/0, no track-local palette indices. The suit and gloves are selectable, named recipe components.

## Validation / limitations
Use the existing Wasp CI build and semantic parser. Verify a new, one-sided rear-facing cowl bulkhead survives the compiled BSP, its forward cap is absent, new crown coordinates match the recipe, brown polygon indices persist, helmet sprite still paints after all bodywork, and wheel references remain unchanged. Flat-color 3DO geometry cannot establish historical photographic fidelity. Final visual test in ICR2 should check that the cowl does not cover the cockpit sprite or mirror from rear-oblique viewpoints.
