import math

def isclockwise(start_angle, end_angle):
    diff = (end_angle - start_angle) % (2*math.pi)
    if diff == 0:
        return False  # It doesn't matter since there's no rotation, return False or True
    elif diff > math.pi:
        return True  # Clockwise
    else:
        return False  # Counterclockwise


def approx_curve_length(a, b, c, d, scale, num_segments=10000):
    def f(x):
        x_scaled = x / scale
        return a * x_scaled**3 + b * x_scaled**2 + c * x_scaled + d

    step = scale / num_segments
    total_length = 0.0

    x_prev = 0.0
    y_prev = f(x_prev)

    for i in range(1, num_segments + 1):
        x_cur = i * step
        y_cur = f(x_cur)

        dx = x_cur - x_prev
        dy = y_cur - y_prev
        total_length += math.hypot(dx, dy)

        x_prev = x_cur
        y_prev = y_cur

    return float(total_length)

def sg_ground_to_trk(sg_type):
    sg_to_trk_types = {
        0: 6,   # Grass
        1: 14,  # Dry grass
        2: 22,  # Dirt
        3: 30,  # Sand
        4: 38,  # Concrete
        5: 46,  # Asphalt
        6: 54,  # Paint (Curbing)
    }
    # If the type is not found, return None.
    return sg_to_trk_types.get(sg_type, None)

def convert_wall_fsect_type(sg_type1, sg_type2):
    # Map type1 to Armco (0) or Wall (1)
    type1_map = {8: 0, 7: 1}

    # Map type2 to No fence (0) or Fence (1)
    type2_map = {0: 0, 2: 1, 4: 0, 6: 1, 8: 0, 10: 1, 12: 0, 14: 1}
    
    # Get the mapped values from type1 and type2
    wall_type = type1_map.get(sg_type1, 0)
    fence_type = type2_map.get(sg_type2, 0)

    # Combine the mapped values to get the TRK type
    trk_wall_type = wall_type * 4 + fence_type * 2
    
    return trk_wall_type
