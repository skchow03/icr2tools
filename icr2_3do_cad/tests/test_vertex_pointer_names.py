"""N3 vertex pointer-name persistence across visual/source changes."""
from pathlib import Path
from unittest.mock import patch
import tempfile
import unittest

from icr2_3do_cad import Editor
from vertex_labels import names_for_vertices, rename_vertex_in_source
from n3_compile import compile_n3_text
from text_3d import parse_document

HERE=Path(__file__).resolve().parents[1]
N3="""3D VERSION 3.0;
% front_left is a deliberately named vertex, not a synthetic binary offset.
nil: NIL;
front_left: [<0,0,0>, T=<0,0>];
front_right: [<1000,0,0>, T=<256,0>];
rear_left: [<0,1000,0>, T=<0,256>];
panel: MATERIAL MIP="body", GROUP=3, POLY [T] <44> {front_left,front_right,rear_left};
root: LIST {panel};
"""


class VertexNameHelpers(unittest.TestCase):
    def test_original_names_and_generated_binary_names_have_distinct_rules(self):
        model,doc=compile_n3_text(N3,"named.3d")
        actual=names_for_vertices(model,doc,original_n3=True)
        self.assertEqual(set(actual.values()),{"front_left","front_right","rear_left"})
        self.assertEqual(names_for_vertices(model,None,original_n3=False),{})
        src="""3D VERSION 3.0;
% ICR2_OFFSET: 4
_4: [<0,0,0>];
"""
        doc=parse_document(src)
        # Standalone sources can genuinely use numerical-looking pointer names.
        from text_3d import Statement, Document
        doc.statements[0].offset=next(iter(model.vertices))
        doc.statements[0].label="_4"
        self.assertEqual(names_for_vertices(model,doc,original_n3=False),{})
        self.assertEqual(list(names_for_vertices(model,doc,original_n3=True).values()),["_4"])

    def test_rename_preserves_comments_strings_and_other_identifiers(self):
        source=N3.replace('front_left:', 'front_left:').replace(
            'front_right:', 'front_left_extra:').replace(
            '{front_left,front_right,rear_left}', '{front_left,front_left_extra,rear_left}')
        doc=parse_document(source,require_offsets=False)
        changed=rename_vertex_in_source(source,doc,"front_left","nose_vertex")
        self.assertIn("nose_vertex: [",changed)
        self.assertIn("{nose_vertex,front_left_extra,rear_left}",changed)
        self.assertIn("% front_left is a deliberately named vertex",changed)
        self.assertIn('MIP="body"',changed)
        self.assertNotIn("nose_vertex_extra",changed)
        with self.assertRaises(ValueError):
            rename_vertex_in_source(source,doc,"front_left","root")
        with self.assertRaises(ValueError):
            rename_vertex_in_source(source,doc,"front_left","bad.name")
        with self.assertRaises(ValueError):
            rename_vertex_in_source(source,doc,"front_left","front_left_extra")


