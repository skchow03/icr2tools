import pandas as pd

def write_obj(filename, vertices, faces, colors):
    with open(filename, 'w') as f:
        f.write("mtllib colors.mtl\n")  # Reference the .mtl file

        for v in vertices:
            f.write("v {} {} {}\n".format(v[0], v[1], v[2]))
        
        for face, color in zip(faces, colors):
            f.write("usemtl {}\n".format(color))  # Use the color for this face
            f.write("f")
            for vertex in face:
                f.write(" {}".format(vertex))
            f.write("\n")

def csv2obj(csvfile, outputfile):
    # Read the polygons from the CSV file
    polygons = pd.read_csv(csvfile)

    vertices = []
    faces = []
    colors = []

    vertex_count = 1
    for _, polygon in polygons.iterrows():
        vertex_indices = []
        for i in range(1, 5):
            x, y, z = polygon[f'x{i}'], polygon[f'y{i}'], polygon[f'z{i}']
            vertices.append((x, y, z))
            vertex_indices.append(vertex_count)
            vertex_count += 1
        faces.append(vertex_indices)
        colors.append(polygon['color'])  # Save the color of each polygon

    write_obj(outputfile, vertices, faces, colors)
