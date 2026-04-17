"""Basic smoke tests — verify the script is importable and version is set."""

import importlib.util
import io
import json
import subprocess
import sys
from pathlib import Path
from unittest.mock import patch

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
    assert "--config wokr" in result.stderr


def test_validate_account_name_valid():
    """validate_account_name raises nothing for a well-formed name."""
    # Should complete without raising.
    altergo.validate_account_name("work")
    altergo.validate_account_name("client-a")
    altergo.validate_account_name("acct_2")


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


# ---------------------------------------------------------------------------
# T8 — Symlink audit tests
# ---------------------------------------------------------------------------


def _create_main_claude_sources(main_claude: Path):
    """Create the source dirs/files in MAIN_CLAUDE that do_config() will symlink."""
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
    """do_config() creates symlinks for SYMLINK_DIRS inside account_home/.claude/."""
    main_claude = fake_home["main_claude"]
    accounts_dir = fake_home["accounts_dir"]
    _create_main_claude_sources(main_claude)

    altergo.do_config("work")

    account_claude = accounts_dir / "work" / ".claude"
    for name in altergo.SYMLINK_DIRS:
        link = account_claude / name
        assert link.is_symlink(), f"{name}/ should be a symlink inside account .claude/"
        assert link.resolve() == (main_claude / name).resolve()


def test_setup_creates_claude_file_symlinks(fake_home):
    """do_config() creates symlinks for SYMLINK_FILES inside account_home/.claude/."""
    main_claude = fake_home["main_claude"]
    accounts_dir = fake_home["accounts_dir"]
    _create_main_claude_sources(main_claude)

    altergo.do_config("work")

    account_claude = accounts_dir / "work" / ".claude"
    for name in altergo.SYMLINK_FILES:
        link = account_claude / name
        assert link.is_symlink(), f"{name} should be a symlink inside account .claude/"
        assert link.resolve() == (main_claude / name).resolve()


def test_setup_creates_home_dir_symlinks(fake_home):
    """do_config() creates CATALOG symlinks at account_home level pointing into MAIN_HOME."""
    main_home = fake_home["main_home"]
    accounts_dir = fake_home["accounts_dir"]
    _create_main_claude_sources(fake_home["main_claude"])
    _create_catalog_sources(main_home)

    altergo.do_config("work")

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

    altergo.do_config("work")

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
    """do_teardown() removes all symlinks that do_config() created."""
    main_home = fake_home["main_home"]
    main_claude = fake_home["main_claude"]
    accounts_dir = fake_home["accounts_dir"]
    _create_main_claude_sources(main_claude)
    _create_catalog_sources(main_home)

    altergo.do_config("work")
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


# ---------------------------------------------------------------------------
# T8b — MCP sync tests
# ---------------------------------------------------------------------------


def test_mcp_sync_from_main_to_account(fake_home):
    """do_config() syncs mcpServers from MAIN_HOME/.claude.json into account."""
    main_home = fake_home["main_home"]
    accounts_dir = fake_home["accounts_dir"]
    _create_main_claude_sources(fake_home["main_claude"])

    # Main home has an MCP server configured
    (main_home / ".claude.json").write_text(json.dumps({
        "mcpServers": {"dispatch": {"url": "http://localhost:4242"}},
        "oauthAccount": {"email": "main@example.com"},
    }))

    altergo.do_config("work")

    acct_cfg = accounts_dir / "work" / ".claude.json"
    assert acct_cfg.exists(), "account must have its own .claude.json"
    assert not acct_cfg.is_symlink(), ".claude.json must be a real file, not a symlink"
    data = json.loads(acct_cfg.read_text())
    assert "dispatch" in data.get("mcpServers", {}), "MCP server must be synced to account"


def test_mcp_sync_from_account_to_main(fake_home):
    """do_config() pushes account-only mcpServers back to MAIN_HOME/.claude.json."""
    main_home = fake_home["main_home"]
    accounts_dir = fake_home["accounts_dir"]
    _create_main_claude_sources(fake_home["main_claude"])

    # Main home has no MCPs; account already has one
    (main_home / ".claude.json").write_text('{}')
    account_home = accounts_dir / "work"
    account_home.mkdir(parents=True, exist_ok=True)
    (account_home / ".claude.json").write_text(json.dumps({
        "mcpServers": {"local-tool": {"command": "npx", "args": ["tool"]}},
    }))

    altergo.do_config("work")

    main_data = json.loads((main_home / ".claude.json").read_text())
    assert "local-tool" in main_data.get("mcpServers", {}), "account MCP must propagate to main home"


