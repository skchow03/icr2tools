"""Track-style N3 import regressions: RENO's source syntax, not its private assets.

RENO.3D is a very large (about 51,700-line) track source with a semicolon-
less VERSION header, hyphenated TSD labels, nested FACE/BSP/MATERIAL,
track DATA hash tables and an 'index' root LIST.
"""
import unittest
from pathlib import Path

from n3_compile import compile_n3_text
from text_3d import parse_document, export_standalone_text
from vertex_labels import names_for_vertices, rename_vertex_in_source
from three_do import Model

# Adapted from representative syntax only; deliberately does not embed
# the actual RENO.3D source or its scenery data in the public repository.
TRACK_N3="""3D VERSION 3.0
% SURF_ED: synthetic track index
__TSO0: DYNAMIC 0, 0, 0, 0, 0, 0, 1, EXTERN "stand100";
ObjectList_L0_0: LIST { __TSO0 };
DetailP_0-1: [<0, 0, 0>];
DetailP_0-0: [<1000, 0, 0>];
DetailP_0-2: [<0, 1000, 0>];
DetailO_0-0: POLY <36> {DetailP_0-1, DetailP_0-0, DetailP_0-2};
DetailN_0-0: LINE <36> {DetailP_0-1, DetailP_0-0};
__walls__: [<0, 0, 0>, c= <192>];
__asphalt__: [<0, 0, 0>, c= <44>];
TOPO_sec0_s0_L_HI: NIL;
sec0_s0_HI: FACE
  (DetailP_0-1, DetailP_0-0, DetailP_0-2),
  LIST {
    BSPA
      (DetailP_0-1, DetailP_0-0, DetailP_0-2),
      TOPO_sec0_s0_L_HI,
      MATERIAL GROUP = 2, MIP = "walls",
        POLY [T] __walls__.c {
          [<0,0,0>, T=<0,0>], [<1000,0,0>, T=<128,0>],
          [<0,1000,0>, T=<0,128>]
        },
      nil,
    ObjectList_L0_0,
    DetailO_0-0,
    DetailN_0-0,
    SWITCH DISTANCE ([<0,0,170000>])
      > {(1800000 ? nil), (0 ?
        POLY <36> {DetailP_0-1, DetailP_0-0, DetailP_0-2})}
  };
sec0_l0: LIST {
  sec0_s0_HI, nil, nil, nil,
  DATA {0, 0, 0, 0}
};
hash: DATA {
  0, 0, 1, 1, 2, 3, 4, 5, 5, 6, 6, 7, 8, 9, 10, 11,
  11, 12, 13, 14, 15, 16, 17, 18, 18, 19, 20, 21, 22,
  23, 24, 25, 26, 27, 28, 29, 30, 31, 31, 32, 33, 34
};
index: LIST { hash, sec0_l0 };
"""


