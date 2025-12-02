from binary import *
import argparse
from trk import Trk
from lpcalc import *
import numpy as np

def papy_speed_to_mph(speed_list):
    for i in range(0,len(speed_list)):
        speed_list[i] = speed_list[i] * (15/1) * (3600/1) * (1/6000) * (1/5280)
    return speed_list

def mph_to_papy_speed(speed_list):
    for i in range(0,len(speed_list)):
        speed_list[i] = speed_list[i] * (1/15) * (1/3600) * (6000) * (5280)
    return speed_list

def read_lp(lp_file):
    with open(lp_file, "rb") as f:
        bytes = f.read()

    num_recs = get_int32(bytes,0)
    print ('Reading {} - {} records'.format(lp_file, num_recs))

    speed = []
    coriolis = []
    dlat = []

    for i in range(0,num_recs):
        sec_pos = 4 + i * 12
        speed.append(get_int32(bytes, sec_pos))
        coriolis.append(get_int32(bytes, sec_pos + 4))
        dlat.append(get_int32(bytes, sec_pos + 8))
    return num_recs, speed, coriolis, dlat

def write_csv(output_file, speed, coriolis, dlat):
    print ('Writing to {} - {} records'.format(output_file, len(speed)))
    with open(output_file,'w') as o:
        o.write('DLONG,LP speed,Coriolis,DLAT\n')
        for i in range(0, len(speed)):
            o.write('{},{},{},{}\n'.format(i*65536,speed[i],coriolis[i],dlat[i]))

parser = argparse.ArgumentParser(description='ICR2 .LP to .CSV converter v2.5')
parser.add_argument('LP_file', help='input .LP file')
parser.add_argument('TRK_file', help='input .trk file')
parser.add_argument('CSV_file', help='output .CSV file')
parser.add_argument('--table', help='Output tables for debugging', action="store_true")
parser.add_argument('--trafo', help='Output Trafo txt', action="store_true")

args = parser.parse_args()

input_file = args.LP_file
output_file = args.CSV_file
trkfile = args.TRK_file

print ('Loading track file {}'.format(trkfile))
trk = Trk(trkfile)

num_lp_recs, lp_speed, coriolis, lp_dlat = read_lp(input_file)
lp_speed = papy_speed_to_mph(lp_speed)

lp_dlong = []
for i in range(0, num_lp_recs):
    cur_dlong = i * 65536
    if i == num_lp_recs - 1:
        cur_dlong = trk.trackLength
    lp_dlong.append(cur_dlong)

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

speed_start_change = lp_speed[1] - lp_speed[0]
speed_end_change = lp_speed[-1] - lp_speed[-2]
lp_speed = [lp_speed[0] - speed_start_change * 2, lp_speed[0] - speed_start_change] \
              + lp_speed \
              + [lp_speed[-1] + speed_end_change, lp_speed[-1] + speed_end_change * 2]

num_lp_recs2 = num_lp_recs + 4
print ('Number of LP records {}, LP2 records {}'.format(num_lp_recs, num_lp_recs2))

# Table 3 ===================================================================
print ('Calculating Table 3')
t3_next_rw_len = []
t3_prev_rw_len = []
t3_next_lp_len = []
t3_prev_lp_len = [0]
t3_radius = []
t3_sect = []
t3_sect_type = []
coriolis1 = [0]
coriolis2 = [0]
lp_rw_speed = []

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
for i in range(1, num_lp_recs2):
    t3_prev_lp_len.append(t3_next_lp_len[i - 1])

# Calculate LP RW speed
for i in range(0, num_lp_recs2 - 1):
    lp_rw_speed.append(lp_speed[i] \
    * (t3_prev_rw_len[i] + t3_next_rw_len[i]) \
    / (t3_next_lp_len[i] + t3_prev_lp_len[i]))

# Calculate coriolis (Method 1)
for i in range(1, num_lp_recs2 - 1):
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

# Output table 3
if args.table:
    print ('Output table3a.csv...')
    with open('table3a.csv', 'w') as o:
        o.write('LP record, DLONG, DLAT, Radius, Prev section RW length, \
                Next section RW length, Prev section LP length, Next section \
                LP length, LP RW speed, LP speed, Coriolis1, Coriolis2\n')
        for i in range(0, num_lp_recs2 - 2):
            o.write("{},{},{},{},{},{},{},{},{},{},{},{}\n".format(i-1, \
                                              lp_dlong[i], lp_dlat[i], \
                                              t3_radius[i], t3_prev_rw_len[i], \
                                              t3_next_rw_len[i], t3_prev_lp_len[i],\
                                              t3_next_lp_len[i], lp_rw_speed[i], lp_speed[i],\
                                              coriolis1[i], coriolis2[i]))

if args.trafo:
    print ('Output data to Trafo txt format {}...'.format(output_file))
    with open(output_file, 'w') as o:
        o.write("No\t Speed[mph]\t Coriolis[?]\t Position[ft]\n")
        for i in range(2, num_lp_recs2 - 2):
            o.write("{}\t {}\t {}\t {}\n".format(i-1, round(lp_rw_speed[i],2), 0, round(lp_dlat[i] / 6000, 2)))

else:
    print ('Output data to csv format {}...'.format(output_file))
    with open(output_file, 'w') as o:
        o.write("Record,DLONG,RW Speed,DLAT\n")
        for i in range(2, num_lp_recs2 - 2):
            o.write("{},{},{},{}\n".format(i-1, lp_dlong[i], lp_rw_speed[i], lp_dlat[i]))
