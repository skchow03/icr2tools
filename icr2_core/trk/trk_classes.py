import numpy as np
import math

from icr2_core.trk.sg_classes import SGFile
import icr2_core.trk.trk_exporter  # if you have this file too
from icr2_core.trk.utils import approx_curve_length, sg_ground_to_trk, convert_wall_fsect_type, isclockwise


class TRKFile:
    def __init__(self, header, xsect_dlats, sect_offsets, xsect_data, ground_data, sects):
        self.header = header
        self.xsect_dlats = xsect_dlats
        self.sect_offsets = sect_offsets
        self.xsect_data = xsect_data
        self.ground_data = ground_data
        self.sects = sects

        self.trklength = self.header[2]
        self.num_xsects = self.header[3]
        self.num_sects = self.header[4]
        self.sect_data_bytes = self.header[6]

        self.sect_offsets.append(int(self.sect_data_bytes / 4))

        self.ground_data2 = []
        for i in range(0, self.num_sects):
            self.ground_data2.append(
                self.ground_data[
                    self.sects[i].ground_counter : self.sects[i].ground_counter
                    + self.sects[i].ground_fsects
                ]
            )
        for i in range(0, self.num_sects):
            for j in range(0, self.sects[i].ground_fsects):
                self.sects[i].ground_type.append(self.ground_data2[i][j][2])
                self.sects[i].ground_dlat_start.append(self.ground_data2[i][j][0])
                self.sects[i].ground_dlat_end.append(self.ground_data2[i][j][1])

        xsect_counter = 0
        for sect in range(0, self.num_sects):
            for _ in range(0, self.num_xsects):
                grade1, grade2, grade3, alt, grade4, grade5, pos1, pos2 = self.xsect_data[
                    xsect_counter
                ]
                self.sects[sect].grade1.append(grade1)
                self.sects[sect].grade2.append(grade2)
                self.sects[sect].grade3.append(grade3)
                self.sects[sect].grade4.append(grade4)
                self.sects[sect].grade5.append(grade5)
                self.sects[sect].alt.append(alt)
                self.sects[sect].pos1.append(pos1)
                self.sects[sect].pos2.append(pos2)
                xsect_counter += 1

    @classmethod
    def _parse_array(cls, arr):
        header = arr[:7]
        file_type, version, track_length, num_xsects, num_sects, fsects_bytes, sect_data_bytes = header

        xsect_dlats = arr[7:17]

        sect_offsets_end = 17 + num_sects
        sect_offsets = arr[17:sect_offsets_end].tolist()
        sect_offsets = [int(x / 4) for x in sect_offsets]
        sect_offsets.append(int(sect_data_bytes / 4))

        xsect_data_end = sect_offsets_end + 8 * num_sects * num_xsects
        xsect_data = arr[sect_offsets_end:xsect_data_end]
        xsect_data = xsect_data.reshape((num_sects * num_xsects, 8))

        fsects_data_end = int(xsect_data_end + fsects_bytes / 4)
        ground_data = arr[xsect_data_end:fsects_data_end].reshape((-1, 3))

        sects_data = arr[fsects_data_end:]

        sects = []
        for i in range(num_sects):
            sect_start = sect_offsets[i]
            sect_end = sect_offsets[i + 1]
            sec_data = sects_data[sect_start:sect_end]
            sects.append(cls.Section(sec_data, num_xsects))

        return cls(header, xsect_dlats, sect_offsets, xsect_data, ground_data, sects)

    @classmethod
    def from_trk(cls, file_name):
        arr = np.fromfile(file_name, dtype=np.int32)
        return cls._parse_array(arr)

    @classmethod
    def from_bytes(cls, raw_bytes: bytes):
        arr = np.frombuffer(raw_bytes, dtype=np.int32)
        return cls._parse_array(arr)

    @classmethod
    def from_sg(cls, file_name):
        sgfile = SGFile.from_sg(file_name)
        num_sects = sgfile.num_sects
        num_xsects = sgfile.num_xsects

        for sect in range(1, num_sects):
            if sgfile.sects[sect].type == 1 and sgfile.sects[sect - 1].type == 1:
                sgfile.sects[sect].sang1 = sgfile.sects[sect - 1].sang1
                sgfile.sects[sect].sang2 = sgfile.sects[sect - 1].sang2
                sgfile.sects[sect].eang1 = sgfile.sects[sect - 1].eang1
                sgfile.sects[sect].eang2 = sgfile.sects[sect - 1].eang2

        headings = []
        headings_rad = []

        for sect in range(0, num_sects):
            sec = sgfile.sects[sect]

            if sec.type == 1:
                d_x = sec.end_x - sec.start_x
                d_y = sec.end_y - sec.start_y
                heading = math.atan2(d_y, d_x) / math.pi * 2**31
                headings_rad.append(math.atan2(d_y, d_x))
                if heading == 2**31:
                    heading = -(2**31)
                headings.append(round(heading))
            elif sec.type == 2:
                svec_x = sec.start_x - sec.center_x
                svec_y = sec.start_y - sec.center_y
                evec_x = sec.end_x - sec.center_x
                evec_y = sec.end_y - sec.center_y
                start_angle = math.atan2(svec_y, svec_x)
                end_angle = math.atan2(evec_y, evec_x)
                if isclockwise(start_angle, end_angle):
                    heading = start_angle - math.pi / 2
                else:
                    heading = start_angle + math.pi / 2
                headings_rad.append(heading)
                heading = round(heading / math.pi * 2**31)
                headings.append(heading)

        xsect_dlats = np.pad(sgfile.xsect_dlats, (0, 10 - len(sgfile.xsect_dlats)), "constant")

        xsect_data = []
        for sect in range(0, num_sects):
            if sect == 0:
                prev_sect = num_sects - 1
            else:
                prev_sect = sect - 1
            for xsect in range(0, num_xsects):
                begin_alt = sgfile.sects[prev_sect].alt[xsect]
                end_alt = sgfile.sects[sect].alt[xsect]
                sg_length = sgfile.sects[sect].length
                cur_slope = sgfile.sects[prev_sect].grade[xsect] / 8192
                next_slope = sgfile.sects[sect].grade[xsect] / 8192
                grade1 = round((2 * begin_alt / sg_length + cur_slope + next_slope - 2 * end_alt / sg_length) * sg_length)
                grade2 = round((3 * end_alt / sg_length - 3 * begin_alt / sg_length - 2 * cur_slope - next_slope) * sg_length)
                grade3 = round(cur_slope * sg_length)
                grade4 = grade1 * 3
                grade5 = grade2 * 2
                if sgfile.sects[sect].type == 2:
                    pos1 = sgfile.sects[sect].radius - sgfile.xsect_dlats[xsect]
                    pos2 = -858993460
                else:
                    x = sgfile.sects[sect].start_x
                    y = sgfile.sects[sect].start_y
                    angle = headings_rad[sect] + math.pi / 2
                    d = sgfile.xsect_dlats[xsect]
                    pos1 = round(x + d * math.cos(angle))
                    pos2 = round(y + d * math.sin(angle))
                xsect_data.extend([grade1, grade2, grade3, begin_alt, grade4, grade5, pos1, pos2])

        xsect_data = np.array(xsect_data)
        xsect_data = xsect_data.reshape((num_sects * num_xsects, 8))

        ground_data = []
        for sect in range(0, num_sects):
            for fsect in range(0, sgfile.sects[sect].num_ground_fsects):
                ground_data.extend(
                    [
                        sgfile.sects[sect].ground_fstart[fsect],
                        sgfile.sects[sect].ground_fend[fsect],
                        sg_ground_to_trk(sgfile.sects[sect].ground_ftype[fsect]),
                    ]
                )

        len_ground_data = len(ground_data)
        ground_data = np.array(ground_data)
        ground_data = ground_data.reshape((-1, 3))

        for xsect in range(0, num_xsects):
            if sgfile.xsect_dlats[xsect] < 0 and sgfile.xsect_dlats[xsect + 1] >= 0:
                rxsect = xsect
                lxsect = xsect + 1

        cline_pct = -sgfile.xsect_dlats[rxsect] / (sgfile.xsect_dlats[lxsect] - sgfile.xsect_dlats[rxsect])

        cline_alt = []
        cline_grade = []
        adj_length = []

        for sect in range(0, num_sects):
            cline_alt.append(
                sgfile.sects[sect].alt[rxsect]
                + cline_pct * (sgfile.sects[sect].alt[lxsect] - sgfile.sects[sect].alt[rxsect])
            )
            cline_grade.append(
                sgfile.sects[sect].grade[rxsect]
                + cline_pct * (sgfile.sects[sect].grade[lxsect] - sgfile.sects[sect].grade[rxsect])
            )

        for sect in range(0, num_sects):
            if sect == 0:
                prev_sect = num_sects - 1
            else:
                prev_sect = sect - 1
            begin_alt = cline_alt[prev_sect]
            end_alt = cline_alt[sect]
            sg_length = sgfile.sects[sect].length
            cur_slope = cline_grade[prev_sect] / 8192
            next_slope = cline_grade[sect] / 8192
            grade1 = round((2 * begin_alt / sg_length + cur_slope + next_slope - 2 * end_alt / sg_length) * sg_length)
            grade2 = round((3 * end_alt / sg_length - 3 * begin_alt / sg_length - 2 * cur_slope - next_slope) * sg_length)
            grade3 = round(cur_slope * sg_length)
            adj_length.append(round(approx_curve_length(grade1, grade2, grade3, cline_alt[sect], sg_length)))

        start_dlong = [0]
        for sect in range(1, num_sects):
            start_dlong.append(start_dlong[sect - 1] + adj_length[sect - 1])

        for sect in range(1, num_sects):
            if sgfile.sects[sect].type == 1 and sgfile.sects[sect - 1].type == 1:
                headings[sect] = headings[sect - 1]

        ang1s = []
        ang2s = []
        ang3s = []
        ang4s = []
        ang5s = []

        for sect in range(0, num_sects):
            heading_rad = headings[sect] / (2**31) * math.pi
            heading_sin = -math.sin(heading_rad)
            heading_cos = math.cos(heading_rad)

            if sgfile.sects[sect].type == 1:
                ang3 = 2**30 * heading_sin
                ang4 = heading_cos * 2**30
                ang5 = 2**30 - 2 * (2**30 - sgfile.sects[sect].length / adj_length[sect] * 2**30)
                ang2 = -ang3 - (-ang3 + heading_sin * ang5) / 2
                ang1 = ang4 - (ang4 - (heading_cos * ang5)) / 2
            elif sgfile.sects[sect].type == 2:
                ang1 = sgfile.sects[sect].center_x
                ang2 = sgfile.sects[sect].center_y
                if sect == num_sects - 1:
                    ang3 = (headings[0] - headings[sect]) / 2
                else:
                    ang3 = (headings[sect + 1] - headings[sect]) / 2
                if ang3 < -2**30:
                    ang3 = 2**31 + ang3
                if ang3 > 2**30:
                    ang3 = ang3 - 2**31
                ang4 = -858993460
                ang5 = -858993460
            ang1s.append(ang1)
            ang2s.append(ang2)
            ang3s.append(ang3)
            ang4s.append(ang4)
            ang5s.append(ang5)

        xsect_counter = []
        for i in range(0, num_sects):
            xsect_counter.append(i * num_xsects)

        ground_counter = []
        for sect in range(0, num_sects):
            if sect == 0:
                ground_counter.append(0)
            else:
                ground_counter.append(sgfile.sects[sect - 1].num_ground_fsects + ground_counter[sect - 1])

        sects = []
        for sect in range(num_sects):
            sec_data = [
                sgfile.sects[sect].type,
                start_dlong[sect],
                adj_length[sect],
                headings[sect],
                ang1s[sect],
                ang2s[sect],
                ang3s[sect],
                ang4s[sect],
                ang5s[sect],
                xsect_counter[sect],
                sgfile.sects[sect].num_ground_fsects,
                ground_counter[sect],
                sgfile.sects[sect].num_boundaries,
            ]
            for i in range(0, sgfile.sects[sect].num_boundaries):
                walltype = convert_wall_fsect_type(sgfile.sects[sect].bound_ftype1[i], sgfile.sects[sect].bound_ftype2[i])
                sec_data.extend(
                    [
                        walltype,
                        sgfile.sects[sect].bound_fstart[i],
                        sgfile.sects[sect].bound_fend[i],
                        -858993460,
                        -858993460,
                    ]
                )
            sects.append(cls.Section(sec_data, num_xsects))

        sect_offsets = [0]
        for sect in range(1, num_sects):
            section_length = 13 + 5 * sgfile.sects[sect - 1].num_boundaries
            sect_offsets.append(sect_offsets[sect - 1] + section_length)

        len_sects = sect_offsets[-1] + 13 + 5 * sgfile.sects[num_sects - 1].num_boundaries

        header = [
            1414676811,
            1,
            sum(adj_length),
            num_xsects,
            num_sects,
            len_ground_data * 4,
            len_sects * 4,
        ]

        return cls(header, xsect_dlats, sect_offsets, xsect_data, ground_data, sects)

    class Section:
        def __init__(self, sec_data, num_xsects):
            self.type = sec_data[0]
            self.start_dlong = sec_data[1]
            self.length = sec_data[2]
            self.heading = round(sec_data[3])
            self.ang1 = round(sec_data[4])
            self.ang2 = round(sec_data[5])
            self.ang3 = round(sec_data[6])
            self.ang4 = round(sec_data[7])
            self.ang5 = round(sec_data[8])
            self.xsect_counter = sec_data[9]
            self.ground_fsects = sec_data[10]
            self.ground_counter = sec_data[11]
            self.num_bounds = sec_data[12]

            self.ground_type = []
            self.ground_dlat_start = []
            self.ground_dlat_end = []

            self.bound_type = []
            self.bound_dlat_start = []
            self.bound_dlat_end = []

            self.grade1 = []
            self.grade2 = []
            self.grade3 = []
            self.grade4 = []
            self.grade5 = []
            self.alt = []
            self.pos1 = []
            self.pos2 = []

            for bound in range(0, self.num_bounds):
                bound_start = 13 + bound * 5
                self.bound_type.append(sec_data[bound_start])
                self.bound_dlat_start.append(sec_data[bound_start + 1])
                self.bound_dlat_end.append(sec_data[bound_start + 2])
