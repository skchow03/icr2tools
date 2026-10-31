@echo off
cd /d "%~dp0"
py -3 -c "import PIL, numpy" 2>NUL
if errorlevel 1 (
  echo Optional texture preview dependencies are missing.
  echo Install them once with: py -3 -m pip install Pillow numpy
  echo The editor will still open using solid-color rendering.
  echo.
)
py -3 icr2_3do_cad.py %*
if errorlevel 1 (
  echo.
  echo Failed to launch the editor. Make sure Python 3 with Tkinter is installed.
  pause
)
