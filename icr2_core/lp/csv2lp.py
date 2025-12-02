import numpy as np
from rpy import Rpy
from trk import Trk
import math
import argparse
from lpcalc import *

def load_csv(csv_file):
    print ('Loading csv file {}'.format(csv_file))
    with open(csv_file,'r') as f:
        data = f.readlines()
        data = data[1:]
        num_lp_recs = len(data)
        print ('Reading {} - {} records'.format(csv_file, num_lp_recs))
        lp_rw_speed = []
        lp_dlat = []
        for i in range(0, num_lp_recs):
            data[i] = data[i].strip().split(',')
            lp_rw_speed.append(float(data[i][2]))
            lp_dlat.append(float(data[i][3]))

        lp_dlong = []
        for i in range(0, num_lp_recs):
            cur_dlong = i * 65536
            if i == num_lp_recs - 1:
                cur_dlong = trk.trackLength
            lp_dlong.append(cur_dlong)
    return num_lp_recs, lp_rw_speed, lp_dlat, lp_dlong

def load_trafo(txt_file):
    print ('Loading txt file {}'.format(txt_file))
    with open(txt_file,'r') as f:
        data = f.readlines()
        data = data[1:]

    lp_rw_speed = []
    lp_dlat = []
    for i in range(0, len(data)):
        row = data[i].split()
        if len(row) == 0:
            break
        else:
            lp_rw_speed.append(float(row[1]))
            lp_dlat.append(float(row[3]) * 6000)

    num_lp_recs = len(lp_dlat)
    lp_dlong = []
    for i in range(0, num_lp_recs):
        cur_dlong = i * 65536
        if i == num_lp_recs - 1:
            cur_dlong = trk.trackLength
        lp_dlong.append(cur_dlong)
    return num_lp_recs, lp_rw_speed, lp_dlat, lp_dlong

parser = argparse.ArgumentParser(description='ICR2 .CSV to .LP converter v2.5')
parser.add_argument('CSV_file', help='input .csv or .txt file')
parser.add_argument('TRK_file', help='input .trk file')
parser.add_argument('Output_file', help='output file name')
parser.add_argument('--table', help='Output table for debugging', action="store_true")
parser.add_argument('--trafo', help='Input file is Trafo format' , action="store_true")

args = parser.parse_args()

input_file = args.CSV_file
output_file = args.Output_file
trkfile = args.TRK_file

print ('Loading track file {}'.format(trkfile))
trk = Trk(trkfile)

if args.trafo:
    num_lp_recs, lp_rw_speed, lp_dlat, lp_dlong = load_trafo(input_file)
else:
    num_lp_recs, lp_rw_speed, lp_dlat, lp_dlong = load_csv(input_file)

# Extend LP records by 2 which is needed for calculations in Table 3. Creates
# 2 LP records before the starting LP record and 2 after. Assumes 65536 length
# for the pre-LP records and length of last true LP record for the post-LP
# records.

print ('Extending start and end of LP records...')
lp_dlong = [trk.trackLength - 65536 * 2, trk.trackLength - 65536] \
           + lp_dlong \
           + [trk.trackLength - lp_dlong[-2],
             (trk.trackLength - lp_dlong[-2]) * 2]

dlat_start_change = lp_dlat[1] - lp_dlat[0]
dlat_end_change = lp_dlat[-1] - lp_dlat[-2]
lp_dlat = [lp_dlat[0] - dlat_start_change * 2, lp_dlat[0] - dlat_start_change] \
          + lp_dlat \
          + [lp_dlat[-1] + dlat_end_change, lp_dlat[-1] + dlat_end_change * 2]

speed_start_change = lp_rw_speed[1] - lp_rw_speed[0]
speed_end_change = lp_rw_speed[-1] - lp_rw_speed[-2]
lp_rw_speed = [lp_rw_speed[0] - speed_start_change * 2, lp_rw_speed[0] - speed_start_change] \
              + lp_rw_speed \
              + [lp_rw_speed[-1] + speed_end_change, lp_rw_speed[-1] + speed_end_change * 2]