def test_mcp_sync_bidirectional_merge(fake_home):
    """do_config() merges mcpServers from both sides; account wins on conflict."""
    main_home = fake_home["main_home"]
    accounts_dir = fake_home["accounts_dir"]
    _create_main_claude_sources(fake_home["main_claude"])

    (main_home / ".claude.json").write_text(json.dumps({
        "mcpServers": {
            "shared": {"url": "http://main"},
            "main-only": {"url": "http://main-only"},
        },
    }))
    account_home = accounts_dir / "work"
    account_home.mkdir(parents=True, exist_ok=True)
    (account_home / ".claude.json").write_text(json.dumps({
        "mcpServers": {
            "shared": {"url": "http://account"},
            "acct-only": {"url": "http://acct-only"},
        },
    }))

    altergo.do_config("work")

    main_data = json.loads((main_home / ".claude.json").read_text())
    acct_data = json.loads((account_home / ".claude.json").read_text())

    # Both should have all 3 servers
    for label, data in [("main", main_data), ("account", acct_data)]:
        mcps = data.get("mcpServers", {})
        assert "shared" in mcps, f"{label} missing 'shared'"
        assert "main-only" in mcps, f"{label} missing 'main-only'"
        assert "acct-only" in mcps, f"{label} missing 'acct-only'"

    # Account wins on conflict
    assert main_data["mcpServers"]["shared"]["url"] == "http://account"
    assert acct_data["mcpServers"]["shared"]["url"] == "http://account"


def test_mcp_sync_preserves_oauth_per_account(fake_home):
    """MCP sync does not clobber account-specific oauthAccount."""
    main_home = fake_home["main_home"]
    accounts_dir = fake_home["accounts_dir"]
    _create_main_claude_sources(fake_home["main_claude"])

    (main_home / ".claude.json").write_text(json.dumps({
        "oauthAccount": {"email": "main@example.com"},
        "mcpServers": {"srv": {"url": "http://srv"}},
    }))
    account_home = accounts_dir / "work"
    account_home.mkdir(parents=True, exist_ok=True)
    (account_home / ".claude.json").write_text(json.dumps({
        "oauthAccount": {"email": "work@example.com"},
    }))

    altergo.do_config("work")

    acct_data = json.loads((account_home / ".claude.json").read_text())
    assert acct_data["oauthAccount"]["email"] == "work@example.com", \
        "account oauthAccount must NOT be overwritten by sync"
    assert "srv" in acct_data.get("mcpServers", {}), "MCP must still be synced"


def test_mcp_sync_unsymlinks_migration(fake_home):
    """If .claude.json is a symlink (v0.21.1 migration), sync replaces it with a real file."""
    main_home = fake_home["main_home"]
    accounts_dir = fake_home["accounts_dir"]
    _create_main_claude_sources(fake_home["main_claude"])

    main_cfg = main_home / ".claude.json"
    main_cfg.write_text(json.dumps({
        "mcpServers": {"srv": {"url": "http://srv"}},
        "oauthAccount": {"email": "main@example.com"},
    }))

    # Simulate v0.21.1 state: account .claude.json is a symlink to main
    account_home = accounts_dir / "work"
    account_home.mkdir(parents=True, exist_ok=True)
    acct_cfg = account_home / ".claude.json"
    acct_cfg.symlink_to(main_cfg)

    altergo.do_config("work")

    assert not acct_cfg.is_symlink(), ".claude.json must be unsymlinked after migration"
    assert acct_cfg.exists(), ".claude.json must exist as a real file"
    data = json.loads(acct_cfg.read_text())
    assert "srv" in data.get("mcpServers", {}), "MCP servers must be preserved after unsymlink"


# ---------------------------------------------------------------------------
# T9 — _ensure_symlinked_dir / _sweep_existing_accounts
# ---------------------------------------------------------------------------


@pytest.fixture()
def sweep_home(tmp_path, monkeypatch):
    """Isolated fake HOME with main .claude/ sources but NO account dirs yet.

    MAIN_CLAUDE/projects and other SYMLINK_DIRS exist as real dirs.
    No accounts are created — tests create them manually to control state.
    """
    main_home = tmp_path / "main_home"
    main_claude = main_home / ".claude"
    accounts_dir = main_home / ".altergo" / "accounts"

    for name in altergo.SYMLINK_DIRS:
        (main_claude / name).mkdir(parents=True, exist_ok=True)
    for name in altergo.SYMLINK_FILES:
        (main_claude / name).touch()

    accounts_dir.mkdir(parents=True, exist_ok=True)

    monkeypatch.setattr(altergo, "MAIN_HOME", main_home)
    monkeypatch.setattr(altergo, "MAIN_CLAUDE", main_claude)
    monkeypatch.setattr(altergo, "ACCOUNTS_DIR", accounts_dir)
    monkeypatch.setattr(altergo, "SETTINGS_FILE", main_home / ".altergo" / ".altergo.json")

    return {
        "main_home": main_home,
        "main_claude": main_claude,
        "accounts_dir": accounts_dir,
    }


