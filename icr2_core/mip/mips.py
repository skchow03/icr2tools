from PIL import Image
import math
import struct
import numpy as np

def blank_img(palette):
    """ Returns a blank image of 256x256 size.

    Arguments:
    palette -- PIL image that has the desired game palette (either sunny.pcx
        or gamepal.pcx)
    """
    img_array = np.zeros((256,256), dtype="uint8")
    im = Image.fromarray(img_array, mode="P")
    im.putpalette(palette)
    return im

def distance(color1, color2):
    """ Given two RGB colors, returns the distance between the two colors

    Arguments:
    color1 -- a 3-tuple representing an RGB color
    color2 -- a 3-tuple representing an RGB color
    """
    return math.sqrt(
        ((color2[0]-color1[0])**2) + ((color2[1]-color1[1])**2) +
        ((color2[2]-color1[2])**2))

def match_closest_color(source_rgb, palette, min_range, max_range):
    """ Given a source color and a palette (in dictionary form), returns the
    palette index of the closest color. Specify the valid color index range in
    the palette.

    Arguments:
    source_rgb -- a 3-tuple representing an RGB color to match
    palette -- a dictionary where the indices are the color number and values
        are RGB tuples
    min_range -- for carsets that do not use all the colors, specify the first
        usable color (usually 32)
    max_range -- for carsets that do not use all the colors, specify the last
        usable color (usually 177)
    """
    distances = []
    for colorid in range(min_range,max_range):
        distances.append(distance(source_rgb, palette[colorid]))
    return distances.index(min(distances))+min_range

def bmp_to_img(bmp_file_path):
    """ Opens a bmp and returns it as a PIL image
    """
    im = Image.open(bmp_file_path)
    return im

def _quantize_to_palette(im_rgb, palette_img, *, dither=False):
    dither_mode = Image.Dither.FLOYDSTEINBERG if dither else Image.Dither.NONE
    return im_rgb.quantize(colors=256, method=2, palette=palette_img, dither=dither_mode)


