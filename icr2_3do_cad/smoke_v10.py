"""GUI smoke test: real MIP, rapid redraw, refinement and preserved 3DO bytes."""
from pathlib import Path
from time import perf_counter
from PIL import ImageGrab
from icr2_3do_cad import Editor
base=Path(__file__).parent
app=Editor()
app.geometry('1400x930+45+45')
app.load_file(base/'fixtures'/'roadcar.3do')
app.update()
p=next(p for p in app.model.polygons.values() if p.kind==2)
app.texture_manual[('group',p.group)]=base/'fixtures'/'ind96.mip'
app.selected_poly=p.offset
app.notebook.select(app.poly_page)
app._refresh_polygon_inspector()
app.azimuth=.35;app.elevation=.28;app.zoom=2.0
app.redraw()
assert app._texture_photos
cache_count=len(app._texture_tile_cache)
assert cache_count>0
start=perf_counter();app.redraw();elapsed=(perf_counter()-start)*1000
print('Reused texture tiles:',cache_count)
print('Cached redraw:',round(elapsed,1),'ms')
print('Rendering status:',app.preview_stats.get())
assert app.texture_quality.get()=='Balanced (75%)'
assert app.model.build_modified_bytes()[0]==app.model.raw
app.request_view_redraw();app.update()
app.finish_view_motion()
app.update()
assert '75% texture' in app.preview_stats.get()
print('Tile count:',len(app._texture_photos))
output=base/'ui_preview_v10.png'
ImageGrab.grab(bbox=(30,30,1490,1005)).save(output)
print('Screenshot:',output,output.stat().st_size)
app.destroy()