def test_merge_conflict_quarantine(sweep_home):
    """When both src and dst have a file with the same name, the dst file is
    moved to a quarantine directory and a warning is printed.
    """
    main_claude = sweep_home["main_claude"]
    accounts_dir = sweep_home["accounts_dir"]

    # Populate MAIN_CLAUDE/projects with one version of a session file.
    proj_dir_main = main_claude / "projects" / "foo"
    proj_dir_main.mkdir(parents=True, exist_ok=True)
    (proj_dir_main / "bar.jsonl").write_text("main-version\n")

    # Populate account_claude/projects with a *conflicting* version.
    account_home = accounts_dir / "default"
    account_claude = account_home / ".claude"
    proj_dir_acct = account_claude / "projects" / "foo"
    proj_dir_acct.mkdir(parents=True, exist_ok=True)
    (proj_dir_acct / "bar.jsonl").write_text("account-version\n")

    with patch("sys.stdout", new_callable=io.StringIO) as mock_out:
        altergo._sweep_existing_accounts()
        output = mock_out.getvalue()

    # The main version must be untouched.
    assert (proj_dir_main / "bar.jsonl").read_text() == "main-version\n", (
        "MAIN_CLAUDE/projects/foo/bar.jsonl must not be modified"
    )

    # The conflicting account version must be quarantined.
    quarantine = account_claude / "projects.altergo-conflict" / "foo" / "bar.jsonl"
    assert quarantine.exists(), (
        f"Conflicting file not found in quarantine at {quarantine}"
    )
    assert quarantine.read_text() == "account-version\n"

    # A warning must be printed.
    assert "conflict" in output.lower(), (
        f"Expected conflict warning in output, got: {output!r}"
    )


def test_list_then_resume_roundtrip(sweep_home):
    """Session written to MAIN_CLAUDE/projects/ is found by get_sessions() and
    is reachable via account_claude/projects/ (the path Claude Code uses when
    HOME=account_home).  This is the full --recall then launch chain.
    """
    main_claude = sweep_home["main_claude"]
    accounts_dir = sweep_home["accounts_dir"]

    # Set up a properly-symlinked default account.
    altergo.do_config("default")

    account_home = accounts_dir / "default"
    account_claude = account_home / ".claude"

    # Write a session into MAIN_CLAUDE/projects (as Claude Code would do).
    proj_dir = main_claude / "projects" / "myproject"
    proj_dir.mkdir(parents=True, exist_ok=True)
    session_id = "deadbeef1234"
    session_content = '{"type":"user","message":{"content":"what is 2+2?"}}\n'
    (proj_dir / f"{session_id}.jsonl").write_text(session_content)

    # get_sessions() must find it (it reads MAIN_CLAUDE/projects).
    sessions = altergo.get_sessions()
    session_ids = [s["id"] for s in sessions]
    assert session_id in session_ids, (
        f"Session {session_id!r} not found by get_sessions(); found: {session_ids}"
    )

    # The session file must be reachable via the account symlink
    # (this is the path Claude Code sees when HOME=account_home).
    via_account = account_claude / "projects" / "myproject" / f"{session_id}.jsonl"
    assert via_account.exists(), (
        "Session file not reachable via account_claude/projects symlink — "
        "--resume would fail after --recall found the session"
    )
    assert via_account.read_text() == session_content


def test_credentials_not_in_symlink_dirs_or_files():
    """.credentials.json must not appear in SYMLINK_DIRS or SYMLINK_FILES.

    Credentials are per-account by design; symlinking them would collapse
    account isolation entirely.
    """
    assert ".credentials.json" not in altergo.SYMLINK_DIRS
    assert ".credentials.json" not in altergo.SYMLINK_FILES
    assert "credentials" not in altergo.SYMLINK_DIRS
    assert "credentials" not in altergo.SYMLINK_FILES


