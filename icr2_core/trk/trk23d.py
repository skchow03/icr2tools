import math
import trk_classes
import csv2obj

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

#test_gaps(trk,0)


# wh = 19000   #wall height

# with open('walls.csv', 'w') as o:
#     o.write('x1,y1,z1,x2,y2,z2,x3,y3,z3,x4,y4,z4,color\n')
#     for sect in range(0, trk.num_sects-1):
#         # straight sections
#         if trk.sects[sect].type == 1:
#             start_dlong = trk.sects[sect].start_dlong
#             end_dlong = start_dlong + trk.sects[sect].length
#             for bound in range(0, trk.sects[sect].num_bounds):
#                 start_dlat = getbounddlat(trk, sect, 0, bound)
#                 end_dlat = getbounddlat(trk, sect+1, 0, bound)
#                 x1,y1,z1 = getxyz(trk,start_dlong,start_dlat)
#                 x2,y2,z2 = x1,y1,z1 + wh
#                 x4,y4,z4 = getxyz(trk,end_dlong,end_dlat)
#                 x3,y3,z3 = x4,y4,z4 + wh

# with open('points.csv', 'w') as o:
#     o.write('x,y\n')

#     for dlong in range(0, trk.trklength, 6000):
#         sect, subsect = dlong2sect(trk, dlong)
#         for bound in range(0, trk.sects[sect].num_bounds):
#             dlat = getbounddlat(trk, sect, subsect, bound)
#             x,y,z = getxyz(trk,dlong,dlat)
#             o.write('{},{}\n'.format(x,y))

#         for ground in range(0, trk.sects[sect].ground_fsects):
#             dlat = getgrounddlat(trk, sect, subsect, ground)
#             x,y,z = getxyz(trk,dlong,dlat)
#             o.write('{},{}\n'.format(x,y))

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


# # Determine sub sections
# subsect_lists = []

# subsects_hi = []
# subsects_med = []
# subsects_lo = []
# subsects_data = []

# straight_length = 350000
# curve_length = 100000           # Adjust based on radius?

# for sect in range(0, trk.num_sects):

#     # Determine number of HI subsects
#     if trk.sects[sect].type == 1:
#         num_subsects = get_subsects(trk.sects[sect].length, straight_length)
#     elif trk.sects[sect].type == 2:
#         num_subsects = get_subsects(trk.sects[sect].length, curve_length)
#     subsects_hi.append(num_subsects)

#     # Determine number of MED and LO subsects
#     if num_subsects == 1 or num_subsects == 2:
#         subsects_med.append(1)
#         subsects_lo.append(1)
#     else:
#         subsects_med.append(int(num_subsects/2))
#         subsects_lo.append(int(num_subsects/4))

#     # Determine number of subsection lists for each section
#     if num_subsects >= 1 and num_subsects <= 4:
#         subsect_lists.append(1)
#     else:
#         subsect_lists.append(
#             int(num_subsects / 4)
#         )

    



# # Name each sub section
# subsect_hi_names = []
# subsect_med_names = []
# subsect_lo_names = []
# subsect_list_names = []

# for sect in range(0, trk.num_sects):
#     for subsect in range(0, subsects_hi[sect]):
#         subsect_hi_names.append(
#             'sec{}_s{}_HI'.format(
#                 sect, subsect
#             )
#         )
#     for subsect in range(0, subsects_med[sect]):
#         subsect_med_names.append(
#             'sec{}_s{}_MED'.format(
#                 sect, subsect
#             )
#         )
#     for subsect in range(0, subsects_lo[sect]):
#         subsect_lo_names.append(
#             'sec{}_s{}_LO'.format(
#                 sect, subsect
#             )
#         )
#     for subsect_list in range(0, subsect_lists[sect]):
#         subsect_list_names.append(
#             'sec{}_l{}'.format(sect, subsect_list)
#         )


# print (subsect_list_names)

