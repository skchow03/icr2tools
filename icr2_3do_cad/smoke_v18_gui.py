from pathlib import Path
from unittest.mock import patch
from icr2_3do_cad import Editor
from geometry_add import list_insert_targets
p=Path(__file__).resolve().parent
ed=Editor()
assert ed.load_file(p/'fixtures'/'roadcar.3do') is True
ed.update_idletasks()
ed.notebook.select(ed.geometry_page)
ed.geometry_anchor.set('8484')
ed.refresh_geometry_targets()
assert ed.geometry_insertion_targets
ed.geometry_fin_a.set(ed.fin_base_a['values'][0]);ed.geometry_fin_b.set(ed.fin_base_b['values'][1]);ed.geometry_fin_height.set('4200')
ed.stage_geometry_vertex()  # draft stage only
assert len(ed.draft_vertices)==1
ed.redraw()
with patch('tkinter.messagebox.askyesno',return_value=True):
    ed.create_geometry_fin()
assert len(ed.model.topology_history)==1
assert len(ed.model.vertices)==326
assert len(ed.model.polygons)==126
ed.notebook.select(ed.raw_page);ed.refresh_raw()
assert 'FACE2' in ed.raw_text.get('1.0','end')
ed.notebook.select(ed.geometry_page)
ed.update_idletasks();ed.update()
try:
    from PIL import ImageGrab
    import time
    ed.geometry('1320x920');ed.update_idletasks();ed.update()
    ImageGrab.grab(bbox=(0,0,1320,920)).save(p/'ui_preview_v18.png')
except Exception as e:print('screenshot omitted',e)
ed.undo();assert len(ed.model.polygons)==124
ed.redo();assert len(ed.model.polygons)==126
out,_=ed.model.build_modified_bytes()
from three_do import Model
assert len(Model('fixtures/roadcar.3do',raw_data=out).polygons)==126
print('PASS v1.8 desktop geometry, raw disassembly, undo/redo, reopen')
ed.destroy()
