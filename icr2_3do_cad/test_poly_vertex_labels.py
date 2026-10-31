"""Polygon preview numbering should match ordinal polygon-list indices."""
import unittest
from types import SimpleNamespace
from pathlib import Path
from three_do import Model,Polygon
from icr2_3do_cad import Editor


class FakeCanvas:
    def __init__(self): self.calls=[]
    def __getattr__(self,name):
        def record(*args,**kwargs): self.calls.append((name,args,kwargs))
        return record


class VertexLabelTests(unittest.TestCase):
    def test_order_and_duplicate_offsets(self):
        p=Polygon(123,1,(44,55,66,44),0)
        self.assertEqual(Editor.polygon_vertex_label_groups(p),
                         [(44,'#1/#4'),(55,'#2'),(66,'#3')])

    def test_preview_labels_correspond_to_selected_polygon_vertices(self):
        model=Model(Path(__file__).parent/'fixtures'/'roadcar.3do')
        poly=model.polygons[7896]
        fake=SimpleNamespace(model=model,canvas=FakeCanvas(),
                             _project=lambda v:(v[0]*0.01,v[1]*0.01,0),
                             polygon_vertex_label_groups=Editor.polygon_vertex_label_groups)
        Editor.draw_selected_polygon_numbers(fake,poly)
        labels=[entry[2]['text'] for entry in fake.canvas.calls
                if entry[0]=='create_text' and entry[2].get('fill')=='#fff0ac']
        self.assertEqual(labels,[f'#{i}' for i in range(1,len(poly.refs)+1)])
        self.assertEqual(len([x for x in fake.canvas.calls if x[0]=='create_oval']),
                         len(poly.refs))


if __name__=='__main__': unittest.main()
