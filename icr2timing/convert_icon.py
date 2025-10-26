from PIL import Image

src = "assets/icon.png"      # your PNG
dst = "assets/icon.ico"

# Open and ensure transparency + square format
img = Image.open(src).convert("RGBA")
size = max(img.width, img.height)
img = img.resize((size, size), Image.LANCZOS)

# Build true multi-size icon (Windows expects these sizes)
img.save(dst, sizes=[
    (16,16),
    (24,24),
    (32,32),
    (48,48),
    (64,64),
    (128,128),
    (256,256)
])

print("✅ Multi-size icon saved as:", dst)
