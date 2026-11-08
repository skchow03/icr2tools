"""Parametric vintage open-wheel *concept* blockouts for subsequent CAD editing.

These templates are visual design scaffolds, not museum-accurate reconstructions.
In particular, the 1911-era template is NOT proof of Marmon Wasp dimensions,
body profiles, color indices, mechanical details or running gear.

The recipe emitted here runs through Stage 2's regular N3 compiler and checks.
"""
from __future__ import annotations

from decimal import Decimal, InvalidOperation
from math import cos, sin, pi

from .parametric import RecipeError, generate_source

SCHEMA = "icr2.n3.job.v1"

DEFAULTS = {
    "overall_length_ft": 15.0,
    "wheelbase_ft": 9.0,
    "track_width_ft": 6.2,
    "wheel_diameter_ft": 3.0,
    "tire_width_ft": 0.48,
    "body_max_width_ft": 2.65,
    "body_max_height_ft": 1.80,
    "body_bottom_ft": 0.75,
    "spokes_per_wheel": 8,
    "body_palette_index": 79,
    "tire_palette_index": 24,
    "spoke_palette_index": 162,
    "cockpit_palette_index": 26,
    "metal_palette_index": 177,
}

LIMITS = {
    "overall_length_ft": (9.0, 25.0),
    "wheelbase_ft": (5.0, 20.0),
    "track_width_ft": (4.0, 12.0),
    "wheel_diameter_ft": (1.5, 5.5),
    "tire_width_ft": (0.2, 1.4),
    "body_max_width_ft": (1.2, 5.0),
    "body_max_height_ft": (0.75, 3.5),
    "body_bottom_ft": (0.1, 2.5),
    "spokes_per_wheel": (0, 12),
    "body_palette_index": (0, 255),
    "tire_palette_index": (0, 255),
    "spoke_palette_index": (0, 255),
    "cockpit_palette_index": (0, 255),
    "metal_palette_index": (0, 255),
}

INTEGER_PARAMETERS = {
    "spokes_per_wheel", "body_palette_index", "tire_palette_index",
    "spoke_palette_index", "cockpit_palette_index", "metal_palette_index",
}


def _parameters(config):
    if not isinstance(config, dict):
        raise RecipeError("parameters: expected an object")
    unknown = set(config) - set(DEFAULTS)
    if unknown:
        raise RecipeError("parameters: unsupported keys " + ", ".join(sorted(unknown)))
    params = dict(DEFAULTS)
    for key, value in config.items():
        if isinstance(value, bool) or not isinstance(value, (int, float, str)):
            raise RecipeError(f"parameters.{key}: expected numeric value")
        try:
            number = Decimal(str(value))
        except InvalidOperation as exc:
            raise RecipeError(f"parameters.{key}: invalid decimal") from exc
        low, high = LIMITS[key]
        if not number.is_finite() or not Decimal(str(low)) <= number <= Decimal(str(high)):
            raise RecipeError(f"parameters.{key}: outside supported {low}..{high} range")
        if key in INTEGER_PARAMETERS and number != number.to_integral_value():
            raise RecipeError(f"parameters.{key}: expected integer")
        params[key] = int(number) if key in INTEGER_PARAMETERS else float(number)
    length = params["overall_length_ft"]
    if params["wheelbase_ft"] >= length - 1.0:
        raise RecipeError("wheelbase must be at least 1 foot shorter than overall length")
    if params["track_width_ft"] <= params["body_max_width_ft"] + params["tire_width_ft"]:
        raise RecipeError("track_width must exceed body width plus tire width")
    if params["body_bottom_ft"] + params["body_max_height_ft"] > 5.5:
        raise RecipeError("overall body height exceeds 5.5 ft template limit")
    return params


def _ellipse(x, y, radius_x, radius_y, segments=12):
    """Counterclockwise convex ring in local cross-section coordinates."""
    return [[round(x + radius_x * cos(2*pi*i/segments), 5),
             round(y + radius_y * sin(2*pi*i/segments), 5)]
            for i in range(segments)]


def _spoke_outline(x, z, inner, outer, angle, width):
    """Strictly convex narrow radial rectangle in x/z plane."""
    dx, dz = cos(angle), sin(angle)
    px, pz = -dz * width / 2, dx * width / 2
    return [
        [round(x+inner*dx+px, 5), round(z+inner*dz+pz, 5)],
        [round(x+outer*dx+px, 5), round(z+outer*dz+pz, 5)],
        [round(x+outer*dx-px, 5), round(z+outer*dz-pz, 5)],
        [round(x+inner*dx-px, 5), round(z+inner*dz-pz, 5)],
    ]