class TRK3D:
    """Creates an object that contains the x,y,z coordinates of the polygons for use in visualization or generating .3D file.
    Organized by section."""
    def __init__(self,trk):
        self.sects = []

        cline = get_cline_pos(trk)

        for sect in range(0, trk.num_sects):
           self.sects.append(self.Section())

        for sect in range(0, trk.num_sects):

            # Straight sections
            if trk.sects[sect].type == 1:
                start_dlong = trk.sects[sect].start_dlong
                if sect == trk.num_sects - 1:
                    end_dlong = trk.sects[0].start_dlong
                else:
                    end_dlong = trk.sects[sect+1].start_dlong
                
                num_bounds = trk.sects[sect].num_bounds
                left_dlat_start = trk.sects[sect].bound_dlat_start[num_bounds - 1]
                left_dlat_end = trk.sects[sect].bound_dlat_end[num_bounds - 1]
                for ground in range(trk.sects[sect].ground_fsects - 1, -1, -1):

                    
                    right_dlat_start = trk.sects[sect].ground_dlat_start[ground]
                    right_dlat_end = trk.sects[sect].ground_dlat_end[ground]
                    x_ls, y_ls, z_ls = getxyz(trk,start_dlong,left_dlat_start,cline)
                    x_le, y_le, z_le = getxyz(trk,end_dlong,left_dlat_end,cline)
                    x_re, y_re, z_re = getxyz(trk,end_dlong,right_dlat_end,cline)
                    x_rs, y_rs, z_rs = getxyz(trk,start_dlong,right_dlat_start,cline)

                    ground_type = trk.sects[sect].ground_type[ground]

                    poly_coords = (x_ls,y_ls,z_ls,x_le,y_le,z_le,x_re,y_re,z_re,x_rs,y_rs,z_rs)
                    self.sects[sect].polys.append(poly_coords)
                    self.sects[sect].poly_types.append(ground_type)

                    # the right side of current poly become left side of the next poly
                    left_dlat_start = right_dlat_start
                    left_dlat_end = right_dlat_end 
            
            # Curve section
            else:
                num_subsects = round(trk.sects[sect].length / 60000)
                if num_subsects == 0: num_subsects = 1

                # DLONG increment for each subsection
                subsect_length = trk.sects[sect].length / num_subsects

                # Initial start and end DLONG
                start_dlong = trk.sects[sect].start_dlong
                end_dlong = start_dlong + subsect_length

                num_bounds = trk.sects[sect].num_bounds

                for subsect in range(0, num_subsects):             

                    first_ground = True

                    for ground in range(trk.sects[sect].ground_fsects - 1, -1, -1): 

                        if first_ground:
                            # Left boundary DLAT start and end for whole section
                            left_dlat_sect_start = trk.sects[sect].bound_dlat_start[num_bounds - 1]
                            left_dlat_sect_end = trk.sects[sect].bound_dlat_end[num_bounds - 1]
                            
                            # Initial left DLAT end should be left start + increment
                            left_dlat_increment = (left_dlat_sect_end - left_dlat_sect_start) / num_subsects

                            left_dlat_start = left_dlat_sect_start + left_dlat_increment * subsect
                            left_dlat_end = left_dlat_sect_start + left_dlat_increment * (subsect + 1)

                            first_ground = False

                        # Get right ground DLATs for whole section
                        right_dlat_sect_start = trk.sects[sect].ground_dlat_start[ground]
                        right_dlat_sect_end = trk.sects[sect].ground_dlat_end[ground]

                        # Adjust both 
                        right_dlat_increm1 = (right_dlat_sect_end - right_dlat_sect_start) * (subsect)/num_subsects
                        right_dlat_increm2 = (right_dlat_sect_end - right_dlat_sect_start) * (subsect + 1)/num_subsects

                        right_dlat_start = right_dlat_sect_start + right_dlat_increm1
                        right_dlat_end = right_dlat_sect_start + right_dlat_increm2

                        x_ls, y_ls, z_ls = getxyz(trk,start_dlong,left_dlat_start,cline)
                        x_le, y_le, z_le = getxyz(trk,end_dlong,left_dlat_end,cline)
                        x_re, y_re, z_re = getxyz(trk,end_dlong,right_dlat_end,cline)
                        x_rs, y_rs, z_rs = getxyz(trk,start_dlong,right_dlat_start,cline)

                        ground_type = trk.sects[sect].ground_type[ground]
                        
                        poly_coords = (x_ls,y_ls,z_ls,x_le,y_le,z_le,x_re,y_re,z_re,x_rs,y_rs,z_rs)
                        self.sects[sect].polys.append(poly_coords)
                        self.sects[sect].poly_types.append(ground_type)

                        # the right side of current poly become left side of the next poly
                        left_dlat_start = right_dlat_start
                        left_dlat_end = right_dlat_end 

                    start_dlong = end_dlong
                    end_dlong += subsect_length

    class Section:
        def __init__(self):
            self.polys = []
            self.poly_types = []
            self.lines = []
            self.line_types = []

# filename = 'laguna.trk'
# trk = trk_classes.TRKFile.from_trk(filename)
# trk3d = TRK3D(trk)


# with open('ground.csv', 'w') as o:
#     o.write('sect,subsect,ground,x1,y1,z1,x2,y2,z2,x3,y3,z3,x4,y4,z4,color\n')

#     for sect in range(0, trk.num_sects):

#         # Straight sections
#         if trk.sects[sect].type == 1:
#             start_dlong = trk.sects[sect].start_dlong
#             if sect == trk.num_sects - 1:
#                 end_dlong = trk.sects[0].start_dlong
#             else:
#                 end_dlong = trk.sects[sect+1].start_dlong
            
#             num_bounds = trk.sects[sect].num_bounds
#             left_dlat_start = trk.sects[sect].bound_dlat_start[num_bounds - 1]
#             left_dlat_end = trk.sects[sect].bound_dlat_end[num_bounds - 1]
#             for ground in range(trk.sects[sect].ground_fsects - 1, -1, -1):

                
#                 right_dlat_start = trk.sects[sect].ground_dlat_start[ground]
#                 right_dlat_end = trk.sects[sect].ground_dlat_end[ground]
#                 x_ls, y_ls, z_ls = getxyz(trk,start_dlong,left_dlat_start)
#                 x_le, y_le, z_le = getxyz(trk,end_dlong,left_dlat_end)
#                 x_re, y_re, z_re = getxyz(trk,end_dlong,right_dlat_end)
#                 x_rs, y_rs, z_rs = getxyz(trk,start_dlong,right_dlat_start)

