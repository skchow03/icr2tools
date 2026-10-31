"""Screenshots v1.7 no-new-vertex split controls using supplied stock geometry."""
from pathlib import Path
from PIL import ImageGrab
from icr2_3do_cad import Editor
P=Path(__file__).parent
app=Editor(str(P/'fixtures'/'roadcar.3do'))
app.geometry('1560x1020+20+20')
app.update();app.notebook.select(app.poly_page)
app.choose_polygon(8548)
choices=list(app.existing_split_combos[0]['values'])
app.existing_split_a.set(choices[0]);app.existing_split_b.set(choices[3])
app.poly_canvas.yview_moveto(.32)
app.split_preview.set(False)
app.existing_split_preview.set(True)
app.redraw();app.update_idletasks();app.update()
app.after(350,app.quit);app.mainloop()
ImageGrab.grab(bbox=(20,20,1580,1040)).save(P/'ui_preview_v17.png')
app.destroy()
