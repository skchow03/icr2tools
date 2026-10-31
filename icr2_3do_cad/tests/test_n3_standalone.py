"""Standalone Papyrus N3 .3D imports (no source .3DO required)."""
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from n3_compile import compile_n3_text
from text_3d import export_standalone_text
from three_do import Model, FormatError

SIMPLE="""3D VERSION 3.0;
% Standalone source. There was never a binary 3DO.
nil: NIL;
front_left: [<0, 0, 0>];
front_right: [<1000, 0, 0>];
rear_left: [<0, 1000, 0>];
% Keep this descriptive surface name.
body_panel: POLY <44> {front_left, front_right, rear_left};
panel_face: FACE (front_left, front_right, rear_left), body_panel;
root: LIST {panel_face, nil};
"""

TEXTURED="""3D VERSION 3.0;
nil: NIL;
a: [<0,0,0>, T=<0,0>];
b: [<100,0,0>, T=<256,0>];
c: [<0,100,0>, T=<0,256>];
nose: MATERIAL MIP="body", GROUP=3, POLY [T] <12> {a,b,c};
root: LIST {nose};
"""

DYNAMIC="""3D VERSION 3.0;
nil: NIL;
a: [<0,0,0>];
b: [<100,0,0>];
c: [<0,100,0>];
poly: POLY <23> {a,b,c};
part: DYNAMIC 0, 0, 0, 0, 0, 0, 1, EXTERN "fwheel";
root: LIST {poly,part};
"""

INLINE="""3D VERSION 3.0;
% Nested Papyrus constructs.
nil: NIL;
root: FACE ([<0,0,0>], [<200,0,0>], [<0,200,0>]),
    LIST { POLY <70> {[<0,0,0>], [<200,0,0>], [<0,200,0>]}, nil };
"""

class StandaloneN3Tests(unittest.TestCase):
    def test_named_records_and_comment_source(self):
        with tempfile.TemporaryDirectory() as temp:
            path=Path(temp)/"body.3d"
            path.write_text(SIMPLE)
            model,doc=compile_n3_text(path.read_text(),path)
            self.assertIsInstance(model,Model)
            self.assertEqual(len(model.polygons),1)
            self.assertEqual(len(model.vertices),3)
            self.assertEqual(model.polygons[next(iter(model.polygons))].color,44)
            self.assertFalse(model.dirty)
            self.assertEqual(export_standalone_text(model,doc,model.raw),SIMPLE)
            first=next(v for v in model.vertices.values() if v.xyz==(0,0,0))
            model.set_vertex(first.offset,(17,0,0))
            changed=export_standalone_text(model,doc,doc and bytes(model.raw))
            self.assertIn("front_left:",changed)
            self.assertIn("% Keep this descriptive surface name.",changed)
            reopened,reparsed=compile_n3_text(changed,path)
            self.assertEqual(len(reopened.polygons),1)
            self.assertIn(17,[v.xyz[0] for v in reopened.vertices.values()])
            self.assertIn("front_left",reparsed.original_text)

    def test_textured_material_resource_table(self):
        model,doc=compile_n3_text(TEXTURED,"simple.3d")
        self.assertEqual(model.mip_names,["body"])
        self.assertEqual(len(model.polygons),1)
        self.assertEqual(next(iter(model.polygons.values())).kind,2)
        self.assertTrue(all(v.textured for v in model.vertices.values()))
        self.assertIn("nose",export_standalone_text(model,doc,model.raw))

    def test_dynamic_external_placement(self):
        model,_=compile_n3_text(DYNAMIC,"parts.3d")
        self.assertEqual(model.external_names,["fwheel"])
        self.assertEqual(len(model.dynamics),1)
        self.assertEqual(len(model.polygons),1)

    def test_nested_faces_and_vertices(self):
        model,_=compile_n3_text(INLINE,"inline.3d")
        self.assertEqual(len(model.polygons),1)
        self.assertEqual(len(model.planes),1)

    def test_unknown_and_cyclic_labels_fail_without_partial_file(self):
        for snippet in (
            SIMPLE.replace("rear_left};","unknown_vertex};"),
            SIMPLE.replace("root: LIST {panel_face, nil};","root: LIST {root};"),
            "3D VERSION 3.0;\nroot: SUPERFAST {nope};\n",
        ):
            with self.subTest(snippet=snippet[-55:]):
                with self.assertRaises(FormatError):
                    compile_n3_text(snippet,"error.3d")

    def test_gui_can_open_standalone_file_and_save_binary(self):
        from icr2_3do_cad import Editor
        with tempfile.TemporaryDirectory() as temp:
            path=Path(temp)/"direct.3d"
            path.write_text(SIMPLE)
            editor=Editor()
            editor.withdraw()
            try:
                self.assertTrue(editor.load_file(path))
                self.assertEqual(editor.model.path,path)
                self.assertTrue(editor.imported_pending)
                self.assertIsNotNone(editor.text_document)
                target=Path(temp)/"direct.3do"
                with mock.patch("icr2_3do_cad.filedialog.asksaveasfilename",return_value=str(target)):
                    with mock.patch("icr2_3do_cad.messagebox.showinfo"):
                        editor.save_as()
                self.assertTrue(target.is_file())
                model=Model(target)
                self.assertEqual(len(model.polygons),1)
                self.assertFalse(editor.imported_pending)
            finally:
                editor.destroy()

if __name__=="__main__":
    unittest.main()