#                 ground_type = trk.sects[sect].ground_type[ground]
#                 color = color_from_ground_type(ground_type)

#                 o.write('{},{},{},{},{},{},{},{},{},{},{},{},{},{},{},"{}"\n'.format(
#                     sect,0,ground,x_ls,y_ls,z_ls,x_le,y_le,z_le,x_re,y_re,z_re,x_rs,y_rs,z_rs,color)
#                 )

#                 # the right side of current poly become left side of the next poly
#                 left_dlat_start = right_dlat_start
#                 left_dlat_end = right_dlat_end 
        
#         # Curve section
#         else:
#             num_subsects = round(trk.sects[sect].length / 60000)
#             if num_subsects == 0: num_subsects = 1

#             # DLONG increment for each subsection
#             subsect_length = trk.sects[sect].length / num_subsects

#             # Initial start and end DLONG
#             start_dlong = trk.sects[sect].start_dlong
#             end_dlong = start_dlong + subsect_length

#             num_bounds = trk.sects[sect].num_bounds

#             for subsect in range(0, num_subsects):             

#                 first_ground = True

#                 for ground in range(trk.sects[sect].ground_fsects - 1, -1, -1): 

#                     if first_ground:
#                         # Left boundary DLAT start and end for whole section
#                         left_dlat_sect_start = trk.sects[sect].bound_dlat_start[num_bounds - 1]
#                         left_dlat_sect_end = trk.sects[sect].bound_dlat_end[num_bounds - 1]
                        
#                         # Initial left DLAT end should be left start + increment
#                         left_dlat_increment = (left_dlat_sect_end - left_dlat_sect_start) / num_subsects

#                         left_dlat_start = left_dlat_sect_start + left_dlat_increment * subsect
#                         left_dlat_end = left_dlat_sect_start + left_dlat_increment * (subsect + 1)

#                         first_ground = False

#                     # Get right ground DLATs for whole section
#                     right_dlat_sect_start = trk.sects[sect].ground_dlat_start[ground]
#                     right_dlat_sect_end = trk.sects[sect].ground_dlat_end[ground]

#                     # Adjust both 
#                     right_dlat_increm1 = (right_dlat_sect_end - right_dlat_sect_start) * (subsect)/num_subsects
#                     right_dlat_increm2 = (right_dlat_sect_end - right_dlat_sect_start) * (subsect + 1)/num_subsects

#                     right_dlat_start = right_dlat_sect_start + right_dlat_increm1
#                     right_dlat_end = right_dlat_sect_start + right_dlat_increm2

#                     x_ls, y_ls, z_ls = getxyz(trk,start_dlong,left_dlat_start)
#                     x_le, y_le, z_le = getxyz(trk,end_dlong,left_dlat_end)
#                     x_re, y_re, z_re = getxyz(trk,end_dlong,right_dlat_end)
#                     x_rs, y_rs, z_rs = getxyz(trk,start_dlong,right_dlat_start)

#                     ground_type = trk.sects[sect].ground_type[ground]
#                     color = color_from_ground_type(ground_type)

#                     o.write('{},{},{},{},{},{},{},{},{},{},{},{},{},{},{},"{}"\n'.format(
#                         sect,subsect,ground,x_ls,y_ls,z_ls,x_le,y_le,z_le,x_re,y_re,z_re,x_rs,y_rs,z_rs,color)
#                     )

#                     # the right side of current poly become left side of the next poly
#                     left_dlat_start = right_dlat_start
#                     left_dlat_end = right_dlat_end 

#                 start_dlong = end_dlong
#                 end_dlong += subsect_length

    # #walls
    # for sect in range(0, trk.num_sects-1):
    #     # straight sections
    #     if trk.sects[sect].type == 1:
    #         start_dlong = trk.sects[sect].start_dlong
    #         end_dlong = start_dlong + trk.sects[sect].length
    #         for bound in range(0, trk.sects[sect].num_bounds):
    #             print("sect {} bound {}".format(sect,bound))
    #             start_dlat = trk.sects[sect].bound_dlat_start[bound]
    #             end_dlat = trk.sects[sect].bound_dlat_end[bound]
    #             x1,y1,z1 = getxyz(trk,start_dlong,start_dlat)
    #             x2,y2,z2 = x1,y1,z1 + wh
    #             x4,y4,z4 = getxyz(trk,end_dlong,end_dlat)
    #             x3,y3,z3 = x4,y4,z4 + wh
    #             color = "white"
    #             o.write('{},{},{},{},{},{},{},{},{},{},{},{},"{}"\n'.format(
    #                     x1,y1,z1,x2,y2,z2,x3,y3,z3,x4,y4,z4,color)
    #                 )

#csv2obj.csv2obj('ground.csv','laguna.obj')
