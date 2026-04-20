"""Tests for multi-provider altergo accounts (schema v3).

Covers the behaviors introduced in the multi-provider feature:
  - v2 → v3 in-memory coercion without forced disk migration
  - --add-provider / --remove-provider / --default-provider
  - Path A reconciliation of orphan account-local data
  - launch_claude membership guard
  - _account_for_provider list membership
  - build_launcher_menu multi-render
"""

import importlib.util
import json
from pathlib import Path

import pytest

ROOT = Path(__file__).parent.parent
SCRIPT = ROOT / "altergo.py"


@pytest.fixture()
def mod(monkeypatch, tmp_path):
    """Fresh altergo module with MAIN_HOME + ACCOUNTS_DIR in a temp directory."""
    spec = importlib.util.spec_from_file_location("altergo_mp", SCRIPT)
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)

    main_home = tmp_path / "main"
    accounts_dir = tmp_path / "accounts"
    main_home.mkdir(parents=True)
    accounts_dir.mkdir(parents=True)
    (main_home / ".claude").mkdir()
    (main_home / ".codex").mkdir()
    (main_home / ".gemini").mkdir()

    monkeypatch.setattr(m, "MAIN_HOME", main_home)
    monkeypatch.setattr(m, "MAIN_CLAUDE", main_home / ".claude")
    monkeypatch.setattr(m, "ACCOUNTS_DIR", accounts_dir)
    monkeypatch.setattr(m, "SETTINGS_FILE", tmp_path / "settings.json")
    monkeypatch.setattr(m, "STARRED_FILE", tmp_path / "starred.json")
    monkeypatch.setattr(m, "LAST_SESSION_FILE", tmp_path / "last_session.json")
    return m


def _write_account(mod, name, on_disk):
    home = mod.ACCOUNTS_DIR / name
    home.mkdir(parents=True, exist_ok=True)
    (home / "account.json").write_text(json.dumps(on_disk))
    (home / ".claude").mkdir(exist_ok=True)
    return home


# ---------------------------------------------------------------------------
# Coercion (_coerce_meta_v3 + load_account_meta)
# ---------------------------------------------------------------------------


def test_load_account_meta_v2_presents_as_v3(mod, tmp_path):
    home = _write_account(mod, "work", {"version": 2, "provider": "gemini", "created": "2026-01-01"})
    meta = mod.load_account_meta(home)
    assert meta["version"] == 3
    assert meta["providers"] == ["gemini"]
    assert meta["default_provider"] == "gemini"
    assert meta["created"] == "2026-01-01"
    on_disk = json.loads((home / "account.json").read_text())
    assert on_disk["version"] == 2


def test_load_account_meta_v3_roundtrip(mod):
    home = _write_account(
        mod,
        "work",
        {
            "version": 3,
            "providers": ["claude", "codex"],
            "default_provider": "codex",
        },
    )
    meta = mod.load_account_meta(home)
    assert meta["version"] == 3
    assert meta["providers"] == ["claude", "codex"]
    assert meta["default_provider"] == "codex"


def test_load_account_meta_legacy_no_file_is_claude(mod):
    home = mod.ACCOUNTS_DIR / "legacy"
    (home / ".claude").mkdir(parents=True)
    meta = mod.load_account_meta(home)
    assert meta["version"] == 3
    assert meta["providers"] == ["claude"]
    assert meta["default_provider"] == "claude"


def test_load_account_meta_corrupt_json_safe_default(mod):
    home = mod.ACCOUNTS_DIR / "broken"
    home.mkdir()
    (home / "account.json").write_text("{not-json")
    meta = mod.load_account_meta(home)
    assert meta["version"] == 3
    assert meta["providers"] == ["claude"]


def test_load_account_meta_coerces_bad_default_provider(mod):
    home = _write_account(
        mod,
        "x",
        {
            "version": 3,
            "providers": ["claude", "codex"],
            "default_provider": "gemini",  # not in providers
        },
    )
    meta = mod.load_account_meta(home)
    assert meta["default_provider"] == "claude"


