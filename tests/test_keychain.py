"""Tests for the macOS keychain isolation subsystem in altergo.py.

Covers: SECURITY_CMD, _KC_SERVICE, _KC_GUID, _KC_SUBSERVICE_TYPE, KeychainError,
_sec, _keychain_path, _keychain_prefs_path, _write_keychain_prefs,
_create_account_keychain, _unlock_account_keychain, _delete_account_keychain,
_is_keychain_isolated, _build_alt_env (unlock path), do_config (keychain_arg),
do_delete_account (keychain teardown).

Patching boundary: _sec only. No real /usr/bin/security calls. Ever.
"""

from __future__ import annotations

import importlib.util
import io
import json
import plistlib
import subprocess
import sys
import types
from pathlib import Path

import pytest

ROOT = Path(__file__).parent.parent
SCRIPT = ROOT / "altergo.py"


# ---------------------------------------------------------------------------
# Module loader — matches pattern established in test_smoke.py / test_new_features.py
# ---------------------------------------------------------------------------


def _load_altergo():
    spec = importlib.util.spec_from_file_location("altergo", SCRIPT)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _cp(rc: int, stdout: str = "", stderr: str = "") -> subprocess.CompletedProcess:
    """Build a CompletedProcess without running anything."""
    return subprocess.CompletedProcess(args=[], returncode=rc, stdout=stdout, stderr=stderr)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture()
def mod():
    """Fresh altergo module per test."""
    return _load_altergo()


@pytest.fixture()
def tmp_account_home(tmp_path):
    """Minimal account home layout with Library/Keychains/ and Library/Preferences/ pre-created."""
    account_home = tmp_path / "accounts" / "work"
    (account_home / "Library" / "Keychains").mkdir(parents=True)
    (account_home / "Library" / "Preferences").mkdir(parents=True)
    return account_home


@pytest.fixture()
def mock_sec_success(monkeypatch, mod):
    """Patch mod._sec to return success for any subcommand.

    Returns a spy list of (argv, kwargs) tuples for every call.
    """
    calls = []

    def fake_sec(argv, *, check=True, timeout=10):
        calls.append((list(argv), {"check": check, "timeout": timeout}))
        subcommand = argv[0]
        if subcommand == "find-generic-password":
            return _cp(0, "deadbeef" * 8 + "\n")
        return _cp(0)

    monkeypatch.setattr(mod, "_sec", fake_sec)
    return calls


@pytest.fixture()
def mock_sec_locked(monkeypatch, mod):
    """_sec returns 'interaction is not allowed' for find-generic-password."""
    calls = []

    def fake_sec(argv, *, check=True, timeout=10):
        calls.append((list(argv), {"check": check, "timeout": timeout}))
        if argv[0] == "find-generic-password":
            return _cp(128, "", "The user interaction is not allowed.")
        return _cp(0)

    monkeypatch.setattr(mod, "_sec", fake_sec)
    return calls


@pytest.fixture()
def mock_sec_missing(monkeypatch, mod):
    """_sec returns 'could not be found' for find-generic-password."""
    calls = []

    def fake_sec(argv, *, check=True, timeout=10):
        calls.append((list(argv), {"check": check, "timeout": timeout}))
        if argv[0] == "find-generic-password":
            return _cp(44, "", "The specified item could not be found in the keychain.")
        return _cp(0)

    monkeypatch.setattr(mod, "_sec", fake_sec)
    return calls


@pytest.fixture()
def mock_sec_auth_failed(monkeypatch, mod):
    """find-generic-password succeeds (password returned) but unlock-keychain returns errSecAuthFailed."""
    calls = []

    def fake_sec(argv, *, check=True, timeout=10):
        calls.append((list(argv), {"check": check, "timeout": timeout}))
        if argv[0] == "find-generic-password":
            return _cp(0, "deadbeef" * 8 + "\n")
        if argv[0] == "unlock-keychain":
            # _sec with check=True raises on non-zero; simulate that path
            if check:
                raise mod.KeychainError(
                    "security unlock-keychain failed (exit 1): errSecAuthFailed"
                )
            return _cp(1, "", "errSecAuthFailed")
        return _cp(0)

    monkeypatch.setattr(mod, "_sec", fake_sec)
    return calls


@pytest.fixture()
def account_meta_isolated():
    # In-memory v3 shape — matches what load_account_meta returns after coercion.
    return {
        "version": 3,
        "providers": ["claude"],
        "default_provider": "claude",
        "keychain": "isolated",
    }


@pytest.fixture()
def account_meta_shared():
    return {
        "version": 3,
        "providers": ["claude"],
        "default_provider": "claude",
    }


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------


def test_security_cmd_constant(mod):
    assert mod.SECURITY_CMD == "/usr/bin/security"


def test_kc_service_constant(mod):
    assert mod._KC_SERVICE == "com.altergo.account-unlock"


def test_kc_guid_constant(mod):
    assert mod._KC_GUID == "{87191ca3-0fc9-11d4-849a-000502b52122}"


def test_kc_subservice_type_is_int_6(mod):
    assert mod._KC_SUBSERVICE_TYPE == 6
    assert isinstance(mod._KC_SUBSERVICE_TYPE, int)


# ---------------------------------------------------------------------------
# _sec — FileNotFoundError translation
# ---------------------------------------------------------------------------


def test_sec_file_not_found_raises_keychain_error(monkeypatch, mod):
    """_sec translates FileNotFoundError (missing binary) into KeychainError."""
    monkeypatch.setattr(mod, "SECURITY_CMD", "/nonexistent/security")
    with pytest.raises(mod.KeychainError) as exc_info:
        mod._sec(["list-keychains"])
    assert "not found" in str(exc_info.value).lower()


def test_sec_nonzero_with_check_true_raises(monkeypatch, mod):
    """_sec with check=True raises KeychainError on non-zero exit."""
    def fake_run(cmd, **kw):
        return _cp(1, "", "some error")

    monkeypatch.setattr(mod.subprocess, "run", fake_run)
    with pytest.raises(mod.KeychainError) as exc_info:
        mod._sec(["create-keychain", "-p", "x", "/fake/path"])
    assert "exit 1" in str(exc_info.value)


