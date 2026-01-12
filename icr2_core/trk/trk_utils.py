import math

def distance_3d(coord1, coord2):
    x1, y1, z1 = coord1
    x2, y2, z2 = coord2
    return math.sqrt((x2 - x1) ** 2 + (y2 - y1) ** 2 + (z2 - z1) ** 2)


def get_cline_pos(trk):
    """Calculates the centerline absolute position (x,y) for straight sections
    and radius for curve sections. Returns a list of pos1, pos2 tuples like
    xsect data
    """
    for xsect in range(0, trk.num_xsects):
        if trk.xsect_dlats[xsect] > 0:
            left_xsect = xsect
            right_xsect = xsect - 1
            break

    right_dlat = trk.xsect_dlats[right_xsect]
    left_dlat = trk.xsect_dlats[left_xsect]
    cline_adj = -right_dlat/(left_dlat - right_dlat)
    cline = []
    for sect in range(0, trk.num_sects):
        r_x = trk.sects[sect].pos1[right_xsect]
        r_y = trk.sects[sect].pos2[right_xsect]
        l_x = trk.sects[sect].pos1[left_xsect]
        l_y = trk.sects[sect].pos2[left_xsect]

        c_x = r_x + cline_adj * (l_x - r_x)
        c_y = r_y + cline_adj * (l_y - r_y)

        cline.append((c_x, c_y))
    return cline

def dlong2sect(trk, dlong):
    """Given a DLONG, return the section number and fraction of the section"""
    for sect in range(0, trk.num_sects):

        if sect < trk.num_sects - 1:
            if trk.sects[sect].start_dlong <= dlong < trk.sects[sect+1].start_dlong:
                subsect = (dlong - trk.sects[sect].start_dlong)/trk.sects[sect].length
                return sect, subsect
        else:
            subsect = (dlong - trk.sects[sect].start_dlong)/trk.sects[sect].length
            return sect, subsect

def heading2rad(heading):
    return (heading / 2**31) * math.pi

def sect2xy(trk,sect,cline):
    """Given sect, get the starting x,y coordinates only"""
    
    if trk.sects[sect].type == 1:
        return cline[sect]
    elif trk.sects[sect].type == 2:
        rad = cline[sect][0]

        cx = trk.sects[sect].ang1
        cy = trk.sects[sect].ang2

        angle = heading2rad(trk.sects[sect].heading) - math.pi/2
        vx = rad * math.cos(angle)
        vy = rad * math.sin(angle)

        return (cx+vx, cy+vy)

def getxyz(trk,dlong,dlat,cline):
    """Given DLONG and DLAT, get the x,y,z coordinates"""

    # First get x, y of the centerline at that DLONG. Store in clx and cly,
    sect, subsect = dlong2sect(trk,dlong)

    if trk.sects[sect].type == 1:
        start_x, start_y = sect2xy(trk,sect,cline)

        if sect == trk.num_sects - 1:
            end_x, end_y = sect2xy(trk,0,cline)
        else:
            end_x, end_y = sect2xy(trk,sect + 1,cline)

        vx = (end_x - start_x) * subsect
        vy = (end_y - start_y) * subsect
        
        clx = start_x + vx
        cly = start_y + vy        

        # Get angle 90 degrees to the left, and walk DLAT units towards it
        angle = heading2rad(trk.sects[sect].heading) + math.pi/2
        vx1 = dlat * math.cos(angle)
        vy1 = dlat * math.sin(angle)

        z = get_alt(trk, sect, subsect, dlat)

        return clx + vx1, cly + vy1, z

    elif trk.sects[sect].type == 2:
        rad = cline[sect][0]

        rad -= dlat

        start_heading = heading2rad(trk.sects[sect].heading) - math.pi/2

        if sect == trk.num_sects - 1:
            end_heading = heading2rad(trk.sects[0].heading) - math.pi/2
        else:
            end_heading = heading2rad(trk.sects[sect + 1].heading) - math.pi/2

        arc_length = end_heading - start_heading
        arc_length = ((arc_length + math.pi) % (2 * math.pi)) - math.pi

        subsect_heading = start_heading + arc_length * subsect
        vx = rad * math.cos(subsect_heading)
        vy = rad * math.sin(subsect_heading)
        cx = trk.sects[sect].ang1
        cy = trk.sects[sect].ang2

        clx = cx + vx
        cly = cy + vy

        z = get_alt(trk, sect, subsect, dlat)

    return clx, cly, z

def getbounddlat(trk,sect,subsect,bound):
    dlat_start = trk.sects[sect].bound_dlat_start[bound]
    dlat_end = trk.sects[sect].bound_dlat_end[bound]
    dlat_change = dlat_end - dlat_start
    dlat_change = dlat_change * subsect
    return dlat_start + dlat_change

