import os
import struct
import sys

def read_3do_header(file_path):
    """
    Reads the header of a .3do file and returns lists of referenced .mip and .3do files.
    """
    try:
        with open(file_path, 'rb') as f:
            f.seek(8)  # Skip the first 8 bytes
            num_mip_files = struct.unpack('I', f.read(4))[0]
            num_pmp_files = struct.unpack('I', f.read(4))[0]
            num_3do_files = struct.unpack('I', f.read(4))[0]

            mip_files = []
            for _ in range(num_mip_files):
                mip_file = f.read(8).decode('latin1').strip('\x00')
                mip_files.append(mip_file + '.mip')

            # Skip PMP file names
            for _ in range(num_pmp_files):
                f.read(8)

            three_do_files = []
            for _ in range(num_3do_files):
                three_do_file = f.read(8).decode('latin1').strip('\x00')
                if '\x00' in three_do_file or not three_do_file.isprintable():
                    print(f"Invalid 3DO file name: {three_do_file}")
                    continue
                three_do_files.append(three_do_file + '.3do')

            return mip_files, three_do_files
    except (IOError, struct.error) as e:
        print(f"Error reading {file_path}: {e}")
        return [], []

def read_mip_header(file_path):
    """
    Reads the header of a .mip file to get its width and height.
    """
    try:
        with open(file_path, 'rb') as f:
            f.seek(8)  # Skip the first 8 bytes
            width = struct.unpack('I', f.read(4))[0]
            height = struct.unpack('I', f.read(4))[0]
            return width, height
    except (IOError, struct.error) as e:
        print(f"Error reading {file_path}: {e}")
        return None, None

def collect_all_3do_files(track_file, folder_path, additional_files=[]):
    """
    Collects all .3do files referenced by the track .3do file and any nested .3do files,
    including additional specified files.
    """
    to_process = [track_file] + additional_files
    all_3do_files = set()

    while to_process:
        current_file = to_process.pop()
        if current_file not in all_3do_files:
            all_3do_files.add(current_file)
            _, referenced_3do_files = read_3do_header(os.path.join(folder_path, current_file))
            for ref_3do in referenced_3do_files:
                if ref_3do not in all_3do_files:
                    to_process.append(ref_3do)

    return list(all_3do_files)

def collect_all_mip_files(three_do_files, folder_path):
    """
    Collects all unique .mip files referenced by the given .3do files.
    """
    all_mip_files = set()

    for three_do_file in three_do_files:
        mip_files, _ = read_3do_header(os.path.join(folder_path, three_do_file))
        all_mip_files.update(mip_files)

    return list(all_mip_files)

def get_file_size(file_path):
    """
    Gets the size of the file in bytes.
    """
    try:
        return os.path.getsize(file_path)
    except OSError as e:
        print(f"Error getting size for {file_path}: {e}")
        return None

def get_mip_file_details(mip_files, folder_path):
    """
    Gets the width, height, and size details for each .mip file.
    """
    mip_details = []

    for mip_file in mip_files:
        mip_path = os.path.join(folder_path, mip_file)
        if os.path.exists(mip_path):
            width, height = read_mip_header(mip_path)
            file_size = get_file_size(mip_path)
            mip_details.append({
                'mip_file': mip_file,
                'width': width,
                'height': height,
                'size': file_size
            })
        else:
            mip_details.append({
                'mip_file': mip_file,
                'width': 'File not found',
                'height': 'File not found',
                'size': 'File not found'
            })

    return mip_details

def get_3do_file_details(three_do_files, folder_path):
    """
    Gets the size details for each .3do file.
    """
    three_do_details = []

    for three_do_file in three_do_files:
        three_do_path = os.path.join(folder_path, three_do_file)
        if os.path.exists(three_do_path):
            file_size = get_file_size(three_do_path)
            three_do_details.append({
                'three_do_file': three_do_file,
                'size': file_size
            })
        else:
            three_do_details.append({
                'three_do_file': three_do_file,
                'size': 'File not found'
            })

    return three_do_details

def get_unused_mip_files(folder_path, used_mip_files):
    """
    Gets the list of all .mip files present in the folder but not used in the track.
    """
    all_mip_files_in_folder = {f.lower() for f in os.listdir(folder_path) if f.lower().endswith('.mip')}
    used_mip_files_set = {f.lower() for f in used_mip_files}
    unused_mip_files = all_mip_files_in_folder - used_mip_files_set
    return list(unused_mip_files)

if __name__ == '__main__':
    if len(sys.argv) != 2:
        print("Usage: python analyze_track_files.py <trackname>")
        sys.exit(1)

    track_name = sys.argv[1]
    track_file_name = f'{track_name}.3do'
    folder_path = os.path.abspath(track_name)  # Automatically determine the track folder path

    # Additional 3DO files to be included
    additional_3do_files = ['sky.3do', 'horiz.3do']

    # Collect all .3do files used by the track
    all_3do_files = collect_all_3do_files(track_file_name, folder_path, additional_files=additional_3do_files)
    
    # Open the output file
    output_file_name = f'{track_name}_file_analysis.txt'
    with open(output_file_name, 'w') as output_file:
        output_file.write(f'All 3DO files used by the track:\n')
        for three_do_file in all_3do_files:
            output_file.write(f'{three_do_file}\n')

        # Get details of each .3do file
        three_do_file_details = get_3do_file_details(all_3do_files, folder_path)
        output_file.write(f'\nDetails of each 3DO file:\n')
        total_3do_size = 0
        for detail in three_do_file_details:
            size = detail['size']
            if isinstance(size, int):
                total_3do_size += size
            output_file.write(f"{detail['three_do_file']}: Size = {size} bytes\n")

        # Collect all unique .mip files used by the track
        all_mip_files = collect_all_mip_files(all_3do_files, folder_path)
        output_file.write(f'\nAll unique MIP files used by the track:\n')
        for mip_file in all_mip_files:
            output_file.write(f'{mip_file}\n')

        # Get details of each .mip file
        mip_file_details = get_mip_file_details(all_mip_files, folder_path)
        output_file.write(f'\nDetails of each MIP file:\n')
        total_mip_size = 0
        for detail in mip_file_details:
            size = detail['size']
            if isinstance(size, int):
                total_mip_size += size
            output_file.write(f"{detail['mip_file']}: Width = {detail['width']}, Height = {detail['height']}, Size = {size} bytes\n")

        # Get the list of unused .mip files
        unused_mip_files = get_unused_mip_files(folder_path, all_mip_files)
        output_file.write(f'\nUnused MIP files in the folder:\n')
        for mip_file in unused_mip_files:
            output_file.write(f'{mip_file}\n')

        # Print totals
        output_file.write(f'\nTotal number of MIP files: {len(all_mip_files)}\n')
        output_file.write(f'Total size of all 3DO files: {total_3do_size} bytes\n')
        output_file.write(f'Total size of all MIP files: {total_mip_size} bytes\n')
        output_file.write(f'Total number of unused MIP files: {len(unused_mip_files)}\n')
