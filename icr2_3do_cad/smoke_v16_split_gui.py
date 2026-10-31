"""GUI integration smoke, run with xvfb-run on Linux."""
from pathlib import Path
from unittest.mock import patch
import tempfile
from three_do import Model
from icr2_3do_cad import Editor
ROOT=Path(__file__).parent
src=ROOT/'fixtures'/'roadcar.3do'
with tempfile.TemporaryDirectory() as tmp:
    original=Path(tmp)/'roadcar.3do'
    original.write_bytes(src.read_bytes())
    app=Editor(str(original))
    app.update_idletasks(); app.update();app.update_idletasks()
    app.notebook.select(app.poly_page)
    app.choose_polygon(8548)
    app.split_edge_a.set('1: #1 → #2')
    app.split_edge_b.set('4: #4 → #5')
    app.split_fraction_a.set('.5');app.split_fraction_b.set('.5')
    app.redraw()
    with patch('tkinter.messagebox.askyesno',return_value=True):
        app.commit_polygon_split()
    assert app.model.dirty
    assert len(app.model.topology_history)==1
    r=app.model.topology_history[0]
    assert app.selected_poly in r.new_polygons
    app.undo();assert 8548 in app.model.polygons
    app.redo();assert 8548 not in app.model.polygons
    # Correct save path validation and parent rebinding in a fresh model.
    dest=Path(tmp)/'roadcar_split.3do'
    with patch('tkinter.filedialog.asksaveasfilename',return_value=str(dest)),\
         patch('tkinter.messagebox.askyesno',return_value=True),\
         patch('tkinter.messagebox.showinfo'):
        app.save_as()
    check=Model(dest)
    assert r.replacement_list in check.records
    assert len(check.polygons)>len(Model(src).polygons)
    assert check.raw!=src.read_bytes()
    app.update_idletasks();app.update()
    app.destroy()
    print('GUI split/undo/redo/save/reopen OK')
