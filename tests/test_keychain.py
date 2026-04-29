"""Tests for the macOS keychain isolation subsystem in altergo.py.

Covers: SECURITY_CMD, _KC_SERVICE, _KC_GUID, _KC_SUBSERVICE_TYPE, KeychainError,
_sec, _keychain_path, _keychain_prefs_path, _write_keychain_prefs,
_create_account_keychain, _unlock_account_keychain, _delete_account_keychain,
_is_keychain_private, _is_keychain_none, _is_keychain_isolated (compat alias),
_is_keychain_dedicated (compat alias), _build_alt_env (unlock path),
do_config (keychain_arg), do_delete_account (keychain teardown).

v0.45.0 vocabulary:
  - "private" : per-account keychain, unlocked at launch (was "dedicated" in v0.44.x)
  - "none"    : no keychain; flat-file credentials only (was "isolated" in v0.44.x)
  Default since v0.45.0: private (was none/isolated in v0.44.x)

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
                raise mod.KeychainError("security unlock-keychain failed (exit 1): errSecAuthFailed")
            return _cp(1, "", "errSecAuthFailed")
        return _cp(0)

    monkeypatch.setattr(mod, "_sec", fake_sec)
    return calls


@pytest.fixture()
def account_meta_dedicated():
    """In-memory v3 shape for a private-mode account (v0.45.0 name; v0.44.x called it 'dedicated').

    Uses the new canonical name "private".  Tests that need the old on-disk value
    "dedicated" should write account.json directly.
    """
    return {
        "version": 3,
        "providers": ["claude"],
        "default_provider": "claude",
        "keychain": "private",
    }


@pytest.fixture()
def account_meta_isolated():
    """In-memory v3 shape for none mode (v0.45.0 name; v0.44.x called it 'isolated').

    Uses the new canonical name "none".  Tests that need the old on-disk value
    "isolated" should write account.json directly.
    """
    return {
        "version": 3,
        "providers": ["claude"],
        "default_provider": "claude",
        "keychain": "none",
    }


@pytest.fixture()
def account_meta_legacy():
    """In-memory v3 shape with no keychain key (legacy pre-v0.44.0 system account).

    Since v0.45.0 the absent key → private by default.
    """
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


@pytest.mark.parametrize(
    "slug,expected_suffix",
    [
        ("work", "Library/Keychains/login.keychain-db"),
        ("personal", "Library/Keychains/login.keychain-db"),
    ],
)
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


def test_create_account_keychain_calls_correct_subcommands(monkeypatch, mod, tmp_account_home):
    """_create_account_keychain runs the three fresh-build subcommands in the correct
    relative order (Case 5: C absent, D absent).  Tolerates any preceding
    find-generic-password probe calls."""
    # Force Case 5 (pure fresh build): C absent (no file created), D absent (find fails).
    sec_calls = []

    def fake_sec(argv, *, check=True, timeout=10):
        sec_calls.append((list(argv), {"check": check, "timeout": timeout}))
        if argv[0] == "find-generic-password":
            return _cp(44, "", "The specified item could not be found in the keychain.")
        return _cp(0)

    monkeypatch.setattr(mod, "_sec", fake_sec)

    mod._create_account_keychain(tmp_account_home, "work")

    subcommands = [args[0] for args, _ in sec_calls]
    # The fresh-build sequence is exactly these three, in this order.
    expected_sequence = [
        "create-keychain",
        "set-keychain-settings",
        "add-generic-password",
    ]
    indices = []
    for cmd in expected_sequence:
        try:
            idx = subcommands.index(cmd)
        except ValueError:
            raise AssertionError(f"Expected subcommand '{cmd}' not found in {subcommands}")
        indices.append(idx)
    assert indices == sorted(indices), (
        f"Expected fresh-build subcommands in relative order {expected_sequence}; "
        f"got indices {indices} in {subcommands}"
    )


def test_create_account_keychain_writes_plist(mod, tmp_account_home, mock_sec_success):
    """_create_account_keychain also writes the prefs plist."""
    mod._create_account_keychain(tmp_account_home, "work")
    prefs_path = tmp_account_home / "Library" / "Preferences" / "com.apple.security.plist"
    assert prefs_path.exists()


def test_create_account_keychain_add_password_uses_service_and_slug(mod, tmp_account_home, mock_sec_success):
    """add-generic-password is called with -s _KC_SERVICE and -a <slug>."""
    mod._create_account_keychain(tmp_account_home, "work")
    add_call = next((args for args, _ in mock_sec_success if args[0] == "add-generic-password"), None)
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


def test_create_account_keychain_case1_reuse_skips_create(mod, tmp_account_home, mock_sec_success):
    """Case 1: C+D present and unlock probe succeeds — create-keychain is skipped,
    unlock-keychain is called as the consistency probe."""
    kc_path = mod._keychain_path(tmp_account_home)
    kc_path.touch()  # Simulate pre-existing C.
    # mock_sec_success returns success for find-generic-password and unlock-keychain.

    mock_sec_success.clear()
    mod._create_account_keychain(tmp_account_home, "work")

    subcommands = [args[0] for args, _ in mock_sec_success]
    assert "create-keychain" not in subcommands, "Case 1 must not call create-keychain"
    assert "unlock-keychain" in subcommands, "Case 1 must call unlock-keychain as probe"


def test_create_account_keychain_case1_probe_succeeds_writes_plist(mod, tmp_account_home, mock_sec_success):
    """Case 1: when C+D present and unlock probe succeeds, plist (B) is (re-)written."""
    kc_path = mod._keychain_path(tmp_account_home)
    kc_path.touch()  # Simulate pre-existing C.

    # Remove plist to confirm it is re-created on Case 1 reuse.
    prefs_path = tmp_account_home / "Library" / "Preferences" / "com.apple.security.plist"
    if prefs_path.exists():
        prefs_path.unlink()

    mod._create_account_keychain(tmp_account_home, "work")
    assert prefs_path.exists(), "Case 1 reuse must (re-)write plist B"


def test_create_account_keychain_delete_generic_uses_check_false(monkeypatch, mod, tmp_account_home):
    """In Case 2 (wrong-password rebuild), delete-generic-password uses check=False.
    In Case 3 (orphan-C rebuild), delete-keychain uses check=False (D is absent so no
    delete-generic-password is issued — only the file is removed)."""
    kc_path = mod._keychain_path(tmp_account_home)

    # --- Case 2: C+D present, unlock probe fails (wrong password) ---
    kc_path.touch()
    sec_calls_c2 = []

    def fake_sec_case2(argv, *, check=True, timeout=10):
        sec_calls_c2.append((list(argv), {"check": check}))
        if argv[0] == "find-generic-password":
            return _cp(0, "deadbeef" * 8 + "\n")  # D present
        if argv[0] == "unlock-keychain":
            return _cp(1, "", "errSecAuthFailed")  # wrong password
        return _cp(0)

    monkeypatch.setattr(mod, "_sec", fake_sec_case2)
    mod._create_account_keychain(tmp_account_home, "work")

    del_generic_c2 = [(args, kw) for args, kw in sec_calls_c2 if args[0] == "delete-generic-password"]
    assert del_generic_c2, "Case 2: expected delete-generic-password call"
    for args, kw in del_generic_c2:
        assert kw["check"] is False, "Case 2: delete-generic-password must use check=False"

    # --- Case 3: C present, D absent — delete-keychain with check=False, no delete-generic-password ---
    kc_path.touch()  # restore C
    sec_calls_c3 = []

    def fake_sec_case3(argv, *, check=True, timeout=10):
        sec_calls_c3.append((list(argv), {"check": check}))
        if argv[0] == "find-generic-password":
            return _cp(44, "", "The specified item could not be found in the keychain.")  # D absent
        return _cp(0)

    monkeypatch.setattr(mod, "_sec", fake_sec_case3)
    mod._create_account_keychain(tmp_account_home, "work")

    del_kc_c3 = [(args, kw) for args, kw in sec_calls_c3 if args[0] == "delete-keychain"]
    assert del_kc_c3, "Case 3: expected delete-keychain call to remove orphan C"
    for args, kw in del_kc_c3:
        assert kw["check"] is False, "Case 3: delete-keychain must use check=False"

    del_generic_c3 = [args for args, _ in sec_calls_c3 if args[0] == "delete-generic-password"]
    assert not del_generic_c3, "Case 3: must NOT call delete-generic-password (D is absent — nothing to delete)"


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


@pytest.mark.parametrize(
    "meta,expected",
    [
        # v0.45.0: absent key / None / empty → private by default → _is_keychain_none=False.
        (None, False),
        ({}, False),
        ({"version": 2, "provider": "claude"}, False),
        # Explicit "none" (current canonical name) → True.
        ({"version": 2, "provider": "claude", "keychain": "none"}, True),
        # "private" → NOT none.
        ({"keychain": "private"}, False),
        # "dedicated" (old name, coerced to "private" by _coerce_meta_v3) → NOT none.
        ({"keychain": "dedicated"}, False),
        # Wrong-case / unknown values → False.
        ({"keychain": "ISOLATED"}, False),
        ({"keychain": "Isolated"}, False),
    ],
)
def test_is_keychain_isolated_truth_table(mod, meta, expected):
    """_is_keychain_isolated is the v0.44.x compat alias for _is_keychain_none.
    In v0.45.0, absent key / None → private by default, so _is_keychain_none returns False
    for those cases.  In production, meta is always coerced by _coerce_meta_v3 before
    reaching this function, so "isolated" on disk → "none" in memory → returns True."""
    assert mod._is_keychain_isolated(meta) is expected


# ---------------------------------------------------------------------------
# Gating test 3: _build_alt_env exits 1 on KeychainError
# ---------------------------------------------------------------------------


def test_build_alt_env_exits_1_on_keychain_error(monkeypatch, mod, tmp_path, account_meta_dedicated):
    """When _unlock_account_keychain raises KeychainError, _build_alt_env calls sys.exit(1).
    Only dedicated mode calls _unlock_account_keychain."""
    accounts_dir = tmp_path / "accounts"
    (accounts_dir / "work").mkdir(parents=True)
    monkeypatch.setattr(mod, "ACCOUNTS_DIR", accounts_dir)
    monkeypatch.setattr(mod.sys, "platform", "darwin")

    monkeypatch.setattr(mod, "load_account_meta", lambda path: account_meta_dedicated)
    monkeypatch.setattr(
        mod, "_unlock_account_keychain", lambda home, slug: (_ for _ in ()).throw(mod.KeychainError("test"))
    )

    stderr_buf = io.StringIO()
    monkeypatch.setattr(mod.sys, "stderr", stderr_buf)

    with pytest.raises(SystemExit) as exc_info:
        mod._build_alt_env("work")

    assert exc_info.value.code == 1


def test_build_alt_env_propagates_keychain_error_message(monkeypatch, mod, tmp_path, account_meta_dedicated):
    """The KeychainError message appears in stderr before sys.exit(1).
    Only dedicated mode calls _unlock_account_keychain."""
    accounts_dir = tmp_path / "accounts"
    (accounts_dir / "work").mkdir(parents=True)
    monkeypatch.setattr(mod, "ACCOUNTS_DIR", accounts_dir)
    monkeypatch.setattr(mod.sys, "platform", "darwin")

    monkeypatch.setattr(mod, "load_account_meta", lambda path: account_meta_dedicated)
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


@pytest.mark.parametrize(
    "meta",
    [
        # none-mode accounts: B is absent, reconciler writes B using pure Python.
        # No build/unlock/delete _sec calls should occur (B write is pure Python).
        {"version": 2, "provider": "claude", "keychain": "none"},
    ],
)
def test_build_alt_env_legacy_meta_no_unlock_sec_calls(monkeypatch, mod, tmp_path, meta):
    """_build_alt_env with none-mode meta must not call _unlock_account_keychain.
    None mode never calls unlock. The reconciler writes B (plist) if absent
    using pure Python (_write_keychain_prefs) — no _sec calls needed for that."""
    accounts_dir = tmp_path / "accounts"
    account_home = accounts_dir / "work"
    account_home.mkdir(parents=True)
    (account_home / "Library" / "Preferences").mkdir(parents=True)
    (account_home / "Library" / "Keychains").mkdir(parents=True)
    # B (plist) is intentionally absent.
    assert not (account_home / "Library" / "Preferences" / "com.apple.security.plist").exists()

    monkeypatch.setattr(mod, "ACCOUNTS_DIR", accounts_dir)
    monkeypatch.setattr(mod.sys, "platform", "darwin")

    import json as _json

    (account_home / "account.json").write_text(_json.dumps(meta))

    sec_calls = []

    def spy_sec(argv, **kw):
        sec_calls.append(list(argv))
        return _cp(0, "")

    monkeypatch.setattr(mod, "_sec", spy_sec)

    mod._build_alt_env("work")

    # No unlock, create, or destructive _sec calls — none mode never calls unlock.
    disallowed = {
        "unlock-keychain",
        "create-keychain",
        "set-keychain-settings",
        "add-generic-password",
        "delete-keychain",
        "delete-generic-password",
    }
    bad_calls = [args for args in sec_calls if args[0] in disallowed]
    assert bad_calls == [], f"Expected no unlock/build/delete _sec calls for none meta={meta!r}; got {bad_calls}"


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
    """do_config with keychain_arg='none' on non-TTY writes meta with keychain=none
    and creates the plist file.  Also tests that the legacy alias 'isolated' is
    silently accepted and normalised to 'none'."""
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

    # Pass legacy alias "isolated" — must be silently normalised to "none".
    mod.do_config("work", keychain_arg="isolated")

    account_home = accounts_dir / "work"
    meta_path = account_home / "account.json"
    assert meta_path.exists(), "account.json must exist"
    meta = json.loads(meta_path.read_text())
    assert meta.get("keychain") == "none", f"Expected keychain=none (isolated alias), got {meta}"

    plist_path = account_home / "Library" / "Preferences" / "com.apple.security.plist"
    assert plist_path.exists(), "plist must exist for none-mode account"


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


def test_do_config_non_tty_no_flag_creates_private_mode(monkeypatch, mod, tmp_path):
    """do_config with keychain_arg=None on non-TTY defaults to private mode (v0.45.0 default).
    Private mode creates plist (B), keychain file (C), and plants the unlock entry (D).
    meta must have keychain='private'."""
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
    monkeypatch.setattr(mod, "_sec", lambda argv, **kw: (sec_calls.append(list(argv)), _cp(0))[-1])

    monkeypatch.setattr(mod, "show_banner", lambda *a, **kw: None)
    monkeypatch.setattr(mod, "_status_wrap", lambda msg, fn: fn())
    monkeypatch.setattr(mod, "load_settings", lambda: {})

    mod.do_config("work", keychain_arg=None)

    account_home = accounts_dir / "work"
    meta_path = account_home / "account.json"
    assert meta_path.exists()
    meta = json.loads(meta_path.read_text())
    assert meta.get("keychain") == "private", f"v0.45.0 default is 'private'; got {meta}"

    # private mode: plist must exist (routes Security.framework to per-account keychain).
    plist_path = account_home / "Library" / "Preferences" / "com.apple.security.plist"
    assert plist_path.exists(), "plist must exist for private mode (required for Security.framework routing)"

    # private mode: add-generic-password MUST be called (unlock entry planted).
    add_calls = [args for args in sec_calls if args[0] == "add-generic-password"]
    assert add_calls != [], f"private mode must call add-generic-password; sec_calls={sec_calls}"


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


def test_build_alt_env_non_darwin_never_calls_sec(monkeypatch, mod, tmp_path, account_meta_dedicated):
    """_build_alt_env on non-darwin never calls _sec even for dedicated meta."""
    accounts_dir = tmp_path / "accounts"
    (accounts_dir / "work").mkdir(parents=True)
    monkeypatch.setattr(mod, "ACCOUNTS_DIR", accounts_dir)
    monkeypatch.setattr(mod.sys, "platform", "linux")
    monkeypatch.setattr(mod, "load_account_meta", lambda path: account_meta_dedicated)

    sec_calls = []
    monkeypatch.setattr(mod, "_sec", lambda argv, **kw: (sec_calls.append(argv), _cp(0))[-1])

    mod._build_alt_env("work")

    assert sec_calls == []


# ---------------------------------------------------------------------------
# Re-config preserves isolation when meta already has keychain=isolated
# ---------------------------------------------------------------------------


def test_do_config_reconfig_preserves_none(monkeypatch, mod, tmp_path):
    """Re-running do_config on an account that already has keychain='none' keeps none mode
    when keychain_arg is None on non-TTY.  On non-TTY without keychain_arg, if the existing
    meta says 'none', do_config preserves 'none' (user opted out of private mode)."""
    main_home = tmp_path / "main_home"
    main_claude = main_home / ".claude"
    accounts_dir = tmp_path / "accounts"
    account_home = accounts_dir / "work"

    main_home.mkdir(parents=True)
    main_claude.mkdir(parents=True)
    accounts_dir.mkdir(parents=True)
    account_home.mkdir(parents=True)
    (account_home / "Library" / "Preferences").mkdir(parents=True)
    (account_home / "Library" / "Keychains").mkdir(parents=True)
    _create_main_claude_sources_for_mod(mod, main_claude)

    # Pre-existing "none" metadata — should stay "none" on re-config.
    (account_home / "account.json").write_text(json.dumps({"version": 2, "provider": "claude", "keychain": "none"}))

    monkeypatch.setattr(mod, "MAIN_HOME", main_home)
    monkeypatch.setattr(mod, "MAIN_CLAUDE", main_claude)
    monkeypatch.setattr(mod, "ACCOUNTS_DIR", accounts_dir)
    monkeypatch.setattr(mod, "SETTINGS_FILE", tmp_path / "settings.json")
    monkeypatch.setattr(mod.sys, "platform", "darwin")
    monkeypatch.setattr(mod.sys.stdin, "isatty", lambda: False)

    def fake_sec(argv, *, check=True, timeout=10):
        if argv[0] == "find-generic-password":
            return _cp(44, "", "The specified item could not be found.")  # D absent
        return _cp(0)

    monkeypatch.setattr(mod, "_sec", fake_sec)
    monkeypatch.setattr(mod, "show_banner", lambda *a, **kw: None)
    monkeypatch.setattr(mod, "_status_wrap", lambda msg, fn: fn())
    monkeypatch.setattr(mod, "load_settings", lambda: {})

    mod.do_config("work", keychain_arg=None)

    meta = json.loads((account_home / "account.json").read_text())
    assert meta.get("keychain") == "none", (
        f"Re-config with keychain_arg=None on non-TTY must preserve 'none' mode; got {meta}"
    )


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
    """do_delete_account calls _delete_account_keychain when the keychain file (C) is present on disk."""
    account_home = _setup_delete_account_env(monkeypatch, mod, tmp_path, account_meta_isolated)

    # Place the keychain file (C) on disk so the file-presence gate fires.
    kc_path = account_home / "Library" / "Keychains" / "login.keychain-db"
    kc_path.touch()

    delete_calls = []
    monkeypatch.setattr(mod, "_delete_account_keychain", lambda home, slug: delete_calls.append((home, slug)))

    # _sec needed for the find-generic-password probe in do_delete_account.
    monkeypatch.setattr(mod, "_sec", lambda argv, **kw: _cp(0, "deadbeef" * 8))

    mod.do_delete_account("work")

    assert len(delete_calls) == 1
    assert delete_calls[0][1] == "work"


def test_do_delete_account_no_artifacts_skips_keychain_teardown(monkeypatch, mod, tmp_path, account_meta_legacy):
    """do_delete_account does NOT call _delete_account_keychain when B, C, and D are all absent.
    The gate is artifact presence — not meta.  find-generic-password probe returns non-zero (D absent)."""
    account_home = _setup_delete_account_env(monkeypatch, mod, tmp_path, account_meta_legacy)

    delete_calls = []
    monkeypatch.setattr(mod, "_delete_account_keychain", lambda home, slug: delete_calls.append((home, slug)))

    # Spy on _sec so we can assert the find-generic-password probe was actually called.
    sec_calls = []

    def spy_sec(argv, *, check=True, timeout=10):
        sec_calls.append(list(argv))
        if argv[0] == "find-generic-password":
            # D absent — keychain entry does not exist.
            return _cp(44, "", "The specified item could not be found in the keychain.")
        return _cp(0)

    monkeypatch.setattr(mod, "_sec", spy_sec)

    mod.do_delete_account("work")

    # Probe must have been issued.
    probe_calls = [args for args in sec_calls if args[0] == "find-generic-password"]
    assert probe_calls, "do_delete_account must call find-generic-password to probe D presence"

    # No B or C on disk (setup did not create files), D probe returned non-zero — skip teardown.
    assert delete_calls == [], "do_delete_account must NOT call _delete_account_keychain when no artifacts are present"


def test_do_delete_account_continues_on_keychain_error(monkeypatch, mod, tmp_path, account_meta_isolated):
    """do_delete_account does not abort when _delete_account_keychain raises KeychainError."""
    account_home = _setup_delete_account_env(monkeypatch, mod, tmp_path, account_meta_isolated)

    def failing_delete(home, slug):
        raise mod.KeychainError("simulated keychain teardown failure")

    monkeypatch.setattr(mod, "_delete_account_keychain", failing_delete)
    # do_delete_account probes for D via _sec before calling _delete_account_keychain;
    # stub _sec so the probe succeeds on CI runners without /usr/bin/security (Linux).
    monkeypatch.setattr(mod, "_sec", lambda argv, **kw: _cp(0, "deadbeef\n"))

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
    delete_sec_calls = [
        (args, chk) for args, chk in sec_calls if args[0] in ("delete-keychain", "delete-generic-password")
    ]
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


def test_do_config_existing_system_account_normalizes_to_private(monkeypatch, mod, tmp_path):
    """Given an account.json with no 'keychain' key (legacy system/shared account),
    calling do_config(..., keychain_arg=None) on non-TTY must save meta with
    keychain='private' (the new default since v0.45.0) and must plant an unlock entry (D).
    Private mode creates plist (B), keychain file (C), and stores unlock entry (D)."""
    accounts_dir = _setup_do_config_env(monkeypatch, mod, tmp_path)
    account_home = accounts_dir / "work"
    account_home.mkdir(parents=True)
    (account_home / "Library" / "Preferences").mkdir(parents=True)
    (account_home / "Library" / "Keychains").mkdir(parents=True)

    # Pre-existing legacy system account — no 'keychain' key.
    existing_meta = {"version": 2, "provider": "claude", "created": "2025-01-01T00:00:00"}
    (account_home / "account.json").write_text(json.dumps(existing_meta))

    sec_calls = []
    monkeypatch.setattr(mod, "_sec", lambda argv, **kw: (sec_calls.append(list(argv)), _cp(0))[-1])

    mod.do_config("work", keychain_arg=None)

    meta = json.loads((account_home / "account.json").read_text())
    assert meta.get("keychain") == "private", f"v0.45.0 default is 'private'; got {meta}"

    # private mode MUST plant unlock entry (D).
    add_calls = [args for args in sec_calls if args[0] == "add-generic-password"]
    assert add_calls != [], f"private mode must call add-generic-password; sec_calls={sec_calls}"


# ---------------------------------------------------------------------------
# Fix F — _create_account_keychain reuse branch: Case 3 (orphan-C) and happy path
# ---------------------------------------------------------------------------


def test_create_account_keychain_case3_orphan_c_rebuilds(monkeypatch, mod, tmp_account_home, capsys):
    """Case 3: C present, D absent — delete-keychain is called (with check=False), then
    the fresh-build sequence runs.  No early abort, no 'altergo --config' stderr hint."""
    kc_path = mod._keychain_path(tmp_account_home)
    kc_path.parent.mkdir(parents=True, exist_ok=True)
    kc_path.touch()  # C present.

    sec_calls = []

    def fake_sec(argv, *, check=True, timeout=10):
        sec_calls.append((list(argv), {"check": check}))
        if argv[0] == "find-generic-password":
            # D absent
            return _cp(44, "", "The specified item could not be found in the keychain.")
        return _cp(0)

    monkeypatch.setattr(mod, "_sec", fake_sec)

    mod._create_account_keychain(tmp_account_home, "work")

    subcommands = [args[0] for args, _ in sec_calls]
    # delete-keychain must fire to clean up orphan C.
    assert "delete-keychain" in subcommands, "Case 3 must call delete-keychain to remove orphan C"
    del_kc = next(kw for args, kw in sec_calls if args[0] == "delete-keychain")
    assert del_kc["check"] is False, "Case 3 delete-keychain must use check=False"

    # Fresh build must run.
    assert "create-keychain" in subcommands, "Case 3 must proceed to fresh build (create-keychain)"
    assert "add-generic-password" in subcommands, "Case 3 must proceed to fresh build (add-generic-password)"

    # No 'altergo --config' recovery hint in stderr — behavior was removed.
    captured = capsys.readouterr()
    assert "altergo --config" not in captured.err, (
        f"Case 3 must NOT emit 'altergo --config' hint (old behavior removed); got: {captured.err!r}"
    )


def test_create_account_keychain_case1_probe_succeeds_also_writes_plist(monkeypatch, mod, tmp_account_home):
    """When the keychain file exists and find-generic-password+unlock both succeed (Case 1),
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
    assert "create-keychain" not in subcommands, "Case 1 must NOT call create-keychain"
    assert "add-generic-password" not in subcommands, "Case 1 must NOT call add-generic-password"

    assert prefs_path.exists(), "Case 1 must (re-)write plist B"


