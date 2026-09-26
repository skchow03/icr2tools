@echo off
setlocal
cd /d "%~dp0"

rem Bundle a factory default for first-run recovery, but keep the working JSON
rem external so it remains editable without rebuilding the EXE.
pyinstaller --noconfirm --windowed --onefile main.py ^
  --name ICR2TrackViewer ^
  --paths .. ^
  --add-data "config\car_performance.json;track_viewer\config"

if errorlevel 1 (
  echo PyInstaller build failed.
  exit /b 1
)

rem Keep the editable JSON next to the EXE and any INI files. Preserve edits
rem from an earlier build that placed the JSON in dist\config.
if not exist "dist\car_performance.json" (
  if exist "dist\config\car_performance.json" (
    copy /y "dist\config\car_performance.json" "dist\car_performance.json" >nul
  ) else (
    copy /y "config\car_performance.json" "dist\car_performance.json" >nul
  )
  if errorlevel 1 (
    echo Failed to copy the editable car performance configuration.
    exit /b 1
  )
)

echo Build complete. Edit dist\car_performance.json to customize the model.
endlocal
