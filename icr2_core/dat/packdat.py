import os
import struct
import shutil
import datetime
import argparse

def packdat(packlist_path, output_file_path, backup=True):
    """
    Rebuilds a .DAT file using the information from the packlist.txt file.

    Args:
        packlist_path (str): Full path to the packlist.txt file.
        output_file_path (str): Full path to the output .DAT file.
        backup (bool): Flag indicating whether to create a backup of the output .DAT file (default=True).
    """

    print("Begin packdat process")

    if not os.path.exists(packlist_path):
        print("Packlist file does not exist")
        return

    if os.path.isdir(output_file_path):
        print("Output file path points to an existing directory")
        return

    # First back up the .dat file if it exists
    if os.path.exists(output_file_path):
        if backup:
            print(".dat file exists. Creating a backup.")
            timestamp = datetime.datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
            backup_file_path = output_file_path + "_" + timestamp + ".bak"
            shutil.copy2(output_file_path, backup_file_path)

    unpack_path = os.path.dirname(packlist_path)

    with open(packlist_path, "r") as packlist_file:
        file_names = packlist_file.read().splitlines()

    num_files = len(file_names)

    # Get file paths for opening the files later
    file_paths = [os.path.join(unpack_path, file_name) for file_name in file_names]

    # Get file sizes
    file_sizes = [os.path.getsize(file_path) for file_path in file_paths]

    # Generate the byte object for the file name (which has to be 13 characters)
    file_names = [(file_name.encode('ascii') + b'\x00' * (13 - len(file_name))) for file_name in file_names]

    # Calculate offsets
    file_offsets = [2 + (27 * num_files) + sum(file_sizes[:i]) for i in range(num_files)]

    # Write the .dat file
    print("Writing the .dat file")
    with open(output_file_path, "wb") as output_file:
        output_file.write(struct.pack("<H", num_files))
        for i in range(num_files):
            output_file.write(struct.pack("<H", 5))
            output_file.write(struct.pack("<L", file_sizes[i]))
            output_file.write(struct.pack("<L", file_sizes[i]))
            output_file.write(file_names[i])
            output_file.write(struct.pack("<L", file_offsets[i]))
        for file_path in file_paths:
            with open(file_path, "rb") as source_file:
                output_file.write(source_file.read())

    print("Done")


def main():
    parser = argparse.ArgumentParser(prog='packdat')
    parser.add_argument('packlist_path', help='Path to the packlist.txt file')
    parser.add_argument('output_file_path', help='Path to the output .DAT file')
    parser.add_argument('-nb', '--no_backup', action='store_true', help='Disable creating a backup of the output .DAT file')

    args = parser.parse_args()

    packdat(args.packlist_path, args.output_file_path, backup=not args.no_backup)


if __name__ == '__main__':
    main()
