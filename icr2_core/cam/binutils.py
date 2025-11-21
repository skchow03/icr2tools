import struct


def _read_int32_bytes(data: bytes):
    return list(struct.unpack("<" + "i" * (len(data) // 4), data))


def read_int32_file(filename):
    with open(filename, "rb") as f:
        data = f.read()
        return _read_int32_bytes(data)


def read_int32_bytes(data: bytes):
    return _read_int32_bytes(data)


def write_int32_file(filename, int_list):
    with open(filename, "wb") as f:
        f.write(struct.pack("<" + "i" * len(int_list), *int_list))


def chunk(lst, n):
    return [lst[i : i + n] for i in range(0, len(lst), n)]
