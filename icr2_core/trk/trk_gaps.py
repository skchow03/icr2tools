import trk_utils
import trk_classes
import sys
import math

if len(sys.argv) != 2:
    print("Usage: python trkgaps.py <TRK file>")
    sys.exit(1)

trk_file = sys.argv[1]

trk = trk_classes.TRKFile.from_trk(trk_file)

cline = trk_utils.get_cline_pos(trk)

dist_list = []

print (f'{trk_file}')

for sect in range(-1,trk.num_sects-1):
    xy2 = trk_utils.getxyz(trk,trk.sects[sect].start_dlong + trk.sects[sect].length-1 ,0,cline)
    xy1 = trk_utils.sect2xy(trk, sect+1, cline)

    xy2 = (xy2[0],xy2[1])

    diffx = xy1[0] - xy2[0]
    diffy = xy1[1] - xy2[1]

    dist = math.dist(xy1, xy2)

    dist_list.append(dist)

    print (f'Sect {sect}/{sect+1}, gap {dist:.1f}')

print (f'Max gap {max(dist_list):.1f}')
print (f'Min gap {min(dist_list):.1f}')
print (f'Sum gaps {sum(dist_list):.1f}')
print (f'Track length: {trk.trklength}')