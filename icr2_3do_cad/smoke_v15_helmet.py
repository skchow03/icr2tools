from pathlib import Path
from PIL import ImageGrab
from icr2_3do_cad import Editor
from dynamic_scene import gather_faces,RenderSprite
ROOT=Path(__file__).resolve().parent
app=Editor()
try:
    app.geometry('1500x950+0+0')
    app.update()
    assert app.load_file(ROOT/'fixtures'/'ind96.3do')
    app.external_resolver.choose_directory(ROOT/'fixtures')
    app.notebook.select(app.component_page)
    app.show_edges.set(False)
    app.show_points.set(False)
    app.show_textures.set(True)
    app.refresh_dynamic_list()
    app.update_idletasks(); app.redraw(); app.update()
    assert not app._dynamic_failures, app._dynamic_failures
    sprite_items=app.canvas.find_withtag('pmp')
    assert sprite_items, 'Helmet sprite not drawn'
    assert any(ref in (5268,5300,5332,5364) for ref,_ in app._screen_dynamics)
    ImageGrab.grab().save(ROOT/'ui_preview_v15_helmet.png')
    print('GUI_HELMET_PASS',len(sprite_items),'stats:',app.preview_stats.get(), 'sprite bbox',app.canvas.bbox(sprite_items[0]))
finally:
    app.destroy()