def test_ensure_symlinked_dir_empty_real_dir(sweep_home, capsys):
    """Case (c): empty real dir is replaced by a symlink."""
    main_claude = sweep_home["main_claude"]
    accounts_dir = sweep_home["accounts_dir"]

    account_home = accounts_dir / "work"
    account_claude = account_home / ".claude"
    account_claude.mkdir(parents=True, exist_ok=True)

    # Create an empty real dir at dst
    dst = account_claude / "projects"
    dst.mkdir()
    src = main_claude / "projects"

    result = altergo._ensure_symlinked_dir("projects", src, dst, account_claude)

    assert result is True
    assert dst.is_symlink(), "Empty real dir must become a symlink"
    assert dst.resolve() == src.resolve()
    captured = capsys.readouterr()
    assert "Converted" in captured.out


def test_ensure_symlinked_dir_noop_when_correct(sweep_home):
    """Case (a): already a correct symlink — no-op, returns False."""
    main_claude = sweep_home["main_claude"]
    accounts_dir = sweep_home["accounts_dir"]

    account_home = accounts_dir / "work"
    account_claude = account_home / ".claude"
    account_claude.mkdir(parents=True, exist_ok=True)

    src = main_claude / "projects"
    dst = account_claude / "projects"
    dst.symlink_to(src)

    result = altergo._ensure_symlinked_dir("projects", src, dst, account_claude)
    assert result is False


# ---------------------------------------------------------------------------
# T10 — Provider structure tests
# ---------------------------------------------------------------------------


def test_providers_dict_structure():
    required_keys = {"display_name", "dot_dir", "binary", "credentials_file", "symlink_dirs", "symlink_files"}
    optional_keys = {"flags"}
    for pid, prov in altergo.PROVIDERS.items():
        actual_keys = set(prov.keys())
        missing = required_keys - actual_keys
        unknown = actual_keys - required_keys - optional_keys
        assert not missing, f"provider {pid!r} missing required keys: {missing}"
        assert not unknown, f"provider {pid!r} has unrecognised keys: {unknown}"
        assert isinstance(prov["symlink_dirs"], list), f"provider {pid!r} symlink_dirs must be a list"
        assert all(isinstance(s, str) for s in prov["symlink_dirs"]), f"provider {pid!r} symlink_dirs must be list of str"
        assert isinstance(prov["symlink_files"], list), f"provider {pid!r} symlink_files must be a list"
        assert all(isinstance(s, str) for s in prov["symlink_files"]), f"provider {pid!r} symlink_files must be list of str"


def test_credentials_isolation_all_providers():
    for pid, prov in altergo.PROVIDERS.items():
        creds = prov["credentials_file"]
        assert creds not in prov["symlink_dirs"], (
            f"provider {pid!r}: credentials_file {creds!r} must not appear in symlink_dirs"
        )
        assert creds not in prov["symlink_files"], (
            f"provider {pid!r}: credentials_file {creds!r} must not appear in symlink_files"
        )


def test_symlink_dirs_is_subset_of_claude_provider():
    assert set(altergo.SYMLINK_DIRS) == set(altergo.PROVIDERS["claude"]["symlink_dirs"])
    assert set(altergo.SYMLINK_FILES) == set(altergo.PROVIDERS["claude"]["symlink_files"])


def test_known_commands_contains_launch():
    assert "--launch" in altergo._KNOWN_COMMANDS


def test_looks_like_account_rejects_known_commands():
    assert altergo._looks_like_account("--launch") is False
    assert altergo._looks_like_account("--settings") is False
    assert altergo._looks_like_account("--use") is False


@pytest.mark.parametrize("provider_id", ["claude", "gemini", "codex", "copilot"])
def test_setup_creates_provider_symlinks(fake_home, provider_id):
    prov = altergo.PROVIDERS[provider_id]
    main_dot_dir = fake_home["main_home"] / prov["dot_dir"]

    for name in prov["symlink_dirs"]:
        (main_dot_dir / name).mkdir(parents=True, exist_ok=True)
    for name in prov["symlink_files"]:
        (main_dot_dir / name).touch()

    altergo.do_config("work", provider_id)

    account_dot_dir = fake_home["accounts_dir"] / "work" / prov["dot_dir"]

    for name in prov["symlink_dirs"]:
        link = account_dot_dir / name
        assert link.is_symlink(), f"provider {provider_id!r}: {name}/ should be a symlink"
        assert link.resolve() == (main_dot_dir / name).resolve()

    for name in prov["symlink_files"]:
        link = account_dot_dir / name
        assert link.is_symlink(), f"provider {provider_id!r}: {name} should be a symlink"

    creds_link = account_dot_dir / prov["credentials_file"]
    assert not creds_link.is_symlink(), (
        f"provider {provider_id!r}: credentials_file {prov['credentials_file']!r} must not be a symlink"
    )


