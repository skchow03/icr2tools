"""Regression: standalone N3 export must not reparse labels as binary offsets.

Based on the Hilton model's N3 structure: nil, named coordinates,
MATERIAL MIP aliases, and a BSPF root, with original CRLF line endings.
"""
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from icr2_3do_cad import Editor
from n3_compile import compile_n3_text

HILTON_STYLE=(
    "3D VERSION 3.0;\r\n"
    "\r\n"
    "nil: NIL;\r\n"
    "% Hilton-like standalone source with descriptive labels\r\n"
    "a0: [<0, 77, 0>, T=<128,395> ];\r\n"
    "b0: [<0, 0, 0>, T=<255,395> ];\r\n"
    "a1: [<0, 77, 275>, T=<128,0> ];\r\n"
    "b1: [<0, 0, 275>, T=<255,0> ];\r\n"
    "west_fr: MATERIAL MIP=\"hilton1\", GROUP=3, POLY [T] <191> {a1, a0, b0, b1};\r\n"
    "root: BSPF (a1, a0, b0), nil, west_fr, nil;\r\n"
)


class StandaloneN3ExportTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.dir=Path(self.temp.name)
        self.source=self.dir/"hilton.3d"
        self.source.write_bytes(HILTON_STYLE.encode("ascii"))
        self.editor=Editor()
        self.editor.withdraw()
        self.addCleanup(self.editor.destroy)
        self.assertTrue(self.editor.load_file(self.source))

    def export_to(self,name):
        destination=self.dir/name
        with mock.patch("icr2_3do_cad.filedialog.asksaveasfilename",
                        return_value=str(destination)):
            with mock.patch("icr2_3do_cad.messagebox.showinfo") as info, \
                 mock.patch("icr2_3do_cad.messagebox.showerror") as error:
                self.editor.export_n3_text()
        return destination,info,error

    def test_original_hilton_style_exports_without_warning_and_exact_crlf(self):
        initial_document=self.editor.text_document
        dest,info,error=self.export_to("hilton2.3d")
        error.assert_not_called()
        self.assertTrue(dest.is_file())
        self.assertEqual(dest.read_bytes(),self.source.read_bytes())
        self.assertIs(self.editor.text_document,initial_document)
        self.assertIn("nil: NIL;",dest.read_text())
        info.assert_called_once()
        dest2,_,error2=self.export_to("hilton3.3d")
        error2.assert_not_called()
        self.assertEqual(dest2.read_bytes(),dest.read_bytes())

    def test_edited_text_exports_with_named_pointer_and_reimports(self):
        vertex=next(v for v in self.editor.model.vertices.values()
                    if v.xyz==(0,77,0))
        self.editor.model.set_vertex(vertex.offset,(0,79,0))
        dest,info,error=self.export_to("hilton_edited.3d")
        error.assert_not_called()
        self.assertTrue(dest.is_file())
        text=dest.read_text()
        self.assertIn("west_fr:",text)
        self.assertIn("% Hilton-like standalone source with descriptive labels",text)
        self.assertIn("MIP=\"hilton1\"",text)
        self.assertIn("nil: NIL;",text)
        compiled,_=compile_n3_text(text,dest)
        self.assertIn((0,79,0),{v.xyz for v in compiled.vertices.values()})
        self.assertEqual(compiled.mip_names,["hilton1"])
        dest2,_,error2=self.export_to("hilton_edited_again.3d")
        error2.assert_not_called()
        self.assertEqual(dest.read_bytes(),dest2.read_bytes())

    def test_original_text_cannot_be_overwritten_by_export(self):
        original=self.source.read_bytes()
        destination,info,error=self.export_to("hilton.3d")
        self.assertEqual(destination.read_bytes(),original)
        info.assert_not_called()
        error.assert_called_once()
        self.assertIn("separate",error.call_args.args[0].lower()
                      +" "+error.call_args.args[1].lower())


if __name__=="__main__":
    unittest.main()
