from __future__ import annotations

import math

Point = tuple[float, float]


def heading(a: Point, b: Point) -> Point | None:
    dx, dy = b[0] - a[0], b[1] - a[1]
    mag = math.hypot(dx, dy)
    return None if mag <= 0 else (dx / mag, dy / mag)


def points_close(a: Point, b: Point, tol: float = 1e-6) -> bool:
    return math.hypot(a[0] - b[0], a[1] - b[1]) <= tol


def directed_angle(start_angle: float, end_angle: float, orientation: float) -> float:
    angle = end_angle - start_angle
    if orientation > 0:
        while angle <= 0:
            angle += 2 * math.pi
    else:
        while angle >= 0:
            angle -= 2 * math.pi
    return angle


def curve_tangent(vec: Point, orientation: float) -> Point | None:
    vx, vy = vec
    mag = math.hypot(vx, vy)
    return None if mag <= 0 else (-orientation * vy / mag, orientation * vx / mag)


def is_perfectly_straight_chain(a: Point, b: Point, c: Point, tol: float = 1e-6) -> bool:
    ab = (b[0] - a[0], b[1] - a[1])
    ac = (c[0] - a[0], c[1] - a[1])
    if abs(ab[0] * ac[1] - ab[1] * ac[0]) > tol:
        return False
    dot = ab[0] * ac[0] + ab[1] * ac[1]
    if dot < -tol:
        return False
    ac_len_sq = ac[0] * ac[0] + ac[1] * ac[1]
    if dot - ac_len_sq > tol:
        return False
    return True
