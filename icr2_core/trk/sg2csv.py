import argparse
from sg_classes import SGFile

def main():
    parser = argparse.ArgumentParser(description='Convert SG file to CSV.')
    parser.add_argument('sgfile', help='The SG file to process')

    args = parser.parse_args()
    sg_file_name = args.sgfile

    output_file = sg_file_name + '_sects.csv'
    header_xsects_file = sg_file_name + '_header_xsects.csv'

    sgfile = SGFile.from_sg(sg_file_name)
    sgfile.output_sg_sections(output_file)
    sgfile.output_sg_header_xsects(header_xsects_file)

if __name__ == '__main__':
    main()