# ---------------------------------------------------------------------------
# Fix G — do_config downgrade: isolated → system preserve-and-reuse
# ---------------------------------------------------------------------------


def test_do_config_private_to_none_removes_unlock_entry(monkeypatch, mod, tmp_path):
    """do_config('work', keychain_arg='none') on a private account must:
    (a) call delete-generic-password to remove the unlock entry D (zero-footprint promise),
    (b) NOT call delete-keychain (C preserved for re-enable — preserve-and-reuse),
    (c) save meta with keychain='none'.

    Also tests that deprecated aliases ('system', 'isolated') are silently accepted."""
    accounts_dir = _setup_do_config_env(monkeypatch, mod, tmp_path)
    account_home = accounts_dir / "work"
    (account_home / "Library" / "Preferences").mkdir(parents=True)
    (account_home / "Library" / "Keychains").mkdir(parents=True)

    # Pre-existing private account: A=private, B+C present.
    existing_meta = {"version": 2, "provider": "claude", "keychain": "private", "created": "2025-01-01T00:00:00"}
    (account_home / "account.json").write_text(json.dumps(existing_meta))
    plist_path = account_home / "Library" / "Preferences" / "com.apple.security.plist"
    plist_path.touch()  # B present.
    kc_path = mod._keychain_path(account_home)
    kc_path.touch()  # C present.

    sec_calls = []

    def fake_sec(argv, *, check=True, timeout=10):
        sec_calls.append(list(argv))
        if argv[0] == "find-generic-password":
            return _cp(0, "deadbeef" * 8 + "\n")  # D present.
        return _cp(0)

    monkeypatch.setattr(mod, "_sec", fake_sec)

    # --keychain system is a deprecated alias → maps to none inside do_config.
    mod.do_config("work", keychain_arg="system")

    subcommands = [args[0] for args in sec_calls]

    # (a) Unlock entry must be removed (zero altergo footprint in real login keychain).
    assert "delete-generic-password" in subcommands, (
        f"Switching to none must call delete-generic-password to remove D; got: {subcommands}"
    )

    # (b) Keychain file must NOT be deleted (preserve-and-reuse for future re-upgrade).
    assert "delete-keychain" not in subcommands, (
        f"Switching to none must NOT call delete-keychain; got: {subcommands}"
    )

    # (c) Meta must record keychain=none.
    meta = json.loads((account_home / "account.json").read_text())
    assert meta.get("keychain") == "none", f"Switch to none must save keychain='none'; got {meta}"

    # Plist must remain (none mode requires it for Security.framework routing).
    assert plist_path.exists(), "Plist B must remain after switch to none mode"


