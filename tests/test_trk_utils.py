from types import SimpleNamespace
import warnings

from icr2_core.trk.trk_utils import get_cline_pos


class _FixedWidthScalar(int):
    """Stand-in for a scalar dtype that warns before overflowing subtraction."""

    def __sub__(self, other):
        warnings.warn("overflow encountered in scalar subtract", RuntimeWarning)
        return super().__sub__(other)


def test_get_cline_pos_avoids_fixed_width_coordinate_overflow():
    section = SimpleNamespace(
        pos1=[_FixedWidthScalar(2_000_000_000), _FixedWidthScalar(-2_000_000_000)],
        pos2=[_FixedWidthScalar(2_000_000_000), _FixedWidthScalar(-2_000_000_000)],
    )
    trk = SimpleNamespace(
        num_xsects=2,
        num_sects=1,
        xsect_dlats=[_FixedWidthScalar(-6_000), _FixedWidthScalar(6_000)],
        sects=[section],
    )

    with warnings.catch_warnings():
        warnings.simplefilter("error", RuntimeWarning)
        centerline = get_cline_pos(trk)

    assert centerline == [(0.0, 0.0)]