num_lp_recs2 = num_lp_recs + 4

# Table 3 ===================================================================
print ('Calculating Table 3')
t3_next_rw_len = []
t3_prev_rw_len = []
t3_next_lp_len = []
t3_prev_lp_len = [0]
t3_radius = []
t3_sect = []
t3_sect_type = []
lp_speed = [0]
coriolis1 = [0]
coriolis2 = [0]

# Get section type
for i in range(0, num_lp_recs2):
    t3_sect_type.append(get_trk_sect_type(trk, lp_dlong[i]))
    t3_sect.append(get_trk_sect_id(trk, lp_dlong[i]))

# Fix sections
lp_dlong[0] = lp_dlong[0] - trk.trackLength
lp_dlong[1] = lp_dlong[1] - trk.trackLength
lp_dlong[-1] = lp_dlong[-1] + trk.trackLength
lp_dlong[-2] = lp_dlong[-2] + trk.trackLength

# Calculate T3 radius
for i in range(0, num_lp_recs2):
    cur = i
    if i == 0:
        prev = num_lp_recs + 2
    else:
        prev = i - 1
    if i == num_lp_recs + 3:
        next = 0
    else:
        next = i + 1

    if t3_sect_type[cur] == 1 and t3_sect_type[next] == 1:
        t3_radius.append(0)
    elif t3_sect_type[cur] == 2 and t3_sect_type[next] == 2:

        # If the next frame is in a new section but going from curve to curve,
        # calculate fictitious radius. Otherwise look up the radius.
        if t3_sect[cur] == t3_sect[next]:
            t3_radius.append(get_trk_sect_radius(trk, t3_sect[cur]))
        else:
            # Dennis curve to curve formula
            dlongc = trk.sects[t3_sect[next]].dlong
            dlong0 = lp_dlong[cur]
            r0 = get_trk_sect_radius(trk, t3_sect[cur])
            dlong1 = lp_dlong[next]
            r1 = get_trk_sect_radius(trk, t3_sect[next])
            t3_radius.append(get_fake_radius3(dlongc, dlong0, r0, dlong1, r1))


    elif t3_sect_type[cur] == 1 and t3_sect_type[next] == 2:
        t3_radius.append(get_fake_radius1(
            get_trk_sect_radius(trk, t3_sect[next]),
            lp_dlong[next],
            trk.sects[t3_sect[next]].dlong,
            lp_dlong[cur]))
        t3_sect_type[cur] = 2
    elif t3_sect_type[cur] == 2 and t3_sect_type[next] == 1:
        t3_radius.append(get_fake_radius2(
            get_trk_sect_radius(trk, t3_sect[prev]),
            trk.sects[t3_sect[next]].dlong,
            lp_dlong[cur],
            lp_dlong[next]))
    else:
        print ('Did not calculate T3 radius at {}'.format(i))

# Calculate previous RW lengths
for i in range(0, num_lp_recs2):
    cur = i
    if i == 0:
        prev = num_lp_recs - 2
        prev_dlong = -65536
    else:
        prev = i - 1
        prev_dlong = int(lp_dlong[prev])
    if i == num_lp_recs - 1:
        next = 0
    else:
        next = i + 1

    if t3_sect_type[prev] == 1:
        a = (lp_dlong[cur] - prev_dlong) ** 2
        b = (lp_dlat[cur] - lp_dlat[prev]) ** 2
        t3_prev_rw_len.append(math.sqrt(a + b))

    else:
        a = (2 * t3_radius[prev] - lp_dlat[cur] - lp_dlat[prev])\
            * (lp_dlong[cur] - lp_dlong[prev]) / (2 * t3_radius[prev])
        b = lp_dlat[cur] - lp_dlat[prev]
        t3_prev_rw_len.append(math.sqrt(a ** 2 + b ** 2))

# Get next RW length
for i in range(0, num_lp_recs2):
    if i == num_lp_recs2 - 1:
        next = 0
    else:
        next = i + 1
    t3_next_rw_len.append(t3_prev_rw_len[next])

