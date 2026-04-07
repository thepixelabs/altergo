"""Ensure the local altergo.py is imported instead of any installed package."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))
