pyinstaller --noconfirm --windowed --onefile main.py ^
  --name ICR2Timing ^
  --add-data "ui/control_panel.ui;ui" ^
  --add-data "assets/icon.ico;assets" ^
  --icon assets/icon.ico
