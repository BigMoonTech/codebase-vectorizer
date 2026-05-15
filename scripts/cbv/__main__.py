"""Module entry point: `python -m cbv <verb> ...`."""
from __future__ import annotations

import sys

from cbv.cli import main

if __name__ == "__main__":
    sys.exit(main())