def test_sec_nonzero_with_check_false_returns_result(monkeypatch, mod):
    """_sec with check=False returns the CompletedProcess even on non-zero exit."""
    def fake_run(cmd, **kw):
        return _cp(44, "", "The specified item could not be found")

    monkeypatch.setattr(mod.subprocess, "run", fake_run)
    r = mod._sec(["find-generic-password", "-s", "svc", "-a", "acct", "-w"], check=False)
    assert r.returncode == 44


def test_sec_success_returns_completed_process(monkeypatch, mod):
    """_sec returns the CompletedProcess on zero exit with check=True."""
    def fake_run(cmd, **kw):
        return _cp(0, "some output")

    monkeypatch.setattr(mod.subprocess, "run", fake_run)
    r = mod._sec(["list-keychains"])
    assert r.returncode == 0
    assert r.stdout == "some output"


# ---------------------------------------------------------------------------
# Path helpers
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("slug,expected_suffix", [
    ("work", "Library/Keychains/login.keychain-db"),
    ("personal", "Library/Keychains/login.keychain-db"),
])
def test_keychain_path(mod, tmp_path, slug, expected_suffix):
    account_home = tmp_path / slug
    result = mod._keychain_path(account_home)
    assert result == account_home / expected_suffix


@pytest.mark.parametrize("slug", ["work", "client-a"])
def test_keychain_prefs_path(mod, tmp_path, slug):
    account_home = tmp_path / slug
    result = mod._keychain_prefs_path(account_home)
    assert result == account_home / "Library" / "Preferences" / "com.apple.security.plist"


# ---------------------------------------------------------------------------
# Gating test 1: Plist shape written by _write_keychain_prefs
# ---------------------------------------------------------------------------


def test_write_keychain_prefs_creates_plist_with_correct_shape(mod, tmp_account_home):
    """_write_keychain_prefs writes a plist whose DLDBSearchList[0] matches the
    exact shape the Security framework expects: no '-db' suffix, correct GUID, SubserviceType==6."""
    mod._write_keychain_prefs(tmp_account_home)

    prefs_path = tmp_account_home / "Library" / "Preferences" / "com.apple.security.plist"
    assert prefs_path.exists(), "plist file must exist"

    with open(prefs_path, "rb") as f:
        data = plistlib.load(f)

    assert "DLDBSearchList" in data
    entry = data["DLDBSearchList"][0]
    # NO -db suffix — engineer verified this against real Mac plist.
    assert entry["DbName"] == "~/Library/Keychains/login.keychain"
    assert entry["GUID"] == mod._KC_GUID
    assert entry["SubserviceType"] == 6
    assert isinstance(entry["SubserviceType"], int)


def test_write_keychain_prefs_creates_parent_dirs(mod, tmp_path):
    """_write_keychain_prefs creates Library/Preferences/ when they don't exist."""
    account_home = tmp_path / "freshaccount"
    account_home.mkdir()
    # No Library/Preferences — should be auto-created.
    mod._write_keychain_prefs(account_home)
    prefs_path = account_home / "Library" / "Preferences" / "com.apple.security.plist"
    assert prefs_path.exists()


# ---------------------------------------------------------------------------
# _create_account_keychain
# ---------------------------------------------------------------------------


def test_create_account_keychain_calls_correct_subcommands(mod, tmp_account_home, mock_sec_success):
    """_create_account_keychain calls create-keychain, set-keychain-settings,
    delete-generic-password, add-generic-password in that order."""
    mod._create_account_keychain(tmp_account_home, "work")

    subcommands = [args[0] for args, _ in mock_sec_success]
    assert subcommands[0] == "create-keychain"
    assert subcommands[1] == "set-keychain-settings"
    assert subcommands[2] == "delete-generic-password"
    assert subcommands[3] == "add-generic-password"


def test_create_account_keychain_writes_plist(mod, tmp_account_home, mock_sec_success):
    """_create_account_keychain also writes the prefs plist."""
    mod._create_account_keychain(tmp_account_home, "work")
    prefs_path = tmp_account_home / "Library" / "Preferences" / "com.apple.security.plist"
    assert prefs_path.exists()


def test_create_account_keychain_add_password_uses_service_and_slug(mod, tmp_account_home, mock_sec_success):
    """add-generic-password is called with -s _KC_SERVICE and -a <slug>."""
    mod._create_account_keychain(tmp_account_home, "work")
    add_call = next(
        (args for args, _ in mock_sec_success if args[0] == "add-generic-password"), None
    )
    assert add_call is not None
    assert "-s" in add_call
    assert add_call[add_call.index("-s") + 1] == mod._KC_SERVICE
    assert "-a" in add_call
    assert add_call[add_call.index("-a") + 1] == "work"


def test_create_account_keychain_password_is_64_hex_chars(monkeypatch, mod, tmp_account_home):
    """The password stored in the keychain is a 64-char hex string (256-bit entropy)."""
    import secrets as _secrets

    known_bytes = bytes(range(32))
    monkeypatch.setattr(_secrets, "token_bytes", lambda n: known_bytes[:n])
    monkeypatch.setattr(mod.secrets, "token_bytes", lambda n: known_bytes[:n])

    captured_passwords = []

    def fake_sec(argv, *, check=True, timeout=10):
        if argv[0] == "add-generic-password" and "-w" in argv:
            captured_passwords.append(argv[argv.index("-w") + 1])
        return _cp(0)

    monkeypatch.setattr(mod, "_sec", fake_sec)
    mod._create_account_keychain(tmp_account_home, "work")

    assert len(captured_passwords) == 1
    pw = captured_passwords[0]
    assert len(pw) == 64
    assert all(c in "0123456789abcdef" for c in pw)


def test_create_account_keychain_idempotent_skips_when_file_exists(mod, tmp_account_home, mock_sec_success):
    """When keychain file already exists, _create_account_keychain skips create-keychain
    and does not call it a second time."""
    kc_path = mod._keychain_path(tmp_account_home)
    kc_path.touch()  # Simulate pre-existing keychain.

    mock_sec_success.clear()
    mod._create_account_keychain(tmp_account_home, "work")

    subcommands = [args[0] for args, _ in mock_sec_success]
    assert "create-keychain" not in subcommands


