pyinstaller --noconfirm --windowed --onefile main.py ^
  --name SGCreate ^
  --icon sg_create.ico ^
  --add-data sg_create.ico;. ^
  --paths ..