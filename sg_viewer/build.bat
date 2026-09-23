pyinstaller --noconfirm --windowed --onefile main.py ^
  --name SGCreate ^
  --icon sg_create.ico ^
  --add-data sg_create.ico;. ^
  --add-data studio_chatter.json;. ^
  --paths ..
copy /Y studio_chatter.json dist\studio_chatter.json
