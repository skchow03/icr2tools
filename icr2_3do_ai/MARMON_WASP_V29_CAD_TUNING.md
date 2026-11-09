# Marmon Wasp V29: CAD-traced curves and component moves

Continuation of V28. All coordinates below are the **final compiled Papyrus 3DO game frame** (forward is +X, ground Z=-8756, 6000 raw units/ft); Stage 2 design source is transformed by gameX=45000-designX and gameZ=designZ-8756.

1. **Tail underside** — flat bottom Z184 between X=-3000 (rear of seat) and X=-10615, then linearly increasing: X=-21720, Z4886; X=-38248, Z11884. This retains the existing tail crown points at (-3000,13902), (-21720,12724), (-38248,12040). The new ring at X=-10615 has interpolated width and roof height; no transverse internal POLY is added.
2. **Fin** — retain one double-sided POLY at Y=0 (no thickness). Nine silhouette points in (X,Z):
   - (-35576,12078), (-35576,16444), (-35061,18074), (-33656,19266), (-31736,19703), (-29815,19266), (-28410,18074), (-27895,16444), (-27895,12390).
   - Its vertical sides are exactly at X=-35576 and X=-27895 to Z16444. A five-segment semi-elliptical upper arc reaches max Z19703. Bottom points are approximately 70–80 units below the roof for no gaps. The bottom edge lies within the tail shell, and the outer silhouette matches the endpoints.
   - Stage 2 uses a shallow extrude solely as an editable source silhouette; assembly deletes all 19 other cap/thickness faces and unused vertices, producing exactly one 9-sided flat POLY.
3. **Cockpit U opening** — forward wall slopes from the existing dashboard shoulder at X13013 down to X8644 at Z5644. The sidewall remains horizontal through X1489, also exactly Z5644, then inclines to the prior rear section at X=-3000. Five named sidewall panels remain, with no invisible transverse bulkheads. The rear seatback stays fixed at X=-3000.
4. **Mirror** — center (midpoint of forward yellow and backward gray caps) moves from X6180 to **X13590**, delta +7410. Both left/right yellow supports translate by +7410 (new support X endpoints 15780 and 13650). The yellow forward/gray rear FACE gates move to X13590. The mirror retains its previous Z and Y position.
5. **Driver** — driver torso, neck, both arms, both gloves, and the external HELMET DYNAMIC translate +1500 game X, with Z and Y unchanged. The helmet center is now (-600,0,12824); the seatback remains at X=-3000 as the fixed anchor.

Dimensions without a user-supplied Z or width are interpolated for continuity; the user-measured coordinates are fixed and verified in the compiled model. Color palette remains 33 black, 158/159 body yellow, 148/149 driver brown, 40 actual mirror gray. Front bonnet, radiator, shadow, wheel locations, and all eight stock helmet PMP sprites remain unchanged.

GitHub Actions must recompile N3 and test exact vertices, fin polygon count and side visibility, mirror FACE gates, driver offset, and previous rendering-order/cockpit/radiator validations. A successful build is structural validation, not direct in-game raster rendering.