def test_create_account_keychain_idempotent_still_writes_plist(mod, tmp_account_home, mock_sec_success):
    """Even when keychain file already exists, plist is (re-)written."""
    kc_path = mod._keychain_path(tmp_account_home)
    kc_path.touch()

    # Remove plist to confirm it is re-created.
    prefs_path = tmp_account_home / "Library" / "Preferences" / "com.apple.security.plist"
    if prefs_path.exists():
        prefs_path.unlink()

    mod._create_account_keychain(tmp_account_home, "work")
    assert prefs_path.exists()


def test_create_account_keychain_delete_generic_uses_check_false(mod, tmp_account_home, mock_sec_success):
    """The pre-flight delete-generic-password is called with check=False (idempotent)."""
    mod._create_account_keychain(tmp_account_home, "work")
    del_call = next(
        ((args, kw) for args, kw in mock_sec_success if args[0] == "delete-generic-password"),
        None,
    )
    assert del_call is not None
    _, kw = del_call
    assert kw["check"] is False


# ---------------------------------------------------------------------------
# Gating test 2: Error translation in _unlock_account_keychain
# ---------------------------------------------------------------------------


def test_unlock_locked_keychain_raises_login_keychain_locked(mod, tmp_account_home, mock_sec_locked):
    """stderr 'interaction is not allowed' → KeychainError mentioning 'login keychain is locked'."""
    with pytest.raises(mod.KeychainError) as exc_info:
        mod._unlock_account_keychain(tmp_account_home, "work")
    assert "login keychain is locked" in str(exc_info.value)


def test_unlock_missing_entry_raises_no_unlock_entry(mod, tmp_account_home, mock_sec_missing):
    """stderr 'could not be found' → KeychainError mentioning 'no unlock entry'."""
    with pytest.raises(mod.KeychainError) as exc_info:
        mod._unlock_account_keychain(tmp_account_home, "work")
    assert "no unlock entry" in str(exc_info.value)


def test_unlock_other_failure_raises_generic_keychain_error(monkeypatch, mod, tmp_account_home):
    """Any other non-zero from find-generic-password → KeychainError with the stderr in the message."""
    def fake_sec(argv, *, check=True, timeout=10):
        if argv[0] == "find-generic-password":
            return _cp(1, "", "some unexpected error")
        return _cp(0)

    monkeypatch.setattr(mod, "_sec", fake_sec)
    with pytest.raises(mod.KeychainError) as exc_info:
        mod._unlock_account_keychain(tmp_account_home, "work")
    assert "some unexpected error" in str(exc_info.value)


def test_unlock_auth_failed_raises_with_config_hint(mod, tmp_account_home, mock_sec_auth_failed):
    """unlock-keychain errSecAuthFailed → KeychainError containing the 'altergo --config' hint phrase."""
    with pytest.raises(mod.KeychainError) as exc_info:
        mod._unlock_account_keychain(tmp_account_home, "work")
    msg = str(exc_info.value)
    assert "altergo --config" in msg


def test_unlock_success_calls_unlock_keychain_subcommand(mod, tmp_account_home, mock_sec_success):
    """On successful find-generic-password, unlock-keychain is called."""
    mod._unlock_account_keychain(tmp_account_home, "work")
    subcommands = [args[0] for args, _ in mock_sec_success]
    assert "find-generic-password" in subcommands
    assert "unlock-keychain" in subcommands


def test_unlock_password_trailing_newline_stripped(monkeypatch, mod, tmp_account_home):
    """Password returned by find-generic-password has trailing newline stripped before
    being forwarded to unlock-keychain."""
    received_passwords = []

    def fake_sec(argv, *, check=True, timeout=10):
        if argv[0] == "find-generic-password":
            return _cp(0, "abc123\n")
        if argv[0] == "unlock-keychain":
            if "-p" in argv:
                received_passwords.append(argv[argv.index("-p") + 1])
        return _cp(0)

    monkeypatch.setattr(mod, "_sec", fake_sec)
    mod._unlock_account_keychain(tmp_account_home, "work")

    assert received_passwords == ["abc123"]


def test_unlock_empty_password_still_calls_unlock(monkeypatch, mod, tmp_account_home):
    """find-generic-password returning empty string → unlock-keychain still called with empty string."""
    unlock_calls = []

    def fake_sec(argv, *, check=True, timeout=10):
        if argv[0] == "find-generic-password":
            return _cp(0, "")
        if argv[0] == "unlock-keychain":
            unlock_calls.append(argv)
        return _cp(0)

    monkeypatch.setattr(mod, "_sec", fake_sec)
    mod._unlock_account_keychain(tmp_account_home, "work")

    assert len(unlock_calls) == 1
    assert "-p" in unlock_calls[0]
    pw_idx = unlock_calls[0].index("-p")
    assert unlock_calls[0][pw_idx + 1] == ""


# ---------------------------------------------------------------------------
# _delete_account_keychain
# ---------------------------------------------------------------------------


def test_delete_account_keychain_calls_both_delete_subcommands(mod, tmp_account_home, mock_sec_success):
    """_delete_account_keychain calls delete-keychain and delete-generic-password."""
    mod._delete_account_keychain(tmp_account_home, "work")
    subcommands = [args[0] for args, _ in mock_sec_success]
    assert "delete-keychain" in subcommands
    assert "delete-generic-password" in subcommands


def test_delete_account_keychain_both_calls_use_check_false(mod, tmp_account_home, mock_sec_success):
    """Both delete calls use check=False so missing entries don't raise."""
    mod._delete_account_keychain(tmp_account_home, "work")
    for args, kw in mock_sec_success:
        if args[0] in ("delete-keychain", "delete-generic-password"):
            assert kw["check"] is False, f"{args[0]} must use check=False"


