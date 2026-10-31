"""Run under xvfb-run or a desktop with Pillow installed."""
from pathlib import Path
import math
from PIL import ImageGrab
from icr2_3do_cad import Editor
base=Path(__file__).parent
app=Editor(str(base/'fixtures'/'roadcar.3do'))
app.geometry('1440x900+20+20')
app.update();app.update()
app.notebook.select(app.poly_page)
app.lod_mode.set('SWITCH DISTANCE')
app.lod_distance.set(0)
app.bsp_mode.set('Original 3DO planes')
app.choose_polygon(5540)
app.elevation=math.radians(15)
app.azimuth=0 # Camera negative Y, polygon is BSP-hidden
app.redraw();app.update()
assert 5540 not in app.visible_polygon_offsets
assert not app.canvas.find_withtag('selected_poly'), 'hidden polygon leaked its selection outline'
assert not app.canvas.find_withtag('poly_number'), 'hidden polygon leaked its vertex labels'
app.show_hidden_polygon_outline.set(True)
app.redraw();app.update()
assert app.canvas.find_withtag('selected_poly'), 'ghost outline toggle did not work'
assert app.canvas.find_withtag('poly_number'), 'ghost vertex overlay not shown'
app.show_hidden_polygon_outline.set(False)
app.azimuth=math.pi  # Camera positive Y, polygon is visible
app.redraw();app.update()
assert 5540 in app.visible_polygon_offsets
assert app.canvas.find_withtag('selected_poly')
assert app.canvas.find_withtag('poly_number')
ImageGrab.grab(bbox=(20,20,1460,920)).save(base/'ui_preview_v06.png')
print('v0.6 GUI smoke passed: 5540 back hidden, ghost optional, front visible')
app.destroy()
