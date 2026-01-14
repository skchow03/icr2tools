from icr2_core.lp.binary import *

class Rpy:

    class Frame:
        def __init__(self, cars=None, g_objs=None, s_objs=None):
            self.cars = [] if cars is None else cars
            self.g_objs = [] if g_objs is None else g_objs
            self.s_objs = [] if s_objs is None else s_objs

    class Car:
        def __init__(self):
            self.car_id = []
            self.dlong = []
            self.dlat = []
            self.orient = []
            self.wheel_orient = []

    def __init__(self, rpy_file):
        with open(rpy_file, "rb") as f:
            bytes = f.read()

        # Read header
        self.data_size = get_int32(bytes, 4)
        self.start_time = get_int32(bytes, 8)
        self.num_cars = get_int32(bytes, 12)

        f_offset = 16       # data starts here
        line = 0

        car_id = []
        dlong = []
        dlat = []
        orient = []
        wheel_orient = []
        g_objects = []
        s_objects = []

        while f_offset < self.data_size:

            # Each while loop is a frame

            # Read cars
            for car in range(0, self.num_cars):
                offset = f_offset + car * 13
                car_id.append(get_int8(bytes, offset))
                dlong.append(get_int24(bytes, offset + 1))    # dlong is multiplied by 256 to get dlong
                dlat.append(get_int16_s(bytes, offset + 4))
                orient.append(get_int16_s(bytes, offset + 6))
                wheel_orient.append(get_int8(bytes, offset + 8))

            # Read graphics objects
            g_offset = f_offset + self.num_cars * 13
            num_g_obj = get_int8(bytes, g_offset)
#            g_objects.append(num_g_obj)

            g_offset_start = g_offset
            g_offset_end = g_offset + num_g_obj * 14 + 1

            objs = []
            for i in range(g_offset_start, g_offset_end):
                objs.append(get_int8(bytes, i))                

            g_objects.append(objs)

            # Sound objects
            s_offset = g_offset + num_g_obj * 14 + 1
            s_object = get_int8(bytes, s_offset)
            s_objects.append(s_object)

            

            flag_offset = s_offset + s_object * 7 + 1
            record_length = get_int32(bytes, flag_offset + 1)

            f_offset += flag_offset + 5 - f_offset

            # Create Frame object
            cur_frame = Rpy.Frame()

        # Generate list of unique car IDs and make list of car records
        car_set = set(car_id)
        self.car_index = list(car_set)
        self.cars = [self.Car() for i in range(0, self.num_cars)]

        for i in range(0, len(car_id)):
            cur_car_id = car_id[i]
            cur_car_index = self.car_index.index(cur_car_id)
            self.cars[cur_car_index].dlong.append(dlong[i] * 256)
            self.cars[cur_car_index].dlat.append(dlat[i] * 256)
            self.cars[cur_car_index].orient.append(orient[i])
            self.cars[cur_car_index].wheel_orient.append(wheel_orient[i])