def test_delete_account_keychain_idempotent_when_both_fail(monkeypatch, mod, tmp_account_home):
    """_delete_account_keychain does not raise even when both _sec calls return non-zero."""
    def fake_sec(argv, *, check=True, timeout=10):
        if argv[0] == "delete-keychain":
            return _cp(1, "", "... could not be found ...")
        if argv[0] == "delete-generic-password":
            return _cp(44, "", "The specified item could not be found")
        return _cp(0)

    monkeypatch.setattr(mod, "_sec", fake_sec)
    # Must not raise.
    mod._delete_account_keychain(tmp_account_home, "work")


# ---------------------------------------------------------------------------
# _is_keychain_isolated — truth table
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("meta,expected", [
    (None, False),
    ({}, False),
    ({"version": 2, "provider": "claude"}, False),
    ({"version": 2, "provider": "claude", "keychain": "shared"}, False),
    ({"version": 2, "provider": "claude", "keychain": "isolated"}, True),
    ({"keychain": "ISOLATED"}, False),   # case-sensitive
    ({"keychain": "Isolated"}, False),   # mixed case not accepted
])
def test_is_keychain_isolated_truth_table(mod, meta, expected):
    assert mod._is_keychain_isolated(meta) is expected


# ---------------------------------------------------------------------------
# Gating test 3: _build_alt_env exits 1 on KeychainError
# ---------------------------------------------------------------------------


def test_build_alt_env_exits_1_on_keychain_error(monkeypatch, mod, tmp_path, account_meta_isolated):
    """When _unlock_account_keychain raises KeychainError, _build_alt_env calls sys.exit(1)."""
    accounts_dir = tmp_path / "accounts"
    (accounts_dir / "work").mkdir(parents=True)
    monkeypatch.setattr(mod, "ACCOUNTS_DIR", accounts_dir)
    monkeypatch.setattr(mod.sys, "platform", "darwin")

    monkeypatch.setattr(mod, "load_account_meta", lambda path: account_meta_isolated)
    monkeypatch.setattr(mod, "_unlock_account_keychain", lambda home, slug: (_ for _ in ()).throw(mod.KeychainError("test")))

    stderr_buf = io.StringIO()
    monkeypatch.setattr(mod.sys, "stderr", stderr_buf)

    with pytest.raises(SystemExit) as exc_info:
        mod._build_alt_env("work")

    assert exc_info.value.code == 1


def test_build_alt_env_propagates_keychain_error_message(monkeypatch, mod, tmp_path, account_meta_isolated):
    """The KeychainError message appears in stderr before sys.exit(1)."""
    accounts_dir = tmp_path / "accounts"
    (accounts_dir / "work").mkdir(parents=True)
    monkeypatch.setattr(mod, "ACCOUNTS_DIR", accounts_dir)
    monkeypatch.setattr(mod.sys, "platform", "darwin")

    monkeypatch.setattr(mod, "load_account_meta", lambda path: account_meta_isolated)
    monkeypatch.setattr(
        mod,
        "_unlock_account_keychain",
        lambda home, slug: (_ for _ in ()).throw(mod.KeychainError("login keychain is locked")),
    )

    stderr_buf = io.StringIO()
    monkeypatch.setattr(mod.sys, "stderr", stderr_buf)

    with pytest.raises(SystemExit):
        mod._build_alt_env("work")

    assert "login keychain is locked" in stderr_buf.getvalue()


# ---------------------------------------------------------------------------
# Gating test 6: Shared/missing meta never calls _sec in _build_alt_env
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("meta", [
    {},
    {"version": 2, "provider": "claude"},
    {"version": 2, "provider": "claude", "keychain": "shared"},
])
def test_build_alt_env_shared_meta_never_calls_sec(monkeypatch, mod, tmp_path, meta):
    """_build_alt_env must not call _sec when keychain is not isolated."""
    accounts_dir = tmp_path / "accounts"
    (accounts_dir / "work").mkdir(parents=True)
    monkeypatch.setattr(mod, "ACCOUNTS_DIR", accounts_dir)
    monkeypatch.setattr(mod.sys, "platform", "darwin")
    monkeypatch.setattr(mod, "load_account_meta", lambda path: meta)

    sec_calls = []

    def spy_sec(argv, **kw):
        sec_calls.append(argv)
        return _cp(0)

    monkeypatch.setattr(mod, "_sec", spy_sec)

    mod._build_alt_env("work")

    assert sec_calls == [], f"Expected zero _sec calls for meta={meta!r}, got {sec_calls}"


# ---------------------------------------------------------------------------
# Gating test 7: Native account never calls _sec
# ---------------------------------------------------------------------------


def test_build_alt_env_native_never_calls_sec(monkeypatch, mod):
    """_build_alt_env('native') returns immediately without calling _sec."""
    sec_calls = []

    def spy_sec(argv, **kw):
        sec_calls.append(argv)
        return _cp(0)

    monkeypatch.setattr(mod, "_sec", spy_sec)
    monkeypatch.setattr(mod.sys, "platform", "darwin")

    mod._build_alt_env("native")

    assert sec_calls == []


# ---------------------------------------------------------------------------
# Gating test 4: do_config non-TTY isolated (Invariant 9)
# ---------------------------------------------------------------------------


def _create_main_claude_sources_for_mod(mod, main_claude: Path):
    """Create the source dirs/files in MAIN_CLAUDE that do_config() will symlink."""
    for name in mod.SYMLINK_DIRS:
        (main_claude / name).mkdir(parents=True, exist_ok=True)
    for name in mod.SYMLINK_FILES:
        (main_claude / name).touch()


