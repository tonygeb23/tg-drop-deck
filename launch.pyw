"""Start TG Drop Deck with no console window.

This is what the desktop shortcut points at. Run it with pythonw.
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from main import main

if __name__ == "__main__":
    sys.exit(main())
