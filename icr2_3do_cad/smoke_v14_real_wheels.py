"""Launch the real supplied wheel files in the GUI for a screenshot + smoke test."""
from pathlib import Path
from PIL import ImageGrab
from icr2_3do_cad import Editor

ROOT=Path(__file__).resolve().parent
app=Editor()
try:
    app.geometry('1500x950+0+0')
    app.update()
    assert app.load_file(ROOT/'fixtures'/'roadcar.3do')
    app.external_resolver.choose_directory(ROOT/'fixtures')
    app.notebook.select(app.component_page)
    app.show_edges.set(False)
    app.show_points.set(False)
    app.show_textures.set(True)
    app.show_axes.set(True)
    app.refresh_dynamic_list()
    app.update_idletasks()
    app.redraw()
    app.update()
    wheel_points=sum(1 for ref,_ in app._screen_dynamics if ref in (5268,5300,5332,5364))
    assert wheel_points>0,wheel_points
    assert set(app._dynamic_failures.keys())=={8700},app._dynamic_failures
    assert 'textured' in app.preview_stats.get(),app.preview_stats.get()
    ImageGrab.grab().save(ROOT/'ui_preview_v14_real_wheels.png')
    print('GUI_PASS',app.preview_stats.get(),'wheel polygon appearances:',wheel_points)
finally:
    app.destroy()