def img_to_mip(im, output_file_path, palette_path, mode, num_images=0, dither=False):
    """ Loads an image from memory and converts it to a .mip file. Special
    handling for cars which use a limited palette. Palette_path should point to
    sunny.pcx for tracks and gamepal.pcx for cars.

    Arguments:
    im -- PIL image in memory
    output_file_path -- where the .mip file will be saved
    palette_path -- should point to sunny.pcx for tracks and gamepal.pcx for cars
    mode -- must be either "carset" or "track"; determines how to handle palettes
    num_images -- how many MIP images (default = 0, to automatically calculate
        how many images are appropriate depending on resolution)
    """

    gamepal = Image.open(palette_path)
    quantized_base = _quantize_to_palette(im.convert(mode="RGB"), gamepal, dither=dither)
    img_pixels = list(quantized_base.getdata())

    # If this is for a car, create a dictionary of RGB values for each color
    # in the palette so that the tool can match the colors manually. This is
    # not needed for tracks because we can use all the colors in sunny.pcx and
    # we will use PIL to apply the palette.
    if mode == "carset":
        gamepal_pal = gamepal.getpalette()
        gamepal_rgb = dict()
        for color_id in range(0,256):
            gamepal_rgb.update({color_id:(gamepal_pal[color_id*3],
                                gamepal_pal[color_id*3+1],
                                gamepal_pal[color_id*3+2])})

        # Go through each pixel and if outside the valid range, match the
        # closest color from the valid range in the palette.

        # First do the color matching over the game palette
        cars_pal = dict()
        for color_id in range(0,256):
            if 32 <= color_id < 176:
                cars_pal.update({color_id: color_id})
            else:
                new_color_id = match_closest_color(gamepal_rgb[color_id],
                    gamepal_rgb, 32, 177)
                cars_pal.update({color_id: new_color_id})

        # Now apply to the car texture
        adj_pixels_list = []
        for pixel in img_pixels:
            new_pixel = cars_pal[pixel]
            adj_pixels_list.append(new_pixel)
        img_pixels = [adj_pixels_list]

    else:
        img_pixels = [img_pixels]

    # For both cars and tracks, get the full size of the image and convert it
    # to RGB for scaling later.
    orig_width, orig_height = im.size
    im = im.convert(mode="RGB")

    # Decide number of images automatically if num images is zero.
    if num_images == 0:
        if orig_width <= 16:
            num_images = 4
        elif orig_width <= 32:
            num_images = 5
        elif orig_width <= 64:
            num_images = 6
        elif orig_width <= 128:
            num_images = 7
        elif orig_width <= 256:
            num_images = 8
        elif orig_width <= 512:
            num_images = 9

    # Set up lists with initial values for the original image
    img_scale1 = [orig_width-1]
    img_scale2 = [0]
    buffer_size = [orig_width]
    img_size = [orig_width*orig_height]
    scaled_width = [orig_width]
    scaled_height = [orig_height]

    # Scale down the image n times based on specified number of images
    for img_id in range(1,num_images):

        # Calculate the width and height of resized image, then perform the resize
        scaled_width.append(int(scaled_width[img_id-1]/2 + 0.5))
        scaled_height.append(int(scaled_height[img_id-1]/2 + 0.5))
        im_scaled = im.resize((scaled_width[img_id], scaled_height[img_id]), Image.LANCZOS)
        im_scaled = _quantize_to_palette(im_scaled, gamepal, dither=dither)

        # Record the subimage size and the actual subimage as a list
        img_size.append(scaled_width[img_id] * scaled_height[img_id])

        if mode=="track":
            img_pixels.append(list(im_scaled.getdata()))

        if mode=="carset":
            im_scaled_pixels = list(im_scaled.getdata())
            adj_pixels_list = []
            for pixel in im_scaled_pixels:
                new_pixel = cars_pal[pixel]
                adj_pixels_list.append(new_pixel)
            img_pixels.append(adj_pixels_list)

        # Calculate the scaling factors that form part of the header
        cur_scale = scaled_width[img_id]-1
        img_scale1.append(cur_scale)
        if cur_scale >= 127:
            img_scale2.append(0)
        elif cur_scale >= 63:
            img_scale2.append(128)
        elif cur_scale >= 31:
            img_scale2.append(192)
        elif cur_scale >= 15:
            img_scale2.append(224)
        elif cur_scale >= 7:
            img_scale2.append(240)
        elif cur_scale >= 3:
            img_scale2.append(248)
        elif cur_scale >= 1:
            img_scale2.append(252)
        else:
            img_scale2.append(255)

        # For purposes of calculating the correct offsets, calculate the size of
        # the buffer (i.e. duplicate rows before and after a subimage)
        buffer_size.append(img_scale1[img_id-1]+1 + scaled_width[img_id])

    # Calculate the buffer size after the last image
    buffer_size.append(img_scale1[num_images - 1] + 1)

    # Calculate the average color
    avg_color = im.resize((1,1), Image.LANCZOS)
    avg_color = _quantize_to_palette(avg_color, gamepal, dither=dither)
    avg_color = list(avg_color.getdata())[0]

    # Calculate header size
    header_size = 20 + 12 * (num_images)
    file_size = sum(buffer_size) + sum(img_size) + header_size

    # Calculate offsets
    offsets = [header_size + scaled_width[0]]
    for img_id in range(1, num_images):
        cur_offset = (offsets[img_id-1] + img_size[img_id-1]
            + scaled_width[img_id-1] + scaled_width[img_id])
        offsets.append(cur_offset)

    # Write data
    with open(output_file_path, "wb") as output_file:

        # Header
        output_file.write(int.to_bytes(file_size,4,byteorder="little"))
        output_file.write(int.to_bytes(0,4,byteorder="little"))
        output_file.write(int.to_bytes(scaled_width[0],4,byteorder="little"))
        output_file.write(int.to_bytes(scaled_height[0],4,byteorder="little"))
        output_file.write(int.to_bytes(num_images,4,byteorder="little"))
        output_file.write(int.to_bytes(avg_color,4,byteorder="little"))

        # Main image header
        output_file.write(int.to_bytes(img_scale1[0],4,byteorder="little"))
        output_file.write(int.to_bytes(img_scale2[0],1,byteorder="little"))

        if num_images == 8:
            output_file.write(int.to_bytes(254,1,byteorder="little"))
        else:
            output_file.write(int.to_bytes(255,1,byteorder="little"))
        output_file.write(int.to_bytes(255,1,byteorder="little"))
        output_file.write(int.to_bytes(255,1,byteorder="little"))
        output_file.write(int.to_bytes(offsets[0],4,byteorder="little"))

        # Subimage headers
        for img_id in range(1,num_images):
            output_file.write(int.to_bytes(img_scale1[img_id],4,byteorder="little"))
            output_file.write(int.to_bytes(img_scale2[img_id],1,byteorder="little"))
            for _ in range(0,3):
                output_file.write(int.to_bytes(255,1,byteorder="little"))
            output_file.write(int.to_bytes(offsets[img_id],4,byteorder="little"))

        # Write each image
        for img_id in range(0,num_images):
            output_file.write(bytes(img_pixels[img_id][0:scaled_width[img_id]]))
            output_file.write(bytes(img_pixels[img_id]))
            # buffer
            output_file.write(bytes(img_pixels[img_id][-scaled_width[img_id]::]))

