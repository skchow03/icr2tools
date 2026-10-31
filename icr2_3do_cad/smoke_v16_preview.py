"""Create a screenshot of the real desktop GUI under Xvfb."""
from pathlib import Path
import tkinter as tk
from PIL import ImageGrab
from icr2_3do_cad import Editor
folder=Path(__file__).parent
app=Editor(str(folder/'fixtures'/'roadcar.3do'))
app.geometry('1560x1020+20+20')
app.update();app.notebook.select(app.poly_page)
app.choose_polygon(8548)
app.split_edge_a.set('1: #1 → #2');app.split_edge_b.set('4: #4 → #5')
app.poly_canvas.yview_moveto(0.34)
app.redraw();app.update_idletasks();app.update()
app.after(500,app.quit);app.mainloop()
ImageGrab.grab(bbox=(20,20,1580,1040)).save(folder/'ui_preview_v16.png')
app.destroy()
