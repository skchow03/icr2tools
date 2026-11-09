# Marmon Wasp V27 — exterior-shell topology correction

## Problem and verified source cause

The V26 screenshot shows unwanted triangular faces across the raised bonnet ramp. V26's **long_bonnet** (with a roof continuing unbroken from X=0.55 to 6.15 ft) and the separately lofted **dashboard_cowl_riser** (X=4.69–6.09 ft) BOTH contain roof and lower/side faces over the same spatial region. The extra cowl was drawn later to cover the original roof. That was a workaround for a true overlapping-shell geometry error, and it left potentially visible inward-facing surfaces.

## V27 single-skin construction

Replace the two overlapping lofts with **one named, CAD-editable five-ring `long_bonnet`**:
- Ring positions design X (ft): 0.55, 3.35, 4.69, 5.39, 6.09
- Shoulder heights Z (ft): 2.87, 2.91, 2.962, 3.29, 3.65
- Crown heights Z (ft): 3.30, 3.34, 3.386, 3.718, 4.03
- Upper 25% of nominal bonnet length remains a smooth progressive rise over X4.69–6.09.
- Each ring has six outer perimeter vertices. Four spans produce **48 exterior side/roof/bottom surface triangles**. No internal longitudinal overlap, no inter-ring transverse cross-section polygons.
- Omit nose-facing bonnet cap (hidden behind the radiator); retain exactly one cockpit-facing cap at design X=6.09 / game X=8460 (palette 159), with a rear-facing FACE plane at game X=8490.
- Remove `dashboard_cowl_riser` as a second CAD component altogether; remove its redundant bulkhead. The raised dashboard is now the single aft-facing closure of the continuous bonnet.
- Move the front cockpit wall 0.01 ft forward so it joins that ring without a visible gap; preserve its exterior shell and inward-facing visible cockpit panels.
- Paint exterior roof triangles in 158 and exterior sides in 159, leaving palette 33 for black and 148/149 for the driver outfit. Wheels, fin, shadow, mirrors, helmet sprite and Z=12824 are unchanged.

## Explicit geometry invariants

- Compiled N3 body retains exactly 49 bonnet POLYs: 48 outward skin triangles + 1 rear cockpit closure. The original nose cap is absent.
- No `dashboard_cowl_riser_` declarations survive source assembly.
- Exactly one six-sided, yellow, rear-facing cockpit closure at game X=8460. The earlier closing bulkhead at X=8100 has been eliminated, not hidden by the painter.
- The two intermediate bonnet ring stations at X=4.69 and 5.39 have **vertices only**, never cross-section polygons.
- One-sided dashboard culling remains visible from the open cockpit and all rear viewpoints; the visor, mirror/strut and wheel painter-order checks remain in place.
- The user may still need to confirm the rasterized output in actual Papyrus ICR2; compilation and structural audits are not an in-game rendering test.

## Design provenance

Proportions remain a visual approximation based on the user-provided side photograph and the prior user-approved V26 appearance. These are not verified manufacturing drawings. The target 25% bonnet ramp is the user's explicit geometric constraint.
