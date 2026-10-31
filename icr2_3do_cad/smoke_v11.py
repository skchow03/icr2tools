"""Desktop smoke test for individual car RECOLOR wrapper + MIP association."""
from pathlib import Path
from PIL import ImageGrab
from icr2_3do_cad import Editor

base=Path(__file__).parent
app=Editor()
app.geometry('1560x970+35+30')
app.update()
assert app.load_file(base/'fixtures'/'ind96.3do')
assert app.model.path.name=='indycar.3do'
assert app.appearance.map_color(1)==49
poly=next(p for p in app.model.polygons.values() if p.color==1)
app.selected_poly=poly.offset
app.notebook.select(app.poly_page)
app.lod_mode.set('SWITCH DISTANCE')
app.show_edges.set(False)
app.show_points.set(False)
app.azimuth=0.60;app.elevation=0.34;app.zoom=0.95
app.update();app._refresh_polygon_inspector();app.redraw();app.update()
assert app._texture_photos, app.preview_stats.get()
assert app.model.build_modified_bytes()[0]==app.model.raw
assert 'RECOLOR' in app.appearance_info.get()
output=base/'ui_preview_v11.png'
ImageGrab.grab(bbox=(20,15,1610,1020)).save(output)
print('Screenshot',output.stat().st_size,'bytes')
print('Header',app.appearance_info.get())
print('Status',app.preview_stats.get())
print('Polygon',app._color_label(poly))
app.destroy()