def test_load_account_meta_preserves_aux_fields(mod):
    home = _write_account(
        mod,
        "iso",
        {
            "version": 2,
            "provider": "claude",
            "keychain": "isolated",
            "created": "2026-01-01",
        },
    )
    meta = mod.load_account_meta(home)
    assert meta["keychain"] == "isolated"
    assert meta["created"] == "2026-01-01"


# ---------------------------------------------------------------------------
# --add-provider / --remove-provider / --default-provider
# ---------------------------------------------------------------------------


def test_add_provider_idempotent(mod, capsys):
    _write_account(
        mod,
        "work",
        {
            "version": 3,
            "providers": ["claude"],
            "default_provider": "claude",
        },
    )
    rc = mod.do_add_provider("work", "claude")
    assert rc == 0
    meta = mod.load_account_meta(mod.ACCOUNTS_DIR / "work")
    assert meta["providers"] == ["claude"]


def test_add_provider_flips_disk_to_v3(mod):
    # v2 on disk.
    home = _write_account(mod, "work", {"version": 2, "provider": "claude"})
    rc = mod.do_add_provider("work", "codex")
    assert rc == 0
    on_disk = json.loads((home / "account.json").read_text())
    assert on_disk["version"] == 3
    assert "codex" in on_disk["providers"]
    assert on_disk["default_provider"] == "claude"


def test_add_provider_reconciles_orphan_codex(mod):
    # Set up a v2-claude account with orphan codex session data.
    home = _write_account(mod, "hocus", {"version": 2, "provider": "claude"})
    orphan_session = home / ".codex" / "sessions" / "2026" / "04" / "20"
    orphan_session.mkdir(parents=True)
    orphan_file = orphan_session / "rollout-test.jsonl"
    orphan_file.write_text('{"type":"session_meta","payload":{"id":"abc","cwd":"/tmp"}}\n')

    rc = mod.do_add_provider("hocus", "codex")
    assert rc == 0
    # Orphan data moved to MAIN_HOME and local dot-dir became a symlink (or was
    # replaced by a symlinked sessions/).  Verify the data now lives under MAIN.
    main_codex = mod.MAIN_HOME / ".codex" / "sessions" / "2026" / "04" / "20" / "rollout-test.jsonl"
    assert main_codex.exists()
    assert main_codex.read_text().startswith('{"type":"session_meta"')


def test_remove_provider_rejects_last(mod, capsys):
    _write_account(
        mod,
        "single",
        {
            "version": 3,
            "providers": ["claude"],
            "default_provider": "claude",
        },
    )
    rc = mod.do_remove_provider("single", "claude", assume_yes=True)
    assert rc == 2
    err = capsys.readouterr().err
    assert "last provider" in err


def test_remove_provider_rebinds_default(mod):
    home = _write_account(
        mod,
        "work",
        {
            "version": 3,
            "providers": ["claude", "codex"],
            "default_provider": "codex",
        },
    )
    # Install symlinks for both so removal has something to remove.
    mod._apply_provider_setup(home, "claude", silent=True)
    mod._apply_provider_setup(home, "codex", silent=True)
    rc = mod.do_remove_provider("work", "codex", assume_yes=True)
    assert rc == 0
    meta = mod.load_account_meta(home)
    assert meta["providers"] == ["claude"]
    assert meta["default_provider"] == "claude"


def test_default_provider_flag_rejects_non_member(mod, capsys):
    _write_account(
        mod,
        "work",
        {
            "version": 3,
            "providers": ["claude"],
            "default_provider": "claude",
        },
    )
    rc = mod.do_default_provider("work", "codex")
    assert rc == 1
    err = capsys.readouterr().err
    assert "does not have provider" in err


def test_default_provider_flag_updates_default(mod):
    home = _write_account(
        mod,
        "work",
        {
            "version": 3,
            "providers": ["claude", "codex"],
            "default_provider": "claude",
        },
    )
    rc = mod.do_default_provider("work", "codex")
    assert rc == 0
    on_disk = json.loads((home / "account.json").read_text())
    assert on_disk["default_provider"] == "codex"