def test_do_config_non_tty_isolated_writes_meta_and_plist(monkeypatch, mod, tmp_path):
    """do_config with keychain_arg='isolated' on non-TTY writes meta with keychain=isolated
    and creates the plist file."""
    main_home = tmp_path / "main_home"
    main_claude = main_home / ".claude"
    accounts_dir = tmp_path / "accounts"

    main_home.mkdir(parents=True)
    main_claude.mkdir(parents=True)
    accounts_dir.mkdir(parents=True)
    _create_main_claude_sources_for_mod(mod, main_claude)

    monkeypatch.setattr(mod, "MAIN_HOME", main_home)
    monkeypatch.setattr(mod, "MAIN_CLAUDE", main_claude)
    monkeypatch.setattr(mod, "ACCOUNTS_DIR", accounts_dir)
    monkeypatch.setattr(mod, "SETTINGS_FILE", tmp_path / "settings.json")
    monkeypatch.setattr(mod.sys, "platform", "darwin")
    monkeypatch.setattr(mod.sys.stdin, "isatty", lambda: False)

    # _sec always succeeds.
    monkeypatch.setattr(mod, "_sec", lambda argv, **kw: _cp(0))

    monkeypatch.setattr(mod, "show_banner", lambda *a, **kw: None)
    monkeypatch.setattr(mod, "_status_wrap", lambda msg, fn: fn())
    monkeypatch.setattr(mod, "load_settings", lambda: {})

    mod.do_config("work", keychain_arg="isolated")

    account_home = accounts_dir / "work"
    meta_path = account_home / "account.json"
    assert meta_path.exists(), "account.json must exist"
    meta = json.loads(meta_path.read_text())
    assert meta.get("keychain") == "isolated", f"Expected keychain=isolated, got {meta}"

    plist_path = account_home / "Library" / "Preferences" / "com.apple.security.plist"
    assert plist_path.exists(), "plist must exist for isolated account"


def test_do_config_non_tty_isolated_sec_is_called(monkeypatch, mod, tmp_path):
    """do_config with keychain_arg='isolated' on non-TTY calls _sec (creates the keychain)."""
    main_home = tmp_path / "main_home"
    main_claude = main_home / ".claude"
    accounts_dir = tmp_path / "accounts"

    main_home.mkdir(parents=True)
    main_claude.mkdir(parents=True)
    accounts_dir.mkdir(parents=True)
    _create_main_claude_sources_for_mod(mod, main_claude)

    monkeypatch.setattr(mod, "MAIN_HOME", main_home)
    monkeypatch.setattr(mod, "MAIN_CLAUDE", main_claude)
    monkeypatch.setattr(mod, "ACCOUNTS_DIR", accounts_dir)
    monkeypatch.setattr(mod, "SETTINGS_FILE", tmp_path / "settings.json")
    monkeypatch.setattr(mod.sys, "platform", "darwin")
    monkeypatch.setattr(mod.sys.stdin, "isatty", lambda: False)

    sec_calls = []
    monkeypatch.setattr(mod, "_sec", lambda argv, **kw: (sec_calls.append(argv), _cp(0))[-1])

    monkeypatch.setattr(mod, "show_banner", lambda *a, **kw: None)
    monkeypatch.setattr(mod, "_status_wrap", lambda msg, fn: fn())
    monkeypatch.setattr(mod, "load_settings", lambda: {})

    mod.do_config("work", keychain_arg="isolated")

    assert len(sec_calls) > 0, "_sec must be called when keychain_arg='isolated'"


# ---------------------------------------------------------------------------
# Gating test 5: do_config non-TTY no flag (Invariant 10)
# ---------------------------------------------------------------------------


def test_do_config_non_tty_no_flag_no_plist_no_sec(monkeypatch, mod, tmp_path):
    """do_config with keychain_arg=None on non-TTY does not create plist and does not call _sec."""
    main_home = tmp_path / "main_home"
    main_claude = main_home / ".claude"
    accounts_dir = tmp_path / "accounts"

    main_home.mkdir(parents=True)
    main_claude.mkdir(parents=True)
    accounts_dir.mkdir(parents=True)
    _create_main_claude_sources_for_mod(mod, main_claude)

    monkeypatch.setattr(mod, "MAIN_HOME", main_home)
    monkeypatch.setattr(mod, "MAIN_CLAUDE", main_claude)
    monkeypatch.setattr(mod, "ACCOUNTS_DIR", accounts_dir)
    monkeypatch.setattr(mod, "SETTINGS_FILE", tmp_path / "settings.json")
    monkeypatch.setattr(mod.sys, "platform", "darwin")
    monkeypatch.setattr(mod.sys.stdin, "isatty", lambda: False)

    sec_calls = []
    monkeypatch.setattr(mod, "_sec", lambda argv, **kw: (sec_calls.append(argv), _cp(0))[-1])

    monkeypatch.setattr(mod, "show_banner", lambda *a, **kw: None)
    monkeypatch.setattr(mod, "_status_wrap", lambda msg, fn: fn())
    monkeypatch.setattr(mod, "load_settings", lambda: {})

    mod.do_config("work", keychain_arg=None)

    account_home = accounts_dir / "work"
    meta_path = account_home / "account.json"
    assert meta_path.exists()
    meta = json.loads(meta_path.read_text())
    assert "keychain" not in meta, f"meta must not have 'keychain' key, got {meta}"

    plist_path = account_home / "Library" / "Preferences" / "com.apple.security.plist"
    assert not plist_path.exists(), "plist must NOT exist for non-isolated account"

    assert sec_calls == [], f"_sec must not be called, got {sec_calls}"


def test_do_config_non_tty_no_flag_does_not_hang(monkeypatch, mod, tmp_path):
    """do_config with keychain_arg=None on non-TTY returns without blocking on input()."""
    import builtins

    main_home = tmp_path / "main_home"
    main_claude = main_home / ".claude"
    accounts_dir = tmp_path / "accounts"

    main_home.mkdir(parents=True)
    main_claude.mkdir(parents=True)
    accounts_dir.mkdir(parents=True)
    _create_main_claude_sources_for_mod(mod, main_claude)

    monkeypatch.setattr(mod, "MAIN_HOME", main_home)
    monkeypatch.setattr(mod, "MAIN_CLAUDE", main_claude)
    monkeypatch.setattr(mod, "ACCOUNTS_DIR", accounts_dir)
    monkeypatch.setattr(mod, "SETTINGS_FILE", tmp_path / "settings.json")
    monkeypatch.setattr(mod.sys, "platform", "darwin")
    monkeypatch.setattr(mod.sys.stdin, "isatty", lambda: False)

    # If input() is called, this raises to fail the test immediately.
    def boom(*a, **kw):
        raise AssertionError("input() must not be called on non-TTY")

    monkeypatch.setattr(builtins, "input", boom)
    monkeypatch.setattr(mod, "_sec", lambda argv, **kw: _cp(0))
    monkeypatch.setattr(mod, "show_banner", lambda *a, **kw: None)
    monkeypatch.setattr(mod, "_status_wrap", lambda msg, fn: fn())
    monkeypatch.setattr(mod, "load_settings", lambda: {})

    # Should complete without raising.
    mod.do_config("work", keychain_arg=None)


