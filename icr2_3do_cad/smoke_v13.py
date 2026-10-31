import shutil,tempfile
from pathlib import Path
from PIL import ImageGrab
from icr2_3do_cad import Editor
from test_v13_dynamic import make_test_wheel

ROOT=Path(__file__).resolve().parent
with tempfile.TemporaryDirectory() as tmp:
    folder=Path(tmp)
    shutil.copyfile(ROOT/'fixtures'/'roadcar.3do',folder/'roadcar.3do')
    shutil.copyfile(ROOT/'fixtures'/'ind96.mip',folder/'ind96.mip')
    shutil.copyfile(ROOT/'fixtures'/'ind96.3do',folder/'ind96.3do')
    for file in ('sfront.3do','srear.3do','helmet.3do'):
        make_test_wheel(folder/file)
    app=Editor()
    app.geometry('1510x965+0+0')
    app.update()
    assert app.load_file(folder/'roadcar.3do')
    app.external_resolver.choose_directory(folder)
    app.notebook.select(app.component_page)
    app.choose_dynamic(5268)
    app.show_edges.set(False)
    app.show_points.set(False)
    app.show_axes.set(True)
    app.refresh_dynamic_list()
    app.update_idletasks()
    app.redraw()
    app.update()
    assert len(app._screen_dynamics)>0
    assert len(app._dynamic_failures)==0,app._dynamic_failures
    initial=app.model.dynamics[5268].xyz
    app.dynamic_posvars[0].set(str(initial[0]+1500))
    app.dynamic_rotvars[0].set('12.5')
    app.apply_dynamic_transform()
    assert app.model.dynamics[5268].xyz[0]==initial[0]+1500
    app.undo(); assert app.model.dynamics[5268].xyz==initial
    app.redo(); assert app.model.dynamics[5268].xyz[0]==initial[0]+1500
    app.update()
    ImageGrab.grab().save(ROOT/'ui_preview_v13_test_geometry.png')
    print('GUI_OK',len(app._screen_dynamics),len(app.model.dynamics),str(ROOT/'ui_preview_v13_test_geometry.png'))
    app.model.reset()
    app.destroy()
