from binutils import write_int32_file

def csv_to_scr(csv_file, output_file):
    output_list = []
    with open(csv_file, 'r') as f:
        num_views = int(f.readline().strip().split(',')[1])
        output_list.append(num_views)

        total_cams = 0
        for _ in range(num_views):
            n = int(f.readline().strip().split(',')[1])
            output_list.append(n)
            total_cams += n

        f.readline()  # Skip header line

        for _ in range(total_cams):
            parts = f.readline().strip().split(',')
            output_list.extend(int(val) for val in parts[1:5])

    write_int32_file(output_file, output_list)

def csv_to_cam(csv_file, output_file):
    output_list = []
    with open(csv_file, 'r') as f:
        num_type6 = int(f.readline().strip().split(',')[1])
        output_list.append(num_type6)
        f.readline()
        for _ in range(num_type6):
            parts = f.readline().strip().split(',')
            output_list.extend(int(parts[i]) for i in range(1, 10))

        num_type2 = int(f.readline().strip().split(',')[1])
        output_list.append(num_type2)
        f.readline()
        for _ in range(num_type2):
            parts = f.readline().strip().split(',')
            output_list.extend(int(parts[i]) for i in range(1, 10))

        num_type7 = int(f.readline().strip().split(',')[1])
        output_list.append(num_type7)
        f.readline()
        for _ in range(num_type7):
            parts = f.readline().strip().split(',')
            output_list.extend(int(parts[i]) for i in range(1, 13))

    write_int32_file(output_file, output_list)