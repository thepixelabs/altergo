"""Basic smoke tests — verify the script is importable and version is set."""

import importlib.util
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).parent.parent
SCRIPT = ROOT / "altergo.py"


def _load_altergo():
    spec = importlib.util.spec_from_file_location("altergo", SCRIPT)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_version_set():
    mod = _load_altergo()
    assert mod.__version__, "version must be non-empty"
    parts = mod.__version__.split(".")
    assert len(parts) == 3, "version must be semver (x.y.z)"


def test_version_flag(tmp_path):
    result = subprocess.run(
        [sys.executable, str(SCRIPT), "--version"],
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0
    assert "altergo" in result.stdout.lower()


def test_help_flag(tmp_path):
    result = subprocess.run(
        [sys.executable, str(SCRIPT), "--help"],
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0