# ---------------------------------------------------------------------------
# launch_claude membership guard & _account_for_provider
# ---------------------------------------------------------------------------


def test_launch_rejects_unlisted_provider(mod, monkeypatch, capsys):
    _write_account(
        mod,
        "work",
        {
            "version": 3,
            "providers": ["claude"],
            "default_provider": "claude",
        },
    )
    # Keep launch_claude from actually running a subprocess.
    monkeypatch.setattr(mod, "_find_claude", lambda: "/usr/bin/claude")
    monkeypatch.setattr(mod, "show_banner", lambda *a, **k: None)
    monkeypatch.setattr(mod, "maybe_refresh_update_cache", lambda: None)
    monkeypatch.setattr(mod, "first_launch_notice_if_needed", lambda: None)
    monkeypatch.setattr(mod, "home_change_notice_if_needed", lambda: None)
    monkeypatch.setattr(mod, "_build_alt_env", lambda name: {})
    with pytest.raises(SystemExit) as exc_info:
        mod.launch_claude("work", provider="codex")
    message = str(exc_info.value)
    assert "does not have provider 'codex'" in message
    assert "--add-provider" in message


def test_account_for_provider_list_membership(mod):
    _write_account(
        mod,
        "multi",
        {
            "version": 3,
            "providers": ["claude", "codex"],
            "default_provider": "claude",
        },
    )
    _write_account(
        mod,
        "single_gemini",
        {
            "version": 3,
            "providers": ["gemini"],
            "default_provider": "gemini",
        },
    )
    assert mod._account_for_provider("codex") == "multi"
    assert mod._account_for_provider("gemini") == "single_gemini"
    assert mod._account_for_provider("copilot") is None


# ---------------------------------------------------------------------------
# build_launcher_menu multi-render
# ---------------------------------------------------------------------------


def test_launcher_menu_multi_provider_account_appears_twice(mod, monkeypatch):
    _write_account(
        mod,
        "work",
        {
            "version": 3,
            "providers": ["claude", "codex"],
            "default_provider": "claude",
        },
    )
    # Pretend all provider binaries are on PATH so the launcher decorates chips.
    monkeypatch.setattr(mod.shutil, "which", lambda name: f"/usr/bin/{name}")
    # Avoid the real session scan (spinner + disk walk).
    monkeypatch.setattr(mod, "_status_wrap", lambda msg, fn: fn())
    monkeypatch.setattr(mod, "get_sessions", lambda: [])

    menu = mod.build_launcher_menu()
    pid_to_chips = {row["provider_id"]: [c["name"] for c in row["accounts"]] for row in menu}
    assert "work" in pid_to_chips.get("claude", [])
    assert "work" in pid_to_chips.get("codex", [])


# ---------------------------------------------------------------------------
# Teardown loops over all providers
# ---------------------------------------------------------------------------


def test_teardown_removes_all_providers_symlinks(mod, monkeypatch):
    home = _write_account(
        mod,
        "multi",
        {
            "version": 3,
            "providers": ["claude", "codex"],
            "default_provider": "claude",
        },
    )
    mod._apply_provider_setup(home, "claude", silent=True)
    mod._apply_provider_setup(home, "codex", silent=True)
    # Precondition: at least one symlink in each dot-dir.
    assert any((home / ".claude").iterdir())
    assert any((home / ".codex").iterdir())

    monkeypatch.setattr(mod, "show_banner", lambda *a, **k: None)
    mod.do_teardown("multi")
    # After teardown, the per-provider symlinks are gone (dot-dirs may still
    # exist as empty dirs).
    claude_symlinks = [p for p in (home / ".claude").iterdir() if p.is_symlink()]
    codex_symlinks = [p for p in (home / ".codex").iterdir() if p.is_symlink()]
    assert claude_symlinks == []
    assert codex_symlinks == []
