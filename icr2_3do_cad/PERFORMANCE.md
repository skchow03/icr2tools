# Profiling ICR2 3DO CAD

The editor supports optional benchmarking of the live OpenGL viewport. From the repository root:

```sh
python icr2_3do_cad/icr2_3do_cad.py path/to/RENO.3D --benchmark --report cad_profile.json
```

Or run from `icr2_3do_cad/` with `python icr2_3do_cad.py path/to/RENO.3D --benchmark --report cad_profile.json`.

`--benchmark` requests redraws at approximately 60 Hz; Qt's `frameSwapped` reports actual presented frames, subject to display refresh/VSync. `--report` writes aggregate timings (loading, scene generation, upload and FPS) when the application closes. Compare the same view and options on the same hardware, using both a large track and a small car/object model. Timing results do not prove a game-exact renderer.

For automated rendering smoke tests, run `python icr2_3do_cad/smoke_test.py icr2_3do_cad/fixtures/roadcar.3do` with a working OpenGL 3.3 context; headless Linux CI uses Xvfb and Mesa. Historical Tk canvas profiling notes remain in Git history.
