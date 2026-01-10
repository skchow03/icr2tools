import os
import struct
import argparse
import logging

logger = logging.getLogger(__name__)

def unpackdat(dat_file_path, output_folder=None, specific_file=None):
    """
    Unpacks files from a .DAT file into a subfolder called "unpack".
    If a specific file is provided, it will be unpacked. Otherwise, all files will be unpacked.
    
    Args:
        dat_file_path (str): Full path to the .DAT file or just the file name.
        output_folder (str): Folder to extract files to; otherwise, 'unpack' folder will be created.
        specific_file (str): Specific file to extract (default=None).
    """

    dat_dir = os.path.dirname(dat_file_path) or os.getcwd()

    print("Unpacking {0} to {1}".format(dat_file_path, os.path.join(dat_dir, "unpack")))

    with open(dat_file_path, "rb") as f:
        num_files = struct.unpack("<H", f.read(2))[0]

        file_lengths = []
        file_names = []
        file_offsets = []

        for file_index in range(num_files):
            f.read(2)
            file_length = struct.unpack("<L", f.read(4))[0]
            file_lengths.append(file_length)

            f.read(4)
            file_name = ""
            for _ in range(13):
                byte = struct.unpack("c", f.read(1))[0].decode('ascii')
                if byte != "\x00":
                    file_name += byte
            file_names.append(file_name)

            file_offset = struct.unpack("<L", f.read(4))[0]
            file_offsets.append(file_offset)

        for file_index in range(num_files - 1, 0, -1):
            if file_names[file_index] == "":
                del file_names[file_index]
                del file_lengths[file_index]
                del file_offsets[file_index]
                num_files -= 1

        newpath = output_folder or os.path.join(dat_dir, "unpack")
        os.makedirs(newpath, exist_ok=True)

        if specific_file is not None:
            print("Extracting a single file: {}".format(specific_file))

            if specific_file in file_names:
                target_id = file_names.index(specific_file)
                f.seek(file_offsets[target_id])
                bytes = f.read(file_lengths[target_id])
                new_file_path = os.path.join(newpath, specific_file)
                with open(new_file_path, "wb") as output_file:
                    output_file.write(bytes)
                print("Done")
            else:
                print("Error: {0} does not exist in {1}".format(specific_file, dat_file_path))
        else:
            print("Unpacking the entire contents of .dat file")
            with open(os.path.join(newpath, "packlist.txt"), "w") as pack_list:
                for file_index in range(num_files):
                    pack_list.write(file_names[file_index])
                    pack_list.write("\n")

                    bytes = f.read(file_lengths[file_index])
                    new_file_path = os.path.join(newpath, file_names[file_index])
                    with open(new_file_path, "wb") as output_file:
                        output_file.write(bytes)
            print("Done")

def _read_dat_entries(f, dat_file_path: str | None = None):
    """Return a list of ``(name, offset, length)`` tuples for ``f``."""

    num_files = struct.unpack("<H", f.read(2))[0]

    file_entries = []
    for entry_index in range(num_files):
        f.read(2)
        file_length = struct.unpack("<L", f.read(4))[0]
        f.read(4)

        raw_name_bytes = b"".join(struct.unpack("c", f.read(1))[0] for _ in range(13))
        try:
            name_text = raw_name_bytes.decode("ascii")
        except UnicodeDecodeError as exc:
            logger.exception(
                "Failed to decode DAT entry name as ASCII: dat=%s entry=%s offset=0x%X raw=%s",
                dat_file_path or "<stream>",
                entry_index,
                f.tell() - 13,
                raw_name_bytes.hex(),
            )
            raise
        file_name = "".join(ch for ch in name_text if ch != "\x00")

        file_offset = struct.unpack("<L", f.read(4))[0]
        file_entries.append((file_name, file_offset, file_length))

    return file_entries


def list_dat_entries(dat_file_path: str):
    """Return a list of ``(name, offset, length)`` tuples inside ``dat_file_path``."""

    with open(dat_file_path, "rb") as f:
        return _read_dat_entries(f, dat_file_path)


def extract_file_bytes(dat_file_path: str, target_name: str) -> bytes:
    """
    Extract a specific file from a .DAT archive into memory.
    Returns the raw bytes of that file, or raises FileNotFoundError.
    """
    with open(dat_file_path, "rb") as f:
        file_entries = _read_dat_entries(f, dat_file_path)

        for file_name, file_offset, file_length in file_entries:
            if file_name.lower() == target_name.lower():
                f.seek(file_offset)
                return f.read(file_length)

    raise FileNotFoundError(f"{target_name} not found in {dat_file_path}")


def main():
    parser = argparse.ArgumentParser(prog='unpackdat')
    parser.add_argument('dat_file_path', help='Path to the .dat file')
    parser.add_argument('-o', '--output_folder', help='Folder to extract file to; otherwise will create "unpack" folder')
    parser.add_argument('-s', '--specific_file', help='Specific file to extract')

    args = parser.parse_args()

    unpackdat(args.dat_file_path, args.output_folder, args.specific_file)

if __name__ == '__main__':
    main()
