"""Live N3 source editing and transactional preview regressions."""
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from icr2_3do_cad import Editor
from n3_source_editor import find_error_line
from n3_compile import compile_n3_text
from three_do import Model

ROOT=Path(__file__).resolve().parents[1]
SOURCE="""3D VERSION 3.0;
% Live N3 source test with named polygons.
nil: NIL;
left: [<0,0,0>];
right: [<200,0,0>];
top: [<0,250,0>];
body: POLY <44> {left,right,top};
root: FACE (left,right,top), body;
"""


class LiveSourceTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.path=Path(self.tmp.name)/"model.3d"
        self.path.write_text(SOURCE,encoding="utf8")
        self.editor=Editor()
        self.editor.withdraw()
        self.addCleanup(self.editor.destroy)
        self.assertTrue(self.editor.load_file(self.path))

    def edit(self,old,new):
        pane=self.editor.source_editor
        current=pane.text.get("1.0","end-1c")
        self.assertIn(old,current)
        pane.text.delete("1.0","end")
        pane.text.insert("1.0",current.replace(old,new,1))
        pane.text.edit_modified(True)
        pane._edited()
        return pane

    def test_standalone_source_initial_and_live_valid_apply(self):
        pane=self.editor.source_editor
        self.assertEqual(pane.get_source(),SOURCE)
        self.assertFalse(pane.pending)
        pane=self.edit("<200,0,0>","<350,0,0>")
        self.assertTrue(pane.pending)
        self.assertTrue(pane.apply_now())
        self.assertFalse(pane.pending)
        self.assertIn((350,0,0),{v.xyz for v in self.editor.model.vertices.values()})
        self.assertEqual(self.editor.notebook.tab(self.editor.source_page,"text"),".3D Source")
        self.assertFalse(self.editor._source_invalid)
        self.assertIn("Valid N3",pane.message.get())

    def test_invalid_statement_highlight_keeps_last_valid_model(self):
        original=self.editor.model
        pane=self.edit("POLY <44>","POLY <bad_color>")
        self.assertFalse(pane.apply_now())
        self.assertIs(self.editor.model,original)
        self.assertTrue(self.editor._source_invalid)
        self.assertGreater(len(pane.text.tag_ranges("error")),0)
        self.assertTrue(pane.message.get().startswith("Line "))
        with patch("icr2_3do_cad.messagebox.showerror") as failed:
            self.editor.save_as()
        failed.assert_called_once()
        self.assertEqual(self.editor.model.raw,original.raw)
        pane=self.edit("POLY <bad_color>","POLY <55>")
        self.assertTrue(pane.apply_now())
        self.assertFalse(self.editor._source_invalid)
        self.assertEqual(next(iter(self.editor.model.polygons.values())).color,55)

    def test_visual_changes_regenerate_source_and_keep_labels(self):
        model=self.editor.model
        ref=next(v.offset for v in model.vertices.values() if v.xyz==(200,0,0))
        self.editor.selected=ref
        self.editor.commit_vertex((350,0,0))
        self.assertIsNotNone(self.editor._source_sync_job)
        self.editor.after_cancel(self.editor._source_sync_job)
        self.editor._synchronize_model_to_source()
        source=self.editor.source_editor.get_source()
        self.assertIn("right:",source)
        self.assertIn("<350, 0, 0>",source)
        self.assertIn("% Live N3 source test",source)
        rebuilt,_=compile_n3_text(source,self.path)
        self.assertIn((350,0,0),{v.xyz for v in rebuilt.vertices.values()})

    def test_binary_open_produces_editable_source(self):
        binary=ROOT/"fixtures"/"roadcar.3do"
        if not binary.exists():self.skipTest("Binary roadcar fixture unavailable")
        source_model=Model(binary)
        with patch("icr2_3do_cad.messagebox.askyesno",return_value=True):
            self.assertTrue(self.editor.load_file(binary))
        data=self.editor.source_editor.get_source()
        self.assertIn("3D VERSION 3.0;",data)
        self.assertIn("% ICR2_OFFSET:",data)
        self.assertIn("POLY",data)
        self.assertEqual(len(self.editor.model.polygons),len(source_model.polygons))


    def test_binary_generated_source_can_be_edited_and_recompiled(self):
        binary=ROOT/"fixtures"/"roadcar.3do"
        if not binary.exists():self.skipTest("Binary roadcar fixture unavailable")
        with patch("icr2_3do_cad.messagebox.askyesno",return_value=True):
            self.assertTrue(self.editor.load_file(binary))
        original=self.editor.model
        vertex=next(iter(original.vertices.values()))
        raw=f"_{vertex.offset}: [<{vertex.xyz[0]}, {vertex.xyz[1]}, {vertex.xyz[2]}"
        pane=self.editor.source_editor
        current=pane.get_source()
        self.assertIn(raw,current)
        changed=raw.replace(f"[<{vertex.xyz[0]},",f"[<{vertex.xyz[0]+9},")
        pane.text.delete("1.0","end")
        pane.text.insert("1.0",current.replace(raw,changed,1))
        pane.text.edit_modified(True)
        pane._edited()
        self.assertTrue(pane.apply_now(),pane.message.get())
        self.assertFalse(self.editor._source_invalid)
        self.assertIsNot(self.editor.model,original)
        self.assertIn((vertex.xyz[0]+9,vertex.xyz[1],vertex.xyz[2]),
                      {v.xyz for v in self.editor.model.vertices.values()})
        self.assertEqual(len(self.editor.model.polygons),len(original.polygons))

    def test_parser_error_line_locator(self):
        self.assertEqual(find_error_line(SOURCE,"Label 'body' (line 7): bad polygon"),7)
        self.assertEqual(find_error_line(SOURCE,"In label 'body': bad polygon"),7)
        self.assertEqual(find_error_line(SOURCE,"line 999: bad polygon"),999)


if __name__=="__main__":
    unittest.main()
