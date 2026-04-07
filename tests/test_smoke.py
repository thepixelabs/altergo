"""Basic smoke tests — verify the script is importable and version is set."""

import importlib.util
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).parent.parent
SCRIPT = ROOT / "altergo.py"


def _load_altergo():
    spec = importlib.util.spec_from_file_location("altergo", SCRIPT)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


# Load once at module level so monkeypatching targets the same object.
import altergo  # noqa: E402  (import after path manipulation is fine here)


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


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture()
def fake_home(tmp_path, monkeypatch):
    """Isolated fake HOME layout.

    Creates the directory skeleton expected by altergo:
      <tmp>/main_home/        ← MAIN_HOME
      <tmp>/main_home/.claude/ ← MAIN_CLAUDE
      <tmp>/main_home/.altergo/accounts/ ← ACCOUNTS_DIR

    Patches the altergo module globals so every function under test uses
    tmp_path instead of the real ~/.
    """
    main_home = tmp_path / "main_home"
    main_claude = main_home / ".claude"
    accounts_dir = main_home / ".altergo" / "accounts"

    main_home.mkdir()
    main_claude.mkdir(parents=True)
    accounts_dir.mkdir(parents=True)

    monkeypatch.setattr(altergo, "MAIN_HOME", main_home)
    monkeypatch.setattr(altergo, "MAIN_CLAUDE", main_claude)
    monkeypatch.setattr(altergo, "ACCOUNTS_DIR", accounts_dir)
    monkeypatch.setattr(altergo, "SETTINGS_FILE", main_home / ".altergo" / ".altergo.json")

    return {
        "main_home": main_home,
        "main_claude": main_claude,
        "accounts_dir": accounts_dir,
    }


# ---------------------------------------------------------------------------
# T6 — Account tests
# ---------------------------------------------------------------------------


def test_unknown_account_error(tmp_path):
    """altergo <name> where the account dir doesn't exist exits 1 with a useful message."""
    # Use a fresh accounts dir with no accounts in it.
    result = subprocess.run(
        [sys.executable, str(SCRIPT), "wokr"],
        capture_output=True,
        text=True,
        env={
            **__import__("os").environ,
            # Point ALTERGO_ACCOUNTS_DIR isn't a real env var — we drive this
            # via the process-level env that sets HOME to a clean tmp dir so
            # that detect_legacy() sees no legacy layout and ACCOUNTS_DIR
            # resolves to a path with no "wokr" subdirectory.
            "HOME": str(tmp_path),
        },
    )
    assert result.returncode == 1
    assert "wokr" in result.stderr
    assert "not found" in result.stderr
    assert "--setup --name wokr" in result.stderr


def test_validate_account_name_valid():
    """validate_account_name raises nothing for a well-formed name."""
    # Should complete without raising.
    altergo.validate_account_name("work")
    altergo.validate_account_name("client-a")
    altergo.validate_account_name("acct_2")


def test_validate_account_name_reserved():
    """validate_account_name raises SystemExit for a reserved name."""
    with pytest.raises(SystemExit):
        altergo.validate_account_name("default")


def test_validate_account_name_bad_chars():
    """validate_account_name raises SystemExit when the name contains spaces."""
    with pytest.raises(SystemExit):
        altergo.validate_account_name("my account")


def test_list_accounts_empty(fake_home):
    """list_accounts returns [] when ACCOUNTS_DIR does not exist."""
    # Remove the accounts dir that fake_home created.
    import shutil
    shutil.rmtree(str(fake_home["accounts_dir"]))
    assert altergo.list_accounts() == []


def test_list_accounts_populated(fake_home):
    """list_accounts returns sorted account names for all subdirectories."""
    accounts_dir = fake_home["accounts_dir"]
    (accounts_dir / "work").mkdir()
    (accounts_dir / "personal").mkdir()
    # Hidden directories should not appear.
    (accounts_dir / ".hidden").mkdir()

    result = altergo.list_accounts()
    assert result == ["personal", "work"]


# ---------------------------------------------------------------------------
# T7 — Migration tests
# ---------------------------------------------------------------------------


