"""Banking/crossfall sampled from Papyrus TRK cross-section elevations.

TRK stores elevation as a cubic along each track section for every fixed-DLAT
cross-section.  Adjacent cross-sections therefore describe the road's lateral
slope at a given DLONG.  Positive angle here means the road slopes downhill
toward positive DLAT (the driver's left).
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from icr2_core.trk.trk_utils import dlong2sect


@dataclass(frozen=True)
class TrkBankingProfile:
    """Precomputed banking at fixed DLONG stations for many candidate LP lines.

    slopes_degrees[i, j] is the left-down bank angle between cross-sections
    j and j+1 at station i.  A candidate's DLAT picks the appropriate
    cross-section interval instead of assuming the whole road is one plane.
    """

    xsect_dlats: np.ndarray
    slopes_degrees: np.ndarray

    def at_dlats(self, dlats) -> np.ndarray:
        lateral = np.asarray(dlats, dtype=float)
        if lateral.ndim != 1 or len(lateral) != len(self.slopes_degrees):
            raise ValueError("Candidate DLATs must match the TRK banking stations.")
        if self.slopes_degrees.shape[1] == 0:
            return np.zeros(len(lateral), dtype=float)
        intervals = np.clip(
            np.searchsorted(self.xsect_dlats, lateral, side="right") - 1,
            0, self.slopes_degrees.shape[1] - 1,
        )
        return self.slopes_degrees[np.arange(len(lateral)), intervals]


def build_trk_banking_profile(trk, dlongs) -> TrkBankingProfile:
    """Sample the actual TRK cross-section height polynomials at each DLONG.

    Both elevations and DLATs are stored in the same TRK distance units, so
    their ratio is dimensionless.  No assumed oval banking angle is needed.
    Tracks without usable elevation cross-sections are treated as flat.
    """
    dl = np.asarray(dlongs, dtype=float)
    xsects = np.asarray(
        trk.xsect_dlats[:int(trk.num_xsects)], dtype=float,
    )
    if len(xsects) < 2 or np.any(np.diff(xsects) <= 0):
        return TrkBankingProfile(
            xsects, np.zeros((len(dl), 0), dtype=float),
        )

    angles = np.zeros((len(dl), len(xsects) - 1), dtype=float)
    spacing = np.diff(xsects)
    for i, dlong in enumerate(dl):
        sect_index, fraction = dlong2sect(trk, float(dlong))
        sect = trk.sects[sect_index]
        t = float(np.clip(fraction, 0.0, 1.0))
        heights = (
            np.asarray(sect.grade1[:len(xsects)], dtype=float) * t**3
            + np.asarray(sect.grade2[:len(xsects)], dtype=float) * t**2
            + np.asarray(sect.grade3[:len(xsects)], dtype=float) * t
            + np.asarray(sect.alt[:len(xsects)], dtype=float)
        )
        if len(heights) != len(xsects):
            raise ValueError("TRK cross-section elevation data is incomplete.")
        # Positive DLAT is left. When elevation falls toward the left, the
        # road is banked into a left turn (positive XY curvature).
        angles[i] = np.degrees(np.arctan(-np.diff(heights) / spacing))

    if not np.all(np.isfinite(angles)):
        raise ValueError("TRK contains nonfinite cross-section banking.")
    return TrkBankingProfile(xsects, angles)
