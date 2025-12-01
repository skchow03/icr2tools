# ui.py
import tkinter as tk
from tkinter import filedialog, messagebox
from to_csv import scr_to_csv, cam_to_csv
from from_csv import csv_to_scr, csv_to_cam


def run_ui():
    def convert_scr_to_csv():
        scr_path = filedialog.askopenfilename(title="Select .scr File")
        if not scr_path:
            return
        csv_path = filedialog.asksaveasfilename(defaultextension=".csv", title="Save CSV File")
        if not csv_path:
            return
        scr_to_csv(scr_path, csv_path)
        messagebox.showinfo("Success", f"Converted {scr_path} to {csv_path}")

    def convert_cam_to_csv():
        cam_path = filedialog.askopenfilename(title="Select .cam File")
        if not cam_path:
            return
        csv_path = filedialog.asksaveasfilename(defaultextension=".csv", title="Save CSV File")
        if not csv_path:
            return
        cam_to_csv(cam_path, csv_path)
        messagebox.showinfo("Success", f"Converted {cam_path} to {csv_path}")

    def convert_csv_to_scr():
        csv_path = filedialog.askopenfilename(title="Select CSV File")
        if not csv_path:
            return
        scr_path = filedialog.asksaveasfilename(defaultextension=".scr", title="Save .scr File")
        if not scr_path:
            return
        csv_to_scr(csv_path, scr_path)
        messagebox.showinfo("Success", f"Converted {csv_path} to {scr_path}")

    def convert_csv_to_cam():
        csv_path = filedialog.askopenfilename(title="Select CSV File")
        if not csv_path:
            return
        cam_path = filedialog.asksaveasfilename(defaultextension=".cam", title="Save .cam File")
        if not cam_path:
            return
        csv_to_cam(csv_path, cam_path)
        messagebox.showinfo("Success", f"Converted {csv_path} to {cam_path}")

    root = tk.Tk()
    root.title("ICR2 Camera Tool")
    root.geometry("300x250")

    tk.Label(root, text="Convert ICR2 Files", font=("Arial", 14)).pack(pady=10)
    tk.Button(root, text="SCR to CSV", width=25, command=convert_scr_to_csv).pack(pady=5)
    tk.Button(root, text="CAM to CSV", width=25, command=convert_cam_to_csv).pack(pady=5)
    tk.Button(root, text="CSV to SCR", width=25, command=convert_csv_to_scr).pack(pady=5)
    tk.Button(root, text="CSV to CAM", width=25, command=convert_csv_to_cam).pack(pady=5)

    root.mainloop()

if __name__ == "__main__":
    run_ui()