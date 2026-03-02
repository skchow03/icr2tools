from __future__ import annotations

import sys
from pathlib import Path

# Ensure repo root is on sys.path when running this file directly
if __package__ is None or __package__ == "":
    sys.path.append(str(Path(__file__).resolve().parent.parent))

from sunny_optimizer.ui.main_window import main


if __name__ == "__main__":
    main()