pyinstaller --noconfirm --clean --windowed --onefile main.py ^
  --name ICR2TrackViewer ^
  --paths .. ^
  --add-data "config\car_performance.json;track_viewer\config"