@pytest.fixture()
def legacy_home(tmp_path, monkeypatch):
    """Fake HOME with the old (pre-v0.5) layout: ~/.altergo/.claude/ exists."""
    main_home = tmp_path / "main_home"
    legacy_claude = main_home / ".altergo" / ".claude"
    legacy_claude.mkdir(parents=True)
    # Write a sentinel file so we can verify it survived the migration.
    (legacy_claude / ".credentials.json").write_text('{"token": "test"}')

    # ACCOUNTS_DIR does NOT exist yet — that is the trigger condition.
    accounts_dir = main_home / ".altergo" / "accounts"

    monkeypatch.setattr(altergo, "MAIN_HOME", main_home)
    monkeypatch.setattr(altergo, "MAIN_CLAUDE", main_home / ".claude")
    monkeypatch.setattr(altergo, "ACCOUNTS_DIR", accounts_dir)
    monkeypatch.setattr(altergo, "SETTINGS_FILE", main_home / ".altergo" / ".altergo.json")

    return {
        "main_home": main_home,
        "accounts_dir": accounts_dir,
    }


def test_detect_legacy_true(legacy_home):
    """detect_legacy returns True when ~/.altergo/.claude/ exists and accounts/ does not."""
    assert altergo.detect_legacy() is True


def test_detect_legacy_false_new(fake_home):
    """detect_legacy returns False when accounts/ already exists (new layout)."""
    assert altergo.detect_legacy() is False


def test_detect_legacy_false_clean(tmp_path, monkeypatch):
    """detect_legacy returns False when neither .claude/ nor accounts/ exists."""
    main_home = tmp_path / "clean_home"
    main_home.mkdir()
    monkeypatch.setattr(altergo, "MAIN_HOME", main_home)
    monkeypatch.setattr(altergo, "ACCOUNTS_DIR", main_home / ".altergo" / "accounts")

    assert altergo.detect_legacy() is False


def test_migrate_legacy_layout(legacy_home):
    """After migrate_legacy(), the old .claude/ content lives under accounts/default/.claude/."""
    altergo.migrate_legacy()

    default_claude = legacy_home["accounts_dir"] / "default" / ".claude"
    assert default_claude.is_dir()
    assert (default_claude / ".credentials.json").exists()


def test_migrate_legacy_backup(legacy_home):
    """After migrate_legacy(), a backup exists at .altergo/.legacy-backup/."""
    altergo.migrate_legacy()

    backup = legacy_home["main_home"] / ".altergo" / ".legacy-backup"
    assert backup.is_dir()
    # Backup preserves the original content.
    assert (backup / ".claude" / ".credentials.json").exists()


def test_migrate_legacy_prints_once(legacy_home, capsys):
    """migrate_legacy() prints a migration block (not silence) exactly once."""
    altergo.migrate_legacy()

    captured = capsys.readouterr()
    out = captured.out
    # Must mention both the new location and the backup in its output.
    assert "accounts/default" in out
    assert ".legacy-backup" in out
    # Must not print anything on a second run (idempotent — covered by separate test).
    altergo.migrate_legacy()
    assert capsys.readouterr().out == ""


def test_migrate_legacy_idempotent(legacy_home, capsys):
    """Running migrate_legacy() twice produces no error and no output on the second run."""
    altergo.migrate_legacy()
    capsys.readouterr()  # discard first-run output

    # Second call: accounts/ already exists, so migration is skipped.
    altergo.migrate_legacy()

    captured = capsys.readouterr()
    assert captured.out == ""
    assert captured.err == ""


# ---------------------------------------------------------------------------
# T8 — Symlink audit tests
# ---------------------------------------------------------------------------


def _create_main_claude_sources(main_claude: Path):
    """Create the source dirs/files in MAIN_CLAUDE that do_setup() will symlink."""
    for name in altergo.SYMLINK_DIRS:
        (main_claude / name).mkdir(parents=True, exist_ok=True)
    for name in altergo.SYMLINK_FILES:
        (main_claude / name).touch()