# ---------------------------------------------------------------------------
# Gating test 8: sys.platform != "darwin" gate
# ---------------------------------------------------------------------------


def test_do_config_non_darwin_no_sec_no_plist(monkeypatch, mod, tmp_path):
    """On non-darwin platforms, do_config with keychain_arg='isolated' does not
    call _sec and does not create Library/Keychains/. Documents current behavior."""
    main_home = tmp_path / "main_home"
    main_claude = main_home / ".claude"
    accounts_dir = tmp_path / "accounts"

    main_home.mkdir(parents=True)
    main_claude.mkdir(parents=True)
    accounts_dir.mkdir(parents=True)
    _create_main_claude_sources_for_mod(mod, main_claude)

    monkeypatch.setattr(mod, "MAIN_HOME", main_home)
    monkeypatch.setattr(mod, "MAIN_CLAUDE", main_claude)
    monkeypatch.setattr(mod, "ACCOUNTS_DIR", accounts_dir)
    monkeypatch.setattr(mod, "SETTINGS_FILE", tmp_path / "settings.json")
    monkeypatch.setattr(mod.sys, "platform", "linux")
    monkeypatch.setattr(mod.sys.stdin, "isatty", lambda: False)

    sec_calls = []
    monkeypatch.setattr(mod, "_sec", lambda argv, **kw: (sec_calls.append(argv), _cp(0))[-1])

    monkeypatch.setattr(mod, "show_banner", lambda *a, **kw: None)
    monkeypatch.setattr(mod, "_status_wrap", lambda msg, fn: fn())
    monkeypatch.setattr(mod, "load_settings", lambda: {})

    mod.do_config("work", keychain_arg="isolated")

    account_home = accounts_dir / "work"
    keychains_dir = account_home / "Library" / "Keychains"

    assert sec_calls == [], f"_sec must not be called on linux, got {sec_calls}"
    assert not keychains_dir.exists(), "Library/Keychains/ must not be created on linux"


def test_build_alt_env_non_darwin_never_calls_sec(monkeypatch, mod, tmp_path, account_meta_isolated):
    """_build_alt_env on non-darwin never calls _sec even for isolated meta."""
    accounts_dir = tmp_path / "accounts"
    (accounts_dir / "work").mkdir(parents=True)
    monkeypatch.setattr(mod, "ACCOUNTS_DIR", accounts_dir)
    monkeypatch.setattr(mod.sys, "platform", "linux")
    monkeypatch.setattr(mod, "load_account_meta", lambda path: account_meta_isolated)

    sec_calls = []
    monkeypatch.setattr(mod, "_sec", lambda argv, **kw: (sec_calls.append(argv), _cp(0))[-1])

    mod._build_alt_env("work")

    assert sec_calls == []


# ---------------------------------------------------------------------------
# Re-config preserves isolation when meta already has keychain=isolated
# ---------------------------------------------------------------------------


def test_do_config_reconfig_preserves_isolation(monkeypatch, mod, tmp_path):
    """Re-running do_config on an account that already has keychain=isolated keeps isolation
    when keychain_arg is None (the code reads existing meta and preserves it)."""
    main_home = tmp_path / "main_home"
    main_claude = main_home / ".claude"
    accounts_dir = tmp_path / "accounts"
    account_home = accounts_dir / "work"

    main_home.mkdir(parents=True)
    main_claude.mkdir(parents=True)
    accounts_dir.mkdir(parents=True)
    account_home.mkdir(parents=True)
    _create_main_claude_sources_for_mod(mod, main_claude)

    # Pre-existing isolated metadata.
    (account_home / "account.json").write_text(
        json.dumps({"version": 2, "provider": "claude", "keychain": "isolated"})
    )

    monkeypatch.setattr(mod, "MAIN_HOME", main_home)
    monkeypatch.setattr(mod, "MAIN_CLAUDE", main_claude)
    monkeypatch.setattr(mod, "ACCOUNTS_DIR", accounts_dir)
    monkeypatch.setattr(mod, "SETTINGS_FILE", tmp_path / "settings.json")
    monkeypatch.setattr(mod.sys, "platform", "darwin")
    monkeypatch.setattr(mod.sys.stdin, "isatty", lambda: False)
    monkeypatch.setattr(mod, "_sec", lambda argv, **kw: _cp(0))
    monkeypatch.setattr(mod, "show_banner", lambda *a, **kw: None)
    monkeypatch.setattr(mod, "_status_wrap", lambda msg, fn: fn())
    monkeypatch.setattr(mod, "load_settings", lambda: {})

    mod.do_config("work", keychain_arg=None)

    meta = json.loads((account_home / "account.json").read_text())
    assert meta.get("keychain") == "isolated"


# ---------------------------------------------------------------------------
# do_delete_account — keychain teardown integration
# ---------------------------------------------------------------------------


def _setup_delete_account_env(monkeypatch, mod, tmp_path, meta):
    """Common setup for do_delete_account tests."""
    main_home = tmp_path / "main_home"
    main_claude = main_home / ".claude"
    accounts_dir = tmp_path / "accounts"
    account_home = accounts_dir / "work"

    main_home.mkdir(parents=True)
    main_claude.mkdir(parents=True)
    (account_home / "Library" / "Keychains").mkdir(parents=True)
    (account_home / "Library" / "Preferences").mkdir(parents=True)
    (account_home / "account.json").write_text(json.dumps(meta))

    monkeypatch.setattr(mod, "MAIN_HOME", main_home)
    monkeypatch.setattr(mod, "MAIN_CLAUDE", main_claude)
    monkeypatch.setattr(mod, "ACCOUNTS_DIR", accounts_dir)
    monkeypatch.setattr(mod, "SETTINGS_FILE", tmp_path / "settings.json")
    monkeypatch.setattr(mod.sys, "platform", "darwin")
    monkeypatch.setattr(mod, "show_banner", lambda *a, **kw: None)

    return account_home


