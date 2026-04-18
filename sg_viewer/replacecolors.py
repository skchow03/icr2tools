import re

def read_color_definitions(colors_file):
    """Reads the color definitions from the colors.txt file"""
    colors = {}
    with open(colors_file, 'r') as file:
        for line in file:
            # Extract color definitions in the format: __ColorName__: [<0, 0, 0>, c= <value>];
            match = re.match(r'(__\w+__):\s*(\[<.*>\]);', line)
            if match:
                color_name, color_value = match.groups()
                colors[color_name] = color_value
    return colors

def replace_color_definitions(track_file, colors):
    """Replaces the color definitions in the track.3d file with the new ones from colors"""
    with open(track_file, 'r') as file:
        content = file.readlines()
    
    # Iterate over the content and replace matching color definitions
    updated_content = []
    for line in content:
        # Check if the line defines a color and extract the name
        match = re.match(r'(__\w+__):\s*(\[<.*>\]);', line)
        if match:
            color_name = match.group(1)
            # Replace the line if the color name is in the provided colors dictionary
            if color_name in colors:
                line = f'{color_name}: {colors[color_name]};\n'
        updated_content.append(line)
    
    # Write the updated content back to the track.3d file
    with open(track_file, 'w') as file:
        file.writelines(updated_content)

def main():
    track_file = 'nash.3d'
    colors_file = 'colors.txt'
    
    # Read the new color definitions from the colors file
    colors = read_color_definitions(colors_file)
    
    # Replace the color definitions in the arling.3d file
    replace_color_definitions(track_file, colors)
    print("Color definitions have been replaced and saved in {}".format(track_file))

if __name__ == "__main__":
    main()