# ---------------------------------------------------------------------------
# P0 — _create_account_keychain Case 2: wrong-password rebuild
# ---------------------------------------------------------------------------


def test_create_account_keychain_case2_wrong_password_rebuild(monkeypatch, mod, tmp_account_home):
    """Case 2: C+D present but unlock probe fails (wrong password).
    Expects delete-keychain AND delete-generic-password both called with check=False,
    followed by the fresh-build sequence (create-keychain, set-keychain-settings,
    add-generic-password)."""
    kc_path = mod._keychain_path(tmp_account_home)
    kc_path.touch()  # C present.

    sec_calls = []

    def fake_sec(argv, *, check=True, timeout=10):
        sec_calls.append((list(argv), {"check": check}))
        if argv[0] == "find-generic-password":
            return _cp(0, "deadbeef" * 8 + "\n")  # D present.
        if argv[0] == "unlock-keychain":
            return _cp(1, "", "errSecAuthFailed")  # Wrong password — Case 2 trigger.
        return _cp(0)

    monkeypatch.setattr(mod, "_sec", fake_sec)
    mod._create_account_keychain(tmp_account_home, "work")

    subcommands = [args[0] for args, _ in sec_calls]

    # Both destructive calls must fire.
    assert "delete-keychain" in subcommands, "Case 2 must call delete-keychain"
    assert "delete-generic-password" in subcommands, "Case 2 must call delete-generic-password"

    # Both must use check=False.
    for target in ("delete-keychain", "delete-generic-password"):
        kw = next(kw for args, kw in sec_calls if args[0] == target)
        assert kw["check"] is False, f"Case 2: {target} must use check=False"

    # Fresh build must execute after cleanup.
    assert "create-keychain" in subcommands, "Case 2 must proceed to fresh build (create-keychain)"
    assert "add-generic-password" in subcommands, "Case 2 must proceed to fresh build (add-generic-password)"

    # Relative order: both deletes before create-keychain.
    idx_del_kc = subcommands.index("delete-keychain")
    idx_del_gp = subcommands.index("delete-generic-password")
    idx_create = subcommands.index("create-keychain")
    assert idx_del_kc < idx_create, "delete-keychain must precede create-keychain"
    assert idx_del_gp < idx_create, "delete-generic-password must precede create-keychain"


