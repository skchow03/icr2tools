from pathlib import Path
from unittest.mock import patch
from three_do import Model
from icr2_3do_cad import Editor
from geometry_add import list_insert_targets
p=Path(__file__).resolve().parent
ed=Editor()
assert ed.load_file(p/'fixtures'/'roadcar.3do')
ed.update_idletasks()
# Create an actual two-sided fin (rather than a synthetic UI selection).
ed.geometry_anchor.set('8484');ed.refresh_geometry_targets()
ed.geometry_fin_a.set(ed.fin_base_a['values'][0]);ed.geometry_fin_b.set(ed.fin_base_b['values'][1]);ed.geometry_fin_height.set('5000')
with patch('tkinter.messagebox.askyesno',return_value=True):
    ed.create_geometry_fin()
assert ed.model.topology_history
result=ed.model.topology_history[-1]
front,back=result.new_polygons
ed.notebook.select(ed.poly_page)
ed.choose_polygon(front)
assert ed.poly_color_index.get()=='40'
assert ed.model.face2_pair(front)==back
ed.poly_color_index.set('146')
ed.apply_polygon_color()
assert ed.model.polygons[front].color==ed.model.polygons[back].color==146
ed.undo()
assert ed.model.polygons[front].color==ed.model.polygons[back].color==40
ed.redo()
assert ed.model.polygons[front].color==ed.model.polygons[back].color==146
assert 'color=146' in ed.raw_text.get('1.0','end')
ed.poly_color_pair.set(False)
ed.poly_color_index.set('120')
ed.apply_polygon_color()
assert ed.model.polygons[front].color==120
assert ed.model.polygons[back].color==146
raw,report=ed.model.build_modified_bytes()
assert report.updated_polygon_colors==2
reopened=Model(ed.model.path,raw_data=raw)
assert reopened.polygons[front].color==120 and reopened.polygons[back].color==146
# Test chooser UI opens, selects palette cell and closes.
ed.choose_polygon(front)
ed.choose_polygon_palette_color()
selector=next(w for w in ed.winfo_children() if w.winfo_class()=='Toplevel')
canvas=next(w for w in selector.winfo_children() if w.winfo_class()=='Canvas')
ed.update_idletasks();ed.update()
canvas.event_generate('<Button-1>',x=6*25+5,y=8*25+5)
ed.update_idletasks();ed.update()
assert ed.poly_color_index.get()==str(8*16+6)
# screenshot under virtual desktop without altering application files.
ed.poly_color_index.set('120')
ed.poly_color_pair.set(False)
ed.bsp_mode.set('Off (show all)')
ed.zoom=1.3
ed.geometry('1330x920')
ed.update_idletasks();ed.update()
try:
    from PIL import ImageGrab
    ImageGrab.grab(bbox=(0,0,1330,920)).save(p/'ui_preview_v19.png')
except Exception as exc: print('screenshot skipped:',exc)
print('PASS v1.9 polygon color editing, pair, undo/redo, palette selector, disassembly, roundtrip')
ed.destroy()