def test_do_delete_account_calls_delete_keychain_for_isolated(monkeypatch, mod, tmp_path, account_meta_isolated):
    """do_delete_account calls _delete_account_keychain for isolated accounts."""
    account_home = _setup_delete_account_env(monkeypatch, mod, tmp_path, account_meta_isolated)

    delete_calls = []
    monkeypatch.setattr(
        mod, "_delete_account_keychain",
        lambda home, slug: delete_calls.append((home, slug))
    )

    mod.do_delete_account("work")

    assert len(delete_calls) == 1
    assert delete_calls[0][1] == "work"


def test_do_delete_account_no_keychain_for_shared(monkeypatch, mod, tmp_path, account_meta_shared):
    """do_delete_account does NOT call _delete_account_keychain for shared accounts."""
    account_home = _setup_delete_account_env(monkeypatch, mod, tmp_path, account_meta_shared)

    delete_calls = []
    monkeypatch.setattr(
        mod, "_delete_account_keychain",
        lambda home, slug: delete_calls.append((home, slug))
    )

    mod.do_delete_account("work")

    assert delete_calls == []


def test_do_delete_account_continues_on_keychain_error(monkeypatch, mod, tmp_path, account_meta_isolated):
    """do_delete_account does not abort when _delete_account_keychain raises KeychainError."""
    account_home = _setup_delete_account_env(monkeypatch, mod, tmp_path, account_meta_isolated)

    def failing_delete(home, slug):
        raise mod.KeychainError("simulated keychain teardown failure")

    monkeypatch.setattr(mod, "_delete_account_keychain", failing_delete)

    # Should not raise; should return True (account home is removed).
    result = mod.do_delete_account("work")
    assert result is True
    assert not account_home.exists(), "account_home must be removed even after keychain error"


def test_do_delete_account_sec_calls_use_check_false(monkeypatch, mod, tmp_path, account_meta_isolated):
    """_delete_account_keychain's internal _sec calls use check=False (tested via real implementation)."""
    account_home = _setup_delete_account_env(monkeypatch, mod, tmp_path, account_meta_isolated)

    sec_calls = []

    def spy_sec(argv, *, check=True, timeout=10):
        sec_calls.append((list(argv), check))
        return _cp(0)

    monkeypatch.setattr(mod, "_sec", spy_sec)

    mod.do_delete_account("work")

    # Every _sec call made during delete must use check=False.
    delete_sec_calls = [(args, chk) for args, chk in sec_calls
                        if args[0] in ("delete-keychain", "delete-generic-password")]
    assert len(delete_sec_calls) > 0
    for args, chk in delete_sec_calls:
        assert chk is False, f"{args[0]} must use check=False"


# ---------------------------------------------------------------------------
# Fix D — End-to-end: do_config → _build_alt_env (seam test)
# ---------------------------------------------------------------------------


def _setup_do_config_env(monkeypatch, mod, tmp_path):
    """Shared environment wiring for do_config integration tests."""
    main_home = tmp_path / "main_home"
    main_claude = main_home / ".claude"
    accounts_dir = tmp_path / "accounts"

    main_home.mkdir(parents=True)
    main_claude.mkdir(parents=True)
    accounts_dir.mkdir(parents=True)
    _create_main_claude_sources_for_mod(mod, main_claude)

    monkeypatch.setattr(mod, "MAIN_HOME", main_home)
    monkeypatch.setattr(mod, "MAIN_CLAUDE", main_claude)
    monkeypatch.setattr(mod, "ACCOUNTS_DIR", accounts_dir)
    monkeypatch.setattr(mod, "SETTINGS_FILE", tmp_path / "settings.json")
    monkeypatch.setattr(mod.sys, "platform", "darwin")
    monkeypatch.setattr(mod.sys.stdin, "isatty", lambda: False)
    monkeypatch.setattr(mod, "show_banner", lambda *a, **kw: None)
    monkeypatch.setattr(mod, "_status_wrap", lambda msg, fn: fn())
    monkeypatch.setattr(mod, "load_settings", lambda: {})

    return accounts_dir


def test_do_config_then_build_alt_env_calls_find_generic_password(monkeypatch, mod, tmp_path):
    """do_config('work', keychain_arg='isolated') followed by _build_alt_env('work') must
    result in _sec being called with find-generic-password during the _build_alt_env phase.
    Catches seam bugs where do_config writes a meta key that _build_alt_env doesn't read."""
    accounts_dir = _setup_do_config_env(monkeypatch, mod, tmp_path)

    # Phase 1: do_config — spy on _sec, always succeed.
    config_sec_calls = []

    def fake_sec_config(argv, *, check=True, timeout=10):
        config_sec_calls.append(list(argv))
        if argv[0] == "find-generic-password":
            return _cp(0, "deadbeef" * 8 + "\n")
        return _cp(0)

    monkeypatch.setattr(mod, "_sec", fake_sec_config)
    mod.do_config("work", keychain_arg="isolated")

    # Phase 2: _build_alt_env — replace spy to capture only calls from this phase.
    build_sec_calls = []

    def fake_sec_build(argv, *, check=True, timeout=10):
        build_sec_calls.append(list(argv))
        if argv[0] == "find-generic-password":
            return _cp(0, "deadbeef" * 8 + "\n")
        return _cp(0)

    monkeypatch.setattr(mod, "_sec", fake_sec_build)
    mod._build_alt_env("work")

    find_calls = [args for args in build_sec_calls if args[0] == "find-generic-password"]
    assert len(find_calls) >= 1, (
        "_build_alt_env must call find-generic-password to unlock the isolated keychain; "
        f"_sec calls were: {build_sec_calls}"
    )


# ---------------------------------------------------------------------------
# Fix E — Regression: existing shared account re-config leaves meta unchanged
# ---------------------------------------------------------------------------


