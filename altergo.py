#!/usr/bin/env python3
"""altergo — compatibility stub that delegates to the altergo package.

This file exists solely so that ``python altergo.py`` and subprocess-level
tests that run the script directly continue to work after the codebase moved
to the ``altergo/`` package layout.  All real logic lives in the package.
"""
import sys
from pathlib import Path

# Ensure the package is importable when running the script from source.
sys.path.insert(0, str(Path(__file__).parent))

from altergo.cli import main  # noqa: E402

if __name__ == "__main__":
    main()