def _create_catalog_sources(main_home: Path):
    """Create source paths in MAIN_HOME for every default_on catalog entry."""
    for entry in altergo.CATALOG:
        if entry["default_on"]:
            for rel in entry["paths"]:
                src = main_home / rel
                src.mkdir(parents=True, exist_ok=True)


def test_setup_creates_claude_symlinks(fake_home):
    """do_setup() creates symlinks for SYMLINK_DIRS inside account_home/.claude/."""
    main_claude = fake_home["main_claude"]
    accounts_dir = fake_home["accounts_dir"]
    _create_main_claude_sources(main_claude)

    altergo.do_setup("work")

    account_claude = accounts_dir / "work" / ".claude"
    for name in altergo.SYMLINK_DIRS:
        link = account_claude / name
        assert link.is_symlink(), f"{name}/ should be a symlink inside account .claude/"
        assert link.resolve() == (main_claude / name).resolve()


def test_setup_creates_claude_file_symlinks(fake_home):
    """do_setup() creates symlinks for SYMLINK_FILES inside account_home/.claude/."""
    main_claude = fake_home["main_claude"]
    accounts_dir = fake_home["accounts_dir"]
    _create_main_claude_sources(main_claude)

    altergo.do_setup("work")

    account_claude = accounts_dir / "work" / ".claude"
    for name in altergo.SYMLINK_FILES:
        link = account_claude / name
        assert link.is_symlink(), f"{name} should be a symlink inside account .claude/"
        assert link.resolve() == (main_claude / name).resolve()


def test_setup_creates_home_dir_symlinks(fake_home):
    """do_setup() creates CATALOG symlinks at account_home level pointing into MAIN_HOME."""
    main_home = fake_home["main_home"]
    accounts_dir = fake_home["accounts_dir"]
    _create_main_claude_sources(fake_home["main_claude"])
    _create_catalog_sources(main_home)

    altergo.do_setup("work")

    account_home = accounts_dir / "work"
    for entry in altergo.CATALOG:
        if not entry["default_on"]:
            continue
        for rel in entry["paths"]:
            link = account_home / rel
            src = main_home / rel
            assert link.is_symlink(), f"~/{rel} should be a symlink at account_home level"
            assert link.resolve() == src.resolve(), f"~/{rel} must point into MAIN_HOME"


def test_symlinks_no_escape(fake_home):
    """All symlink targets inside account_home/.claude/ resolve within MAIN_HOME/.claude/."""
    main_claude = fake_home["main_claude"]
    accounts_dir = fake_home["accounts_dir"]
    _create_main_claude_sources(main_claude)

    altergo.do_setup("work")

    account_claude = accounts_dir / "work" / ".claude"
    for link in account_claude.iterdir():
        if not link.is_symlink():
            continue
        resolved = link.resolve()
        # The target must live inside MAIN_HOME/.claude/, never outside it.
        try:
            resolved.relative_to(main_claude.resolve())
        except ValueError:
            pytest.fail(
                f"Symlink {link.name} escapes MAIN_CLAUDE: target is {resolved}"
            )


def test_teardown_removes_symlinks(fake_home):
    """do_teardown() removes all symlinks that do_setup() created."""
    main_home = fake_home["main_home"]
    main_claude = fake_home["main_claude"]
    accounts_dir = fake_home["accounts_dir"]
    _create_main_claude_sources(main_claude)
    _create_catalog_sources(main_home)

    altergo.do_setup("work")
    altergo.do_teardown("work")

    account_claude = accounts_dir / "work" / ".claude"
    account_home = accounts_dir / "work"

    # All .claude/ symlinks must be gone.
    for name in altergo.SYMLINK_DIRS:
        assert not (account_claude / name).is_symlink(), f"{name}/ symlink should be removed"

    for name in altergo.SYMLINK_FILES:
        assert not (account_claude / name).is_symlink(), f"{name} symlink should be removed"

    # All CATALOG symlinks at account_home level must be gone.
    for entry in altergo.CATALOG:
        if not entry["default_on"]:
            continue
        for rel in entry["paths"]:
            link = account_home / rel
            assert not link.is_symlink(), f"~/{rel} symlink should be removed after teardown"
