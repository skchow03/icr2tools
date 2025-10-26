import numpy as np

def write_txt(trk, filename):
    print ("Exporting TRK information to {}".format(filename))
    with open(filename, 'w') as o:
        o.write('Importing the track data.\n')
        o.write('len={} numX={} sizeS={} sizeF={}\n'.format(
            trk.header[2], 
            trk.header[3],
            trk.header[6],
            trk.header[5],
        ))
        o.write('trackLength: {}\n'.format(trk.header[2]))
        o.write('numXsections: {}\n'.format(trk.num_xsects))
        o.write('numSections: {}\n'.format(trk.num_sects))
        o.write('sizeF: {}\n'.format(trk.header[5]))
        o.write('sizeS: {}\n'.format(trk.header[6]))

        for i in range(0,trk.num_xsects):
            o.write(' xdlat {}: {}\n'.format(
                i,
                trk.xsect_dlats[i]
            ))

        for i in range(0,trk.num_sects):
            o.write('Section {}: '.format(i))
            if trk.sects[i].type == 1:
                o.write('straight\n')
            elif trk.sects[i].type == 2:
                o.write('curve\n')

            o.write('  {} dlong {}\n'.format(i, trk.sects[i].start_dlong))
            o.write('  {} length {}\n'.format(i, trk.sects[i].length))
            o.write('  {} heading {}\n'.format(i, trk.sects[i].heading))

            if trk.sects[i].type == 1:
                o.write('   Xdir={}\n'.format(trk.sects[i].ang1))
                o.write('   Ydir={}\n'.format(trk.sects[i].ang2))
                o.write('   Xperp={}\n'.format(trk.sects[i].ang3))
                o.write('   Yperp={}\n'.format(trk.sects[i].ang4))
                o.write('   cosgrade2={}\n'.format(trk.sects[i].ang5))
            elif trk.sects[i].type == 2:
                o.write('   Xcenter={}\n'.format(trk.sects[i].ang1))
                o.write('   Ycenter={}\n'.format(trk.sects[i].ang2))
                o.write('   dHeading={}\n'.format(trk.sects[i].ang3))               

            for xsect in range(0,trk.num_xsects):
                o.write('     xs {}: {} {} {} {} {} {}\n'.format(
                    xsect,
                    trk.sects[i].grade1[xsect],
                    trk.sects[i].grade2[xsect],
                    trk.sects[i].grade3[xsect],
                    trk.sects[i].alt[xsect],
                    trk.sects[i].grade4[xsect],
                    trk.sects[i].grade5[xsect]
                ))
                if trk.sects[i].type == 1:
                    o.write('        x0: {} y0: {}\n'.format(
                        trk.sects[i].pos1[xsect],
                        trk.sects[i].pos2[xsect]
                    ))
                elif trk.sects[i].type == 2:
                    o.write('        dlatCenter: {}\n'.format(
                        trk.sects[i].pos1[xsect]
                    ))

            for j in range(0,trk.sects[i].ground_fsects):
                o.write('      fs {}: {} {} {}\n'.format(
                    j,
                    trk.sects[i].ground_dlat_start[j],
                    trk.sects[i].ground_dlat_end[j],
                    trk.sects[i].ground_type[j]
                ))

def write_trk(trk, filename):
    """
    Outputs the information in the TRK class object to a binary .TRK file readable by the game
    """

    print ('Writing TRK file to {}'.format(filename))

    # Convert all lists to NumPy arrays and Int32 format
    header = np.array(trk.header).astype(np.int32)
    xsect_dlats = np.array(trk.xsect_dlats).astype(np.int32)
    sect_offsets = np.array(trk.sect_offsets).astype(np.int32)
    sect_offsets = (sect_offsets * 4).tolist()
    sect_offsets = sect_offsets[:-1]
    xsect_data = np.array(trk.xsect_data).astype(np.int32).flatten()
    ground_data = np.array(trk.ground_data).astype(np.int32).flatten()

    # Combine all section data into one list
    sects_data = []
    for i in range(0, trk.num_sects):
        sects_data.extend([
            trk.sects[i].type,
            trk.sects[i].start_dlong,
            trk.sects[i].length,
            trk.sects[i].heading,
            trk.sects[i].ang1,
            trk.sects[i].ang2,
            trk.sects[i].ang3,
            trk.sects[i].ang4,
            trk.sects[i].ang5,
            trk.sects[i].xsect_counter,
            trk.sects[i].ground_fsects,
            trk.sects[i].ground_counter,
            trk.sects[i].num_bounds])
        for j in range(0, trk.sects[i].num_bounds):
            sects_data.extend([
                trk.sects[i].bound_type[j],
                trk.sects[i].bound_dlat_start[j],
                trk.sects[i].bound_dlat_end[j],
                -858993460,
                -858993460
            ])
    sects_data = np.array(sects_data).astype(np.int32)

    # Combine all data and output to .trk file
    all_data = np.concatenate([header, xsect_dlats, sect_offsets, xsect_data, ground_data, sects_data])
    all_data.tofile(filename, sep="")