def getgrounddlat(trk,sect,subsect,ground):
    dlat_start = trk.sects[sect].ground_dlat_start[ground]
    dlat_end = trk.sects[sect].ground_dlat_end[ground]
    dlat_change = dlat_end - dlat_start
    dlat_change = dlat_change * subsect
    return dlat_start + dlat_change

def color_from_ground_type(ground):
    """Return a display colour name for a TRK ground type."""

    mapping = {
        (0, 2, 4, 6): "#2e7d32",  # Grass
        (8, 10, 12, 14): "#d8c091",  # Dry grass
        (16, 18, 20, 22): "#8d6e63",  # Dirt
        (24, 26, 28, 30): "#c9a26b",  # Sand
        (32, 34, 36, 38): "#b0b0b0",  # Concrete
        (40, 42, 44, 46): "#9e9e9e",  # Asphalt
        (48, 50, 52, 54): "#ffffff",  # Paint / curbing
    }
    for values, color in mapping.items():
        if ground in values:
            return color
    return "#808080"


def get_alt(trk, sect, subsect, dlat):
    # determine which two xsects the dlat is between
    # or if dlat is outside the range of xsects then go with
    # the closest xsect
    
    #print ('Get altitude for sect {} subsect {} dlat {}'.format(sect,subsect,dlat))

    #print ('Check if DLAT is less than {} and greater than {}'.format(trk.xsect_dlats[0],trk.xsect_dlats[trk.num_xsects - 1]))
    if dlat <= trk.xsect_dlats[0]:
        left_xsect_id = 0
        right_xsect_id = 0
    elif dlat >= trk.xsect_dlats[trk.num_xsects - 1]:
        left_xsect_id = trk.num_xsects - 1
        right_xsect_id = trk.num_xsects - 1
    else:
        for xsect in range(0, trk.num_xsects-1):
            if trk.xsect_dlats[xsect] <= dlat < trk.xsect_dlats[xsect + 1]:
                left_xsect_id = xsect + 1
                right_xsect_id = xsect

    #print ('Left xsect {} right {}'.format(left_xsect_id, right_xsect_id))

    # calculate alt at left xsect at subsection using cubic function
    left_xsect_data_index = sect * trk.num_xsects + left_xsect_id
    left_xsect_data = trk.xsect_data[left_xsect_data_index]
    g1 = left_xsect_data[0]
    g2 = left_xsect_data[1]
    g3 = left_xsect_data[2]
    g4 = left_xsect_data[3]
    left_alt = g1 * subsect**3 + g2 * subsect**2 + g3 * subsect + g4

    # calculate alt at right xsect at subsection using cubic function
    right_xsect_data_index = sect * trk.num_xsects + right_xsect_id
    right_xsect_data = trk.xsect_data[right_xsect_data_index]
    g1 = right_xsect_data[0]
    g2 = right_xsect_data[1]
    g3 = right_xsect_data[2]
    g4 = right_xsect_data[3]
    right_alt = g1 * subsect**3 + g2 * subsect**2 + g3 * subsect + g4

    # interpolate between left and right xsect
    left_xsect_dlat = trk.xsect_dlats[left_xsect_id]
    right_xsect_dlat = trk.xsect_dlats[right_xsect_id]
    dlat_distance = left_xsect_dlat - right_xsect_dlat

    if dlat_distance == 0:
        final_alt = right_alt
    else:
        dlat_to_right = dlat - right_xsect_dlat
        distance_percent = dlat_to_right / dlat_distance
        alt_change = left_alt - right_alt
        final_alt = right_alt + alt_change * distance_percent

    # return alt
    #print (final_alt)
    return final_alt

def test_gaps(trk,dlat):
    """Compare ending DLONG of each section with starting DLONG of next section"""

    for sect in range(0,trk.num_sects):
        dlongtest = trk.sects[sect].start_dlong
        if dlongtest == 0:
            x1,y1,z1 = getxyz(trk,trk.trklength,dlat)
        else:
            x1,y1,z1 = getxyz(trk,dlongtest-1,dlat)
        x2,y2,z2 = getxyz(trk,dlongtest,dlat)
        distance = distance_3d((x1,y1,z1),(x2,y2,z2))
        print (sect,dlongtest, distance)

def get_subsects(sect_length, min_length):
    """Determines how many subsections based on section length and minimum length needed"""
    cur_div = 1
    while True:
        div_length = sect_length / cur_div
        if div_length <= min_length:
            return cur_div
        else:
            if cur_div == 1:
                cur_div += 1
            elif cur_div == 2:
                cur_div += 2
            else:
                cur_div += 4
