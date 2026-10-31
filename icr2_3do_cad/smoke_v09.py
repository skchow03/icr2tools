"""Smoke test rendering the supplied real ICR2 MIP in the editor GUI."""
from pathlib import Path
from time import perf_counter
from PIL import ImageGrab
from icr2_3do_cad import Editor
base=Path(__file__).resolve().parent
app=Editor()
app.load_file(base/'fixtures'/'roadcar.3do')
app.geometry('1400x940+45+45')
app.update_idletasks()
textured=next(p for p in app.model.polygons.values() if p.kind==2)
app.texture_manual[('group',textured.group)]=base/'fixtures'/'ind96.mip'
app.selected_poly=textured.offset
app.notebook.select(app.poly_page)
app._refresh_polygon_inspector()
app.azimuth=0.35
app.elevation=0.28
start=perf_counter()
app.redraw()
app.update()
print('GUI seconds:',round(perf_counter()-start,3))
print('textured photos:',len(app._texture_photos))
print('info:',app.texture_info.get())
print('stats:',app.preview_stats.get())
assert app._texture_photos
assert '128×165' in app.texture_info.get()
out=base/'ui_preview_v09.png'
ImageGrab.grab(bbox=(20,20,1510,1025)).save(out)
print(out,out.stat().st_size)
app.destroy()