def test_teardown_removes_provider_symlinks(fake_home):
    prov = altergo.PROVIDERS["gemini"]
    main_dot_dir = fake_home["main_home"] / ".gemini"

    for name in prov["symlink_dirs"]:
        (main_dot_dir / name).mkdir(parents=True, exist_ok=True)
    for name in prov["symlink_files"]:
        (main_dot_dir / name).touch()

    altergo.do_config("work", "gemini")

    account_dot_dir = fake_home["accounts_dir"] / "work" / ".gemini"
    created_symlinks = [account_dot_dir / name for name in prov["symlink_dirs"] if (account_dot_dir / name).is_symlink()]
    assert created_symlinks, "precondition: at least one symlink must exist after config"

    altergo.do_teardown("work")

    for name in prov["symlink_dirs"]:
        assert not (account_dot_dir / name).is_symlink(), f"gemini: {name}/ symlink should be removed after teardown"
    for name in prov["symlink_files"]:
        assert not (account_dot_dir / name).is_symlink(), f"gemini: {name} symlink should be removed after teardown"


# ---------------------------------------------------------------------------
# T11 — load_account_meta schema handling
# ---------------------------------------------------------------------------


def _write_account_json(account_home, data):
    """Write a JSON account.json file into account_home."""
    import json
    account_home.mkdir(parents=True, exist_ok=True)
    (account_home / "account.json").write_text(json.dumps(data))


def test_load_account_meta_v2_passthrough(tmp_path):
    """v2 file is returned unchanged without any upgrade logic applied."""
    account_home = tmp_path / "acct"
    _write_account_json(account_home, {
        "version": 2,
        "provider": "gemini",
        "created": "2026-01-01T00:00:00",
    })
    result = altergo.load_account_meta(account_home)
    assert result["version"] == 2
    assert result["provider"] == "gemini"
    assert result["created"] == "2026-01-01T00:00:00"


# ---------------------------------------------------------------------------
# T12 — v0.22.0 fixes
# ---------------------------------------------------------------------------


# T-A: 'use' subcommand exits 1 with "separate account" guidance in stderr.
# ACCOUNTS_DIR is anchored to the real passwd home (not $HOME) so we drive
# this as a unit test with monkeypatching rather than a subprocess test.
def test_use_subcommand_exits_with_separate_account_message(fake_home, monkeypatch, capsys):
    """altergo <account> use <provider> exits 1 and tells the user to create a separate account."""
    # Create a real account directory so account resolution succeeds.
    acct_dir = fake_home["accounts_dir"] / "myacct"
    acct_dir.mkdir(parents=True)

    monkeypatch.setattr(sys, "argv", ["altergo", "myacct", "use", "gemini"])
    with pytest.raises(SystemExit) as exc_info:
        altergo.main()

    assert exc_info.value.code == 1
    captured = capsys.readouterr()
    assert "separate account" in captured.err


# T-D: load_account_meta on a corrupt v2 file (missing "provider") returns safe default
def test_load_account_meta_v2_missing_provider_returns_default(tmp_path):
    """A v2 file without a 'provider' key returns a safe fallback without crashing."""
    account_home = tmp_path / "acct"
    _write_account_json(account_home, {
        "version": 2,
        "created": "2026-01-01T00:00:00",
        # "provider" key intentionally absent
    })
    result = altergo.load_account_meta(account_home)
    assert result["version"] == 2
    assert result["provider"] == "claude"


# T-E: integration — v1 multi-provider file on disk, 'use' subcommand exits 1 with --config hint
def test_use_subcommand_with_v1_disk_file_exits_1(tmp_path):
    """Write a v1 account.json with multiple providers into a temp accounts dir,
    run 'altergo work use gemini', assert exit code 1 and '--config' in stderr."""
    import json

    accounts_dir = tmp_path / ".altergo" / "accounts"
    account_home = accounts_dir / "work"
    account_home.mkdir(parents=True)
    (account_home / "account.json").write_text(
        json.dumps({"version": 1, "providers": ["claude", "gemini"], "default_provider": "claude"})
    )

    result = subprocess.run(
        [sys.executable, str(SCRIPT), "work", "use", "gemini"],
        capture_output=True,
        text=True,
        env={**__import__("os").environ, "HOME": str(tmp_path)},
    )
    assert result.returncode == 1
    assert "--config" in result.stderr