def vintage_open_wheel_recipe(config=None):
    """Return an editable Stage 2 recipe for a generic early racing automobile.

    X runs longitudinally forward, Y across the car, Z upward. The body is
    rounded and tapered using multiple loft cross-sections, and four wheels
    are independently modeled. The cockpit is *suggested* with an overlay
    rather than boolean-cut from the hull.
    """
    p = _parameters(config or {})
    L = p["overall_length_ft"]
    WB = p["wheelbase_ft"]
    T = p["track_width_ft"]
    diameter = p["wheel_diameter_ft"]
    radius = diameter / 2.0
    tire_width = p["tire_width_ft"]
    max_width = p["body_max_width_ft"]
    height = p["body_max_height_ft"]
    bottom = p["body_bottom_ft"]
    body_color = p["body_palette_index"]
    tire_color = p["tire_palette_index"]
    spokes_color = p["spoke_palette_index"]
    cockpit_color = p["cockpit_palette_index"]
    metal_color = p["metal_palette_index"]

    # Section outline is in Y/Z for an X-axis loft. Each has the same
    # angular correspondence, avoiding accidentally twisted surfaces.
    section_data = [
        (0.0, 0.20, 0.32, bottom+0.70),
        (0.09, 0.67, 0.83, bottom+0.82),
        (0.25, 0.95, 0.95, bottom+height/2),
        (0.43, 1.00, 1.00, bottom+height/2),
        (0.61, 0.92, 0.87, bottom+height/2-0.05),
        (0.79, 0.65, 0.64, bottom+height/2-0.12),
        (0.94, 0.33, 0.36, bottom+0.58),
        (1.00, 0.10, 0.16, bottom+0.58),
    ]
    sections = [{
        "at": round(t*L, 5),
        "outline": _ellipse(0.0, zc, max_width*wf/2, height*hf/2),
    } for t, wf, hf, zc in section_data]
    ops = [{
        "type": "loft", "name": "streamlined_body", "axis": "x",
        "sections": sections, "color": body_color,
    }]

    # Dark raised insert implies an opening, but the main hull is *not*
    # perforated. Manual CAD cleanup is expected for a true cockpit.
    cx, cz = 0.44*L, bottom+height-0.03
    cockpit_ring = _ellipse(cx, 0, 0.078*L, 0.31*max_width)
    ops.append({
        "type": "extrude", "name": "cockpit_placeholder", "axis": "z",
        "outline": cockpit_ring, "from": round(cz, 5),
        "to": round(cz + 0.045, 5),
        "color": cockpit_color,
    })

    # Early rear-view mirror is a feature often associated with the 1911
    # Marmon Wasp, but exact mounting dimensions here are *invented*.
    mirror_x = cx + .09*L
    stalk_x = round(mirror_x, 5)
    stalk_ring = _ellipse(stalk_x, 0, .055, .05, 8)
    ops.append({
        "type": "extrude", "name": "mirror_stalk", "axis": "z",
        "outline": stalk_ring, "from": round(cz+.06, 5),
        "to": round(cz+0.90, 5), "color": metal_color,
    })
    ops.append({
        "type": "extrude", "name": "mirror_head", "axis": "z",
        "outline": _ellipse(stalk_x, 0, .20, .12, 10),
        "from": round(cz+0.89, 5),
        "to": round(cz+1.04, 5), "color": metal_color,
    })

    rear_x = (L-WB)/2
    front_x = (L+WB)/2
    for end, x in (("rear", rear_x), ("front", front_x)):
        for side, cy in (("left", -T/2), ("right", T/2)):
            abbr = ("r" if end == "rear" else "f") + (
                "l" if side == "left" else "r")
            # Axis Y cross-sections are in Z/X, thus the first coordinate
            # is elevation, the second is longitudinal position.
            ring = _ellipse(radius, x, radius, radius)
            inner, outer = cy - tire_width/2, cy + tire_width/2
            ops.append({
                "type": "loft", "name": f"tire_{abbr}", "axis": "y",
                "sections": [
                    {"at": round(inner, 5), "outline": ring},
                    {"at": round(outer, 5), "outline": ring},
                ], "color": tire_color,
            })
            # Spokes are separate shallow 3D prisms placed just beyond the
            # outside tire face, so users can recolor/replace them in CAD.
            outer_face = (outer + .035) if cy > 0 else (inner - .035)
            hub_from = (outer_face - .045) if cy > 0 else (outer_face - .045)
            hub_to = (outer_face + .045) if cy > 0 else (outer_face + .045)
            count = p["spokes_per_wheel"]
            for j in range(count):
                theta = 2 * pi * j / count
                ops.append({
                    "type": "extrude",
                    "name": f"spoke_{abbr}_{j:02d}",
                    "axis": "y",
                    "outline": _spoke_outline(
                        x, radius, radius*0.23, radius*0.83,
                        theta, max(radius*.08, .065)),
                    "from": round(hub_from, 5),
                    "to": round(hub_to, 5),
                    "color": spokes_color,
                })
            ops.append({
                "type": "extrude", "name": f"hub_{abbr}", "axis": "y",
                "outline": _ellipse(radius, x, radius*.20, radius*.20, 10),
                "from": round(hub_from-.02, 5),
                "to": round(hub_to+.02, 5),
                "color": metal_color,
            })

    recipe = {
        "schema": "icr2.n3.recipe.v1",
        "coordinate_scale": 6000,
        "description": (
            "Generic vintage single-seat open-wheel racing car blockout. "
            "Illustrative geometry, not a documented replica of the Marmon Wasp."
        ),
        "operations": ops,
    }
    # Stage 2's strict validator is authoritative. Never return a recipe
    # that cannot produce even its intermediate editable N3 source.
    generate_source(recipe)
    return recipe, {
        "template": "vintage_open_wheel",
        "parameters": p,
        "historical_verified": False,
        "limitations": [
            "Dimensions, contour and wheels are illustrative, not verified against period drawings.",
            "Cockpit is a dark overlay, not a cutout; edit it in CAD.",
            "Spokes, suspension, steering, engine and mirror are schematic placeholders.",
            "Palette indices are not guaranteed to appear as historically accurate colors.",
            "No BSP/LOD, shading/occlusion or in-game fidelity is guaranteed.",
        ],
    }