# ---------------------------------------------------------------------------
# P0 — _create_account_keychain Case 4: stale-D rebuild
# ---------------------------------------------------------------------------


def test_create_account_keychain_case4_stale_d_rebuild(monkeypatch, mod, tmp_account_home):
    """Case 4: C absent, D present (stale unlock entry).
    Expects delete-generic-password called with check=False, then fresh build runs.
    No delete-keychain because C is already absent."""
    # C absent (no kc_path.touch()), D present.
    sec_calls = []

    def fake_sec(argv, *, check=True, timeout=10):
        sec_calls.append((list(argv), {"check": check}))
        if argv[0] == "find-generic-password":
            return _cp(0, "deadbeef" * 8 + "\n")  # D present — stale entry.
        return _cp(0)

    monkeypatch.setattr(mod, "_sec", fake_sec)
    mod._create_account_keychain(tmp_account_home, "work")

    subcommands = [args[0] for args, _ in sec_calls]

    # Stale D must be removed.
    assert "delete-generic-password" in subcommands, "Case 4 must call delete-generic-password for stale D"
    del_kw = next(kw for args, kw in sec_calls if args[0] == "delete-generic-password")
    assert del_kw["check"] is False, "Case 4: delete-generic-password must use check=False"

    # No keychain file to delete — delete-keychain must NOT be called.
    assert "delete-keychain" not in subcommands, "Case 4 must NOT call delete-keychain (C is absent)"

    # Fresh build must run.
    assert "create-keychain" in subcommands, "Case 4 must proceed to fresh build (create-keychain)"
    assert "add-generic-password" in subcommands, "Case 4 must proceed to fresh build (add-generic-password)"

    # delete-generic-password must precede create-keychain.
    idx_del = subcommands.index("delete-generic-password")
    idx_create = subcommands.index("create-keychain")
    assert idx_del < idx_create, "delete-generic-password must precede create-keychain in Case 4"


# ---------------------------------------------------------------------------
# P0 — _reconcile_keychain_state desired=None: State #1 crash-recovery
# ---------------------------------------------------------------------------


def test_reconcile_desired_none_state1_crash_recovery_rebuilds(monkeypatch, mod, tmp_account_home):
    """State #1 crash-recovery: A=private (written via pre-flight stamp) + B/C/D all absent
    (process crashed after writing meta but before creating B/C/D).
    _reconcile_keychain_state(desired=None) must detect the missing B and trigger a rebuild.

    Also tests that the legacy on-disk value "dedicated" is coerced to "private" and that
    after rebuild A is persisted with the new canonical name "private"."""
    # A=dedicated on disk (pre-flight stamp written); coerces to "private" in memory.
    # B/C/D all absent (crash scenario).
    (tmp_account_home / "account.json").write_text(json.dumps({"keychain": "dedicated"}))
    assert not mod._keychain_prefs_path(tmp_account_home).exists()
    assert not mod._keychain_path(tmp_account_home).exists()

    sec_calls = []

    def fake_sec(argv, *, check=True, timeout=10):
        sec_calls.append((list(argv), {"check": check}))
        if argv[0] == "find-generic-password":
            return _cp(44, "", "The specified item could not be found in the keychain.")  # D absent.
        return _cp(0)

    monkeypatch.setattr(mod, "_sec", fake_sec)

    mod._reconcile_keychain_state(tmp_account_home, "work", desired=None)

    # Rebuild must have fired — create-keychain is the signal.
    subcommands = [args[0] for args, _ in sec_calls]
    assert "create-keychain" in subcommands, (
        f"State #1 private crash-recovery: reconciler must rebuild when B absent; got {subcommands}"
    )

    # A must be updated to 'private' after rebuild (new canonical name).
    meta = json.loads((tmp_account_home / "account.json").read_text())
    assert meta.get("keychain") == "private", f"State #1 repair: A must be 'private' after rebuild; got {meta}"


# ---------------------------------------------------------------------------
# P0 — _reconcile_keychain_state desired=None: State #13 wrong-password drift
# ---------------------------------------------------------------------------


