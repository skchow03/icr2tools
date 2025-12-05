import numpy as np
import csv

class SGFile:
    """
    This class represents an .SG file which is used to further create a .TRK
    file for Papyrus IndyCar Racing 2.

    The SGFile object is created using the information from an existing SG file,
    or from corresponding header and sections CSV files. This object is 
    capable of parsing the SG file structure into its different components,
    which includes the header information, xsections, and sections.

    Each section in the SG file corresponds to a `Section` object and these 
    sections are stored in the `sects` list attribute of the `SGFile` object.

    The `SGFile` object can output its information into different forms: 
    it can output the header and xsect information into a CSV file, 
    the section information into a different CSV file, or it can regenerate 
    an SG file using its current information.

    Attributes
    ----------
    header : ndarray
        Header information from the SG file.
    num_sects : int
        Number of sections in the SG file.
    num_xsects : int
        Number of cross sections (xsects) in the SG file.
    xsect_dlats : ndarray
        Cross section deltas in latitude (DLATs) in the SG file.
    sects : list
        List of `Section` objects corresponding to sections in the SG file.
    """
    def __init__(self, header, num_sects, num_xsects, xsect_dlats, sects):
        self.header = header
        self.num_sects = num_sects
        self.num_xsects = num_xsects
        self.xsect_dlats = xsect_dlats
        self.sects = sects
    
    # Fix sang and eang for straight sections
    


    @classmethod
    def from_sg(cls, file_name):
        """
        Creates an SGFile object from the provided SG file.

        The method reads the SG file, extracts the header and section information,
        and maps these values into the corresponding attributes of the SGFile object. 
        Each section in the SG file is expected to correspond to a Section object.

        Args:
            file_name (str): The path to the SG file.

        Returns:
            SGFile: A new SGFile instance with attributes populated from the SG file.
        """

        print ('Opening SG file {}'.format(file_name))

        a = np.fromfile(file_name, dtype=np.int32)

        header = a[0:6]
        num_sects = header[4]
        num_xsects = header[5]
        xsect_dlats = a[6:num_xsects + 6]
        sections_start = num_xsects + 6
        sections_length = 58 + 2 * num_xsects

        # Read each section and store each section object into the sects list.
        sects = []
        for i in range(0,num_sects):
            sec_data = a[sections_start + i * sections_length: \
                         sections_start + (i + 1) * sections_length]
            sects.append(cls.Section(sec_data, num_xsects))
        return cls(header, num_sects, num_xsects, xsect_dlats, sects)


    @classmethod
    def from_csv(cls, header_file_name, sections_file_name):
        """
        Creates an SGFile object from the provided header and sections CSV files.

        The method reads the header CSV file and sections CSV file, and maps 
        the read values into the corresponding attributes of the SGFile object. 
        Each row in the sections CSV file is expected to correspond to a Section 
        object. The header CSV file is expected to contain only one row.

        Args:
            header_file_name (str): The path to the header CSV file.
            sections_file_name (str): The path to the sections CSV file.

        Returns:
            SGFile: A new SGFile instance with attributes populated from the CSV files.
        """
        
        print ('Opening CSV files {} and {}...'.format(header_file_name, sections_file_name), end='')
        
        with open(header_file_name, 'r') as f:
            reader = csv.reader(f)
            next(reader)  # Skip header row
            header_data = next(reader)  # assumes only one row of header data

        header = list(map(int, header_data[0:6]))
        num_sects = int(header_data[4])
        num_xsects = int(header_data[5])
        xsect_dlats = list(map(int, header_data[6:num_xsects+6]))

        sects = []
        with open(sections_file_name, 'r') as f:
            reader = csv.reader(f)
            next(reader)  # Skip header row
            for sec_data in reader:
                sec_data = list(map(int, sec_data))[1:]  # convert to integers
                sects.append(cls.Section(sec_data, num_xsects))
        return cls(header, num_sects, num_xsects, xsect_dlats, sects)

    class Section:
        """
        A class used to represent a Section within an SG file.

        This class contains a variety of attributes representing information about a section,
        including its type, location, height, grade, and other details.

        Attributes
        ----------
        type : int
            The type of the section (1 = line, 2 = curve)
        sec_next : int
            The next section in the track.
        sec_prev : int
            The previous section in the track.
        start_x, start_y, end_x, end_y : int
            Coordinates for the start and end of the section.
        start_dlong, length : int
            The starting DLONG and the length of the section.
        center_x, center_y : int
            The coordinates for the center of the circle defining the curve.
        sang1, sang2, eang1, eang2 : int
            Sine and cosine of the start and ending headings for the section.
        radius : int
            The radius of a curved section.
        num1 : int
            An unknown attribute of the section.
        alt : list of int
            The altitude data for the section's xsects.
        grade : list of int
            The grade data for the section's xsects.
        num_fsects : int
            The number of fsects in the section.
        ftype1, ftype2 : list of int
            The type attributes for the section's fsects.
        fstart, fend : list of int
            The start and end DLATs for the section's fsects.
        """
        def __init__(self, sec_data, num_xsects):

            # Read header
            self.type = sec_data[0]
            self.sec_next = sec_data[1]
            self.sec_prev = sec_data[2]
            self.start_x = sec_data[3]
            self.start_y = sec_data[4]
            self.end_x = sec_data[5]
            self.end_y = sec_data[6]
            self.start_dlong = sec_data[7]
            self.length = sec_data[8]
            self.center_x = sec_data[9]
            self.center_y = sec_data[10]
            self.sang1 = sec_data[11]
            self.sang2 = sec_data[12]
            self.eang1 = sec_data[13]
            self.eang2 = sec_data[14]
            self.radius = sec_data[15]
            self.num1 = sec_data[16]
            self.end_dlong = self.start_dlong + self.length

            # Read height and grade data
            self.alt = []
            self.grade = []
            for i in range(0, num_xsects):
                self.alt.append(sec_data[17 + 2 * i])
                self.grade.append(sec_data[18 + 2 * i])

            # Read fsections
            fsect_start = 17 + 2 * num_xsects
            self.num_fsects = sec_data[fsect_start]
            self.ftype1 = []
            self.ftype2 = []
            self.fstart = []
            self.fend = []

            self.ground_ftype = []
            self.ground_fstart = []
            self.ground_fend = []

            self.bound_ftype1 = []
            self.bound_ftype2 = []
            self.bound_fstart = []
            self.bound_fend = []


            for i in range(0, self.num_fsects):
                ftype1 = sec_data[fsect_start+1+ i*4]
                ftype2 = sec_data[fsect_start+2+ i*4]
                fstart = sec_data[fsect_start+3+ i*4]
                fend = sec_data[fsect_start+4+ i*4]

                self.ftype1.append(ftype1)
                self.ftype2.append(ftype2)
                self.fstart.append(fstart)
                self.fend.append(fend)

                # create separate lists for ground and boundaries
                if ftype1 in [0,1,2,3,4,5,6]:
                    self.ground_ftype.append(ftype1)
                    self.ground_fstart.append(fstart)
                    self.ground_fend.append(fend)
                else:
                    self.bound_ftype1.append(ftype1)
                    self.bound_ftype2.append(ftype2)
                    self.bound_fstart.append(fstart)
                    self.bound_fend.append(fend)

            self.num_ground_fsects = len(self.ground_ftype)
            self.num_boundaries = len(self.bound_ftype1)

    def output_sg_header_xsects(self, output_file):
        """
        Outputs the header and xsect DLATs data from the SGFile to a CSV file.
        
        Args:
            output_file (str): The path and name of the CSV file to be written.
        """

        print('Exporting header and xsect data to {}...'.format(output_file), end='')

        with open(output_file, 'w', newline='') as o:
            writer = csv.writer(o)
            
            # Output headers
            headers = ['filetype', 'unknown1', 'unknown2', 'unknown3', 'number_of_sects', 'number_of_xsects']
            xsect_headers = ['Xsect_DLAT_'+str(i+1) for i in range(10)] # assuming a maximum of 10 DLATs
            writer.writerow(headers + xsect_headers)

            # Output header values and xsect DLATs
            header_values = list(self.header)
            xsect_dlats_values = self.xsect_dlats.tolist() + [0]*(10-len(self.xsect_dlats)) # fill with zeros if less than 10
            writer.writerow(header_values + xsect_dlats_values)
        print ('done')

    def output_sg_sections(self, output_file):
        """
        Outputs the sections data from the SGFile to a CSV file.

        Args:
            output_file (str): The path and name of the CSV file to be written.
        """
        print ('Exporting data to {}...'.format(output_file), end='')

        with open(output_file, 'w') as o:

            # Output headers
            o.write(
                'sec,type,sec_next,sec_prev,start_x,start_y,end_x,end_y,'
                'start_dlong,length,center_x,center_y,sang1,sang2,eang1,'
                'eang2,radius,num1'
            )
            for i in range(0,self.num_xsects):
                cur_xsect = ',xsect' + str(i)
                o.write(cur_xsect + '_alt'
                        + cur_xsect + '_grade')
            o.write(',fsects_count')
            for i in range(0,10):
                cur_fsect = ',fsect' + str(i)
                o.write(cur_fsect + '_ftype1' + cur_fsect + '_ftype2'
                        + cur_fsect + '_fstart' + cur_fsect +'_fend')
            o.write('\n')

            # Output section info
            for i in range(0, self.num_sects):
                cur = self.sects[i]
                type = cur.type

                output_string = (
                    f'{i},{type},{cur.sec_next},{cur.sec_prev},{cur.start_x},'
                    f'{cur.start_y},{cur.end_x},{cur.end_y},{cur.start_dlong},{cur.length},'
                    f'{cur.center_x},{cur.center_y},{cur.sang1},{cur.sang2},{cur.eang1},'
                    f'{cur.eang2},{cur.radius},{cur.num1}'
                )

                o.write(output_string)

                # Output grade and alt for each section
                for j in range(0,self.num_xsects):
                    cur_xsect_alt = str(cur.alt[j])
                    cur_xsect_grade = str(cur.grade[j])
                    output_string = ',{},{}'.format(cur_xsect_alt,
                                                       cur_xsect_grade)
                    o.write(output_string)

                # Output fsects for each section
                o.write(','+str(cur.num_fsects))

                for j in range(0,10):
                    if j < cur.num_fsects:
                        cur_fsect_ftype1 = cur.ftype1[j]
                        cur_fsect_ftype2 = cur.ftype2[j]
                        cur_fsect_fstart = str(cur.fstart[j])
                        cur_fsect_fend = str(cur.fend[j])
                        output_string = f',{cur_fsect_ftype1},{cur_fsect_ftype2},{cur_fsect_fstart},{cur_fsect_fend}'
                        o.write(output_string)
                    else:
                        o.write(',0,0,0,0')

                o.write('\n')
        print ('done')

    def _build_output_array(self):
        output_array = []
        output_array.extend(self.header)
        output_array.extend(self.xsect_dlats)
        for i in range(0,self.num_sects):
            output_array.extend([self.sects[i].type])
            output_array.extend([self.sects[i].sec_next])
            output_array.extend([self.sects[i].sec_prev])
            output_array.extend([self.sects[i].start_x])
            output_array.extend([self.sects[i].start_y])
            output_array.extend([self.sects[i].end_x])
            output_array.extend([self.sects[i].end_y])
            output_array.extend([self.sects[i].start_dlong])
            output_array.extend([self.sects[i].length])
            output_array.extend([self.sects[i].center_x])
            output_array.extend([self.sects[i].center_y])
            output_array.extend([self.sects[i].sang1])
            output_array.extend([self.sects[i].sang2])
            output_array.extend([self.sects[i].eang1])
            output_array.extend([self.sects[i].eang2])
            output_array.extend([self.sects[i].radius])
            output_array.extend([self.sects[i].num1])       # Unknown value
            for j in range(0,self.num_xsects):
                output_array.extend([self.sects[i].alt[j]])
                output_array.extend([self.sects[i].grade[j]])
            output_array.extend([self.sects[i].num_fsects])
            for j in range(0,self.sects[i].num_fsects):
                output_array.extend([self.sects[i].ftype1[j]])
                output_array.extend([self.sects[i].ftype2[j]])
                output_array.extend([self.sects[i].fstart[j]])
                output_array.extend([self.sects[i].fend[j]])
            unused_fsects = 10-self.sects[i].num_fsects
            for j in range(0, unused_fsects):
                output_array.extend([0,0,0,0])

        return np.array(output_array)

    def output_bytes(self):
        """Return the binary SG representation as bytes."""

        output_array = self._build_output_array()
        return output_array.astype('int32').tobytes()

    def output_sg(self, output_file):
        """
        Regenerates an SG file from the current SGFile object.

        Args:
            output_file (str): The path and name of the SG file to be written.
        """

        print ('Creating SG file {}...'.format(output_file),end='')

        output_array = self._build_output_array()
        output_array.astype('int32').tofile(output_file)
        print ('done')