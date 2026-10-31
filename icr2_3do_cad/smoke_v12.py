"""Visual smoke of BSP2 endplate visibility in roadcar 3DO."""
from pathlib import Path
from PIL import ImageGrab
from icr2_3do_cad import Editor
from car_appearance import read_car_appearance
base=Path(__file__).parent
app=Editor(base/'fixtures'/'roadcar.3do')
app.geometry('1540x950+10+10')
app.update()
app.appearance=read_car_appearance(base/'fixtures'/'ind96.3do')
app.bsp_mode.set('Original 3DO planes')
app.lod_mode.set('SWITCH DISTANCE')
app.lod_distance.set(250000)
app.show_points.set(False)
app.show_edges.set(False)
app.azimuth=-1.10
app.elevation=0.29
app.zoom=1.15
app.center=(-34000.0,0.0,6800.0)
app.extent=42000.0
app.selected_poly=7136
app.notebook.select(app.poly_page)
app.update();app.redraw();app.update()
cam=app._camera_position()
vis=set(app.visible_polygon_offsets)&{7136,7168,7076,7108}
print('cam',cam,'plate polys visible',vis)
print('stats',app.preview_stats.get())
assert 7136 in vis and 7168 not in vis,vis
out=base/'ui_preview_v12.png'
ImageGrab.grab(bbox=(0,0,1560,970)).save(out)
print('screenshot',out,out.stat().st_size)
app.destroy()
