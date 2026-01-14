import numpy as np
from rpy import Rpy
from trk import Trk
import math
import argparse
from lpcalc import *

def get_lap_frames(rpy, car_id):
    """Identify when a car crosses the finish line and return the lap starting
    records in a list. If DLONG decreases more than 1000000 in one frame, should
    be safe to assume lap has restarted. Sometimes a car driven normally can
    go backwards in DLONG such as if it crashes, therefore this is a way to
    avoid falsely detecting those as new laps.
    """
    num_recs = len(rpy.cars[car_id].dlong)
    lap_recs = []

    for i in range(0, num_recs):
        if i > 0 and i < num_recs:
            if rpy.cars[car_id].dlong[i] < (rpy.cars[car_id].dlong[i-1]-1000000):
                lap_recs.append(i)
    return lap_recs

parser = argparse.ArgumentParser(description='ICR2 .RPY to .CSV converter v2.4')
parser.add_argument('RPY_file', help='input .rpy file')
parser.add_argument('TRK_file', help='input .trk file')
parser.add_argument('CSV_file', help='output .csv or .txt file')
parser.add_argument('--table', help='Output tables for debugging', action="store_true")
parser.add_argument('--lap', help='Specify lap to extract', type=int)
parser.add_argument('--trafo', help='Output Trafo txt', action="store_true")

args = parser.parse_args()

trkfile = args.TRK_file
rpyfile = args.RPY_file
output_csv = args.CSV_file
if not args.lap:
    extract_lap = 0
else:
    extract_lap = args.lap

print ('Loading replay file {}...'.format(rpyfile))
rpy = Rpy(rpyfile)
lap_frames = get_lap_frames(rpy, 1)
print ('Laps at {}'.format(lap_frames))

# Extract full lap with a 2 frame buffer before and after lap
print ('Extracting lap {} at frame {}...'.format(extract_lap, lap_frames[extract_lap]))
start_frame = lap_frames[extract_lap] - 2
end_frame = lap_frames[extract_lap + 1] + 2
player_rpy = rpy.cars[1]
frames = end_frame - start_frame
print ('done')

print ('Loading track file {}...'.format(trkfile))
trk = Trk(trkfile)
print ('done')

# Dennis Table 1 (row = replay frame) ======================================
print ('Calculating Table 1...')
t1_dlong = []
t1_dlat = []
t1_radius = []
t1_prev_rw_len = [0]        # Pre-populate non-calculable number
t1_next_rw_len = []
t1_rw_speed = [0]           # Pre-populate non-calculable number
t1_sect = []
t1_sect_type = []

for i in range(start_frame, end_frame):
    t1_dlong.append(int(player_rpy.dlong[i]))
    t1_dlat.append(int(player_rpy.dlat[i]))
    cur_sect = get_trk_sect_id(trk, player_rpy.dlong[i])
    t1_sect.append(cur_sect)
    t1_sect_type.append(trk.sects[cur_sect].type)

# Make pre-start DLONGs negative numbers and post-end DLONGs continuing
# from track length
t1_dlong[0] = t1_dlong[0] - trk.trackLength
t1_dlong[1] = t1_dlong[1] - trk.trackLength
t1_dlong[-1] = t1_dlong[-1] + trk.trackLength
t1_dlong[-2] = t1_dlong[-2] + trk.trackLength

# Calculate radius column (Column G of Dennis spreadsheet)
for i in range(0, frames):
    cur_frame = i
    if i == frames - 1:
        next_frame = 4
    else:
        next_frame = i + 1
    if t1_sect_type[cur_frame] == 1 and t1_sect_type[next_frame] == 1:
        t1_radius.append(0)
    elif t1_sect_type[cur_frame] == 2 and t1_sect_type[next_frame] == 2:

        # If the next frame is in a new section but going from curve to curve,
        # calculate fictitious radius. Otherwise look up the radius.
        if t1_sect[cur_frame] == t1_sect[next_frame]:
            t1_radius.append(get_trk_sect_radius(trk, t1_sect[cur_frame]))
        else:
            # Dennis curve to curve formula
            dlongc = trk.sects[t1_sect[next_frame]].dlong
            dlong0 = t1_dlong[cur_frame]
            r0 = get_trk_sect_radius(trk, t1_sect[cur_frame])
            dlong1 = t1_dlong[next_frame]
            r1 = get_trk_sect_radius(trk, t1_sect[next_frame])
            t1_radius.append(get_fake_radius3(dlongc, dlong0, r0, dlong1, r1))

    elif t1_sect_type[cur_frame] == 1 and t1_sect_type[next_frame] == 2:
        t1_radius.append(get_fake_radius1(
            get_trk_sect_radius(trk, t1_sect[next_frame]),
            t1_dlong[next_frame],
            trk.sects[t1_sect[next_frame]].dlong,
            t1_dlong[cur_frame]))
        t1_sect_type[cur_frame] = 2
    elif t1_sect_type[cur_frame] == 2 and t1_sect_type[next_frame] == 1:
        t1_radius.append(get_fake_radius2(
            get_trk_sect_radius(trk, t1_sect[cur_frame - 1]),
            trk.sects[t1_sect[next_frame]].dlong,
            t1_dlong[cur_frame],
            t1_dlong[next_frame]))
    else:
        print ('Did not calculate T1 radius at {}'.format(i))

