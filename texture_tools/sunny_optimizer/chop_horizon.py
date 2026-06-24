from __future__ import annotations

from pathlib import Path
from tkinter import Button, Entry, Label, Spinbox, StringVar, Tk, filedialog, messagebox

from PIL import Image


def chop_horizon(input_path: str | Path, output_dir: str | Path, start_panel: int = 1) -> tuple[Path, Path]:
    input_path = Path(input_path)
    output_dir = Path(output_dir)

    if not 1 <= start_panel <= 8:
        raise ValueError(f"Start panel must be between 1 and 8, got {start_panel}")

    img = Image.open(input_path).convert("RGBA")

    if img.size != (2048, 64):
        raise ValueError(f"Expected 2048x64 image, got {img.size}")

    segments = []
    for i in range(8):
        left = i * 256
        segments.append(img.crop((left, 0, left + 256, 64)))

    start_index = start_panel - 1
    ordered_segments = segments[start_index:] + segments[:start_index]

    sheets = []
    for sheet_index in range(2):
        sheet = Image.new("RGBA", (256, 256), (0, 0, 0, 0))
        for row in range(4):
            segment_index = sheet_index * 4 + row
            sheet.paste(ordered_segments[segment_index], (0, row * 64))
        sheets.append(sheet)

    output_dir.mkdir(parents=True, exist_ok=True)

    base = input_path.stem
    out1 = output_dir / f"{base}_sheet_1.png"
    out2 = output_dir / f"{base}_sheet_2.png"

    sheets[0].save(out1)
    sheets[1].save(out2)

    return out1, out2


def _build_gui() -> Tk:
    root = Tk()
    root.title("Texture Tools - Chop Horizon")
    root.geometry("650x220")

    source_var = StringVar()
    output_var = StringVar()
    start_panel_var = StringVar(value="1")

    def choose_source() -> None:
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
            output_var.set(str(Path(filename).parent))

    def choose_output_folder() -> None:
        folder = filedialog.askdirectory(title="Choose output folder")
        if folder:
            output_var.set(folder)

    def run_conversion() -> None:
        source = source_var.get().strip()
        output = output_var.get().strip()

        try:
            start_panel = int(start_panel_var.get())
        except ValueError:
            messagebox.showerror("Invalid start panel", "Start panel must be a number from 1 to 8.")
            return

        if not source:
            messagebox.showerror("Missing source image", "Choose a source PNG or BMP file.")
            return

        if not output:
            messagebox.showerror("Missing output folder", "Choose an output folder.")
            return

        try:
            out1, out2 = chop_horizon(source, output, start_panel=start_panel)
        except Exception as exc:
            messagebox.showerror("Conversion failed", str(exc))
            return

        messagebox.showinfo("Done", f"Created:\n\n{out1}\n{out2}")

    Label(root, text="Source image:").grid(row=0, column=0, padx=10, pady=10, sticky="e")
    Entry(root, textvariable=source_var, width=65).grid(row=0, column=1, padx=5, pady=10)
    Button(root, text="Browse...", command=choose_source).grid(row=0, column=2, padx=10, pady=10)

    Label(root, text="Output folder:").grid(row=1, column=0, padx=10, pady=10, sticky="e")
    Entry(root, textvariable=output_var, width=65).grid(row=1, column=1, padx=5, pady=10)
    Button(root, text="Browse...", command=choose_output_folder).grid(row=1, column=2, padx=10, pady=10)

    Label(root, text="Start with panel:").grid(row=2, column=0, padx=10, pady=10, sticky="e")
    Spinbox(root, from_=1, to=8, textvariable=start_panel_var, width=5).grid(row=2, column=1, padx=5, pady=10, sticky="w")

    Button(root, text="Create 256x256 Sheets", command=run_conversion).grid(row=3, column=1, pady=20)

    return root


def main() -> None:
    root = _build_gui()
    root.mainloop()


if __name__ == "__main__":
    main()