def img_to_bmp(im, output_file_path):
    """ Saves a PIL image to .bmp
    """
    im.save(output_file_path)

def save_palette_pcx(palette, output_file_path):
    img_array = np.zeros((128,128), dtype="uint8")
    im = Image.fromarray(img_array, mode="P")
    im.putpalette(palette)
    im.save(output_file_path)

def load_palette(palette_file_path):
    """ Loads a palette file (usually a .pcx) and converts to PIL palette
    """
    im = Image.open(palette_file_path)
    return im.getpalette()

def fread(fdata, offset):
    return struct.unpack("<i",fdata[offset:offset + 4])[0]

def fread2(fdata, offset):
    return struct.unpack("B",fdata[offset:offset + 1])[0]

def mip_to_img(mip_file_path, palette):
    """ Loads a .mip file and turns it into a PIL image

    Arguments:
    mip_file_path -- file path to the .mip file
    palette -- palette file to apply to the .mip (usually from sunny.pcx or
        gamepal.pcx, should be loaded as a PIL image prior to running this
        function)
    """

    # Open the .mip file
    with open(mip_file_path, "rb") as f:
        fdata = f.read()
 
        # Read header
        file_size = fread(fdata, 0)

        # Rest the rest of the file
        fdata = fdata[4:]

        width = fread(fdata, 4)
        height = fread(fdata, 8)
        num_images = fread(fdata, 12)
        color = fread(fdata, 16)
        width_minus_one = fread(fdata, 20)
        unknown1 = fread(fdata, 24)
        first_offset = fread(fdata, 28)

        print ('Header')
        print (f'File size = {file_size}')
        print (f'Width = {width}, Height = {height}')
        print (f'Number of images = {num_images}')
        print (f'Color = {color}')
        print (f'Width minus one = {width_minus_one}')
        print (f'Unknown = {unknown1}')               # negative width * 2
        print (f'First offset = {first_offset}')

        # Read subheader for each subimage
        img_scale_down=[]
        img_scale_up=[]
        subimg_offsets=[]
        for img_id in range(0,num_images-1):
            offset = 32 + img_id * 12
            img_scale_down.append(fread(fdata, offset))   # Buffer index
            img_scale_up.append(fread(fdata, offset + 4))
            subimg_offsets.append(fread(fdata, offset + 8))
            print (f'Image ID {img_id}: Offset {subimg_offsets[img_id]}; Scale {img_scale_down[img_id]}, {img_scale_up[img_id]}')

        # Read main image data
        offset = first_offset
        img_pixels = []
        for _ in range(0,height*width):
            pixel = fread2(fdata, offset)
            img_pixels.append(pixel)
            offset += 1

        ims = []

        # Convert to numpy array, then convert to PIL image
        img_array = np.array(img_pixels, dtype="uint8")
        img_array = img_array.reshape(height,width)
        im = Image.fromarray(img_array, mode="P")
        im.putpalette(palette)

        ims.append(im)
        # Read subimages

        for img_id in range(0, num_images - 1):
            img_pixels = []
            offset = subimg_offsets[img_id] + img_scale_down[img_id] - img_scale_down[img_id]
            sub_height = int(height / (2 ** (img_id + 1)))
            sub_width = int(width / (2 ** (img_id + 1)))
            if sub_height == 0: sub_height = 1
            if sub_width == 0: sub_width = 1

            print (f'Subimage {img_id} W {sub_width} H {sub_height}')
            for _ in range(0, sub_height * sub_width):
                pixel = fread2(fdata, offset)
                img_pixels.append(pixel)
                offset += 1

            img_array = np.array(img_pixels, dtype="uint8")
            img_array = img_array.reshape(sub_height,sub_width)
            im = Image.fromarray(img_array, mode="P")
            im.putpalette(palette)

            ims.append(im)

        return ims

# palette = load_palette('sunny.pcx')
# # img = mip_to_img('page03.mip',palette)
# # img_to_bmp(img,'page03.bmp')

# imgs = mip_to_img('armco0.mip',palette)

# print (len(imgs))

# for id in range(0, len(imgs)):
#     file_name = f'mip{id}.bmp'
#     print (f'Writing to {file_name}')
#     img_to_bmp(imgs[id],file_name)
