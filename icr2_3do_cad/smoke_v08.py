"""GUI smoke: load 3DO, bind a synthetic MIP to all group-16 polys, save screenshot."""
from pathlib import Path
from tempfile import TemporaryDirectory
from time import perf_counter
import tkinter as tk
from PIL import ImageGrab
from icr2_3do_cad import Editor
from test_v08_texture import create_test_mip
root=Path(__file__).parent
with TemporaryDirectory() as t:
    mip=Path(t)/'uv-checker.mip'
    create_test_mip(mip)
    app=Editor()
    app.load_file(root/'fixtures'/'roadcar.3do')
    app.geometry('1350x920+35+35');app.update_idletasks()
    textured=next(p for p in app.model.polygons.values() if p.kind==2)
    app.texture_manual[('group',textured.group)]=mip
    app.selected_poly=textured.offset
    app.notebook.select(app.poly_page)
    app._refresh_polygon_inspector()
    app.azimuth=0.35;app.elevation=0.3
    start=perf_counter();app.redraw();app.update();duration=perf_counter()-start
    print('GUI render seconds',duration,'texture photos',len(app._texture_photos), 'offset',textured.offset)
    print('preview stats:',app.preview_stats.get())
    assert len(app._texture_photos)>=1
    out=root/'ui_preview_v08.png'
    ImageGrab.grab(bbox=(20,20,1400,1000)).save(out)
    print(out,out.stat().st_size)
    app.destroy()
