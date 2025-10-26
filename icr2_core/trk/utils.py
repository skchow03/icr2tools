import numpy as np
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
    # Define the function with scaled x
    def f(x):
        x_scaled = x / scale
        return a * x_scaled**3 + b * x_scaled**2 + c * x_scaled + d

    # Generate x values
    x_values = np.linspace(0, scale, num_segments + 1)

    # Calculate the y values
    y_values = f(x_values)

    # Calculate the differences between consecutive x and y values
    delta_x = np.diff(x_values)
    delta_y = np.diff(y_values)

    # Calculate the lengths of the line segments
    segment_lengths = np.sqrt(delta_x**2 + delta_y**2)

    # Sum the segment lengths to get the total length
    approx_length = np.sum(segment_lengths)

    return approx_length

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