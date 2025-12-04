import argparse
from trk_classes import TRKFile
from trk_exporter import write_trk, write_txt, write_csv

def sg_to_trk(sg_file, export_format, output_file=None):
    # Load the .sg file using TRKFile.from_sg method
    trk_file = TRKFile.from_sg(sg_file)

    # If no output file name is specified, use the input file name
    if output_file is None:
        output_file = sg_file.split(".")[0]

    # Export to .trk, .txt or .csv using the appropriate method
    if export_format == 'trk':
        write_trk(trk_file, f'{output_file}.trk')
    elif export_format == 'txt':
        write_txt(trk_file, f'{output_file}.txt')
    elif export_format == 'csv':
        write_csv(trk_file, output_file)

def main():
    parser = argparse.ArgumentParser(description='Converts .sg file to .trk, .txt or .csv file.')
    parser.add_argument('sg_file', type=str, help='Input .sg file to be converted.')
    parser.add_argument('-f', '--format', type=str, choices=['trk', 'txt', 'csv'], default='trk', help='Output format. Can be "trk", "txt" or "csv". Default is "trk".')
    parser.add_argument('-o', '--output', type=str, help='Optional output file name without extension. If not provided, input file name is used.')

    args = parser.parse_args()
    sg_to_trk(args.sg_file, args.format, args.output)

if __name__ == "__main__":
    main()
