from binutils import read_int32_file, chunk

def scr_to_csv(scr_file, output_file):
    a = read_int32_file(scr_file)
    num_views = a[0]
    num_tv = [a[1 + i] for i in range(num_views)]
    a = a[1 + num_views:]
    a = chunk(a, 4)

    if num_views == 2:
        a1 = a[0:num_tv[0]]
        a2 = a[num_tv[0]:num_tv[0] + num_tv[1]]
        a = [a1, a2]
    elif num_views == 1:
        a = [a]
    else:
        print("Error: number of views must be 1 or 2")
        quit()

    with open(output_file, 'w') as w:
        w.write(f'Number of views,{num_views}\n')
        for i in range(num_views):
            w.write(f'Number of TV{i + 1} cams,{num_tv[i]}\n')
        w.write('View,Mark,Cam ID, Start DLONG, End DLONG\n')
        for i in range(num_views):
            for cam in range(num_tv[i]):
                row = a[i][cam]
                w.write(f'TV{i + 1},{row[0]},{row[1]},{row[2]},{row[3]}\n')

def cam_to_csv(cam_file, output_file):
    a = read_int32_file(cam_file)

    num_type6 = a[0]
    type6_end = num_type6 * 9 + 1
    type6 = chunk(a[1:type6_end], 9)

    type2_start = type6_end
    num_type2 = a[type2_start]
    type2_end = type2_start + num_type2 * 9 + 1
    type2 = chunk(a[type2_start + 1:type2_end], 9)

    type7_start = type2_end
    num_type7 = a[type7_start]
    type7_end = type7_start + num_type7 * 12 + 1
    type7 = chunk(a[type7_start + 1:type7_end], 12)

    with open(output_file, 'w') as w:
        w.write(f'Number of Type 6 cams,{num_type6}\n')
        w.write('ID,middle point,x,y,z,start point, start zoom, middle point zoom, end point, end zoom\n')
        for i, row in enumerate(type6):
            w.write(f'{i},' + ','.join(map(str, row)) + '\n')

        w.write(f'Number of Type 2 cams,{num_type2}\n')
        w.write('ID,middle point,x,y,z,start point, start zoom, middle point zoom, end point, end zoom\n')
        for i, row in enumerate(type2):
            w.write(f'{i},' + ','.join(map(str, row)) + '\n')

        w.write(f'Number of Type 7 cams,{num_type7}\n')
        w.write('ID,zero,x,y,z,z rotation,vert rotation, tilt, ?, zero,zero,zero,zero\n')
        for i, row in enumerate(type7):
            w.write(f'{i},' + ','.join(map(str, row)) + '\n')