def write_csv(trk, trk_name):

    print ('Writing TRK information to CSV files using track name {}'.format(trk_name))

    # Read and write header
    header_labels = ['type', 'unknown1', 'track_length', 'number_of_xsects', 'number_of_sects', 'byte_length_fsects', 'byte_length_sect_data']
    with open(trk_name+'-1-header.csv', 'w') as o:
        o.write(','.join(header_labels) + '\n')
        o.write(','.join(map(str, trk.header)) + '\n')

    # Read and write xsects DLATs
    with open(trk_name+'-2-xsect_dlats.csv', 'w') as o:
        o.write('xsect,dlat\n')
        for i, xsect in enumerate(trk.xsect_dlats):
            o.write('{},{}\n'.format(i, xsect))

    # Calculate and write section offsets
    with open(trk_name+'-3-sect_offsets.csv', 'w') as o:
        o.write('sect,sect_offset\n')
        for i in range(0, len(trk.sect_offsets)):
            o.write('{},{}\n'.format(i, trk.sect_offsets[i]))

    # Xsect data
    with open(trk_name+'-4-xsect.csv', 'w') as o:
        o.write('sect, xsect, grade1, grade2, grade3, alt, grade4, grade5, pos1, pos2\n')
        c = 0
        for i in range(0,trk.num_sects):
            for j in range(0,trk.num_xsects):
                o.write('{},{}'.format(i,j))
                for k in range(0,8):
                    o.write(',{}'.format(trk.xsect_data[c][k]))
                o.write('\n')
                c += 1

    # section data

    # Combine all section data into one list
        sects_data = []
        for i in range(0, trk.num_sects):
            sects_data.extend([
                trk.sects[i].type,
                trk.sects[i].start_dlong,
                trk.sects[i].length,
                trk.sects[i].heading,
                trk.sects[i].ang1,
                trk.sects[i].ang2,
                trk.sects[i].ang3,
                trk.sects[i].ang4,
                trk.sects[i].ang5,
                trk.sects[i].xsect_counter,
                trk.sects[i].ground_fsects,
                trk.sects[i].ground_counter,
                trk.sects[i].num_bounds])
            for j in range(0, trk.sects[i].num_bounds):
                sects_data.extend([
                    trk.sects[i].bound_type[j],
                    trk.sects[i].bound_dlat_start[j],
                    trk.sects[i].bound_dlat_end[j],
                    -858993460,
                    -858993460
                ])
        sects_data = np.array(sects_data).astype(np.int32)


    with open(trk_name+'-6-sects_data.csv', 'w') as o6:
        o6.write('sect,type,start_dlong,length,heading,ang1,ang2,ang3,ang4,ang5,unknown_counter,ground_fsects,ground_counter,num_wall_fsects')
        for i in range(0,10):
            o6.write(',boundary{}_type,boundary{}_dlat_start,boundary{}_dlat_end,placeholder1,placeholder2'.format(i,i,i))
        o6.write('\n')

        with open(trk_name+'-5-fsect-ground.csv', 'w') as o5:
            o5.write('sect,fsect_start, fsect_end, fsect_ground_type\n')

            fsect_index = 0

            for i in range(trk.num_sects):
                sect_start = trk.sect_offsets[i]
                sect_end = trk.sect_offsets[i + 1]
                cur_sect = sects_data[sect_start:sect_end]
                num_fsects = cur_sect[12]
                num_ground_fsects = cur_sect[10]
                o6.write('{},'.format(i))
                o6.write(','.join(map(str, cur_sect)) + '\n')

                for j in range(num_ground_fsects):
                    o5.write('{},'.format(i))
                    fsect = trk.ground_data[fsect_index]
                    o5.write(','.join(map(str, fsect)) + '\n')
                    fsect_index += 1

                