def test_do_config_existing_shared_account_no_sec_no_keychain_key(monkeypatch, mod, tmp_path):
    """Given an account.json with no 'keychain' key (existing shared account),
    calling do_config(..., keychain_arg=None) on non-TTY must not call _sec at all
    and must save meta still without a 'keychain' key."""
    accounts_dir = _setup_do_config_env(monkeypatch, mod, tmp_path)
    account_home = accounts_dir / "work"
    account_home.mkdir(parents=True)

    # Pre-existing shared account — no 'keychain' key.
    existing_meta = {"version": 2, "provider": "claude", "created": "2025-01-01T00:00:00"}
    (account_home / "account.json").write_text(json.dumps(existing_meta))

    sec_calls = []
    monkeypatch.setattr(mod, "_sec", lambda argv, **kw: (sec_calls.append(list(argv)), _cp(0))[-1])

    mod.do_config("work", keychain_arg=None)

    assert sec_calls == [], f"_sec must not be called for shared re-config, got {sec_calls}"

    meta = json.loads((account_home / "account.json").read_text())
    assert "keychain" not in meta, f"meta must not gain a 'keychain' key, got {meta}"


# ---------------------------------------------------------------------------
# Fix F — _create_account_keychain reuse branch: orphan detection and happy path
# ---------------------------------------------------------------------------


def test_create_account_keychain_reuse_orphan_aborts_and_warns(monkeypatch, mod, tmp_account_home, capsys):
    """When the keychain file exists but find-generic-password returns 'could not be found',
    _create_account_keychain must NOT call create-keychain or add-generic-password,
    and must print a warning to stderr mentioning orphan state and manual recovery."""
    kc_path = mod._keychain_path(tmp_account_home)
    kc_path.parent.mkdir(parents=True, exist_ok=True)
    kc_path.touch()  # Simulate pre-existing keychain file.

    sec_calls = []

    def fake_sec(argv, *, check=True, timeout=10):
        sec_calls.append(list(argv))
        if argv[0] == "find-generic-password":
            return _cp(44, "", "The specified item could not be found in the keychain.")
        return _cp(0)

    monkeypatch.setattr(mod, "_sec", fake_sec)

    mod._create_account_keychain(tmp_account_home, "work")

    subcommands = [args[0] for args in sec_calls]
    assert "create-keychain" not in subcommands, "create-keychain must NOT be called for orphan"
    assert "add-generic-password" not in subcommands, "add-generic-password must NOT be called for orphan"

    captured = capsys.readouterr()
    assert "orphan" in captured.err.lower() or "orphaned" in captured.err.lower(), (
        f"stderr must mention orphan state; got: {captured.err!r}"
    )
    assert "altergo --config" in captured.err, (
        f"stderr must mention manual recovery via 'altergo --config'; got: {captured.err!r}"
    )


def test_create_account_keychain_reuse_happy_path_writes_plist(monkeypatch, mod, tmp_account_home):
    """When the keychain file exists and find-generic-password succeeds,
    _create_account_keychain rewrites the plist and returns without error."""
    kc_path = mod._keychain_path(tmp_account_home)
    kc_path.parent.mkdir(parents=True, exist_ok=True)
    kc_path.touch()

    # Remove plist to confirm it is re-written on happy reuse.
    prefs_path = tmp_account_home / "Library" / "Preferences" / "com.apple.security.plist"
    if prefs_path.exists():
        prefs_path.unlink()

    sec_calls = []

    def fake_sec(argv, *, check=True, timeout=10):
        sec_calls.append(list(argv))
        if argv[0] == "find-generic-password":
            return _cp(0, "deadbeef" * 8 + "\n")
        return _cp(0)

    monkeypatch.setattr(mod, "_sec", fake_sec)

    mod._create_account_keychain(tmp_account_home, "work")

    # create-keychain and add-generic-password must NOT be called (reuse path).
    subcommands = [args[0] for args in sec_calls]
    assert "create-keychain" not in subcommands, "create-keychain must NOT be called on reuse"
    assert "add-generic-password" not in subcommands, "add-generic-password must NOT be called on reuse"

    assert prefs_path.exists(), "plist must be (re-)written on happy reuse path"


# ---------------------------------------------------------------------------
# Fix G — do_config downgrade: isolated → shared cleanup
# ---------------------------------------------------------------------------


def test_do_config_downgrade_isolated_to_shared_runs_cleanup(monkeypatch, mod, tmp_path, capsys):
    """do_config('work', keychain_arg='shared') on an account previously marked
    keychain=isolated must:
    (a) call _sec with delete-keychain and delete-generic-password,
    (b) save meta without keychain=isolated,
    (c) print the dim 'Removed per-account keychain' confirmation line."""
    accounts_dir = _setup_do_config_env(monkeypatch, mod, tmp_path)
    account_home = accounts_dir / "work"
    account_home.mkdir(parents=True)

    # Pre-existing isolated account.
    existing_meta = {"version": 2, "provider": "claude", "keychain": "isolated", "created": "2025-01-01T00:00:00"}
    (account_home / "account.json").write_text(json.dumps(existing_meta))

    sec_calls = []

    def fake_sec(argv, *, check=True, timeout=10):
        sec_calls.append(list(argv))
        if argv[0] == "find-generic-password":
            return _cp(0, "deadbeef" * 8 + "\n")
        return _cp(0)

    monkeypatch.setattr(mod, "_sec", fake_sec)

    mod.do_config("work", keychain_arg="shared")

    # (a) Cleanup calls must have been made.
    subcommands = [args[0] for args in sec_calls]
    assert "delete-keychain" in subcommands, (
        f"delete-keychain must be called during downgrade; got subcommands: {subcommands}"
    )
    assert "delete-generic-password" in subcommands, (
        f"delete-generic-password must be called during downgrade; got subcommands: {subcommands}"
    )

    # (b) Saved meta must not carry keychain=isolated.
    meta = json.loads((account_home / "account.json").read_text())
    assert meta.get("keychain") != "isolated", (
        f"Downgrade must remove keychain=isolated from saved meta; got {meta}"
    )

    # (c) Confirmation line must appear on stdout.
    captured = capsys.readouterr()
    assert "Removed per-account keychain" in captured.out, (
        f"Downgrade confirmation must appear in stdout; got: {captured.out!r}"
    )
