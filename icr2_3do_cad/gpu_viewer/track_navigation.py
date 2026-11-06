"""Read-only TRK-guided GPU camera in raw Papyrus DLONG/DLAT coordinates.

Reuse icr2_core.trk geometry rather than duplicating its straight/curve
interpolation. The TRK provides the camera's ground XYZ and travel tangent;
the rendered .3D/.3DO mesh remains independent and completely unchanged.
"""
from __future__ import annotations

from dataclasses import dataclass
import math
from pathlib import Path
import sys

# Running gpu_viewer/main.py directly puts icr2_3do_cad, not the monorepo
# root, on sys.path. icr2_core is a sibling package in the same repository.
_REPO_ROOT = Path(__file__).resolve().parents[2]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from icr2_core.trk.trk_classes import TRKFile
from icr2_core.trk.trk_utils import dlong2sect, get_cline_pos, getxyz


UNITS_PER_FOOT = 6000.0
DEFAULT_EYE_HEIGHT_UNITS = 10000.0  # raw Papyrus units above TRK ground
DEFAULT_EYE_HEIGHT_FT = DEFAULT_EYE_HEIGHT_UNITS / UNITS_PER_FOOT
DEFAULT_LONG_STEP_FT = 10.0
DEFAULT_LAT_STEP_FT = 2.0


def find_matching_trk(model_path):
    """Find only <opened-model-stem>.TRK in the same directory.

    A folder can contain several unrelated TRK files; never substitute the
    first one. Case-fold the filename to support DOS names on Linux.
    """
    path = Path(model_path)
    folder = path.parent
    wanted = (path.stem + ".trk").casefold()
    direct = folder / (path.stem + ".trk")
    if direct.is_file():
        return direct
    if not folder.is_dir():
        return None
    for candidate in folder.iterdir():
        if candidate.is_file() and candidate.name.casefold() == wanted:
            return candidate
    return None


@dataclass(frozen=True)
class TrackPose:
    dlong: float
    dlat: float
    section: int
    ground: tuple[float, float, float]
    eye: tuple[float, float, float]
    azimuth: float
    elevation: float


class TrackNavigation:
    """TRK centerline driver; eye defaults to 10,000 Papyrus units above ground."""

    def __init__(self, path, trk, *, eye_height_ft=DEFAULT_EYE_HEIGHT_FT):
        self.path = Path(path)
        self.trk = trk
        if int(trk.num_sects) < 1 or int(trk.num_xsects) < 2:
            raise ValueError("TRK contains no usable sections or cross-sections")
        self.length = float(trk.trklength)
        if not math.isfinite(self.length) or self.length <= 0:
            raise ValueError("TRK has an invalid lap length")
        if any(float(sect.length) <= 0 or int(sect.type) not in (1, 2)
               for sect in trk.sects):
            raise ValueError("TRK contains an invalid straight/curve section")
        if int(trk.sects[0].start_dlong) != 0:
            raise ValueError("TRK DLONG origin is not zero")
        if not math.isfinite(eye_height_ft) or eye_height_ft < 0:
            raise ValueError("Camera height must be finite and nonnegative")
        self.centerline = get_cline_pos(trk)
        self.eye_height = eye_height_ft * UNITS_PER_FOOT
        self.dlong = 0.0
        self.dlat = 0.0
        # Verify the origin before activating a camera for this TRK.
        self.pose()

    @classmethod
    def from_file(cls, path):
        return cls(path, TRKFile.from_trk(path))

    def set_coordinates(self, dlong, dlat):
        if not math.isfinite(dlong) or not math.isfinite(dlat):
            raise ValueError("DLONG and DLAT must be finite")
        self.dlong = float(dlong) % self.length
        self.dlat = float(dlat)

    def move(self, *, forward_feet=0.0, left_feet=0.0):
        """Positive longitudinal is forward; positive lateral is left."""
        if not math.isfinite(forward_feet) or not math.isfinite(left_feet):
            raise ValueError("Movement must be finite")
        self.set_coordinates(
            self.dlong + forward_feet * UNITS_PER_FOOT,
            self.dlat + left_feet * UNITS_PER_FOOT,
        )
        return self.pose()

    def pose(self):
        dlong = self.dlong % self.length
        x, y, z = getxyz(self.trk, dlong, self.dlat, self.centerline)
        section, _ = dlong2sect(self.trk, dlong)
        segment = self.trk.sects[section]

        # Compute the true local tangent from the SAME TRK interpolation that
        # positions the camera. Stay within this section at boundaries, so a
        # discontinuity or lap wrap cannot reverse the view direction.
        begin = float(segment.start_dlong)
        end = min(begin + float(segment.length), self.length)
        delta = min(UNITS_PER_FOOT, (end - begin) / 4.0)
        if delta <= 0:
            raise ValueError("TRK section has no longitudinal extent")
        before = max(begin, dlong - delta)
        after = min(end - min(0.01, delta / 10), dlong + delta)
        if after <= before:
            before = begin
            after = min(end - min(0.01, delta / 10), begin + delta)
        x0, y0, z0 = getxyz(self.trk, before, 0.0, self.centerline)
        x1, y1, z1 = getxyz(self.trk, after, 0.0, self.centerline)
        dx, dy, dz = x1 - x0, y1 - y0, z1 - z0
        horizontal = math.hypot(dx, dy)
        if horizontal < 1e-8:
            raise ValueError("TRK has no usable forward tangent")
        # camera_view's forward XY is (-sin(azimuth), cos(azimuth)).
        azimuth = math.atan2(-dx, dy)
        # camera_view's forward Z is -sin(elevation).
        elevation = -math.atan2(dz, horizontal)
        eye = (float(x), float(y), float(z + self.eye_height))
        return TrackPose(dlong, self.dlat, section,
                         (float(x), float(y), float(z)),
                         eye, azimuth, elevation)