# Calculate previous RW lengths
for i in range(1, frames):
    cur = i
    prev = i - 1
    if i == frames - 1:
        next = 4
    else:
        next = i + 1

    if t1_sect_type[prev] == 1:
        a = (t1_dlong[cur] - t1_dlong[prev]) ** 2
        b = (t1_dlat[cur] - t1_dlat[prev]) ** 2
        t1_prev_rw_len.append(math.sqrt(a + b))
    else:
        a = (2 * t1_radius[prev] - t1_dlat[cur] - t1_dlat[prev]) \
            * (t1_dlong[cur] - t1_dlong[prev]) / (2 * int(t1_radius[prev]))
        b = t1_dlat[cur] - t1_dlat[prev]
        t1_prev_rw_len.append(math.sqrt(a ** 2 + b ** 2))

# Calculate next RW length
for i in range(0, frames):
    prev = i - 1
    if i == frames - 1:
        next = 4
    else:
        next = i + 1
    t1_next_rw_len.append(t1_prev_rw_len[next])

# Calculate RW speed
for i in range(1, frames):
    t1_rw_speed.append((t1_prev_rw_len[i] + t1_next_rw_len[i]) / 2 \
                       * 54000/31680000)

print ('done')

# Output table 1
if args.table:
    print ('Output table1.csv...')
    with open('table1.csv', 'w') as o:
        o.write("Frame,Section Type,DLONG,DLAT,Radius,Previous RW length,Next RW length,RW speed\n")
        for i in range(0, frames):
            o.write("{}, {},{},{},{},{},{},{}\n".format(i, t1_sect_type[i],
                                                        t1_dlong[i], t1_dlat[i],
                                                        t1_radius[i],
                                                        t1_prev_rw_len[i],
                                                        t1_next_rw_len[i],
                                                        t1_rw_speed[i]))

# Table 2 ===================================================================
num_lp_recs = (trk.trackLength // 65536) + 2
print ('Track length: {}  Number of LP records: {}'.format(trk.trackLength,
                                                           num_lp_recs))
print ('Calculating Table 2...')

lp_dlong = []
lp_dlat = []
lp_rw_speed = []

for i in range(0, num_lp_recs):
    cur_dlong = i * 65536
    if i == num_lp_recs - 1:
        cur_dlong = trk.trackLength

    lp_dlong.append(cur_dlong)

    for j in range(0, len(t1_dlong) - 1):
        if t1_dlong[j] <= cur_dlong < t1_dlong[j + 1]:
            ref_index = j

    cur_dlat = ((cur_dlong - t1_dlong[ref_index]) \
                * t1_dlat[ref_index + 1] \
                + (t1_dlong[ref_index + 1] - cur_dlong) \
                * t1_dlat[ref_index]) \
                / (t1_dlong[ref_index + 1] - t1_dlong[ref_index])
    lp_dlat.append(cur_dlat)

    cur_rw_speed = ((cur_dlong - t1_dlong[ref_index]) \
                * t1_rw_speed[ref_index + 1] \
                + (t1_dlong[ref_index + 1] - cur_dlong) \
                * t1_rw_speed[ref_index]) \
                / (t1_dlong[ref_index + 1] - t1_dlong[ref_index])
    lp_rw_speed.append(cur_rw_speed)

# Output table 2
if args.table:
    print ('Output table2.csv...')

    with open('table2.csv', 'w') as o:
        o.write("Record,DLONG,DLAT,RW speed (LP)\n")
        for i in range(0, num_lp_recs):
            o.write("{},{},{},{}\n".format(i+1, lp_dlong[i],
                                           lp_dlat[i],
                                           lp_rw_speed[i]))

if args.trafo:
    print ('Output data to Trafo txt format {}...'.format(output_csv))
    with open(output_csv, 'w') as o:
        o.write("No\t Speed[mph]\t Coriolis[?]\t Position[ft]\n")
        for i in range(0, num_lp_recs):
            o.write("{}\t {}\t {}\t {}\n".format(i+1, round(lp_rw_speed[i],2), 0, round(lp_dlat[i] / 6000, 2)))

else:
    print ('Output data to csv format {}...'.format(output_csv))
    with open(output_csv, 'w') as o:
        o.write("Record,DLONG,RW Speed,DLAT\n")
        for i in range(0, num_lp_recs):
            o.write("{},{},{},{}\n".format(i+1, lp_dlong[i], lp_rw_speed[i], lp_dlat[i]))