class VertexPointerNameUITests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.path=Path(self.tmp.name)/"named.3d"
        self.path.write_text(N3,encoding="utf-8")
        self.app=Editor()
        self.app.withdraw()
        self.addCleanup(self.app.destroy)
        self.assertTrue(self.app.load_file(self.path))

    def ref(self,name):
        return next(offset for offset,label in self.app.vertex_pointer_names.items()
                    if label==name)

    def sync(self):
        job=self.app._source_sync_job
        if job is not None:self.app.after_cancel(job)
        self.app._synchronize_model_to_source()

    def test_inspector_and_vertex_list_show_imported_pointer_names(self):
        self.assertEqual(set(self.app.vertex_pointer_names.values()),
                         {"front_left","front_right","rear_left"})
        ref=self.ref("front_left")
        self.app.choose(ref)
        self.assertEqual(self.app.pointer_name_var.get(),"front_left")
        self.assertIn("front_left",self.app.selection_label.get())
        self.assertIn("front_left",self.app._vertex_list_text(ref))
        self.assertIn("front_left",self.app.context_title.get())

    def test_position_and_uv_edits_preserve_name(self):
        ref=self.ref("front_left")
        self.app.choose(ref)
        self.app.commit_vertex((11,21,31))
        self.assertEqual(self.app.vertex_pointer_names[ref],"front_left")
        self.sync()
        self.assertIn("front_left:",self.app.source_editor.get_source())
        self.assertEqual(self.app.pointer_name_var.get(),"front_left")
        self.app.uvvars[0].set("99")
        self.app.uvvars[1].set("101")
        self.app.apply_uv()
        self.sync()
        self.assertEqual(self.app.vertex_pointer_names[ref],"front_left")
        self.assertIn("front_left:",self.app.source_editor.get_source())
        self.assertEqual(self.app.model.vertices[ref].xyz,(11,21,31))
        self.assertEqual(self.app.model.vertices[ref].uv,(99,101))
        self.assertIn("front_left",self.app.pointer_name_var.get())

    def test_label_mode_renders_names_offsets_and_respects_off(self):
        self.app.deiconify()
        self.app.update_idletasks()
        ref=self.ref("front_left")
        self.app.choose(ref)
        self.app.vertex_label_mode.set("Names")
        self.app.redraw()
        self.assertTrue(any("front_left" in self.app.canvas.itemcget(i,"text")
                            for i in self.app.canvas.find_all()
                            if self.app.canvas.type(i)=="text"))
        self.app.vertex_label_mode.set("Offsets")
        self.app.redraw()
        self.assertTrue(any(self.app.canvas.itemcget(i,"text")==str(ref)
                            for i in self.app.canvas.find_all()
                            if self.app.canvas.type(i)=="text"))
        self.app.vertex_label_mode.set("Off")
        self.app.redraw()
        self.assertEqual(self.app.canvas.find_withtag("vertex_label"),())

    def test_rename_pointer_updates_source_and_all_references(self):
        self.app.choose(self.ref("front_left"))
        self.app.pointer_name_var.set("nose_top")
        self.app.apply_vertex_pointer_name()
        self.assertIn("nose_top",self.app.vertex_pointer_names.values())
        self.assertNotIn("front_left",self.app.vertex_pointer_names.values())
        self.assertEqual(self.app.pointer_name_var.get(),"nose_top")
        source=self.app.source_editor.get_source()
        self.assertIn("nose_top: [",source)
        self.assertIn("{nose_top,front_right,rear_left}",source)
        # The comment has not been rewritten (comments are human authored).
        self.assertIn("% front_left is a deliberately named vertex",source)
        with patch("icr2_3do_cad.messagebox.showerror") as show_error:
            self.app.pointer_name_var.set("front_right")
            self.app.apply_vertex_pointer_name()
        show_error.assert_called_once()
        self.assertIn("nose_top",self.app.vertex_pointer_names.values())

    def test_live_source_coordinate_change_retains_pointer_name(self):
        pane=self.app.source_editor
        source=pane.get_source()
        self.assertIn("front_left: [<0,0,0>",source)
        pane.text.delete("1.0","end")
        pane.text.insert("1.0",source.replace("front_left: [<0,0,0>",
                                             "front_left: [<9,5,0>",1))
        pane.text.edit_modified(True);pane._edited()
        self.assertTrue(pane.apply_now(),pane.message.get())
        ref=self.ref("front_left")
        self.assertEqual(self.app.model.vertices[ref].xyz,(9,5,0))
        self.app.choose(ref)
        self.assertEqual(self.app.pointer_name_var.get(),"front_left")

    def test_binary_3do_has_no_name_until_user_assigns_one(self):
        binary=HERE/"fixtures"/"roadcar.3do"
        if not binary.is_file():self.skipTest("no roadcar fixture")
        with patch("icr2_3do_cad.messagebox.askyesno",return_value=True):
            self.assertTrue(self.app.load_file(binary))
        self.assertEqual(self.app.vertex_pointer_names,{})
        offset=next(iter(self.app.model.vertices))
        self.app.choose(offset)
        self.assertEqual(self.app.pointer_name_var.get(),"")
        self.app.pointer_name_var.set("new_name")
        self.app.apply_vertex_pointer_name()
        self.assertIn("new_name",self.app.vertex_pointer_names.values())
        self.assertIn("new_name:",self.app.source_editor.get_source())


if __name__=="__main__":
    unittest.main()
