"""Ensure the local altergo.py is imported instead of any installed package."""
import os
import stat
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

import pytest  # noqa: E402

# ---------------------------------------------------------------------------
# Ensure the fake claude sentinel binary is executable.
#
# Git does not always preserve the +x bit (e.g. on Windows checkouts, or when
# the file was just created by a tool).  Setting the bit here at import time
# means it is guaranteed to be executable before any test collection starts.
# ---------------------------------------------------------------------------
_FAKE_CLAUDE = Path(__file__).parent / "bin" / "claude"
if _FAKE_CLAUDE.exists():
    _FAKE_CLAUDE.chmod(_FAKE_CLAUDE.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)


# ---------------------------------------------------------------------------
# full_home — realistic on-disk HOME structure for subprocess-level tests
# ---------------------------------------------------------------------------


@pytest.fixture()
def full_home(tmp_path):
    """Create a complete realistic HOME structure on disk for subprocess tests.

    Layout::

        <tmp>/home/                        <- MAIN_HOME (will be HOME env var)
          .claude/
            projects/                      <- real dir (sessions live here)
            tasks/
            settings.json
            CLAUDE.md
          .altergo/
            accounts/
              default/
                .claude/
                  projects -> ../../../.claude/projects  (symlink)
                  tasks    -> ../../../.claude/tasks      (symlink)
                  settings.json -> ...                    (symlink)
                  CLAUDE.md     -> ...                    (symlink)
              work/
                .claude/ ...               (same symlinks)
              personal/
                .claude/ ...               (same symlinks)

    The accounts are set up by calling altergo.do_setup() with module globals
    temporarily pointed at this tree.  Globals are restored before the fixture
    yields so that the test body sees the original (real) globals — subprocess
    tests drive altergo via HOME env, not via Python globals.

    Returns a dict::

        {
            "home":         Path  <- the fake HOME root (pass as HOME= in env)
            "main_claude":  Path  <- <home>/.claude/
            "accounts_dir": Path  <- <home>/.altergo/accounts/
            "default_home": Path  <- <home>/.altergo/accounts/default/
            "work_home":    Path  <- <home>/.altergo/accounts/work/
            "personal_home":Path  <- <home>/.altergo/accounts/personal/
        }
    """
    import altergo

    home = tmp_path / "home"
    main_claude = home / ".claude"
    accounts_dir = home / ".altergo" / "accounts"

    # Build the MAIN_HOME/.claude/ sources that do_setup() will symlink from.
    for name in altergo.SYMLINK_DIRS:
        (main_claude / name).mkdir(parents=True, exist_ok=True)
    for name in altergo.SYMLINK_FILES:
        (main_claude / name).touch()

    accounts_dir.mkdir(parents=True, exist_ok=True)

    # Temporarily redirect module globals so do_setup() operates on our tree.
    # We save and restore manually (rather than using monkeypatch) so that
    # globals are clean when the fixture yields and the test body runs.
    _saved = {
        "MAIN_HOME": altergo.MAIN_HOME,
        "MAIN_CLAUDE": altergo.MAIN_CLAUDE,
        "ACCOUNTS_DIR": altergo.ACCOUNTS_DIR,
        "SETTINGS_FILE": altergo.SETTINGS_FILE,
    }
    altergo.MAIN_HOME = home
    altergo.MAIN_CLAUDE = main_claude
    altergo.ACCOUNTS_DIR = accounts_dir
    altergo.SETTINGS_FILE = home / ".altergo" / ".altergo.json"
    try:
        altergo.do_setup("default")
        altergo.do_setup("work")
        altergo.do_setup("personal")
    finally:
        # Always restore — even if do_setup raises.
        for attr, val in _saved.items():
            setattr(altergo, attr, val)

    return {
        "home": home,
        "main_claude": main_claude,
        "accounts_dir": accounts_dir,
        "default_home": accounts_dir / "default",
        "work_home": accounts_dir / "work",
        "personal_home": accounts_dir / "personal",
    }


# ---------------------------------------------------------------------------
# fake_claude_bin — puts tests/bin/ at the front of PATH
# ---------------------------------------------------------------------------

_TESTS_BIN = Path(__file__).parent / "bin"


@pytest.fixture()
def fake_claude_bin(monkeypatch):
    """Add tests/bin/ to the front of PATH so altergo finds the fake claude binary.

    The fake binary at tests/bin/claude is a real executable shell script that
    prints ALTERGO_TEST_* sentinel lines to stdout.  shutil.which("claude")
    will resolve to it when tests/bin/ is first on PATH.
    """
    current_path = os.environ.get("PATH", "")
    monkeypatch.setenv("PATH", f"{_TESTS_BIN}:{current_path}")
