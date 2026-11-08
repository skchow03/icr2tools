# ICR2 3DO AI contributor instructions

Scope: icr2_3do_ai/.

The inspector is a read-only consumer of icr2_3do_cad, not another 3DO
binary parser or a GUI. Preserve all source game binaries and sibling assets.
Reports must only be written under explicitly requested output directories;
do not silently overwrite existing analysis or source files.

Keep stable instance and original body-record offsets in JSON. Distinguish
geometric adjacency from subjective component identification. Geometric normals
are not proof of FACE/BSP visibility. Missing dependencies are incomplete
analysis, not confirmed absent game components.

Run the headless tests from the repository root:

    python -m unittest discover -s icr2_3do_ai/tests -p 'test_*.py' -v

Do not depend on an LLM, network access, Qt, or OpenGL for core inspection.
