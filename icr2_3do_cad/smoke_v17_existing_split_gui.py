"""GUI integration: original edge split followed by no-new-vertices split."""
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch
from three_do import Model
from icr2_3do_cad import Editor

ROOT=Path(__file__).parent
with TemporaryDirectory() as tmp:
    src=ROOT/'fixtures'/'roadcar.3do'
    file=Path(tmp)/'roadcar.3do';file.write_bytes(src.read_bytes())
    app=Editor(str(file));app.geometry('1560x1020+0+0')
    app.update_idletasks();app.update()
    app.notebook.select(app.poly_page)
    app.choose_polygon(7832)
    original=app.model.polygons[7832]
    ei=next(i for i in range(len(original.refs)) if {original.refs[i],original.refs[(i+1)%len(original.refs)]}=={1020,1040})
    choices=list(app.split_edge_combos[0]['values'])
    app.split_edge_a.set(choices[ei])
    app.split_edge_b.set(choices[(ei+2)%len(choices)])
    with patch('tkinter.messagebox.askyesno',return_value=True):
        app.commit_polygon_split()
    first=app.model.topology_history[-1]
    neighbor=dict(first.updated_neighbors)[7864]
    app.choose_polygon(neighbor)
    refs=app.model.polygons[neighbor].refs
    position=next(i for i,ref in enumerate(refs) if ref in first.new_vertices)
    other=(position+2)%len(refs)
    choices=list(app.existing_split_combos[0]['values'])
    app.existing_split_a.set(choices[position]);app.existing_split_b.set(choices[other]);app.redraw()
    count=len(app.model.vertices)
    with patch('tkinter.messagebox.askyesno',return_value=True):
        app.commit_existing_vertex_split()
    second=app.model.topology_history[-1]
    assert not second.new_vertices
    assert len(app.model.vertices)==count
    assert len(app.model.topology_history)==2
    assert all(off in app.model.polygons for off in second.new_polygons)
    app.undo();assert neighbor in app.model.polygons
    app.redo();assert neighbor not in app.model.polygons
    dest=Path(tmp)/'double_split.3do'
    with patch('tkinter.filedialog.asksaveasfilename',return_value=str(dest)),\
         patch('tkinter.messagebox.askyesno',return_value=True),\
         patch('tkinter.messagebox.showinfo'):
        app.save_as()
    verified=Model(dest)
    assert all(off in verified.polygons for off in second.new_polygons)
    assert len(verified.vertices)==count
    print('GUI existing-vertex split/undo/redo/save/reopen OK')
    app.destroy()