class TrackStyleN3Tests(unittest.TestCase):
    def test_header_without_semicolon_and_hyphenated_declarations(self):
        document=parse_document(TRACK_N3,require_offsets=False)
        names={stmt.label for stmt in document.statements}
        self.assertIn("DetailP_0-1",names)
        self.assertIn("DetailO_0-0",names)
        self.assertEqual(document.original_text,TRACK_N3)

    def test_windows_crlf_reno_header_is_accepted(self):
        # Actual RENO.3D begins with b'3D VERSION 3.0\r\n' (no semicolon).
        source=TRACK_N3.replace("\n","\r\n")
        doc=parse_document(source,require_offsets=False)
        self.assertEqual(doc.original_text,source)
        self.assertEqual(len(doc.statements),
                         len(parse_document(TRACK_N3,require_offsets=False).statements))
        self.assertEqual(doc.statements[-1].label,"index")

        # The full synthetic RENO tree exercises additional compiler features;
        # verify the end-to-end header fix separately on a minimal N3 model.
        simple=("3D VERSION 3.0\r\n"
                "nil: NIL;\r\n"
                "a: [<0,0,0>];\r\n"
                "b: [<100,0,0>];\r\n"
                "c: [<0,100,0>];\r\n"
                "p: POLY <44> {a,b,c};\r\n"
                "root: LIST {p};\r\n")
        model,_=compile_n3_text(simple,"simple_crlf.3d")
        self.assertEqual(len(model.polygons),1)

    def test_header_variants_and_comments(self):
        for header in ("3D VERSION 3.0", "3D VERSION 3.0;",
                       "3D VERSION 3.0; % track notes",
                       "\ufeff3D VERSION 3.0"):
            with self.subTest(header=header):
                sample=TRACK_N3.replace("3D VERSION 3.0",header,1).replace("\n","\r\n")
                doc=parse_document(sample,require_offsets=False)
                self.assertIn("index",{entry.label for entry in doc.statements})

    def test_invalid_header_is_rejected(self):
        from three_do import FormatError
        with self.assertRaisesRegex(FormatError,"VERSION 3.0"):
            parse_document(TRACK_N3.replace("3D VERSION 3.0","3D VERSION 2.0",1),
                           require_offsets=False)

    def test_compile_track_hierarchy_hash_data_and_root_index(self):
        model,document=compile_n3_text(TRACK_N3,"RENO.3D")
        self.assertEqual(model.records[model.root_offset],11)
        self.assertEqual(len(model.dynamics),1)
        self.assertGreaterEqual(len(model.polygons),3)
        self.assertGreaterEqual(len(model.planes),2)
        self.assertEqual(len(model.switches),1)
        self.assertEqual(next(iter(model.switches.values())).branches[0][0],1800000)
        self.assertEqual(model.mip_names,["walls"])
        self.assertEqual(model.external_names,["stand100"])
        hashes=[s for s in document.statements if s.label=="hash"]
        self.assertEqual(len(hashes),1)
        hash_offset=hashes[0].offset
        self.assertEqual(model.records[hash_offset],17)
        self.assertEqual(model.n3_data_lengths[hash_offset],42)
        self.assertEqual(model.body[hash_offset:hash_offset+4],b"\x11\x00\x00\x80")
        self.assertEqual(set(names_for_vertices(model,document,original_n3=True).values())&
                         {"DetailP_0-1","DetailP_0-0","DetailP_0-2"},
                         {"DetailP_0-1","DetailP_0-0","DetailP_0-2"})

    def test_standalone_data_survives_export_after_coordinate_edit(self):
        model,doc=compile_n3_text(TRACK_N3,"RENO.3D")
        original_raw=model.raw
        ref=next(x.offset for x in doc.statements if x.label=="DetailP_0-1")
        model.set_vertex(ref,(100,0,0))
        source=export_standalone_text(model,doc,original_raw)
        self.assertIn("DetailP_0-1:",source)
        self.assertIn("hash: DATA {",source)
        rebuilt,remapped=compile_n3_text(source,"RENO_edited.3D")
        old_hash=next(x.command for x in doc.statements if x.label=="hash")
        new_hash=next(x.command for x in remapped.statements if x.label=="hash")
        self.assertEqual(old_hash,new_hash)
        self.assertEqual(rebuilt.records[rebuilt.root_offset],11)

    def test_hyphenated_names_rename_without_corrupting_neighbors(self):
        model,doc=compile_n3_text(TRACK_N3,"RENO.3D")
        renamed=rename_vertex_in_source(TRACK_N3,doc,"DetailP_0-1","TSD_start")
        self.assertIn("TSD_start:",renamed)
        self.assertIn("DetailP_0-0:",renamed)
        self.assertNotIn("DetailP_0-1",renamed)
        rebuilt,_=compile_n3_text(renamed,"RENORenamed.3D")
        self.assertGreater(len(rebuilt.vertices),0)


if __name__=="__main__":
    unittest.main()
