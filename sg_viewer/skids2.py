import random
import csv
import argparse

# input_file = 'skids.csv'
# output_file = 'skids.tsd'

colors = [45,28,44,29]

parser = argparse.ArgumentParser(description='Create skid mark TSD file')
parser.add_argument('Input_file', help='input .CSV file')
parser.add_argument('Output_file', help='output .TSD file')
args = parser.parse_args()

input_file = args.Input_file
output_file = args.Output_file

print ('Converting {} to {}...'.format(input_file, output_file), end='')


# Determine number of sections
with open(input_file,'r') as n:
    num_sections = sum(1 for line in n)-1


with open(input_file,'r') as n:
    with open(output_file, 'w') as o:

        # Read header
        n.readline()

        # Do for each section
        for i in range(0,num_sections):

            # Read the csv file containing the parameters
            params = n.readline().strip().split(',')
            section_name = params[0]
            start_dlong = int(params[1])
            apex_dlong = int(params[2])
            end_dlong = int(params[3])
            min_length = int(params[4])
            max_length = int(params[5])
            width = int(params[6])
            num_skids = int(params[7])
            start_dlat = [int(params[8]), int(params[9])]
            apex_dlat = [int(params[10]), int(params[11])]
            end_dlat = [int(params[12]), int(params[13])]

            # Finds min and max DLATs in case user enters them in
            # different orders
            start_dlat_min = min(start_dlat)
            start_dlat_max = max(start_dlat)
            apex_dlat_min = min(apex_dlat)
            apex_dlat_max = max(apex_dlat)
            end_dlat_min = min(end_dlat)
            end_dlat_max = max(end_dlat)

            print (start_dlat, apex_dlat, end_dlat)

            # Other calculations
            entry_length = apex_dlong - start_dlong
            exit_length = end_dlong - apex_dlong

            o.write('% {}\n'.format(section_name))

            for j in range(0,num_skids):

                # Randomize color, length, start dlong
                color = random.choice(colors)
                length = random.randrange(min_length, max_length)
                start_skid = random.randrange(start_dlong, end_dlong-length)
                end_skid = start_skid + length

                # Calculate dlat range at start dlong
                if start_skid <= apex_dlong:
                    entry_pos = (start_skid-start_dlong)/entry_length
                    dlat_range = [start_dlat_min + (apex_dlat_min - start_dlat_min) * entry_pos,
                                  start_dlat_max + (apex_dlat_max - start_dlat_max) * entry_pos]
                else:
                    exit_pos = (start_skid-apex_dlong)/exit_length
                    dlat_range = [apex_dlat_min + (end_dlat_min - apex_dlat_min) * exit_pos,
                                  apex_dlat_max + (end_dlat_max - apex_dlat_max) * exit_pos]

                # Calculate dlat range at end of skid dlong
                if end_skid <= apex_dlong:
                    entry_pos = (end_skid-start_dlong)/entry_length
                    dlat_range2 = [start_dlat_min + (apex_dlat_min - start_dlat_min) * entry_pos,
                                  start_dlat_max + (apex_dlat_max - start_dlat_max) * entry_pos]
                else:
                    exit_pos = (end_skid-apex_dlong)/exit_length
                    dlat_range2 = [apex_dlat_min + (end_dlat_min - apex_dlat_min) * exit_pos,
                                  apex_dlat_max + (end_dlat_max - apex_dlat_max) * exit_pos]


                # Convert dlat ranges to integers and randomly choose starting dlat
                dlat_range = [int(dlat_range[0]), int(dlat_range[1])]
                dlat = random.randrange(dlat_range[0], dlat_range[1])
                dlat_pos = (dlat - dlat_range[0])/(dlat_range[1] - dlat_range[0])

                # Get ending dlat by calculating based on where the starting dlat is
                dlat_range2 = [int(dlat_range2[0]), int(dlat_range2[1])]
                dlat2 = int(dlat_range2[0] + (dlat_range2[1] - dlat_range2[0]) * dlat_pos)

                print (dlat, dlat_range, dlat2, dlat_range2)


                o.write('Detail: {} {} {} {} {} {}\n'.format(color, width, start_skid, dlat, end_skid, dlat2))