# Calculate next section LP length
for i in range(0, num_lp_recs2 - 1):
    if t3_radius[i] == 0:
        t3_next_lp_len.append(lp_dlong[i + 1] - lp_dlong[i])
    else:
        t3_next_lp_len.append(
        (lp_dlong[i + 1] - lp_dlong[i]) \
        * (t3_radius[i] - lp_dlat[i]) / t3_radius[i])
# Calculate previous section LP length
for i in range(1, num_lp_recs2 - 1):
    t3_prev_lp_len.append(t3_next_lp_len[i - 1])

# Calculate LP speed
for i in range(1, num_lp_recs2 - 1):
    lp_speed.append(lp_rw_speed[i] \
    * (t3_prev_lp_len[i] \
    + t3_next_lp_len[i]) \
    / (t3_next_rw_len[i] + t3_prev_rw_len[i]))

# Calculate coriolis (Method 1)
for i in range(1, num_lp_recs2 - 1):
    # coriolis1.append((lp_dlat[i + 1] - lp_dlat[i - 1]) / 2 \
    #                 * lp_speed[i] / 65536 * 31680000 / 54000)
    a = ((lp_dlat[i + 1] - lp_dlat[i - 1]) / (lp_dlong[i + 1] - lp_dlong[i - 1])) * (lp_speed[i] * 31680000/54000)
    coriolis1.append(a)


# Calculate coriolis (Method 2)
for i in range(1, num_lp_recs2 - 1):
    if (lp_rw_speed[i] ** 2 - lp_speed[i] ** 2) > 0:
        a = math.sqrt(lp_rw_speed[i] ** 2 - lp_speed[i] ** 2)
    else:
        a = 0

    coriolis2.append(
        a * np.sign(lp_dlat[i + 1] - lp_dlat[i]) * 31680000/54000
    )

# Closed loop check
first_dlat = round(lp_dlat[2])
last_dlat = round(lp_dlat[num_lp_recs2 - 3])
diff_dlat = round(lp_dlat[num_lp_recs2 - 3] - lp_dlat[2])
diff_dlat_ft = round((lp_dlat[num_lp_recs2 - 3] - lp_dlat[2])/6000, 2)
first_speed = round(lp_speed[2], 2)
last_speed = round(lp_speed[num_lp_recs2 - 3], 2)
diff_speed = round(lp_speed[num_lp_recs2 - 3] - lp_speed[2], 2)

print ('Last DLAT {} vs first DLAT {} = {} difference ({} ft)'.format(
        last_dlat, first_dlat, diff_dlat, diff_dlat_ft))
print ('Last LP speed {} mph vs first LP speed {} mph = {} mph difference'\
       .format(last_speed, first_speed, diff_speed))

# Output table 3
if args.table:
    print ('Output table3.csv...')
    with open('table3.csv', 'w') as o:
        o.write('LP record, DLONG, DLAT, Radius, Prev section RW length, \
                Next section RW length, Prev section LP length, Next section \
                LP length, LP RW speed, LP speed, Coriolis1, Coriolis2\n')
        for i in range(0, num_lp_recs2 - 1):
            o.write("{},{},{},{},{},{},{},{},{},{},{},{}\n".format(i-1, \
                                              lp_dlong[i], lp_dlat[i], \
                                              t3_radius[i], t3_prev_rw_len[i], \
                                              t3_next_rw_len[i], t3_prev_lp_len[i],\
                                              t3_next_lp_len[i], lp_rw_speed[i], lp_speed[i],\
                                              coriolis1[i], coriolis2[i]))

print ('Writing to {} - {} records'.format(output_file, num_lp_recs2 - 4))
output_array = []
output_array.extend([num_lp_recs2 - 4])
for i in range(2, num_lp_recs2 - 2):
    output_array.extend([round(lp_speed[i] * (1/15) * (1/3600) * (6000) * (5280)), round(coriolis1[i]), round(lp_dlat[i])])
output_array = np.array(output_array)
output_array.astype('int32').tofile(output_file)