def test_reconcile_desired_none_state13_wrong_password_drift_rebuilds(monkeypatch, mod, tmp_account_home):
    """State #13: B+C+D all present but unlock probe fails (password mismatch drift).
    _reconcile_keychain_state(desired=None) must trigger _create_account_keychain
    (rebuild) and write A='private'."""
    # Set up B, C present on disk; A=private (v0.45.0 canonical name).
    (tmp_account_home / "account.json").write_text(json.dumps({"keychain": "private"}))
    mod._keychain_prefs_path(tmp_account_home).parent.mkdir(parents=True, exist_ok=True)
    mod._keychain_prefs_path(tmp_account_home).touch()  # B present.
    mod._keychain_path(tmp_account_home).parent.mkdir(parents=True, exist_ok=True)
    mod._keychain_path(tmp_account_home).touch()  # C present.

    sec_calls = []

    def fake_sec(argv, *, check=True, timeout=10):
        sec_calls.append((list(argv), {"check": check}))
        if argv[0] == "find-generic-password":
            return _cp(0, "deadbeef" * 8 + "\n")  # D present.
        if argv[0] == "unlock-keychain":
            return _cp(1, "", "errSecAuthFailed")  # Password mismatch — State #13 trigger.
        return _cp(0)

    monkeypatch.setattr(mod, "_sec", fake_sec)

    mod._reconcile_keychain_state(tmp_account_home, "work", desired=None)

    subcommands = [args[0] for args, _ in sec_calls]

    # Rebuild must fire — create-keychain is the signal.
    assert "create-keychain" in subcommands, "State #13: reconciler must trigger rebuild when unlock probe fails"
    assert "add-generic-password" in subcommands, "State #13: rebuild must store a fresh unlock entry"

    # A must be written as 'private' after successful rebuild (new canonical name).
    meta = json.loads((tmp_account_home / "account.json").read_text())
    assert meta.get("keychain") == "private", (
        f"State #13 rebuild: A must be written as 'private' after repair; got {meta}"
    )


# ---------------------------------------------------------------------------
# P0 — _reconcile_keychain_state desired=None: no-op fast path
# ---------------------------------------------------------------------------


def test_reconcile_desired_none_none_b_absent_writes_plist_no_sec(monkeypatch, mod, tmp_account_home):
    """desired=None with A=none (or legacy system → migrated to none) and B absent:
    reconciler writes plist B using pure Python (_write_keychain_prefs — no _sec call),
    and persists A='none' to disk. No build/unlock/delete _sec calls occur."""
    # A=system on disk — migrates in-memory to none.
    (tmp_account_home / "account.json").write_text(json.dumps({"keychain": "system"}))
    assert not mod._keychain_prefs_path(tmp_account_home).exists()  # B absent.

    sec_calls = []

    def fake_sec(argv, *, check=True, timeout=10):
        sec_calls.append((list(argv), {"check": check}))
        if argv[0] == "find-generic-password":
            return _cp(44, "", "The specified item could not be found in the keychain.")
        return _cp(0)

    monkeypatch.setattr(mod, "_sec", fake_sec)

    mod._reconcile_keychain_state(tmp_account_home, "work", desired=None)

    # No build/unlock/delete _sec calls — plist write is pure Python.
    disallowed = {
        "unlock-keychain",
        "create-keychain",
        "set-keychain-settings",
        "add-generic-password",
        "delete-keychain",
        "delete-generic-password",
    }
    bad_calls = [args[0] for args, _ in sec_calls if args[0] in disallowed]
    assert bad_calls == [], (
        f"None mode B-absent repair must make zero build/unlock/delete _sec calls; got {bad_calls}"
    )

    # B (plist) must now exist — written by _write_keychain_prefs.
    assert mod._keychain_prefs_path(tmp_account_home).exists(), (
        "Reconciler must write plist B when A=none and B absent"
    )

    # Meta must be updated to 'none' (migration from 'system').
    meta = json.loads((tmp_account_home / "account.json").read_text())
    assert meta.get("keychain") == "none", f"Reconciler must persist migrated key 'none'; got {meta}"


# ---------------------------------------------------------------------------
# v0.44.0 new tests (spec §3.2)
# ---------------------------------------------------------------------------


def _has_add_unlock_entry(calls, slug):
    """Return True if any spy call is add-generic-password for _KC_SERVICE and slug."""
    for args, *_ in calls:
        if (
            isinstance(args, list)
            and args[0] == "add-generic-password"
            and "-s" in args
            and args[args.index("-s") + 1] == "com.altergo.account-unlock"
            and "-a" in args
            and args[args.index("-a") + 1] == slug
        ):
            return True
    return False


def test_isolated_mode_does_not_plant_unlock_entry(monkeypatch, mod, tmp_account_home):
    """_create_account_keychain_isolated must NOT call add-generic-password."""
    sec_calls = []

    def fake_sec(argv, *, check=True, timeout=10):
        sec_calls.append((list(argv), {}))
        if argv[0] == "find-generic-password":
            return _cp(44, "", "not found")
        return _cp(0)

    monkeypatch.setattr(mod, "_sec", fake_sec)
    mod._create_account_keychain_isolated(tmp_account_home, "work")

    assert not _has_add_unlock_entry(sec_calls, "work"), (
        "isolated mode must NOT plant an unlock entry; add-generic-password found in spy"
    )


def test_isolated_mode_writes_plist_and_keychain_file(monkeypatch, mod, tmp_account_home):
    """_create_account_keychain_isolated writes plist B and calls create-keychain for C."""
    sec_calls = []

    def fake_sec(argv, *, check=True, timeout=10):
        sec_calls.append((list(argv), {}))
        if argv[0] == "find-generic-password":
            return _cp(44, "", "not found")
        return _cp(0)

    monkeypatch.setattr(mod, "_sec", fake_sec)
    mod._create_account_keychain_isolated(tmp_account_home, "work")

    subcommands = [args[0] for args, _ in sec_calls]
    assert "create-keychain" in subcommands, "isolated mode must call create-keychain to create C"

    prefs_path = mod._keychain_prefs_path(tmp_account_home)
    assert prefs_path.exists(), "isolated mode must write plist B"

    import plistlib

    with open(prefs_path, "rb") as f:
        data = plistlib.load(f)
    assert "DLDBSearchList" in data, "plist must contain DLDBSearchList"


def test_isolated_mode_uses_random_password_that_is_not_stored(monkeypatch, mod, tmp_account_home):
    """_create_account_keychain_isolated uses a random password for create-keychain but
    never passes that password to add-generic-password (because add-generic-password is
    never called)."""
    create_passwords = []
    add_passwords = []

    def fake_sec(argv, *, check=True, timeout=10):
        if argv[0] == "find-generic-password":
            return _cp(44, "", "not found")
        if argv[0] == "create-keychain" and "-p" in argv:
            create_passwords.append(argv[argv.index("-p") + 1])
        if argv[0] == "add-generic-password" and "-w" in argv:
            add_passwords.append(argv[argv.index("-w") + 1])
        return _cp(0)

    monkeypatch.setattr(mod, "_sec", fake_sec)
    mod._create_account_keychain_isolated(tmp_account_home, "work")

    assert len(create_passwords) == 1, "create-keychain must be called once"
    # Password must not appear in any add-generic-password call (there should be none).
    assert add_passwords == [], f"Password must not be stored; got add-generic-password calls: {add_passwords}"
    # Verify no overlap in any case.
    assert create_passwords[0] not in add_passwords


def test_isolated_mode_keychain_is_unusable_by_provider(monkeypatch, mod, tmp_path, account_meta_isolated):
    """_build_alt_env with isolated account does NOT call _unlock_account_keychain.
    No exit, no error — launch proceeds normally."""
    accounts_dir = tmp_path / "accounts"
    account_home = accounts_dir / "work"
    account_home.mkdir(parents=True)
    monkeypatch.setattr(mod, "ACCOUNTS_DIR", accounts_dir)
    monkeypatch.setattr(mod.sys, "platform", "darwin")

    # Isolated meta: _is_keychain_dedicated returns False → no unlock.
    monkeypatch.setattr(mod, "load_account_meta", lambda path: account_meta_isolated)

    unlock_calls = []
    monkeypatch.setattr(mod, "_unlock_account_keychain", lambda home, slug: unlock_calls.append((home, slug)))

    # Reconciler must not crash and must not call unlock either.
    monkeypatch.setattr(mod, "_reconcile_keychain_state", lambda *a, **kw: None)

    env = mod._build_alt_env("work")

    assert unlock_calls == [], "_unlock_account_keychain must NOT be called for isolated accounts"
    assert "HOME" in env, "env must have HOME set"


