"""Lossless copy of the user's supplied 128x165 MARMON.mip atlas.

The original 28,846-byte binary is zlib-compressed and base64-encoded here
because source-review GitHub tools accept UTF-8 text files. Exact SHA256 is
verified before writing. This is user-supplied model artwork, not game stock.
"""
from __future__ import annotations
import base64
from hashlib import sha256
from pathlib import Path
import struct
import zlib

SOURCE_SHA256 = "46a6a8bd7e0cd969417710a51c10fa7be8bfa727dcb5935566f178ac12e06d39"
SOURCE_LENGTH = 28846
SOURCE_SIZE = (128, 165)
ATLAS_RECTS = {
    "radiator": (0, 0, 47, 42),
    "bonnet": (47, 0, 127, 72),
    "tail": (47, 74, 127, 127),
    "fin": (104, 131, 127, 154),
}
ZLIB_BASE64 = """
eNrtnbtu5LoZgB2kSJlHiIwNvMGeoS6FpTLF0QzyADEgzRukCfIGSZEn8Io0KdpZJ0AOgiCA21PmUVKmTJkiwOa/ULexZmzJlnwW
yx+jETnUr4/XnxRF03//3RnJH+D4Kxw/geMajt/jj58/f/43nH6J4eD+xa/Pzn4G7n+C+1e/OTv7Kbj/Be7vf8t6/wF3APf7Mbj/
C+4/gvtH4P4fuP8C7rARAbJhESybTetvr9Ijou5uhqJ6353cqTHlHwp/I8IoivBwAk78nb83J/k3z+LfnOKLsEODM+RzJ2JZvrt9
h+zoYnBaht8rYI7EMPG9Sxbhb8QhLXzED8VmKb54jG/50UEOLMAXT5BFGz+xBF/0q/dIyYMZaK8QC/AJKI6WfOSKR3DcFuJzSpVS
Qqhem6es72rnMvwWJytZlqWU0v0ATvDCR3WZsRxfVMVHSXhZOjx5UMTSfMxn2QnBKCacIcpVgkXzH2jEK5kvmK+Yv3z+hwiGCtdU
AOEKYjW+UGUJ2Vy68heYFXxelt8zv4L5kjsF0VTDsnShC/JFUw2b9DdGSWAlEKvwleQGWHY/cX1YiV8W3PzKHhobBURoQX6v6CvG
C+az+cFvIRavfx2/pGbAFZFNghCLpr/hs7j0iqbhi3aEIpa1/xwHrISc3z3DL1axPxuBjxqK67sQZA/X42PvjzVPNfa2sX9rpd/l
d8MXTUc04KvXlm74U7b8suUfjk2jhflhy+fyV8OnkyhaZPwXtfySBlwljjec9aMBQcmZv8j4L4565e+QxG+8Xf8fxcvYH9Gm36U4
7MyvpFGoK4ZF08/j3QZP7Y/Hv2W5YPrd8/6wnY09kEU0Q7AAv0FEo/Coxw8X4buZllF82MyIcEyW4UfROHtYAnzh6/M3Xdfbinvm
ZmfIfnRvogXtf3gw3zSI0IL9T68Eerwetcv9aLH5tx7jZH14df43H6bIN6/OfzdNPN/zPd/zv1Z+VVkWcDROZQ9EnfoZVG3vLhP5
Fgbjih7R8FBwGnjZp0Z8kn1q6JV2Ir8eE62tHhU7cI7qzih/u9u5G28rOt08T/Tr1L9tliTMra/idCLfpiAP2jntDL7Nkp0FRTrS
wE7i2yzex3FAEbDn+1n8/bmlO2HSt8F2Gv8ctPKYYj2TbzD9eb5LstxOT39wCd+7JJ3P11V2jpLiKVB6Il9tqRQe7HaX7OtZ9s9u
QXI+Ta3/aXBFSUhQ9uZV7O+k9ldR0wHDVz087Obwze7hAbRtd7N127/ZU95liL4KprZ/jYVmdc6nOfx6n+y29iHOQH2rJtZ/rQKo
tVlKNZiSMLf9p8kOvi8nt7/U2hxacJ5baMHmBfYniHOIxfk0PturNLMvtn/6IYjBlmbT0+9MN6Z/Fp+6DYwAdiV2avuPr2puh1CF
t/oN2v/WjQdcJ/7Oy7z8V/Py/1DX8yfJq79/+ML4vv55vud7vud7vud7vuf78a8f//r65/me7/me7/me7/me7/me7/me/9p8Ly9+
cchizLr5D8S8fWHNy6DSelX+ZRwkQcCv/uMAJa1X5DtmkNXa7tkZpGY9/jbBVRdpkliMCi7DiINsTX6Aa0V2jn+pdR0na/Jzqns7
jIVNd1tcSLNq+o3BJreLY+sa38p8bvW7JHBrJ02eJCvz7eVlnMTENzZduf5zs09w1RAtnAyCOetvXsZPgiTZ0uLJBExRmuuV+eku
xvZXgxVI0tzolfnQArj9A/5y9f6HhNs/pN6sPP7Q3+Y52R9Of7r2+KezvznWw93b8I3jJ46/av+TXOKCYeanW5J1+1+SmOs/LyJd
kU+NPiH78yZ8sD6IxDW/NmtkVftf419cmMZhbV1bY95q/M3V//6jfzLx4sWLl69Tuj+27/4AHhxF20cUf3LTZ5Y+7Bz+/foL9UWz
+ULvz957+jdP6Ivw8Y6BE/TF450Hwin6LgItfEM/TNHnPbaaXaj4btP4tEsJb+HmNs2Zxi8lfARuuaYm67tdwpTEiCjctmSyPuqV
0uUkbX40VZ82zaMEuE17punjbjMlbXmjQiXExPLn2o+7RmEmcoZM08c4Y763Gy6FsmhENn++K+nDzja0iFz5hbhrWSnbvWQm6fM+
X7TlTkn3eH79i/p71JVu9xwxUf/xjifP1x/bLCOa0n66TU96+39MK7/hHrGTyv/9xahcP1f/iFm/+8r1/1YbYyx+FcZJ0bnxXNd0
yRH9f9iqsAV8FRWcQAo6FXzC3znYHo2/zGqtKzn6duqTNkVh6A/xjumbxBp4WkzrcX2lZGS0ksfzT6Vplqm9GdeXEpTr9IS+oQfU
+kj8a6WNUqo6wVeq0PZY+iHpCNAn0v9tndn66kj8K6WyVGWn8s/o4qrIjuhDzkljTqTfUPkU9nj6tZaqXmr+gOp/cezt5qcu9Ij+
NZl+svD2sRRd6EL6L42/1/+69X399fpe/8vVX/hdAo+eqmIe3+yDQGkb4PccfRtUeWLklVHBLP26MkVgbKVlPEsfki4Dfo8xU18G
KYzfgriay1eQ/kTOXL9iLKa/zObWHxuYKrEv0E+UCuoyTtN0XvpVkijIwyCYm/+4AIMfRfwM5Jc/f9rMGtKeXGgfjcGv/vzAU+Hh
U+H4DyLGwwVOfdEM0DH9ko8T+iFuOn9MX0i3PT7ul2ax0lpLT9coEc08hfJEOAnODD6R/tHw/u6jY+G9orh9abh7K1vX/HKWpB9e
WLDcXS9YS7hsoC/hsboXbof7291Wsqh64QYuN4P7m6KvD3eX/ft/d3f3/m4g4B3oD4e7h+NbSP/gcZ68a4bjfEJtWiHvlPC3jv8L
ww/k4voOPsfDpapUWZwYRVhZF9WpXqqS6kT/UtRSnYqf3FcqO3H/u4u7i4uLH4T9Rct5Qx896g97fnHoV2C+cDKQPvXh9e9JOj+3
RKic2IfXrv/+zhZU7trNBx76f37dCodr84nC3fqTR342o6Z29uXJ6w/8jXz8OFzfYQ+ed6Uazl/e3t4+I78bu92cKarOPAP/z7TC
Gc/39/d4xqzA39Hgms5P06xF0xYecWBsj8f7a9C5uIeD8r697oP+oG/1u9t3t/8HvSWJ+A==
"""


def load_original_bytes():
    data = zlib.decompress(base64.b64decode("".join(ZLIB_BASE64.split())))
    if len(data) != SOURCE_LENGTH or sha256(data).hexdigest() != SOURCE_SHA256:
        raise ValueError("Uploaded MARMON.mip payload failed exact byte verification")
    length, _, width, height, levels, _ = struct.unpack_from("<6i", data)
    if (width, height) != SOURCE_SIZE or levels != 7 or length != len(data) - 4:
        raise ValueError("Unexpected uploaded MIP header")
    return data


def install_to(folder):
    target = Path(folder) / "MARMON.mip"
    data = load_original_bytes()
    if target.exists():
        if target.read_bytes() != data:
            raise FileExistsError(f"Existing {target} has different MIP bytes")
        return target
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(data)
    return target
