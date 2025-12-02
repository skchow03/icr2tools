import struct


def get_int8(input_bytes, offset):
    return int.from_bytes(input_bytes[offset:offset+1],byteorder='little',signed=False)

def get_int16(input_bytes, offset):
    return int.from_bytes(input_bytes[offset:offset+2],byteorder='little',signed=False)

def get_int16_2(input_bytes, offset):
    return int.from_bytes(input_bytes[offset:offset+2],byteorder='little',signed=False)

def get_int16_s(input_bytes, offset):
    return int.from_bytes(input_bytes[offset:offset+2],byteorder='little',signed=True)

def get_int24(input_bytes, offset):
    return int.from_bytes(input_bytes[offset:offset+3],byteorder='little',signed=True)

def get_int32(input_bytes, offset):
    return int.from_bytes(input_bytes[offset:offset+4],byteorder='little',signed=True)

def get_int64(input_bytes, offset):
    return int.from_bytes(input_bytes[offset:offset+8],byteorder='little',signed=True)

def get_hex(input_bytes, offset, size=4):
    return input_bytes[offset:offset+size].hex()

def print_hex_lines(bytes, start, length):
    """Use this for debugging. It will return the hex values and int32 values
    where you specify."""
    for i in range(start,start+length,4):
        print ('{} {} {}'.format(i, get_hex(bytes,i), get_int32(bytes,i)))

def pack_24_bit_signed(num):
    # Check if the number is negative
    if num < 0:
        # Convert to 24-bit two's complement representation
        num = (1 << 24) + num
    # Pack as 32-bit then truncate
    return struct.pack('I', num)[:3]

def pack_integer(num, byte_size):
    if byte_size == 1:
        return struct.pack('B', num)  # 8-bit unsigned
    elif byte_size == 2:
        return struct.pack('h', num)  # 16-bit signed
    elif byte_size == 3:
        return pack_24_bit_signed(num)  # 24-bit signed
    elif byte_size == 4:
        return struct.pack('i', num)  # 32-bit signed
    else:
        raise ValueError("Unsupported byte size")

def write_integers_to_binary(file_name, integers):
    with open(file_name, 'wb') as file:
        for num, byte_size in integers:
            packed_data = pack_integer(num, byte_size)
            file.write(packed_data)