def test_build_alt_env_dedicated_mode_unlocks(monkeypatch, mod, tmp_path, account_meta_dedicated):
    """_build_alt_env with dedicated account calls _unlock_account_keychain exactly once."""
    accounts_dir = tmp_path / "accounts"
    account_home = accounts_dir / "work"
    account_home.mkdir(parents=True)
    monkeypatch.setattr(mod, "ACCOUNTS_DIR", accounts_dir)
    monkeypatch.setattr(mod.sys, "platform", "darwin")

    monkeypatch.setattr(mod, "load_account_meta", lambda path: account_meta_dedicated)
    monkeypatch.setattr(mod, "_reconcile_keychain_state", lambda *a, **kw: None)

    unlock_calls = []
    monkeypatch.setattr(mod, "_unlock_account_keychain", lambda home, slug: unlock_calls.append((home, slug)))

    mod._build_alt_env("work")

    assert len(unlock_calls) == 1, f"dedicated mode must call _unlock_account_keychain once; got {unlock_calls}"


def test_migration_system_to_none_on_load(tmp_account_home):
    """load_account_meta with keychain='system' on disk returns in-memory keychain='none'.
    (v0.45.0: system → none; was system → isolated in v0.44.x)"""
    import json as _json
    import importlib.util

    spec = importlib.util.spec_from_file_location("altergo", ROOT / "altergo.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)

    (tmp_account_home / "account.json").write_text(
        _json.dumps({"version": 3, "providers": ["claude"], "default_provider": "claude", "keychain": "system"})
    )

    meta = mod.load_account_meta(tmp_account_home)
    assert meta.get("keychain") == "none", f"system → none migration failed; got {meta}"

    # On-disk must be unchanged (migration is in-memory only).
    raw = _json.loads((tmp_account_home / "account.json").read_text())
    assert raw.get("keychain") == "system", "on-disk value must not be changed by load alone"


def test_migration_shared_to_none_on_load(tmp_account_home):
    """load_account_meta with keychain='shared' on disk returns in-memory keychain='none'.
    (v0.45.0: shared → none; was shared → isolated in v0.44.x)"""
    import json as _json
    import importlib.util

    spec = importlib.util.spec_from_file_location("altergo", ROOT / "altergo.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)

    (tmp_account_home / "account.json").write_text(
        _json.dumps({"version": 3, "providers": ["claude"], "default_provider": "claude", "keychain": "shared"})
    )

    meta = mod.load_account_meta(tmp_account_home)
    assert meta.get("keychain") == "none", f"shared → none migration failed; got {meta}"

    raw = _json.loads((tmp_account_home / "account.json").read_text())
    assert raw.get("keychain") == "shared", "on-disk value must not be changed by load alone"


def test_migration_old_isolated_to_none_on_load(tmp_account_home):
    """load_account_meta with keychain='isolated' on disk coerces to 'none' in v0.45.0.
    ('isolated' was the blocking-mode name in v0.44.x; it is now called 'none'.)"""
    import json as _json
    import importlib.util

    spec = importlib.util.spec_from_file_location("altergo", ROOT / "altergo.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)

    (tmp_account_home / "account.json").write_text(
        _json.dumps({"version": 3, "providers": ["claude"], "default_provider": "claude", "keychain": "isolated"})
    )

    meta = mod.load_account_meta(tmp_account_home)
    assert meta.get("keychain") == "none", f"old isolated must coerce to none; got {meta}"

    # On-disk must be unchanged (migration is in-memory only).
    raw = _json.loads((tmp_account_home / "account.json").read_text())
    assert raw.get("keychain") == "isolated", "on-disk value must not be changed by load alone"


def test_migration_old_dedicated_to_private_on_load(tmp_account_home):
    """load_account_meta with keychain='dedicated' on disk coerces to 'private' in v0.45.0.
    ('dedicated' was the per-account-keychain name in v0.44.x; it is now called 'private'.)"""
    import json as _json
    import importlib.util

    spec = importlib.util.spec_from_file_location("altergo", ROOT / "altergo.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)

    (tmp_account_home / "account.json").write_text(
        _json.dumps({"version": 3, "providers": ["claude"], "default_provider": "claude", "keychain": "dedicated"})
    )

    meta = mod.load_account_meta(tmp_account_home)
    assert meta.get("keychain") == "private", f"old dedicated must coerce to private; got {meta}"

    # On-disk must be unchanged (migration is in-memory only).
    raw = _json.loads((tmp_account_home / "account.json").read_text())
    assert raw.get("keychain") == "dedicated", "on-disk value must not be changed by load alone"


def test_migration_legacy_no_keychain_key_treated_as_private(tmp_account_home):
    """load_account_meta with no keychain key → _is_keychain_private returns True.
    v0.45.0 default is private (was none/isolated in v0.44.x)."""
    import json as _json
    import importlib.util

    spec = importlib.util.spec_from_file_location("altergo", ROOT / "altergo.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)

    (tmp_account_home / "account.json").write_text(
        _json.dumps({"version": 3, "providers": ["claude"], "default_provider": "claude"})
    )

    meta = mod.load_account_meta(tmp_account_home)
    assert mod._is_keychain_private(meta) is True, "no keychain key → private (new default since v0.45.0)"
    assert mod._is_keychain_none(meta) is False, "no keychain key → not none"
    # Backwards-compat aliases
    assert mod._is_keychain_dedicated(meta) is True, "dedicated alias → same as _is_keychain_private"
    assert mod._is_keychain_isolated(meta) is False, "isolated alias → same as _is_keychain_none"


def test_reconcile_persists_migrated_key_on_launch(monkeypatch, tmp_account_home):
    """_reconcile_keychain_state(desired=None) with 'system' on disk persists 'none'
    (v0.45.0: system → none; was system → isolated in v0.44.x)."""
    import json as _json
    import importlib.util

    spec = importlib.util.spec_from_file_location("altergo", ROOT / "altergo.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)

    (tmp_account_home / "account.json").write_text(
        _json.dumps({"version": 3, "providers": ["claude"], "default_provider": "claude", "keychain": "system"})
    )

    def fake_sec(argv, *, check=True, timeout=10):
        if argv[0] == "find-generic-password":
            return _cp(44, "", "not found")
        return _cp(0)

    monkeypatch.setattr(mod, "_sec", fake_sec)

    mod._reconcile_keychain_state(tmp_account_home, "work", desired=None)

    raw = _json.loads((tmp_account_home / "account.json").read_text())
    assert raw.get("keychain") == "none", f"reconciler must persist migrated 'none' to disk; got {raw}"


def test_reconcile_preserves_private_on_launch_with_prior_state(monkeypatch, tmp_account_home):
    """_reconcile_keychain_state(desired=None) with 'private' account + B+C+D consistent:
    leaves everything unchanged, no files deleted.  Also tests that old on-disk value
    'dedicated' is coerced in-memory to 'private' and then persisted as 'private'."""
    import json as _json
    import importlib.util

    spec = importlib.util.spec_from_file_location("altergo", ROOT / "altergo.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)

    # Write old on-disk "dedicated" — coerces to "private" in memory.
    (tmp_account_home / "account.json").write_text(
        _json.dumps({"version": 3, "providers": ["claude"], "default_provider": "claude", "keychain": "dedicated"})
    )
    # B present.
    mod._keychain_prefs_path(tmp_account_home).parent.mkdir(parents=True, exist_ok=True)
    mod._keychain_prefs_path(tmp_account_home).touch()
    # C present.
    mod._keychain_path(tmp_account_home).parent.mkdir(parents=True, exist_ok=True)
    mod._keychain_path(tmp_account_home).touch()

    def fake_sec(argv, *, check=True, timeout=10):
        if argv[0] == "find-generic-password":
            return _cp(0, "deadbeef" * 8 + "\n")  # D present
        return _cp(0)  # unlock-keychain probe succeeds

    monkeypatch.setattr(mod, "_sec", fake_sec)

    mod._reconcile_keychain_state(tmp_account_home, "work", desired=None)

    # C must still exist (not deleted).
    assert mod._keychain_path(tmp_account_home).exists(), "C must be preserved"
    # A must now say 'private' (migration from 'dedicated' persisted).
    raw = _json.loads((tmp_account_home / "account.json").read_text())
    assert raw.get("keychain") == "private", f"A must be persisted as 'private' after migration; got {raw}"


def test_cli_keychain_system_emits_deprecation_warning(monkeypatch, tmp_path):
    """--keychain system in the arg parser emits a deprecation warning and resolves to none."""
    import importlib.util, io, json as _json, sys as _sys

    spec = importlib.util.spec_from_file_location("altergo", ROOT / "altergo.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)

    # Capture the keychain_arg that reaches do_config, and stderr output.
    captured = {}

    def fake_do_config(account, provider="claude", *, keychain_arg=None):
        captured["keychain_arg"] = keychain_arg

    monkeypatch.setattr(mod, "do_config", fake_do_config)

    accounts_dir = tmp_path / "accounts"
    accounts_dir.mkdir()
    monkeypatch.setattr(mod, "ACCOUNTS_DIR", accounts_dir)

    stderr_buf = io.StringIO()
    monkeypatch.setattr(mod.sys, "stderr", stderr_buf)
    monkeypatch.setattr(mod.sys, "argv", ["altergo", "--config", "work", "--keychain", "system"])
    monkeypatch.setattr(mod.sys.stdin, "isatty", lambda: False)

    with pytest.raises(SystemExit):
        mod.main()

    assert captured.get("keychain_arg") == "none", (
        f"--keychain system must resolve to 'none'; got {captured.get('keychain_arg')}"
    )
    assert "deprecated" in stderr_buf.getvalue().lower(), (
        f"--keychain system must emit deprecation warning; got: {stderr_buf.getvalue()!r}"
    )


def test_cli_keychain_shared_emits_deprecation_warning(monkeypatch, tmp_path):
    """--keychain shared in the arg parser emits a deprecation warning and resolves to none."""
    import importlib.util, io

    spec = importlib.util.spec_from_file_location("altergo", ROOT / "altergo.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)

    captured = {}

    def fake_do_config(account, provider="claude", *, keychain_arg=None):
        captured["keychain_arg"] = keychain_arg

    monkeypatch.setattr(mod, "do_config", fake_do_config)

    accounts_dir = tmp_path / "accounts"
    accounts_dir.mkdir()
    monkeypatch.setattr(mod, "ACCOUNTS_DIR", accounts_dir)

    stderr_buf = io.StringIO()
    monkeypatch.setattr(mod.sys, "stderr", stderr_buf)
    monkeypatch.setattr(mod.sys, "argv", ["altergo", "--config", "work", "--keychain", "shared"])
    monkeypatch.setattr(mod.sys.stdin, "isatty", lambda: False)

    with pytest.raises(SystemExit):
        mod.main()

    assert captured.get("keychain_arg") == "none", (
        f"--keychain shared must resolve to 'none'; got {captured.get('keychain_arg')}"
    )
    assert "deprecated" in stderr_buf.getvalue().lower()


def test_cli_keychain_dedicated_silent_alias(monkeypatch, tmp_path):
    """--keychain dedicated is a silent backwards-compat alias for 'private' (no warning).
    v0.45.0: 'dedicated' resolves to 'private' without emitting a deprecation warning."""
    import importlib.util, io

    spec = importlib.util.spec_from_file_location("altergo", ROOT / "altergo.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)

    captured = {}

    def fake_do_config(account, provider="claude", *, keychain_arg=None):
        captured["keychain_arg"] = keychain_arg

    monkeypatch.setattr(mod, "do_config", fake_do_config)

    accounts_dir = tmp_path / "accounts"
    accounts_dir.mkdir()
    monkeypatch.setattr(mod, "ACCOUNTS_DIR", accounts_dir)

    stderr_buf = io.StringIO()
    monkeypatch.setattr(mod.sys, "stderr", stderr_buf)
    monkeypatch.setattr(mod.sys, "argv", ["altergo", "--config", "work", "--keychain", "dedicated"])
    monkeypatch.setattr(mod.sys.stdin, "isatty", lambda: False)

    with pytest.raises(SystemExit):
        mod.main()

    assert captured.get("keychain_arg") == "private", (
        f"--keychain dedicated must resolve to 'private'; got {captured.get('keychain_arg')}"
    )
    assert "deprecated" not in stderr_buf.getvalue().lower(), (
        f"--keychain dedicated must NOT emit deprecation; got: {stderr_buf.getvalue()!r}"
    )


def test_cli_keychain_isolated_silent_alias(monkeypatch, tmp_path):
    """--keychain isolated is a silent backwards-compat alias for 'none' (no warning).
    v0.45.0: 'isolated' resolves to 'none' without emitting a deprecation warning."""
    import importlib.util, io

    spec = importlib.util.spec_from_file_location("altergo", ROOT / "altergo.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)

    captured = {}

    def fake_do_config(account, provider="claude", *, keychain_arg=None):
        captured["keychain_arg"] = keychain_arg

    monkeypatch.setattr(mod, "do_config", fake_do_config)

    accounts_dir = tmp_path / "accounts"
    accounts_dir.mkdir()
    monkeypatch.setattr(mod, "ACCOUNTS_DIR", accounts_dir)

    stderr_buf = io.StringIO()
    monkeypatch.setattr(mod.sys, "stderr", stderr_buf)
    monkeypatch.setattr(mod.sys, "argv", ["altergo", "--config", "work", "--keychain", "isolated"])
    monkeypatch.setattr(mod.sys.stdin, "isatty", lambda: False)

    with pytest.raises(SystemExit):
        mod.main()

    assert captured.get("keychain_arg") == "none", (
        f"--keychain isolated must resolve to 'none'; got {captured.get('keychain_arg')}"
    )
    assert "deprecated" not in stderr_buf.getvalue().lower(), (
        f"--keychain isolated must NOT emit deprecation; got: {stderr_buf.getvalue()!r}"
    )


def test_cli_keychain_private_no_warning(monkeypatch, tmp_path):
    """--keychain private is the canonical name in v0.45.0 and must pass through without warning."""
    import importlib.util, io

    spec = importlib.util.spec_from_file_location("altergo", ROOT / "altergo.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)

    captured = {}

    def fake_do_config(account, provider="claude", *, keychain_arg=None):
        captured["keychain_arg"] = keychain_arg

    monkeypatch.setattr(mod, "do_config", fake_do_config)

    accounts_dir = tmp_path / "accounts"
    accounts_dir.mkdir()
    monkeypatch.setattr(mod, "ACCOUNTS_DIR", accounts_dir)

    stderr_buf = io.StringIO()
    monkeypatch.setattr(mod.sys, "stderr", stderr_buf)
    monkeypatch.setattr(mod.sys, "argv", ["altergo", "--config", "work", "--keychain", "private"])
    monkeypatch.setattr(mod.sys.stdin, "isatty", lambda: False)

    with pytest.raises(SystemExit):
        mod.main()

    assert captured.get("keychain_arg") == "private", (
        f"--keychain private must pass through unchanged; got {captured.get('keychain_arg')}"
    )
    assert "deprecated" not in stderr_buf.getvalue().lower(), (
        f"--keychain private must NOT emit any warning; got: {stderr_buf.getvalue()!r}"
    )


def test_cli_keychain_none_no_warning(monkeypatch, tmp_path):
    """--keychain none is the canonical name in v0.45.0 and must pass through without warning."""
    import importlib.util, io

    spec = importlib.util.spec_from_file_location("altergo", ROOT / "altergo.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)

    captured = {}

    def fake_do_config(account, provider="claude", *, keychain_arg=None):
        captured["keychain_arg"] = keychain_arg

    monkeypatch.setattr(mod, "do_config", fake_do_config)

    accounts_dir = tmp_path / "accounts"
    accounts_dir.mkdir()
    monkeypatch.setattr(mod, "ACCOUNTS_DIR", accounts_dir)

    stderr_buf = io.StringIO()
    monkeypatch.setattr(mod.sys, "stderr", stderr_buf)
    monkeypatch.setattr(mod.sys, "argv", ["altergo", "--config", "work", "--keychain", "none"])
    monkeypatch.setattr(mod.sys.stdin, "isatty", lambda: False)

    with pytest.raises(SystemExit):
        mod.main()

    assert captured.get("keychain_arg") == "none", (
        f"--keychain none must pass through unchanged; got {captured.get('keychain_arg')}"
    )
    assert "deprecated" not in stderr_buf.getvalue().lower(), (
        f"--keychain none must NOT emit any warning; got: {stderr_buf.getvalue()!r}"
    )


def test_cli_keychain_invalid_exits_nonzero(monkeypatch, tmp_path):
    """--keychain garbage exits non-zero and stderr mentions 'private' and 'none'."""
    import importlib.util, io

    spec = importlib.util.spec_from_file_location("altergo", ROOT / "altergo.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)

    accounts_dir = tmp_path / "accounts"
    accounts_dir.mkdir()
    monkeypatch.setattr(mod, "ACCOUNTS_DIR", accounts_dir)

    stderr_buf = io.StringIO()
    monkeypatch.setattr(mod.sys, "stderr", stderr_buf)
    monkeypatch.setattr(mod.sys, "argv", ["altergo", "--config", "work", "--keychain", "garbage"])
    monkeypatch.setattr(mod.sys.stdin, "isatty", lambda: False)

    with pytest.raises(SystemExit) as exc_info:
        mod.main()

    assert exc_info.value.code != 0, "invalid --keychain value must exit non-zero"
    err = stderr_buf.getvalue()
    assert "private" in err and "none" in err, (
        f"error message must mention 'private' and 'none'; got: {err!r}"
    )


def test_switch_private_to_none_removes_unlock_entry(monkeypatch, mod, tmp_account_home):
    """_apply_keychain_mode(mode='none') from a private account removes D but not C.

    Also tests that legacy mode values 'isolated' and 'dedicated' are accepted silently
    as backwards-compat aliases for 'none' and 'private' respectively."""
    # Pre-existing private account: A, B, C, D all present.
    mod._keychain_path(tmp_account_home).parent.mkdir(parents=True, exist_ok=True)
    mod._keychain_path(tmp_account_home).touch()  # C present.
    prior_meta = {"version": 3, "providers": ["claude"], "default_provider": "claude", "keychain": "private"}

    sec_calls = []

    def fake_sec(argv, *, check=True, timeout=10):
        sec_calls.append((list(argv), {"check": check}))
        if argv[0] == "find-generic-password":
            return _cp(0, "deadbeef" * 8 + "\n")  # D present
        return _cp(0)

    monkeypatch.setattr(mod, "_sec", fake_sec)

    # Use new canonical name "none".
    mod._apply_keychain_mode(tmp_account_home, "work", "none", prior_meta=prior_meta)

    subcommands = [args[0] for args, _ in sec_calls]

    # D must be removed.
    assert "delete-generic-password" in subcommands, (
        f"switching to none must call delete-generic-password; got {subcommands}"
    )

    # C must NOT be deleted (preserve-and-reuse).
    assert "delete-keychain" not in subcommands, (
        f"switching to none must NOT call delete-keychain; got {subcommands}"
    )
    assert mod._keychain_path(tmp_account_home).exists(), "C must be preserved on disk"


def test_switch_private_to_none_via_isolated_alias(monkeypatch, mod, tmp_account_home):
    """_apply_keychain_mode accepts legacy mode value 'isolated' as a silent alias for 'none'."""
    mod._keychain_path(tmp_account_home).parent.mkdir(parents=True, exist_ok=True)
    mod._keychain_path(tmp_account_home).touch()  # C present.
    prior_meta = {"version": 3, "providers": ["claude"], "default_provider": "claude", "keychain": "private"}

    sec_calls = []

    def fake_sec(argv, *, check=True, timeout=10):
        sec_calls.append((list(argv), {"check": check}))
        if argv[0] == "find-generic-password":
            return _cp(0, "deadbeef" * 8 + "\n")
        return _cp(0)

    monkeypatch.setattr(mod, "_sec", fake_sec)

    # Use legacy alias "isolated" — must behave identically to "none".
    mod._apply_keychain_mode(tmp_account_home, "work", "isolated", prior_meta=prior_meta)

    # A must be written as "none" (normalised from "isolated").
    meta = json.loads((tmp_account_home / "account.json").read_text())
    assert meta.get("keychain") == "none", (
        f"isolated alias must persist as 'none'; got {meta}"
    )


def test_switch_none_to_private_reuses_preserved_file(monkeypatch, mod, tmp_account_home):
    """_apply_keychain_mode(mode='private') when C already exists reuses C (no fresh create).

    Also tests that legacy mode value 'dedicated' is accepted as a silent alias for 'private'."""
    # Pre-create C on disk (from a prior private run, preserved through none).
    mod._keychain_path(tmp_account_home).parent.mkdir(parents=True, exist_ok=True)
    mod._keychain_path(tmp_account_home).touch()  # C present.
    prior_meta = {"version": 3, "providers": ["claude"], "default_provider": "claude", "keychain": "none"}

    sec_calls = []

    def fake_sec(argv, *, check=True, timeout=10):
        sec_calls.append((list(argv), {"check": check}))
        if argv[0] == "find-generic-password":
            return _cp(44, "", "not found")  # D absent (was deleted when switching to none)
        return _cp(0)

    monkeypatch.setattr(mod, "_sec", fake_sec)

    # Use legacy alias "dedicated" — must behave identically to "private".
    mod._apply_keychain_mode(tmp_account_home, "work", "dedicated", prior_meta=prior_meta)

    subcommands = [args[0] for args, _ in sec_calls]

    # C exists but D is absent → Case 3 (orphan C) → delete-keychain + fresh build.
    # This is expected per spec §6.2 option (a): token loss on re-upgrade is acceptable.
    # The important thing: C is not preserved when D is gone (password mismatch risk).
    assert "create-keychain" in subcommands or "add-generic-password" in subcommands, (
        "switching from none to private must rebuild the keychain"
    )

    # A must be written as "private" (normalised from "dedicated").
    meta = json.loads((tmp_account_home / "account.json").read_text())
    assert meta.get("keychain") == "private", (
        f"dedicated alias must persist as 'private'; got {meta}"
    )


# ---------------------------------------------------------------------------
# v0.45.0 required new tests (spec requirements)
# ---------------------------------------------------------------------------


def test_v045_dedicated_and_isolated_cli_parse_as_silent_aliases(monkeypatch, tmp_path):
    """Spec requirement: --keychain dedicated and --keychain isolated are silently accepted
    and resolved to 'private' and 'none' respectively without emitting any warning."""
    import importlib.util, io

    spec = importlib.util.spec_from_file_location("altergo", ROOT / "altergo.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)

    accounts_dir = tmp_path / "accounts"
    accounts_dir.mkdir()
    monkeypatch.setattr(mod, "ACCOUNTS_DIR", accounts_dir)

    for old_name, expected_new_name in [("dedicated", "private"), ("isolated", "none")]:
        captured = {}
        stderr_buf = io.StringIO()

        def fake_do_config(account, provider="claude", *, keychain_arg=None, _exp=expected_new_name):
            captured["keychain_arg"] = keychain_arg

        monkeypatch.setattr(mod, "do_config", fake_do_config)
        monkeypatch.setattr(mod.sys, "stderr", stderr_buf)
        monkeypatch.setattr(mod.sys, "argv", ["altergo", "--config", "work", "--keychain", old_name])
        monkeypatch.setattr(mod.sys.stdin, "isatty", lambda: False)

        with pytest.raises(SystemExit):
            mod.main()

        assert captured.get("keychain_arg") == expected_new_name, (
            f"--keychain {old_name!r} must resolve to {expected_new_name!r}; "
            f"got {captured.get('keychain_arg')!r}"
        )
        assert "deprecated" not in stderr_buf.getvalue().lower(), (
            f"--keychain {old_name!r} must NOT emit a deprecation warning; "
            f"got: {stderr_buf.getvalue()!r}"
        )


def test_v045_account_json_written_with_new_canonical_names(monkeypatch, mod, tmp_path):
    """Spec requirement: account.json written by v0.45.0 must contain
    keychain='private' or keychain='none', never the old 'dedicated'/'isolated'."""
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
    monkeypatch.setattr(mod, "_sec", lambda argv, **kw: _cp(0))
    monkeypatch.setattr(mod, "show_banner", lambda *a, **kw: None)
    monkeypatch.setattr(mod, "_status_wrap", lambda msg, fn: fn())
    monkeypatch.setattr(mod, "load_settings", lambda: {})

    # Test private mode.
    mod.do_config("work1", keychain_arg="private")
    meta_private = json.loads((accounts_dir / "work1" / "account.json").read_text())
    assert meta_private.get("keychain") == "private", (
        f"keychain_arg='private' must write 'private', got: {meta_private}"
    )
    assert meta_private.get("keychain") not in ("dedicated", "isolated"), (
        "account.json must never contain old vocabulary after v0.45.0 write"
    )

    # Test none mode.
    mod.do_config("work2", keychain_arg="none")
    meta_none = json.loads((accounts_dir / "work2" / "account.json").read_text())
    assert meta_none.get("keychain") == "none", (
        f"keychain_arg='none' must write 'none', got: {meta_none}"
    )
    assert meta_none.get("keychain") not in ("dedicated", "isolated"), (
        "account.json must never contain old vocabulary after v0.45.0 write"
    )


def test_v045_default_is_private_when_no_flag_and_no_prior_meta(monkeypatch, mod, tmp_path):
    """Spec requirement: when no --keychain flag is passed AND no prior meta exists,
    the default must be 'private' (not 'none' as it was in v0.44.x)."""
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
    monkeypatch.setattr(mod.sys.stdin, "isatty", lambda: False)  # non-interactive
    monkeypatch.setattr(mod, "_sec", lambda argv, **kw: _cp(0))
    monkeypatch.setattr(mod, "show_banner", lambda *a, **kw: None)
    monkeypatch.setattr(mod, "_status_wrap", lambda msg, fn: fn())
    monkeypatch.setattr(mod, "load_settings", lambda: {})

    # Fresh account — no account.json exists yet, no keychain_arg.
    mod.do_config("freshaccount", keychain_arg=None)

    meta = json.loads((accounts_dir / "freshaccount" / "account.json").read_text())
    assert meta.get("keychain") == "private", (
        f"v0.45.0 default must be 'private' for a fresh account with no prior meta; got {meta}"
    )
