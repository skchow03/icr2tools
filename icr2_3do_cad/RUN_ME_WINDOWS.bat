@echo off
setlocal
cd /d "%~dp0"
py -3 -c "import numpy, PySide6, OpenGL, PIL" 2>NUL
if errorlevel 1 (
  echo The 3DO CAD dependencies are missing.
  echo Install them with: py -3 -m pip install -r "%~dp0requirements.txt"
  pause
  exit /b 1
)
py -3 icr2_3do_cad.py %*
if errorlevel 1 (
  echo.
  echo Could not launch ICR2 3DO CAD. Check Python and your OpenGL driver.
  pause
)
