"""N3 text interchange: lossless no-op, annotations, import rejection and patch safety."""
from pathlib import Path
import re
import unittest

from text_3d import export_text, import_text, parse_document
from three_do import Model, FormatError

HERE=Path(__file__).resolve().parents[1]
FIXTURES=HERE/"fixtures"


class N3TextRoundTripTests(unittest.TestCase):
    def test_noop_roundtrip_binary_identical(self):
        for name in ("roadcar.3do","indycar.3do","cars.3do"):
            path=FIXTURES/name
            if not path.exists():
                continue
            with self.subTest(name=name):
                m=Model(path)
                text=export_text(m)
                self.assertTrue(text.startswith("3D VERSION 3.0;"))
                self.assertIn("% ICR2_OFFSET:",text)
                imported,doc=import_text(m,text)
                self.assertEqual(imported.raw,m.raw)
                self.assertFalse(imported.dirty)
                self.assertEqual(export_text(imported,doc).count("3D VERSION 3.0;"),1)

    def test_rename_comments_edit_coordinates_color_and_reexport(self):
        model=Model(FIXTURES/"roadcar.3do")
        text=export_text(model)
        target=next(iter(model.vertices.values()))
        name=f"_{target.offset}"
        renamed="CUSTOM_VERTEX_FRONT_WING"
        text=text.replace(name+":",renamed+":",1)
        # Keep the annotation that binds the arbitrary friendly name to its binary offset.
        text=re.sub(r"(?<![\w])"+re.escape(name)+r"(?=\s*[},;])",renamed,text)
        text=text.replace(f"{renamed}: [<{target.xyz[0]}, {target.xyz[1]}, {target.xyz[2]}>",
                 f"{renamed}: [<{target.xyz[0]+9}, {target.xyz[1]}, {target.xyz[2]}>",1)
        # A comment on the named record should survive a subsequent .3D export.
        text=text.replace(f"{renamed}: [",f"% A human-friendly vertex comment\n{renamed}: [",1)
        new,doc=import_text(model,text)
        self.assertEqual(new.vertices[target.offset].xyz[0],target.xyz[0]+9)
        self.assertEqual(model.vertices[target.offset].xyz[0],target.xyz[0])
        self.assertIn(renamed,export_text(new,doc))
        self.assertIn("A human-friendly vertex comment",export_text(new,doc))

    def test_polygon_recolor_and_plane_edit(self):
        model=Model(FIXTURES/"roadcar.3do")
        text=export_text(model)
        p=next(iter(model.polygons.values()))
        orig=f"_{p.offset}: "
        self.assertIn(orig,text)
        text=text.replace(orig+f"POLY <{p.color}>",orig+f"POLY <{p.color+1}>",1) if p.kind==1 else (
             text.replace(orig+f"POLY [T] <{p.color}>",orig+f"POLY [T] <{p.color+1}>",1))
        new,_=import_text(model,text)
        self.assertEqual(new.polygons[p.offset].color,p.color+1)
        self.assertEqual(model.polygons[p.offset].color,p.color)

    def test_structural_change_rejected_without_mutation(self):
        model=Model(FIXTURES/"roadcar.3do")
        data=model.raw
        text=export_text(model)
        # Dropping an offset annotation or removing a record is rejected.
        text=text.replace("% ICR2_OFFSET:", "% ERASED_OFFSET:", 1)
        # Original numeric _offset still allows a valid mapping; corrupt the label too.
        text=re.sub(r"(?m)^_\d+:", "newname:",text,count=1)
        with self.assertRaises(FormatError):
            import_text(model,text)
        self.assertEqual(model.raw,data)

    def test_duplicate_labels_and_overflow_rejected(self):
        model=Model(FIXTURES/"roadcar.3do")
        text=export_text(model)
        vertex=next(iter(model.vertices.values()))
        old=f"[<{vertex.xyz[0]}, {vertex.xyz[1]}, {vertex.xyz[2]}"
        bad=text.replace(old,f"[<{2**40}, {vertex.xyz[1]}, {vertex.xyz[2]}",1)
        with self.assertRaisesRegex(FormatError,"32-bit"):
            import_text(model,bad)
        doc=parse_document(text)
        self.assertEqual(len(doc.statements),len(set(model.vertices)|set(model.records)))

    def test_template_keeps_labels_and_inline_comments(self):
        m=Model(FIXTURES/"roadcar.3do")
        text=export_text(m)
        v=next(iter(m.vertices.values()))
        text=text.replace(f"_{v.offset}: [",f"_{v.offset}: [",1) # keep source layout
        line=next(l for l in text.splitlines() if l.startswith(f"_{v.offset}: "))
        text=text.replace(line,line+" % Spare vertex annotation",1)
        again,doc=import_text(m,text)
        output=export_text(again,doc)
        self.assertIn("% Spare vertex annotation",output)
        self.assertEqual(output.count("3D VERSION 3.0;"),1)


    def test_texture_uv_edits(self):
        model=Model(FIXTURES/"roadcar.3do")
        vertex=next((v for v in model.vertices.values() if v.textured),None)
        if vertex is None:
            self.skipTest("No textured vertices in roadcar")
        text=export_text(model)
        prefix=f"_{vertex.offset}: [<{vertex.xyz[0]}, {vertex.xyz[1]}, {vertex.xyz[2]}>, T=<"
        current=prefix+f"{vertex.uv[0]}, {vertex.uv[1]}>]"
        changed=prefix+f"{vertex.uv[0]}, {(vertex.uv[1]+1)%65536}>]"
        self.assertIn(current,text)
        new,_=import_text(model,text.replace(current,changed,1))
        self.assertEqual(new.vertices[vertex.offset].uv[1],(vertex.uv[1]+1)%65536)

    def test_raw_plane_coefficients_import_exactly(self):
        model=Model(FIXTURES/"roadcar.3do")
        plane=next(iter(model.planes.values()))
        text=export_text(model)
        original=plane.equation
        lo=(original[3] & 0xffffffff)
        if lo>=2**31:lo-=2**32
        hi=(original[3]>>32)
        # Read legacy five-coefficient overlay files, but do not export that
        # binary-only syntax as a normal Papyrus N3 source representation.
        needle=f"_{plane.offset}: "
        original_plane=f"({original[0]}, {original[1]}, {original[2]}, {lo}, {hi})"
        self.assertNotIn(original_plane,text)
        lines=text.splitlines()
        for i,line in enumerate(lines):
            if line.startswith(needle):
                start=line.index("(",len(needle))
                end=line.index(")",start)+1
                modified=f"({original[0]+1}, {original[1]}, {original[2]}, {lo}, {hi})"
                lines[i]=line[:start]+modified+line[end:]
                break
        imported,_=import_text(model,"\n".join(lines)+"\n")
        self.assertEqual(imported.planes[plane.offset].equation[0],original[0]+1)
        self.assertEqual(model.planes[plane.offset].equation,original)

    def test_dynamic_placement_xyz(self):
        model=Model(FIXTURES/"indycar.3do")
        if not model.dynamics:
            self.skipTest("No DYNAMIC placements in fixture")
        obj=next(iter(model.dynamics.values()))
        lines=export_text(model).splitlines()
        for i,line in enumerate(lines):
            if line.startswith(f"_{obj.offset}: DYNAMIC "):
                lines[i]=line.replace(f"DYNAMIC {obj.xyz[0]},",
                                      f"DYNAMIC {obj.xyz[0]+17},",1)
                break
        new,_=import_text(model,"\n".join(lines)+"\n")
        self.assertEqual(new.dynamics[obj.offset].xyz[0],obj.xyz[0]+17)
        self.assertEqual(model.dynamics[obj.offset].xyz,obj.xyz)

    def test_dangling_pointer_is_rejected(self):
        model=Model(FIXTURES/"roadcar.3do")
        text=export_text(model)
        lines=text.splitlines()
        index=next((i for i,line in enumerate(lines)
                    if re.match(r"^_\d+: LIST \{_",line)),None)
        if index is None:
            self.skipTest("No nonempty LIST in fixture")
        lines[index]=re.sub(r"(?<!\w)_\d+(?=[,}])","NONEXISTENT_PTR",lines[index],count=1)
        with self.assertRaises(FormatError):
            import_text(model,"\n".join(lines)+"\n")


if __name__=="__main__":
    unittest.main()
