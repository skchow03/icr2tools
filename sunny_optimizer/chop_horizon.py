from pathlib import Path
from tkinter import Tk, Button, Label, Entry, filedialog, StringVar, messagebox
from PIL import Image


def chop_horizon(input_path, output_dir):
    input_path = Path(input_path)
    output_dir = Path(output_dir)

    img = Image.open(input_path).convert("RGBA")

    if img.size != (2048, 64):
        raise ValueError(f"Expected 2048x64 image, got {img.size}")

    segments = []
    for i in range(8):
        left = i * 256
        segments.append(img.crop((left, 0, left + 256, 64)))

    sheets = []

    for sheet_index in range(2):
        sheet = Image.new("RGBA", (256, 256), (0, 0, 0, 0))

        for row in range(4):
            segment_index = sheet_index * 4 + row
            sheet.paste(segments[segment_index], (0, row * 64))

        sheets.append(sheet)

    output_dir.mkdir(parents=True, exist_ok=True)

    base = input_path.stem
    out1 = output_dir / f"{base}_sheet_1.png"
    out2 = output_dir / f"{base}_sheet_2.png"

    sheets[0].save(out1)
    sheets[1].save(out2)

    return out1, out2


def choose_source():
    filename = filedialog.askopenfilename(
        title="Choose source horizon texture",
        filetypes=[
            ("Image files", "*.png *.bmp"),
            ("PNG files", "*.png"),
            ("BMP files", "*.bmp"),
            ("All files", "*.*"),
        ],
    )

    if filename:
        source_var.set(filename)

        # Default output folder to the source image folder
        output_var.set(str(Path(filename).parent))


def choose_output_folder():
    folder = filedialog.askdirectory(
        title="Choose output folder"
    )

    if folder:
        output_var.set(folder)


def run_conversion():
    source = source_var.get().strip()
    output = output_var.get().strip()

    if not source:
        messagebox.showerror("Missing source image", "Choose a source PNG or BMP file.")
        return

    if not output:
        messagebox.showerror("Missing output folder", "Choose an output folder.")
        return

    try:
        out1, out2 = chop_horizon(source, output)
    except Exception as e:
        messagebox.showerror("Conversion failed", str(e))
        return

    messagebox.showinfo(
        "Done",
        f"Created:\n\n{out1}\n{out2}"
    )


root = Tk()
root.title("Horizon Texture Chopper")
root.geometry("650x180")

source_var = StringVar()
output_var = StringVar()

Label(root, text="Source image:").grid(row=0, column=0, padx=10, pady=10, sticky="e")
Entry(root, textvariable=source_var, width=65).grid(row=0, column=1, padx=5, pady=10)
Button(root, text="Browse...", command=choose_source).grid(row=0, column=2, padx=10, pady=10)

Label(root, text="Output folder:").grid(row=1, column=0, padx=10, pady=10, sticky="e")
Entry(root, textvariable=output_var, width=65).grid(row=1, column=1, padx=5, pady=10)
Button(root, text="Browse...", command=choose_output_folder).grid(row=1, column=2, padx=10, pady=10)

Button(root, text="Create 256x256 Sheets", command=run_conversion).grid(
    row=2, column=1, pady=20
)

root.mainloop()