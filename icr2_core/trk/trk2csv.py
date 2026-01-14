import sys
import numpy as np

if len(sys.argv) != 2:
    print("Usage: python trk2csv.py <TRK file>")
    sys.exit(1)

trk_file = sys.argv[1]
trk_name = trk_file.split('.')[0]

arr = np.fromfile(trk_file, dtype=np.int32)

np.savetxt(trk_name+'-0-raw.csv', arr.reshape((len(arr),1)), delimiter=',', fmt='%i')

# Read and write header
header = arr[:7]
file_type, version, track_length, num_xsects, num_sects, fsects_bytes, sect_data_bytes = header
header_labels = ['type', 'unknown1', 'track_length', 'number_of_xsects', 'number_of_sects', 'byte_length_fsects', 'byte_length_sect_data']

with open(trk_name+'-1-header.csv', 'w') as o:
    o.write(','.join(header_labels) + '\n')
    o.write(','.join(map(str, header)) + '\n')

# Read and write xsects DLATs
xsects = arr[7:17]
with open(trk_name+'-2-xsect_dlats.csv', 'w') as o:
    o.write('xsect,dlat\n')
    for i, xsect in enumerate(xsects):
        o.write('{},{}\n'.format(i, xsect))

# Calculate and write section offsets
sect_offsets_end = 17 + num_sects
sect_offsets = arr[17:sect_offsets_end].tolist()
sect_offsets = [int(x / 4) for x in sect_offsets]
sect_offsets.append(int(sect_data_bytes / 4))

with open(trk_name+'-3-sect_offsets.csv', 'w') as o:
    o.write('sect,sect_offset\n')
    for i, sect_offset in enumerate(sect_offsets[:-1]):
        o.write('{},{}\n'.format(i, sect_offset))

# Xsect data
xsect_data_end = sect_offsets_end + 8 * num_sects * num_xsects
xsect_data = arr[sect_offsets_end:xsect_data_end]
xsect_data = xsect_data.reshape((num_sects * num_xsects, 8))
with open(trk_name+'-4-xsect.csv', 'w') as o:
    o.write('sect, xsect, grade1, grade2, grade3, alt, grade4, grade5, pos1, pos2\n')
    c = 0
    for i in range(0,num_sects):
        for j in range(0,num_xsects):
            o.write('{},{}'.format(i,j))
            for k in range(0,8):
                o.write(',{}'.format(xsect_data[c][k]))
            o.write('\n')
            c += 1

# fsects ground
fsects_data_end = int(xsect_data_end + fsects_bytes / 4)
fsects_data = arr[xsect_data_end:fsects_data_end].reshape((-1, 3))

# section data
sects_data = arr[fsects_data_end:]

with open(trk_name+'-6-sects_data.csv', 'w') as o6:
    o6.write('sect,type,start_dlong,length,heading,ang1,ang2,ang3,ang4,ang5,unknown_counter,ground_fsects,ground_counter,num_wall_fsects')
    for i in range(0,10):
        o6.write(',boundary{}_type,boundary{}_dlat_start,boundary{}_dlat_end,placeholder1,placeholder2'.format(i,i,i))
    o6.write('\n')

    with open(trk_name+'-5-fsect-ground.csv', 'w') as o5:
        o5.write('sect,fsect_start, fsect_end, fsect_ground_type\n')

        fsect_index = 0

        for i in range(num_sects):
            sect_start = sect_offsets[i]
            sect_end = sect_offsets[i + 1]
            cur_sect = sects_data[sect_start:sect_end]
            num_fsects = cur_sect[12]
            num_ground_fsects = cur_sect[10]
            o6.write('{},'.format(i))
            o6.write(','.join(map(str, cur_sect)) + '\n')

            for j in range(num_ground_fsects):
                o5.write('{},'.format(i))
                fsect = fsects_data[fsect_index]
                o5.write(','.join(map(str, fsect)) + '\n')
                fsect_index += 1

            