"""Tests for the macOS keychain isolation subsystem in altergo.py.

Covers: SECURITY_CMD, _KC_SERVICE, _KC_GUID, _KC_SUBSERVICE_TYPE, KeychainError,
_sec, _keychain_path, _keychain_prefs_path, _write_keychain_prefs,
_create_account_keychain, _unlock_account_keychain, _delete_account_keychain,
_uses_keychain, _is_keychain_none, _build_alt_env (unlock path),
configure_account (keychain_arg), do_delete_account (keychain teardown).

Vocabulary (canonical):
  - "keychain" : per-account keychain, unlocked at launch — only canonical name
  - "none"     : no keychain; flat-file credentials only
  All legacy aliases (private, dedicated, isolated, system, shared) removed.
  Default: keychain

Patching boundary: _sec only. No real /usr/bin/security calls. Ever.
"""

from __future__ import annotations

import io
import json
import plistlib
import subprocess
import sys
import types
from pathlib import Path

import pytest

import altergo.accounts
import altergo.cli
import altergo.constants
import altergo.keychain
import altergo.persistence
import altergo.runner
import altergo.ui


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
    """Returns altergo.keychain for test patching of keychain-layer functions."""
    return altergo.keychain


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
    """In-memory v3 shape for a keychain-mode account (v0.45.0 name; v0.44.x called it 'dedicated').

    Uses the new canonical name "keychain".  Tests that need the old on-disk value
    "dedicated" should write account.json directly.
    """
    return {
        "version": 3,
        "providers": ["claude"],
        "default_provider": "claude",
        "keychain": "keychain",
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

    Since v0.45.0 the absent key → keychain by default.
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


def test_create_account_keychain_does_not_pin_partition_list(monkeypatch, mod, tmp_account_home):
    """_create_account_keychain must NOT call `set-generic-password-partition-list`.

    That command requires the user's macOS login password (interactive prompt
    from /usr/bin/security itself, with a 10s subprocess timeout that crashes
    on slow input). The trade-off without it: first launch from the desktop
    may show a one-time 'Always Allow' dialog. SSH access uses the OAuth
    token bridge, which bypasses the keychain entirely (and so doesn't need
    the partition pin). See `_build_alt_env`'s `has_oauth_token` skip."""
    sec_calls = []

    def fake_sec(argv, *, check=True, timeout=10):
        sec_calls.append(list(argv))
        if argv[0] == "find-generic-password":
            return _cp(44, "", "The specified item could not be found in the keychain.")
        return _cp(0)

    monkeypatch.setattr(mod, "_sec", fake_sec)

    mod._create_account_keychain(tmp_account_home, "work")

    subcommands = [args[0] for args in sec_calls]
    assert "set-generic-password-partition-list" not in subcommands, (
        "set-generic-password-partition-list must NOT be called — that command "
        "requires the user's macOS login password and crashes on slow input"
    )


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
# _is_keychain_none — truth table
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "meta,expected",
    [
        # Absent key / None / empty → keychain by default → _is_keychain_none=False.
        (None, False),
        ({}, False),
        ({"version": 2, "provider": "claude"}, False),
        # Explicit "none" → True.
        ({"version": 2, "provider": "claude", "keychain": "none"}, True),
        # "keychain" → NOT none.
        ({"keychain": "keychain"}, False),
        # Unrecognized values (legacy or malformed) → fall through to default → False.
        ({"keychain": "private"}, False),
        ({"keychain": "ISOLATED"}, False),
        ({"keychain": "Isolated"}, False),
    ],
)
def test_is_keychain_none_truth_table(mod, meta, expected):
    """The default mode is keychain; _is_keychain_none returns True only for
    the literal 'none' value. Anything else (absent key, unrecognized legacy
    value, wrong case) falls through to keychain mode and the function
    returns False."""
    assert altergo.keychain._is_keychain_none(meta) is expected


# ---------------------------------------------------------------------------
# Gating test 3: _build_alt_env exits 1 on KeychainError
# ---------------------------------------------------------------------------


def test_build_alt_env_exits_1_on_keychain_error(monkeypatch, mod, tmp_path, account_meta_dedicated):
    """When _unlock_account_keychain raises KeychainError, _build_alt_env calls sys.exit(1).
    Only dedicated mode calls _unlock_account_keychain."""
    accounts_dir = tmp_path / "accounts"
    (accounts_dir / "work").mkdir(parents=True)
    monkeypatch.setattr(altergo.constants, "ACCOUNTS_DIR", accounts_dir)
    monkeypatch.setattr(mod.sys, "platform", "darwin")

    monkeypatch.setattr(altergo.runner, "load_account_meta", lambda path: account_meta_dedicated)
    monkeypatch.setattr(
        altergo.runner, "_unlock_account_keychain", lambda home, slug: (_ for _ in ()).throw(mod.KeychainError("test"))
    )

    stderr_buf = io.StringIO()
    monkeypatch.setattr(mod.sys, "stderr", stderr_buf)

    with pytest.raises(SystemExit) as exc_info:
        altergo.runner._build_alt_env("work")

    assert exc_info.value.code == 1


def test_build_alt_env_propagates_keychain_error_message(monkeypatch, mod, tmp_path, account_meta_dedicated):
    """The KeychainError message appears in stderr before sys.exit(1).
    Only dedicated mode calls _unlock_account_keychain."""
    accounts_dir = tmp_path / "accounts"
    (accounts_dir / "work").mkdir(parents=True)
    monkeypatch.setattr(altergo.constants, "ACCOUNTS_DIR", accounts_dir)
    monkeypatch.setattr(mod.sys, "platform", "darwin")

    monkeypatch.setattr(altergo.runner, "load_account_meta", lambda path: account_meta_dedicated)
    monkeypatch.setattr(
        altergo.runner,
        "_unlock_account_keychain",
        lambda home, slug: (_ for _ in ()).throw(mod.KeychainError("login keychain is locked")),
    )

    stderr_buf = io.StringIO()
    monkeypatch.setattr(mod.sys, "stderr", stderr_buf)

    with pytest.raises(SystemExit):
        altergo.runner._build_alt_env("work")

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

    monkeypatch.setattr(altergo.constants, "ACCOUNTS_DIR", accounts_dir)
    monkeypatch.setattr(mod.sys, "platform", "darwin")

    import json as _json

    (account_home / "account.json").write_text(_json.dumps(meta))

    sec_calls = []

    def spy_sec(argv, **kw):
        sec_calls.append(list(argv))
        return _cp(0, "")

    monkeypatch.setattr(mod, "_sec", spy_sec)

    altergo.runner._build_alt_env("work")

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
# Gating test 6b: keychain mode + OAuth token present → skip unlock
#
# When a keychain-mode account has an .oauth-token file, claude reads the
# token from env and never touches the keychain. _build_alt_env must skip
# _unlock_account_keychain in that case — the unlock would either prompt
# for partition-list approval (over SSH: fail) or do unnecessary work.
# This is the load-bearing reason we removed the partition-list pin: with
# OAuth tokens for SSH, the unlock step is bypassable.
# ---------------------------------------------------------------------------


def test_build_alt_env_keychain_mode_with_oauth_token_skips_unlock(
    monkeypatch, mod, tmp_path, account_meta_dedicated
):
    """A keychain-mode account with a per-account .oauth-token file must NOT
    trigger _unlock_account_keychain in _build_alt_env. The token in env is
    sufficient for claude auth and the keychain doesn't need to be touched."""
    accounts_dir = tmp_path / "accounts"
    account_home = accounts_dir / "work"
    account_home.mkdir(parents=True)
    (account_home / "Library" / "Preferences").mkdir(parents=True)
    (account_home / "Library" / "Keychains").mkdir(parents=True)

    # Plant a per-account OAuth token. Should bypass keychain unlock.
    token_file = account_home / ".claude" / ".oauth-token"
    token_file.parent.mkdir(parents=True)
    token_file.write_text("sk-ant-oat01-fake-token-for-test\n")

    monkeypatch.setattr(altergo.constants, "ACCOUNTS_DIR", accounts_dir)
    monkeypatch.setattr(mod.sys, "platform", "darwin")
    monkeypatch.setattr(altergo.runner, "load_account_meta", lambda path: account_meta_dedicated)

    unlock_calls: list[tuple[Path, str]] = []

    def spy_unlock(account_home_arg, slug):
        unlock_calls.append((account_home_arg, slug))

    monkeypatch.setattr(altergo.runner, "_unlock_account_keychain", spy_unlock)
    # Stub _sec so the reconcile pass doesn't shell out.
    monkeypatch.setattr(mod, "_sec", lambda *a, **kw: _cp(0))

    env = altergo.runner._build_alt_env("work")

    assert unlock_calls == [], (
        f"keychain-mode account with OAuth token must skip _unlock_account_keychain; "
        f"got calls: {unlock_calls}"
    )
    assert env.get("CLAUDE_CODE_OAUTH_TOKEN") == "sk-ant-oat01-fake-token-for-test", (
        "the per-account token must still be exported to the subprocess env"
    )


def test_build_alt_env_keychain_mode_with_oauth_token_skips_reconcile(
    monkeypatch, mod, tmp_path, account_meta_dedicated
):
    """A keychain-mode account with a per-account .oauth-token file must NOT
    trigger _reconcile_keychain_state either.

    Regression test for v1.2.1 bug: reconcile ran unconditionally before the
    OAuth-token check, so it tried to read the unlock entry. In non-GUI
    contexts (rover-spawned tmux sessions, SSH) where the partition list
    isn't pinned, this surfaced a "user interaction is not allowed" error
    AND a destructive 'orphaned keychain file found — rebuilding' attempt
    that also failed. With the token in env claude bypasses the keychain
    entirely, so reconcile is wasted work — and worse, surfaces the error."""
    accounts_dir = tmp_path / "accounts"
    account_home = accounts_dir / "work"
    account_home.mkdir(parents=True)
    (account_home / "Library" / "Preferences").mkdir(parents=True)
    (account_home / "Library" / "Keychains").mkdir(parents=True)

    token_file = account_home / ".claude" / ".oauth-token"
    token_file.parent.mkdir(parents=True)
    token_file.write_text("sk-ant-oat01-fake\n")

    monkeypatch.setattr(altergo.constants, "ACCOUNTS_DIR", accounts_dir)
    monkeypatch.setattr(mod.sys, "platform", "darwin")
    monkeypatch.setattr(altergo.runner, "load_account_meta", lambda path: account_meta_dedicated)

    reconcile_calls: list[tuple] = []

    def spy_reconcile(account_home_arg, slug, *, desired):
        reconcile_calls.append((account_home_arg, slug, desired))

    monkeypatch.setattr(altergo.runner, "_reconcile_keychain_state", spy_reconcile)
    monkeypatch.setattr(altergo.runner, "_unlock_account_keychain", lambda *a, **kw: None)

    altergo.runner._build_alt_env("work")

    assert reconcile_calls == [], (
        "keychain-mode account with OAuth token must skip _reconcile_keychain_state — "
        "the token bypasses the keychain entirely, so reconcile is wasted work and "
        "may surface 'user interaction is not allowed' errors in non-GUI contexts"
    )


def test_build_alt_env_none_mode_with_oauth_token_still_reconciles(
    monkeypatch, mod, tmp_path, account_meta_isolated
):
    """The skip is keychain-mode-only. None-mode accounts must still
    reconcile (the locked-keychain file + plist is what makes flat-file
    fallback work). A stray .oauth-token in a none-mode account home must
    not disable reconcile — that mode doesn't depend on the OAuth bridge."""
    accounts_dir = tmp_path / "accounts"
    account_home = accounts_dir / "work"
    account_home.mkdir(parents=True)
    (account_home / "Library" / "Preferences").mkdir(parents=True)
    (account_home / "Library" / "Keychains").mkdir(parents=True)
    # Stray token + none-mode meta: reconcile must still run.
    token_file = account_home / ".claude" / ".oauth-token"
    token_file.parent.mkdir(parents=True)
    token_file.write_text("sk-ant-oat01-fake\n")

    monkeypatch.setattr(altergo.constants, "ACCOUNTS_DIR", accounts_dir)
    monkeypatch.setattr(mod.sys, "platform", "darwin")
    monkeypatch.setattr(altergo.runner, "load_account_meta", lambda path: account_meta_isolated)

    reconcile_calls: list[tuple] = []

    def spy_reconcile(account_home_arg, slug, *, desired):
        reconcile_calls.append((account_home_arg, slug, desired))

    monkeypatch.setattr(altergo.runner, "_reconcile_keychain_state", spy_reconcile)
    monkeypatch.setattr(altergo.runner, "_unlock_account_keychain", lambda *a, **kw: None)

    altergo.runner._build_alt_env("work")

    assert len(reconcile_calls) == 1, (
        f"none-mode reconcile must still run regardless of token presence; "
        f"got: {reconcile_calls}"
    )


def test_build_alt_env_keychain_mode_without_oauth_token_does_unlock(
    monkeypatch, mod, tmp_path, account_meta_dedicated
):
    """The complement: when keychain mode is set AND no OAuth token file is
    present, _unlock_account_keychain MUST run (otherwise claude can't read
    its credentials at the desk)."""
    accounts_dir = tmp_path / "accounts"
    account_home = accounts_dir / "work"
    account_home.mkdir(parents=True)
    (account_home / "Library" / "Preferences").mkdir(parents=True)
    (account_home / "Library" / "Keychains").mkdir(parents=True)
    # No .oauth-token file planted.

    monkeypatch.setattr(altergo.constants, "ACCOUNTS_DIR", accounts_dir)
    monkeypatch.setattr(mod.sys, "platform", "darwin")
    monkeypatch.setattr(altergo.runner, "load_account_meta", lambda path: account_meta_dedicated)

    unlock_calls: list[tuple[Path, str]] = []

    def spy_unlock(account_home_arg, slug):
        unlock_calls.append((account_home_arg, slug))

    monkeypatch.setattr(altergo.runner, "_unlock_account_keychain", spy_unlock)
    monkeypatch.setattr(mod, "_sec", lambda *a, **kw: _cp(0))

    altergo.runner._build_alt_env("work")

    assert len(unlock_calls) == 1, (
        f"keychain-mode account without OAuth token must call _unlock_account_keychain; "
        f"got calls: {unlock_calls}"
    )
    assert unlock_calls[0] == (account_home, "work")


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

    altergo.runner._build_alt_env("native")

    assert sec_calls == []


# ---------------------------------------------------------------------------
# Gating test 4: configure_account non-TTY none mode (Invariant 9)
# ---------------------------------------------------------------------------


def _create_main_claude_sources_for_mod(mod, main_claude: Path):
    """Create the source dirs/files in MAIN_CLAUDE that configure_account() will symlink."""
    for name in altergo.constants.SYMLINK_DIRS:
        (main_claude / name).mkdir(parents=True, exist_ok=True)
    for name in altergo.constants.SYMLINK_FILES:
        (main_claude / name).touch()


def test_configure_account_non_tty_none_writes_meta_and_plist(monkeypatch, mod, tmp_path):
    """configure_account with keychain_arg='none' on non-TTY writes meta with keychain=none
    and creates the plist file."""
    main_home = tmp_path / "main_home"
    main_claude = main_home / ".claude"
    accounts_dir = tmp_path / "accounts"

    main_home.mkdir(parents=True)
    main_claude.mkdir(parents=True)
    accounts_dir.mkdir(parents=True)
    _create_main_claude_sources_for_mod(mod, main_claude)

    monkeypatch.setattr(altergo.constants, "MAIN_HOME", main_home)
    monkeypatch.setattr(altergo.constants, "MAIN_CLAUDE", main_claude)
    monkeypatch.setattr(altergo.constants, "ACCOUNTS_DIR", accounts_dir)
    monkeypatch.setattr(altergo.constants, "SETTINGS_FILE", tmp_path / "settings.json")
    monkeypatch.setattr(mod.sys, "platform", "darwin")
    monkeypatch.setattr(mod.sys.stdin, "isatty", lambda: False)

    # _sec always succeeds.
    monkeypatch.setattr(mod, "_sec", lambda argv, **kw: _cp(0))

    monkeypatch.setattr(altergo.ui, "show_banner", lambda *a, **kw: None)
    monkeypatch.setattr(altergo.ui, "_status_wrap", lambda msg, fn: fn())
    monkeypatch.setattr(altergo.accounts, "load_settings", lambda: {})

    altergo.accounts.configure_account("work", keychain_arg="none")

    account_home = accounts_dir / "work"
    meta_path = account_home / "account.json"
    assert meta_path.exists(), "account.json must exist"
    meta = json.loads(meta_path.read_text())
    assert meta.get("keychain") == "none", f"Expected keychain=none, got {meta}"

    plist_path = account_home / "Library" / "Preferences" / "com.apple.security.plist"
    assert plist_path.exists(), "plist must exist for none-mode account"


def test_configure_account_non_tty_none_sec_is_called(monkeypatch, mod, tmp_path):
    """configure_account with keychain_arg='none' on non-TTY calls _sec (creates the keychain)."""
    main_home = tmp_path / "main_home"
    main_claude = main_home / ".claude"
    accounts_dir = tmp_path / "accounts"

    main_home.mkdir(parents=True)
    main_claude.mkdir(parents=True)
    accounts_dir.mkdir(parents=True)
    _create_main_claude_sources_for_mod(mod, main_claude)

    monkeypatch.setattr(altergo.constants, "MAIN_HOME", main_home)
    monkeypatch.setattr(altergo.constants, "MAIN_CLAUDE", main_claude)
    monkeypatch.setattr(altergo.constants, "ACCOUNTS_DIR", accounts_dir)
    monkeypatch.setattr(altergo.constants, "SETTINGS_FILE", tmp_path / "settings.json")
    monkeypatch.setattr(mod.sys, "platform", "darwin")
    monkeypatch.setattr(mod.sys.stdin, "isatty", lambda: False)

    sec_calls = []
    monkeypatch.setattr(mod, "_sec", lambda argv, **kw: (sec_calls.append(argv), _cp(0))[-1])

    monkeypatch.setattr(altergo.ui, "show_banner", lambda *a, **kw: None)
    monkeypatch.setattr(altergo.ui, "_status_wrap", lambda msg, fn: fn())
    monkeypatch.setattr(altergo.accounts, "load_settings", lambda: {})

    altergo.accounts.configure_account("work", keychain_arg="none")

    assert len(sec_calls) > 0, "_sec must be called when keychain_arg='none'"


# ---------------------------------------------------------------------------
# Gating test 5: configure_account non-TTY no flag (Invariant 10)
# ---------------------------------------------------------------------------


def test_configure_account_non_tty_no_flag_creates_keychain_mode(monkeypatch, mod, tmp_path):
    """configure_account with keychain_arg=None on non-TTY defaults to keychain mode (v0.45.0 default).
    Keychain mode creates plist (B), keychain file (C), and plants the unlock entry (D).
    meta must have keychain='keychain'."""
    main_home = tmp_path / "main_home"
    main_claude = main_home / ".claude"
    accounts_dir = tmp_path / "accounts"

    main_home.mkdir(parents=True)
    main_claude.mkdir(parents=True)
    accounts_dir.mkdir(parents=True)
    _create_main_claude_sources_for_mod(mod, main_claude)

    monkeypatch.setattr(altergo.constants, "MAIN_HOME", main_home)
    monkeypatch.setattr(altergo.constants, "MAIN_CLAUDE", main_claude)
    monkeypatch.setattr(altergo.constants, "ACCOUNTS_DIR", accounts_dir)
    monkeypatch.setattr(altergo.constants, "SETTINGS_FILE", tmp_path / "settings.json")
    monkeypatch.setattr(mod.sys, "platform", "darwin")
    monkeypatch.setattr(mod.sys.stdin, "isatty", lambda: False)

    sec_calls = []
    monkeypatch.setattr(mod, "_sec", lambda argv, **kw: (sec_calls.append(list(argv)), _cp(0))[-1])

    monkeypatch.setattr(altergo.ui, "show_banner", lambda *a, **kw: None)
    monkeypatch.setattr(altergo.ui, "_status_wrap", lambda msg, fn: fn())
    monkeypatch.setattr(altergo.accounts, "load_settings", lambda: {})

    altergo.accounts.configure_account("work", keychain_arg=None)

    account_home = accounts_dir / "work"
    meta_path = account_home / "account.json"
    assert meta_path.exists()
    meta = json.loads(meta_path.read_text())
    assert meta.get("keychain") == "keychain", f"v0.45.0 default is 'keychain'; got {meta}"

    # keychain mode: plist must exist (routes Security.framework to per-account keychain).
    plist_path = account_home / "Library" / "Preferences" / "com.apple.security.plist"
    assert plist_path.exists(), "plist must exist for keychain mode (required for Security.framework routing)"

    # keychain mode: add-generic-password MUST be called (unlock entry planted).
    add_calls = [args for args in sec_calls if args[0] == "add-generic-password"]
    assert add_calls != [], f"keychain mode must call add-generic-password; sec_calls={sec_calls}"


def test_configure_account_non_tty_no_flag_does_not_hang(monkeypatch, mod, tmp_path):
    """configure_account with keychain_arg=None on non-TTY returns without blocking on input()."""
    import builtins

    main_home = tmp_path / "main_home"
    main_claude = main_home / ".claude"
    accounts_dir = tmp_path / "accounts"

    main_home.mkdir(parents=True)
    main_claude.mkdir(parents=True)
    accounts_dir.mkdir(parents=True)
    _create_main_claude_sources_for_mod(mod, main_claude)

    monkeypatch.setattr(altergo.constants, "MAIN_HOME", main_home)
    monkeypatch.setattr(altergo.constants, "MAIN_CLAUDE", main_claude)
    monkeypatch.setattr(altergo.constants, "ACCOUNTS_DIR", accounts_dir)
    monkeypatch.setattr(altergo.constants, "SETTINGS_FILE", tmp_path / "settings.json")
    monkeypatch.setattr(mod.sys, "platform", "darwin")
    monkeypatch.setattr(mod.sys.stdin, "isatty", lambda: False)

    # If input() is called, this raises to fail the test immediately.
    def boom(*a, **kw):
        raise AssertionError("input() must not be called on non-TTY")

    monkeypatch.setattr(builtins, "input", boom)
    monkeypatch.setattr(mod, "_sec", lambda argv, **kw: _cp(0))
    monkeypatch.setattr(altergo.ui, "show_banner", lambda *a, **kw: None)
    monkeypatch.setattr(altergo.ui, "_status_wrap", lambda msg, fn: fn())
    monkeypatch.setattr(altergo.accounts, "load_settings", lambda: {})

    # Should complete without raising.
    altergo.accounts.configure_account("work", keychain_arg=None)


# ---------------------------------------------------------------------------
# Gating test 8: sys.platform != "darwin" gate
# ---------------------------------------------------------------------------


def test_configure_account_non_darwin_no_sec_no_plist(monkeypatch, mod, tmp_path):
    """On non-darwin platforms, configure_account with keychain_arg='none' does not
    call _sec and does not create Library/Keychains/. Documents current behavior."""
    main_home = tmp_path / "main_home"
    main_claude = main_home / ".claude"
    accounts_dir = tmp_path / "accounts"

    main_home.mkdir(parents=True)
    main_claude.mkdir(parents=True)
    accounts_dir.mkdir(parents=True)
    _create_main_claude_sources_for_mod(mod, main_claude)

    monkeypatch.setattr(altergo.constants, "MAIN_HOME", main_home)
    monkeypatch.setattr(altergo.constants, "MAIN_CLAUDE", main_claude)
    monkeypatch.setattr(altergo.constants, "ACCOUNTS_DIR", accounts_dir)
    monkeypatch.setattr(altergo.constants, "SETTINGS_FILE", tmp_path / "settings.json")
    monkeypatch.setattr(mod.sys, "platform", "linux")
    monkeypatch.setattr(mod.sys.stdin, "isatty", lambda: False)

    sec_calls = []
    monkeypatch.setattr(mod, "_sec", lambda argv, **kw: (sec_calls.append(argv), _cp(0))[-1])

    monkeypatch.setattr(altergo.ui, "show_banner", lambda *a, **kw: None)
    monkeypatch.setattr(altergo.ui, "_status_wrap", lambda msg, fn: fn())
    monkeypatch.setattr(altergo.accounts, "load_settings", lambda: {})

    altergo.accounts.configure_account("work", keychain_arg="none")

    account_home = accounts_dir / "work"
    keychains_dir = account_home / "Library" / "Keychains"

    assert sec_calls == [], f"_sec must not be called on linux, got {sec_calls}"
    assert not keychains_dir.exists(), "Library/Keychains/ must not be created on linux"


def test_build_alt_env_non_darwin_never_calls_sec(monkeypatch, mod, tmp_path, account_meta_dedicated):
    """_build_alt_env on non-darwin never calls _sec even for dedicated meta."""
    accounts_dir = tmp_path / "accounts"
    (accounts_dir / "work").mkdir(parents=True)
    monkeypatch.setattr(altergo.constants, "ACCOUNTS_DIR", accounts_dir)
    monkeypatch.setattr(mod.sys, "platform", "linux")
    monkeypatch.setattr(altergo.runner, "load_account_meta", lambda path: account_meta_dedicated)

    sec_calls = []
    monkeypatch.setattr(mod, "_sec", lambda argv, **kw: (sec_calls.append(argv), _cp(0))[-1])

    altergo.runner._build_alt_env("work")

    assert sec_calls == []


# ---------------------------------------------------------------------------
# Re-config preserves isolation when meta already has keychain=isolated
# ---------------------------------------------------------------------------


def test_configure_account_reconfig_preserves_none(monkeypatch, mod, tmp_path):
    """Re-running configure_account on an account that already has keychain='none' keeps none mode
    when keychain_arg is None on non-TTY.  On non-TTY without keychain_arg, if the existing
    meta says 'none', configure_account preserves 'none' (user opted out of keychain mode)."""
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

    monkeypatch.setattr(altergo.constants, "MAIN_HOME", main_home)
    monkeypatch.setattr(altergo.constants, "MAIN_CLAUDE", main_claude)
    monkeypatch.setattr(altergo.constants, "ACCOUNTS_DIR", accounts_dir)
    monkeypatch.setattr(altergo.constants, "SETTINGS_FILE", tmp_path / "settings.json")
    monkeypatch.setattr(mod.sys, "platform", "darwin")
    monkeypatch.setattr(mod.sys.stdin, "isatty", lambda: False)

    def fake_sec(argv, *, check=True, timeout=10):
        if argv[0] == "find-generic-password":
            return _cp(44, "", "The specified item could not be found.")  # D absent
        return _cp(0)

    monkeypatch.setattr(mod, "_sec", fake_sec)
    monkeypatch.setattr(altergo.ui, "show_banner", lambda *a, **kw: None)
    monkeypatch.setattr(altergo.ui, "_status_wrap", lambda msg, fn: fn())
    monkeypatch.setattr(altergo.accounts, "load_settings", lambda: {})

    altergo.accounts.configure_account("work", keychain_arg=None)

    meta = json.loads((account_home / "account.json").read_text())
    assert meta.get("keychain") == "none", (
        f"Re-config with keychain_arg=None on non-TTY must preserve 'none' mode; got {meta}"
    )


# ---------------------------------------------------------------------------
# Interactive re-config: existing accounts must always re-prompt
#
# The prior behaviour silently preserved a 'none' account on re-config — users
# couldn't switch to keychain without passing --keychain explicitly. The new
# behaviour: in interactive (TTY) mode, --config always re-prompts so the user
# can change their mind, with the current mode as the default answer.
# ---------------------------------------------------------------------------


def _setup_interactive_reconfig_env(monkeypatch, mod, tmp_path, *, current_keychain: str):
    """Stand up an account with the given keychain mode in account.json + a TTY stdin."""
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
    (account_home / "account.json").write_text(
        json.dumps({"version": 3, "providers": ["claude"], "default_provider": "claude", "keychain": current_keychain})
    )

    monkeypatch.setattr(altergo.constants, "MAIN_HOME", main_home)
    monkeypatch.setattr(altergo.constants, "MAIN_CLAUDE", main_claude)
    monkeypatch.setattr(altergo.constants, "ACCOUNTS_DIR", accounts_dir)
    monkeypatch.setattr(altergo.constants, "SETTINGS_FILE", tmp_path / "settings.json")
    monkeypatch.setattr(mod.sys, "platform", "darwin")
    monkeypatch.setattr(mod.sys.stdin, "isatty", lambda: True)
    monkeypatch.setattr(mod, "_sec", lambda *a, **kw: _cp(0))
    monkeypatch.setattr(altergo.ui, "show_banner", lambda *a, **kw: None)
    monkeypatch.setattr(altergo.ui, "_status_wrap", lambda msg, fn: fn())
    monkeypatch.setattr(altergo.accounts, "load_settings", lambda: {})
    # Suppress the SSH-token offer; we're testing the keychain-mode prompt only.
    monkeypatch.setattr(altergo.accounts, "_maybe_offer_oauth_token_setup", lambda *a, **kw: False)
    return account_home


def test_interactive_reconfig_existing_none_account_prompts_user(monkeypatch, mod, tmp_path):
    """The fix: an existing 'none' account that runs --config in interactive mode
    must SEE the keychain prompt — previously it was silently preserved.

    We capture the prompt text via the input() argument rather than capsys
    because monkeypatching `builtins.input` with a lambda never writes the
    prompt to stdout (Python writes it before reading from stdin, but the
    lambda short-circuits the whole function)."""
    _setup_interactive_reconfig_env(monkeypatch, mod, tmp_path, current_keychain="none")

    captured_prompts: list[str] = []

    def fake_input(prompt=""):
        captured_prompts.append(prompt)
        return ""  # Enter → accept default

    monkeypatch.setattr("builtins.input", fake_input)

    altergo.accounts.configure_account("work", "claude")

    # The keychain-mode prompt must have been issued.
    assert any("Switch to keychain mode?" in p for p in captured_prompts), (
        f"for an existing 'none' account, prompt must offer to switch to "
        f"keychain (with default=stay). got prompts: {captured_prompts!r}"
    )


def test_interactive_reconfig_existing_none_can_switch_to_keychain(monkeypatch, mod, tmp_path):
    """User explicitly types 'y' on a 'none' account → switches to keychain mode."""
    account_home = _setup_interactive_reconfig_env(monkeypatch, mod, tmp_path, current_keychain="none")
    monkeypatch.setattr("builtins.input", lambda prompt="": "y")

    altergo.accounts.configure_account("work", "claude")

    meta = json.loads((account_home / "account.json").read_text())
    assert meta.get("keychain") == "keychain", (
        f"interactive re-config of none + 'y' answer must switch to keychain mode; got {meta}"
    )


def test_interactive_reconfig_existing_none_default_preserves_none(monkeypatch, mod, tmp_path):
    """User accepts default (Enter) on a 'none' account → stays none.
    The default-answer convention for [y/N] is the highlighted-uppercase letter."""
    account_home = _setup_interactive_reconfig_env(monkeypatch, mod, tmp_path, current_keychain="none")
    monkeypatch.setattr("builtins.input", lambda prompt="": "")

    altergo.accounts.configure_account("work", "claude")

    meta = json.loads((account_home / "account.json").read_text())
    assert meta.get("keychain") == "none", (
        f"empty answer on a 'none' account must preserve none (default); got {meta}"
    )


def test_interactive_reconfig_existing_keychain_default_preserves_keychain(monkeypatch, mod, tmp_path):
    """User accepts default (Enter) on a 'keychain' account → stays in keychain mode."""
    account_home = _setup_interactive_reconfig_env(monkeypatch, mod, tmp_path, current_keychain="keychain")
    monkeypatch.setattr("builtins.input", lambda prompt="": "")

    altergo.accounts.configure_account("work", "claude")

    meta = json.loads((account_home / "account.json").read_text())
    assert meta.get("keychain") == "keychain", (
        f"empty answer on a 'keychain' account must preserve keychain (default); got {meta}"
    )


def test_interactive_reconfig_existing_keychain_can_switch_to_none(monkeypatch, mod, tmp_path):
    """User explicitly types 'n' on a 'keychain' account → switches to none."""
    account_home = _setup_interactive_reconfig_env(monkeypatch, mod, tmp_path, current_keychain="keychain")
    monkeypatch.setattr("builtins.input", lambda prompt="": "n")

    altergo.accounts.configure_account("work", "claude")

    meta = json.loads((account_home / "account.json").read_text())
    assert meta.get("keychain") == "none", (
        f"interactive re-config of keychain + 'n' answer must switch to none; got {meta}"
    )


def test_interactive_keychain_prompt_includes_ssh_context_and_link(monkeypatch, mod, tmp_path, capsys):
    """The keychain-mode prompt must explain BOTH modes' actual SSH behaviour
    accurately and link to docs/ssh-auth.md — so the user picks with full
    context, in one prompt.

    Truth being asserted:
      - keychain: at-rest encryption; one-time 'Always Allow' dialog at the
        desk on first launch (no upfront macOS password prompt during
        --config); OAuth token bridge offered for SSH.
      - none: macOS popup IS expected (locked keychain causes a write to
        prompt for a password that doesn't exist); user must click Cancel
        and never 'Reset To Defaults'."""
    _setup_interactive_reconfig_env(monkeypatch, mod, tmp_path, current_keychain="keychain")
    monkeypatch.setattr("builtins.input", lambda prompt="": "")

    altergo.accounts.configure_account("work", "claude")

    out = capsys.readouterr().out
    # keychain-mode reality: encrypted at rest, one-time desk Always-Allow
    # dialog (NOT an upfront password prompt), OAuth bridge for SSH.
    assert "encrypted at rest" in out, "keychain mode must mention at-rest encryption"
    assert "Always Allow" in out, (
        "keychain mode must mention the one-time desk 'Always Allow' dialog "
        "so users aren't surprised the first time it appears"
    )
    assert "OAuth token bridge" in out, "keychain mode must reference the SSH OAuth bridge"
    # none-mode reality: popup DOES happen, user clicks Cancel.
    assert "flat files" in out, "none mode must mention flat-file storage"
    assert "Allow access" in out and "Cancel" in out, (
        "none mode must warn that macOS will pop the 'Allow access' dialog "
        "and that the user must click Cancel"
    )
    assert "Reset To Defaults" in out, (
        "none mode must warn against the 'Reset To Defaults' button "
        "(destroys real login keychain — unrelated, very destructive)"
    )
    # link to long-form docs
    assert "github.com/thepixelabs/altergo/blob/main/docs/ssh-auth.md" in out, (
        "must link to the long-form SSH auth doc"
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

    monkeypatch.setattr(altergo.constants, "MAIN_HOME", main_home)
    monkeypatch.setattr(altergo.constants, "MAIN_CLAUDE", main_claude)
    monkeypatch.setattr(altergo.constants, "ACCOUNTS_DIR", accounts_dir)
    monkeypatch.setattr(altergo.constants, "SETTINGS_FILE", tmp_path / "settings.json")
    monkeypatch.setattr(mod.sys, "platform", "darwin")
    monkeypatch.setattr(altergo.ui, "show_banner", lambda *a, **kw: None)

    return account_home


def test_do_delete_account_calls_delete_keychain_for_isolated(monkeypatch, mod, tmp_path, account_meta_isolated):
    """do_delete_account calls _delete_account_keychain when the keychain file (C) is present on disk."""
    account_home = _setup_delete_account_env(monkeypatch, mod, tmp_path, account_meta_isolated)

    # Place the keychain file (C) on disk so the file-presence gate fires.
    kc_path = account_home / "Library" / "Keychains" / "login.keychain-db"
    kc_path.touch()

    delete_calls = []
    monkeypatch.setattr(altergo.accounts, "_delete_account_keychain", lambda home, slug: delete_calls.append((home, slug)))

    # _sec needed for the find-generic-password probe in do_delete_account.
    monkeypatch.setattr(altergo.accounts, "_sec", lambda argv, **kw: _cp(0, "deadbeef" * 8))

    altergo.accounts.do_delete_account("work")

    assert len(delete_calls) == 1
    assert delete_calls[0][1] == "work"


def test_do_delete_account_no_artifacts_skips_keychain_teardown(monkeypatch, mod, tmp_path, account_meta_legacy):
    """do_delete_account does NOT call _delete_account_keychain when B, C, and D are all absent.
    The gate is artifact presence — not meta.  find-generic-password probe returns non-zero (D absent)."""
    account_home = _setup_delete_account_env(monkeypatch, mod, tmp_path, account_meta_legacy)

    delete_calls = []
    monkeypatch.setattr(altergo.accounts, "_delete_account_keychain", lambda home, slug: delete_calls.append((home, slug)))

    # Spy on _sec so we can assert the find-generic-password probe was actually called.
    sec_calls = []

    def spy_sec(argv, *, check=True, timeout=10):
        sec_calls.append(list(argv))
        if argv[0] == "find-generic-password":
            # D absent — keychain entry does not exist.
            return _cp(44, "", "The specified item could not be found in the keychain.")
        return _cp(0)

    monkeypatch.setattr(altergo.accounts, "_sec", spy_sec)

    altergo.accounts.do_delete_account("work")

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

    monkeypatch.setattr(altergo.accounts, "_delete_account_keychain", failing_delete)
    # do_delete_account probes for D via _sec before calling _delete_account_keychain;
    # stub _sec so the probe succeeds on CI runners without /usr/bin/security (Linux).
    monkeypatch.setattr(altergo.accounts, "_sec", lambda argv, **kw: _cp(0, "deadbeef\n"))

    # Should not raise; should return True (account home is removed).
    result = altergo.accounts.do_delete_account("work")
    assert result is True
    assert not account_home.exists(), "account_home must be removed even after keychain error"


def test_do_delete_account_sec_calls_use_check_false(monkeypatch, mod, tmp_path, account_meta_isolated):
    """_delete_account_keychain's internal _sec calls use check=False (tested via real implementation)."""
    account_home = _setup_delete_account_env(monkeypatch, mod, tmp_path, account_meta_isolated)

    sec_calls = []

    def spy_sec(argv, *, check=True, timeout=10):
        sec_calls.append((list(argv), check))
        return _cp(0)

    monkeypatch.setattr(altergo.accounts, "_sec", spy_sec)
    monkeypatch.setattr(mod, "_sec", spy_sec)

    altergo.accounts.do_delete_account("work")

    # Every _sec call made during delete must use check=False.
    delete_sec_calls = [
        (args, chk) for args, chk in sec_calls if args[0] in ("delete-keychain", "delete-generic-password")
    ]
    assert len(delete_sec_calls) > 0
    for args, chk in delete_sec_calls:
        assert chk is False, f"{args[0]} must use check=False"


# ---------------------------------------------------------------------------
# Fix D — End-to-end: configure_account → _build_alt_env (seam test)
# ---------------------------------------------------------------------------


def _setup_configure_account_env(monkeypatch, mod, tmp_path):
    """Shared environment wiring for configure_account integration tests."""
    main_home = tmp_path / "main_home"
    main_claude = main_home / ".claude"
    accounts_dir = tmp_path / "accounts"

    main_home.mkdir(parents=True)
    main_claude.mkdir(parents=True)
    accounts_dir.mkdir(parents=True)
    _create_main_claude_sources_for_mod(mod, main_claude)

    monkeypatch.setattr(altergo.constants, "MAIN_HOME", main_home)
    monkeypatch.setattr(altergo.constants, "MAIN_CLAUDE", main_claude)
    monkeypatch.setattr(altergo.constants, "ACCOUNTS_DIR", accounts_dir)
    monkeypatch.setattr(altergo.constants, "SETTINGS_FILE", tmp_path / "settings.json")
    monkeypatch.setattr(mod.sys, "platform", "darwin")
    monkeypatch.setattr(mod.sys.stdin, "isatty", lambda: False)
    monkeypatch.setattr(altergo.ui, "show_banner", lambda *a, **kw: None)
    monkeypatch.setattr(altergo.ui, "_status_wrap", lambda msg, fn: fn())
    monkeypatch.setattr(altergo.accounts, "load_settings", lambda: {})

    return accounts_dir


def test_configure_account_then_build_alt_env_calls_find_generic_password(monkeypatch, mod, tmp_path):
    """configure_account('work', keychain_arg='none') followed by _build_alt_env('work') must
    result in _sec being called with find-generic-password during the _build_alt_env phase.
    Catches seam bugs where configure_account writes a meta key that _build_alt_env doesn't read."""
    accounts_dir = _setup_configure_account_env(monkeypatch, mod, tmp_path)

    # Phase 1: configure_account — spy on _sec, always succeed.
    config_sec_calls = []

    def fake_sec_config(argv, *, check=True, timeout=10):
        config_sec_calls.append(list(argv))
        if argv[0] == "find-generic-password":
            return _cp(0, "deadbeef" * 8 + "\n")
        return _cp(0)

    monkeypatch.setattr(mod, "_sec", fake_sec_config)
    altergo.accounts.configure_account("work", keychain_arg="none")

    # Phase 2: _build_alt_env — replace spy to capture only calls from this phase.
    build_sec_calls = []

    def fake_sec_build(argv, *, check=True, timeout=10):
        build_sec_calls.append(list(argv))
        if argv[0] == "find-generic-password":
            return _cp(0, "deadbeef" * 8 + "\n")
        return _cp(0)

    monkeypatch.setattr(mod, "_sec", fake_sec_build)
    altergo.runner._build_alt_env("work")

    find_calls = [args for args in build_sec_calls if args[0] == "find-generic-password"]
    assert len(find_calls) >= 1, (
        "_build_alt_env must call find-generic-password to unlock the isolated keychain; "
        f"_sec calls were: {build_sec_calls}"
    )


# ---------------------------------------------------------------------------
# Fix E — Regression: existing shared account re-config leaves meta unchanged
# ---------------------------------------------------------------------------


def test_configure_account_existing_system_account_normalizes_to_keychain(monkeypatch, mod, tmp_path):
    """Given an account.json with no 'keychain' key (legacy system/shared account),
    calling configure_account(..., keychain_arg=None) on non-TTY must save meta with
    keychain='keychain' (the new default since v0.45.0) and must plant an unlock entry (D).
    Keychain mode creates plist (B), keychain file (C), and stores unlock entry (D)."""
    accounts_dir = _setup_configure_account_env(monkeypatch, mod, tmp_path)
    account_home = accounts_dir / "work"
    account_home.mkdir(parents=True)
    (account_home / "Library" / "Preferences").mkdir(parents=True)
    (account_home / "Library" / "Keychains").mkdir(parents=True)

    # Pre-existing legacy system account — no 'keychain' key.
    existing_meta = {"version": 2, "provider": "claude", "created": "2025-01-01T00:00:00"}
    (account_home / "account.json").write_text(json.dumps(existing_meta))

    sec_calls = []
    monkeypatch.setattr(mod, "_sec", lambda argv, **kw: (sec_calls.append(list(argv)), _cp(0))[-1])

    altergo.accounts.configure_account("work", keychain_arg=None)

    meta = json.loads((account_home / "account.json").read_text())
    assert meta.get("keychain") == "keychain", f"v0.45.0 default is 'keychain'; got {meta}"

    # keychain mode MUST plant unlock entry (D).
    add_calls = [args for args in sec_calls if args[0] == "add-generic-password"]
    assert add_calls != [], f"keychain mode must call add-generic-password; sec_calls={sec_calls}"


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
# Fix G — configure_account downgrade: keychain → none preserve-and-reuse
# ---------------------------------------------------------------------------


def test_configure_account_keychain_to_none_removes_unlock_entry(monkeypatch, mod, tmp_path):
    """configure_account('work', keychain_arg='none') on a keychain-mode account must:
    (a) call delete-generic-password to remove the unlock entry D (zero-footprint promise),
    (b) NOT call delete-keychain (C preserved for re-enable — preserve-and-reuse),
    (c) save meta with keychain='none'."""
    accounts_dir = _setup_configure_account_env(monkeypatch, mod, tmp_path)
    account_home = accounts_dir / "work"
    (account_home / "Library" / "Preferences").mkdir(parents=True)
    (account_home / "Library" / "Keychains").mkdir(parents=True)

    # Pre-existing keychain account: A=keychain, B+C present.
    existing_meta = {"version": 2, "provider": "claude", "keychain": "keychain", "created": "2025-01-01T00:00:00"}
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

    altergo.accounts.configure_account("work", keychain_arg="none")

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
    """State #1 crash-recovery: A=keychain + B/C/D all absent (process crashed after
    writing meta but before creating B/C/D).
    _reconcile_keychain_state(desired=None) must detect the missing B and trigger a rebuild.

    v0.46.0: legacy on-disk value "dedicated" is coerced to "keychain" with a warning;
    after rebuild A is persisted with the canonical name "keychain"."""
    # A=keychain on disk (canonical v0.46.0 value); B/C/D all absent (crash scenario).
    (tmp_account_home / "account.json").write_text(json.dumps({"keychain": "keychain"}))
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
        f"State #1 keychain crash-recovery: reconciler must rebuild when B absent; got {subcommands}"
    )

    # A must be updated to 'keychain' after rebuild (new canonical name).
    meta = json.loads((tmp_account_home / "account.json").read_text())
    assert meta.get("keychain") == "keychain", f"State #1 repair: A must be 'keychain' after rebuild; got {meta}"


# ---------------------------------------------------------------------------
# P0 — _reconcile_keychain_state desired=None: State #13 wrong-password drift
# ---------------------------------------------------------------------------


def test_reconcile_desired_none_state13_wrong_password_drift_rebuilds(monkeypatch, mod, tmp_account_home):
    """State #13: B+C+D all present but unlock probe fails (password mismatch drift).
    _reconcile_keychain_state(desired=None) must trigger _create_account_keychain
    (rebuild) and write A='keychain'."""
    # Set up B, C present on disk; A=keychain (v0.45.0 canonical name).
    (tmp_account_home / "account.json").write_text(json.dumps({"keychain": "keychain"}))
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

    # A must be written as 'keychain' after successful rebuild (new canonical name).
    meta = json.loads((tmp_account_home / "account.json").read_text())
    assert meta.get("keychain") == "keychain", (
        f"State #13 rebuild: A must be written as 'keychain' after repair; got {meta}"
    )


# ---------------------------------------------------------------------------
# P0 — _reconcile_keychain_state desired=None: no-op fast path
# ---------------------------------------------------------------------------


def test_reconcile_desired_none_none_b_absent_writes_plist_no_sec(monkeypatch, mod, tmp_account_home):
    """desired=None with A=none and B absent: reconciler writes plist B using pure Python
    (_write_keychain_prefs — no _sec call), and persists A='none' to disk.
    No build/unlock/delete _sec calls occur."""
    # A=none on disk (canonical v0.46.0 value); B absent.
    (tmp_account_home / "account.json").write_text(json.dumps({"keychain": "none"}))
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

    # Meta must persist 'none'.
    meta = json.loads((tmp_account_home / "account.json").read_text())
    assert meta.get("keychain") == "none", f"Reconciler must persist 'none'; got {meta}"


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
    monkeypatch.setattr(altergo.constants, "ACCOUNTS_DIR", accounts_dir)
    monkeypatch.setattr(mod.sys, "platform", "darwin")

    # Isolated meta: _uses_keychain returns False → no unlock.
    monkeypatch.setattr(altergo.runner, "load_account_meta", lambda path: account_meta_isolated)

    unlock_calls = []
    monkeypatch.setattr(altergo.runner, "_unlock_account_keychain", lambda home, slug: unlock_calls.append((home, slug)))

    # Reconciler must not crash and must not call unlock either.
    monkeypatch.setattr(altergo.runner, "_reconcile_keychain_state", lambda *a, **kw: None)

    env = altergo.runner._build_alt_env("work")

    assert unlock_calls == [], "_unlock_account_keychain must NOT be called for isolated accounts"
    assert "HOME" in env, "env must have HOME set"


def test_build_alt_env_dedicated_mode_unlocks(monkeypatch, mod, tmp_path, account_meta_dedicated):
    """_build_alt_env with dedicated account calls _unlock_account_keychain exactly once."""
    accounts_dir = tmp_path / "accounts"
    account_home = accounts_dir / "work"
    account_home.mkdir(parents=True)
    monkeypatch.setattr(altergo.constants, "ACCOUNTS_DIR", accounts_dir)
    monkeypatch.setattr(mod.sys, "platform", "darwin")

    monkeypatch.setattr(altergo.runner, "load_account_meta", lambda path: account_meta_dedicated)
    monkeypatch.setattr(altergo.runner, "_reconcile_keychain_state", lambda *a, **kw: None)

    unlock_calls = []
    monkeypatch.setattr(altergo.runner, "_unlock_account_keychain", lambda home, slug: unlock_calls.append((home, slug)))

    altergo.runner._build_alt_env("work")

    assert len(unlock_calls) == 1, f"dedicated mode must call _unlock_account_keychain once; got {unlock_calls}"


def test_migration_system_to_keychain_on_load_with_warning(tmp_account_home, capsys):
    """v0.46.0: load_account_meta with keychain='system' on disk returns in-memory
    keychain='keychain' (all legacy values → 'keychain') AND emits a warning to stderr.
    On-disk file is unchanged."""
    import json as _json

    (tmp_account_home / "account.json").write_text(
        _json.dumps({"version": 3, "providers": ["claude"], "default_provider": "claude", "keychain": "system"})
    )

    meta = altergo.persistence.load_account_meta(tmp_account_home)
    assert meta.get("keychain") == "keychain", f"system → keychain (v0.46.0); got {meta}"

    captured = capsys.readouterr()
    assert "legacy keychain mode" in captured.err, (
        f"Expected legacy-mode warning in stderr; got: {captured.err!r}"
    )
    assert "system" in captured.err

    # On-disk must be unchanged (migration is in-memory only).
    raw = _json.loads((tmp_account_home / "account.json").read_text())
    assert raw.get("keychain") == "system", "on-disk value must not be changed by load alone"


def test_migration_shared_to_keychain_on_load_with_warning(tmp_account_home, capsys):
    """v0.46.0: load_account_meta with keychain='shared' on disk returns in-memory
    keychain='keychain' AND emits a warning to stderr."""
    import json as _json

    (tmp_account_home / "account.json").write_text(
        _json.dumps({"version": 3, "providers": ["claude"], "default_provider": "claude", "keychain": "shared"})
    )

    meta = altergo.persistence.load_account_meta(tmp_account_home)
    assert meta.get("keychain") == "keychain", f"shared → keychain (v0.46.0); got {meta}"

    captured = capsys.readouterr()
    assert "legacy keychain mode" in captured.err
    assert "shared" in captured.err

    raw = _json.loads((tmp_account_home / "account.json").read_text())
    assert raw.get("keychain") == "shared", "on-disk value must not be changed by load alone"


def test_migration_old_isolated_to_keychain_on_load_with_warning(tmp_account_home, capsys):
    """v0.46.0: load_account_meta with keychain='isolated' on disk returns in-memory
    keychain='keychain' AND emits a warning. (Was 'none' in v0.45.0; removed alias in v0.46.0.)"""
    import json as _json

    (tmp_account_home / "account.json").write_text(
        _json.dumps({"version": 3, "providers": ["claude"], "default_provider": "claude", "keychain": "isolated"})
    )

    meta = altergo.persistence.load_account_meta(tmp_account_home)
    assert meta.get("keychain") == "keychain", f"isolated → keychain (v0.46.0); got {meta}"

    captured = capsys.readouterr()
    assert "legacy keychain mode" in captured.err
    assert "isolated" in captured.err

    # On-disk must be unchanged (migration is in-memory only).
    raw = _json.loads((tmp_account_home / "account.json").read_text())
    assert raw.get("keychain") == "isolated", "on-disk value must not be changed by load alone"


def test_migration_old_dedicated_to_keychain_on_load_with_warning(tmp_account_home, capsys):
    """v0.46.0: load_account_meta with keychain='dedicated' on disk returns in-memory
    keychain='keychain' AND emits a warning. (Was silent in v0.45.0; removed alias in v0.46.0.)"""
    import json as _json

    (tmp_account_home / "account.json").write_text(
        _json.dumps({"version": 3, "providers": ["claude"], "default_provider": "claude", "keychain": "dedicated"})
    )

    meta = altergo.persistence.load_account_meta(tmp_account_home)
    assert meta.get("keychain") == "keychain", f"dedicated → keychain (v0.46.0); got {meta}"

    captured = capsys.readouterr()
    assert "legacy keychain mode" in captured.err
    assert "dedicated" in captured.err

    # On-disk must be unchanged (migration is in-memory only).
    raw = _json.loads((tmp_account_home / "account.json").read_text())
    assert raw.get("keychain") == "dedicated", "on-disk value must not be changed by load alone"


def test_migration_legacy_no_keychain_key_defaults_to_keychain(tmp_account_home):
    """load_account_meta with no keychain key → _uses_keychain returns True.
    Default mode is `keychain` (per-account macOS keychain) since v0.45.0."""
    import json as _json

    (tmp_account_home / "account.json").write_text(
        _json.dumps({"version": 3, "providers": ["claude"], "default_provider": "claude"})
    )

    meta = altergo.persistence.load_account_meta(tmp_account_home)
    assert altergo.keychain._uses_keychain(meta) is True, "no keychain key → keychain mode (default)"
    assert altergo.keychain._is_keychain_none(meta) is False, "no keychain key → not none"


def test_reconcile_persists_migrated_key_on_launch(monkeypatch, tmp_account_home):
    """v0.46.0: _reconcile_keychain_state(desired=None) with 'system' on disk
    coerces to 'keychain' (with warning) and persists 'keychain' to disk.
    (v0.45.0 mapped system → none; v0.46.0 maps all legacy values → keychain.)"""
    import json as _json
    mod = altergo.keychain

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
    # v0.46.0: all legacy values coerce to 'keychain'; reconciler persists 'keychain'.
    assert raw.get("keychain") == "keychain", (
        f"reconciler must persist 'keychain' for legacy 'system' on disk; got {raw}"
    )


def test_reconcile_preserves_keychain_mode_on_launch_with_prior_state(monkeypatch, tmp_account_home):
    """_reconcile_keychain_state(desired=None) with 'keychain' account + B+C+D consistent:
    leaves everything unchanged, no files deleted."""
    import json as _json
    mod = altergo.keychain

    # Write canonical 'keychain' on disk.
    (tmp_account_home / "account.json").write_text(
        _json.dumps({"version": 3, "providers": ["claude"], "default_provider": "claude", "keychain": "keychain"})
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
    # A must remain 'keychain'.
    raw = _json.loads((tmp_account_home / "account.json").read_text())
    assert raw.get("keychain") == "keychain", f"A must remain 'keychain'; got {raw}"


@pytest.mark.parametrize("old_name", ["system", "shared", "dedicated", "isolated"])
def test_cli_keychain_legacy_alias_rejected(monkeypatch, tmp_path, old_name):
    """v0.46.0: all legacy --keychain aliases (system, shared, dedicated, isolated) are
    rejected with a non-zero exit and an error message naming the valid choices."""

    accounts_dir = tmp_path / "accounts"
    accounts_dir.mkdir()
    monkeypatch.setattr(altergo.constants, "ACCOUNTS_DIR", accounts_dir)

    stderr_buf = io.StringIO()
    monkeypatch.setattr(sys, "stderr", stderr_buf)
    monkeypatch.setattr(sys, "argv", ["altergo", "--config", "work", "--keychain", old_name])
    monkeypatch.setattr(sys.stdin, "isatty", lambda: False)

    with pytest.raises(SystemExit) as exc_info:
        altergo.cli.main()

    assert exc_info.value.code != 0, f"--keychain {old_name!r} must exit non-zero"
    err = stderr_buf.getvalue()
    assert "keychain" in err and "none" in err, (
        f"error for --keychain {old_name!r} must mention 'keychain' and 'none'; got: {err!r}"
    )


def test_cli_keychain_keychain_no_warning(monkeypatch, tmp_path):
    """--keychain keychain is the canonical name in v0.45.0 and must pass through without warning."""

    captured = {}

    def fake_configure_account(account, provider="claude", *, keychain_arg=None):
        captured["keychain_arg"] = keychain_arg

    monkeypatch.setattr(altergo.cli, "configure_account", fake_configure_account)

    accounts_dir = tmp_path / "accounts"
    accounts_dir.mkdir()
    monkeypatch.setattr(altergo.constants, "ACCOUNTS_DIR", accounts_dir)

    stderr_buf = io.StringIO()
    monkeypatch.setattr(sys, "stderr", stderr_buf)
    monkeypatch.setattr(sys, "argv", ["altergo", "--config", "work", "--keychain", "keychain"])
    monkeypatch.setattr(sys.stdin, "isatty", lambda: False)

    with pytest.raises(SystemExit):
        altergo.cli.main()

    assert captured.get("keychain_arg") == "keychain", (
        f"--keychain keychain must pass through unchanged; got {captured.get('keychain_arg')}"
    )
    assert "deprecated" not in stderr_buf.getvalue().lower(), (
        f"--keychain keychain must NOT emit any warning; got: {stderr_buf.getvalue()!r}"
    )


def test_cli_keychain_none_no_warning(monkeypatch, tmp_path):
    """--keychain none is the canonical name in v0.45.0 and must pass through without warning."""

    captured = {}

    def fake_configure_account(account, provider="claude", *, keychain_arg=None):
        captured["keychain_arg"] = keychain_arg

    monkeypatch.setattr(altergo.cli, "configure_account", fake_configure_account)

    accounts_dir = tmp_path / "accounts"
    accounts_dir.mkdir()
    monkeypatch.setattr(altergo.constants, "ACCOUNTS_DIR", accounts_dir)

    stderr_buf = io.StringIO()
    monkeypatch.setattr(sys, "stderr", stderr_buf)
    monkeypatch.setattr(sys, "argv", ["altergo", "--config", "work", "--keychain", "none"])
    monkeypatch.setattr(sys.stdin, "isatty", lambda: False)

    with pytest.raises(SystemExit):
        altergo.cli.main()

    assert captured.get("keychain_arg") == "none", (
        f"--keychain none must pass through unchanged; got {captured.get('keychain_arg')}"
    )
    assert "deprecated" not in stderr_buf.getvalue().lower(), (
        f"--keychain none must NOT emit any warning; got: {stderr_buf.getvalue()!r}"
    )


def test_cli_keychain_invalid_exits_nonzero(monkeypatch, tmp_path):
    """--keychain garbage exits non-zero and stderr mentions 'keychain' and 'none'."""

    accounts_dir = tmp_path / "accounts"
    accounts_dir.mkdir()
    monkeypatch.setattr(altergo.constants, "ACCOUNTS_DIR", accounts_dir)

    stderr_buf = io.StringIO()
    monkeypatch.setattr(sys, "stderr", stderr_buf)
    monkeypatch.setattr(sys, "argv", ["altergo", "--config", "work", "--keychain", "garbage"])
    monkeypatch.setattr(sys.stdin, "isatty", lambda: False)

    with pytest.raises(SystemExit) as exc_info:
        altergo.cli.main()

    assert exc_info.value.code != 0, "invalid --keychain value must exit non-zero"
    err = stderr_buf.getvalue()
    assert "keychain" in err and "none" in err, (
        f"error message must mention 'keychain' and 'none'; got: {err!r}"
    )


def test_switch_keychain_to_none_removes_unlock_entry(monkeypatch, mod, tmp_account_home):
    """_apply_keychain_mode(mode='none') from a keychain-mode account removes D but not C."""
    # Pre-existing keychain account: A, B, C, D all present.
    mod._keychain_path(tmp_account_home).parent.mkdir(parents=True, exist_ok=True)
    mod._keychain_path(tmp_account_home).touch()  # C present.
    prior_meta = {"version": 3, "providers": ["claude"], "default_provider": "claude", "keychain": "keychain"}

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


def test_switch_none_to_keychain_reuses_preserved_file(monkeypatch, mod, tmp_account_home):
    """_apply_keychain_mode(mode='keychain') when C already exists (from a prior keychain run
    preserved through none) rebuilds the keychain since D is absent."""
    # Pre-create C on disk (from a prior keychain run, preserved through none).
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

    mod._apply_keychain_mode(tmp_account_home, "work", "keychain", prior_meta=prior_meta)

    subcommands = [args[0] for args, _ in sec_calls]

    # C exists but D is absent → Case 3 (orphan C) → delete-keychain + fresh build.
    assert "create-keychain" in subcommands or "add-generic-password" in subcommands, (
        "switching from none to keychain must rebuild the keychain"
    )

    # A must be written as "keychain".
    meta = json.loads((tmp_account_home / "account.json").read_text())
    assert meta.get("keychain") == "keychain", (
        f"mode='keychain' must persist as 'keychain'; got {meta}"
    )


# ---------------------------------------------------------------------------
# v0.46.0 required new tests (spec requirements)
# ---------------------------------------------------------------------------


def test_v046_legacy_cli_aliases_all_rejected(monkeypatch, tmp_path):
    """v0.46.0 spec requirement: --keychain dedicated, isolated, system, and shared are
    all rejected with a non-zero exit — no silent normalisation, no configure_account call."""

    accounts_dir = tmp_path / "accounts"
    accounts_dir.mkdir()
    monkeypatch.setattr(altergo.constants, "ACCOUNTS_DIR", accounts_dir)

    for old_name in ("dedicated", "isolated", "system", "shared"):
        configure_account_called = []
        stderr_buf = io.StringIO()

        def fake_configure_account(account, provider="claude", *, keychain_arg=None):
            configure_account_called.append(keychain_arg)

        monkeypatch.setattr(altergo.cli, "configure_account", fake_configure_account)
        monkeypatch.setattr(sys, "stderr", stderr_buf)
        monkeypatch.setattr(sys, "argv", ["altergo", "--config", "work", "--keychain", old_name])
        monkeypatch.setattr(sys.stdin, "isatty", lambda: False)

        with pytest.raises(SystemExit) as exc_info:
            altergo.cli.main()

        assert exc_info.value.code != 0, (
            f"--keychain {old_name!r} must exit non-zero in v0.46.0"
        )
        assert not configure_account_called, (
            f"configure_account must NOT be called when --keychain {old_name!r} is given"
        )
        err = stderr_buf.getvalue()
        assert "keychain" in err and "none" in err, (
            f"error for --keychain {old_name!r} must name valid choices; got: {err!r}"
        )


def test_v046_account_json_written_with_canonical_names(monkeypatch, mod, tmp_path):
    """Spec requirement: account.json written by v0.46.0 must contain
    keychain='keychain' or keychain='none', never any legacy value."""
    main_home = tmp_path / "main_home"
    main_claude = main_home / ".claude"
    accounts_dir = tmp_path / "accounts"

    main_home.mkdir(parents=True)
    main_claude.mkdir(parents=True)
    accounts_dir.mkdir(parents=True)
    _create_main_claude_sources_for_mod(mod, main_claude)

    monkeypatch.setattr(altergo.constants, "MAIN_HOME", main_home)
    monkeypatch.setattr(altergo.constants, "MAIN_CLAUDE", main_claude)
    monkeypatch.setattr(altergo.constants, "ACCOUNTS_DIR", accounts_dir)
    monkeypatch.setattr(altergo.constants, "SETTINGS_FILE", tmp_path / "settings.json")
    monkeypatch.setattr(mod.sys, "platform", "darwin")
    monkeypatch.setattr(mod.sys.stdin, "isatty", lambda: False)
    monkeypatch.setattr(mod, "_sec", lambda argv, **kw: _cp(0))
    monkeypatch.setattr(altergo.ui, "show_banner", lambda *a, **kw: None)
    monkeypatch.setattr(altergo.ui, "_status_wrap", lambda msg, fn: fn())
    monkeypatch.setattr(altergo.accounts, "load_settings", lambda: {})

    # Test keychain mode.
    altergo.accounts.configure_account("work1", keychain_arg="keychain")
    meta_keychain = json.loads((accounts_dir / "work1" / "account.json").read_text())
    assert meta_keychain.get("keychain") == "keychain", (
        f"keychain_arg='keychain' must write 'keychain', got: {meta_keychain}"
    )
    assert meta_keychain.get("keychain") not in ("dedicated", "isolated"), (
        "account.json must never contain old vocabulary after v0.45.0 write"
    )

    # Test none mode.
    altergo.accounts.configure_account("work2", keychain_arg="none")
    meta_none = json.loads((accounts_dir / "work2" / "account.json").read_text())
    assert meta_none.get("keychain") == "none", (
        f"keychain_arg='none' must write 'none', got: {meta_none}"
    )
    assert meta_none.get("keychain") not in ("dedicated", "isolated"), (
        "account.json must never contain old vocabulary after v0.45.0 write"
    )


def test_v046_default_is_keychain_when_no_flag_and_no_prior_meta(monkeypatch, mod, tmp_path):
    """Spec requirement: when no --keychain flag is passed AND no prior meta exists,
    the default must be 'keychain'."""
    main_home = tmp_path / "main_home"
    main_claude = main_home / ".claude"
    accounts_dir = tmp_path / "accounts"

    main_home.mkdir(parents=True)
    main_claude.mkdir(parents=True)
    accounts_dir.mkdir(parents=True)
    _create_main_claude_sources_for_mod(mod, main_claude)

    monkeypatch.setattr(altergo.constants, "MAIN_HOME", main_home)
    monkeypatch.setattr(altergo.constants, "MAIN_CLAUDE", main_claude)
    monkeypatch.setattr(altergo.constants, "ACCOUNTS_DIR", accounts_dir)
    monkeypatch.setattr(altergo.constants, "SETTINGS_FILE", tmp_path / "settings.json")
    monkeypatch.setattr(mod.sys, "platform", "darwin")
    monkeypatch.setattr(mod.sys.stdin, "isatty", lambda: False)  # non-interactive
    monkeypatch.setattr(mod, "_sec", lambda argv, **kw: _cp(0))
    monkeypatch.setattr(altergo.ui, "show_banner", lambda *a, **kw: None)
    monkeypatch.setattr(altergo.ui, "_status_wrap", lambda msg, fn: fn())
    monkeypatch.setattr(altergo.accounts, "load_settings", lambda: {})

    # Fresh account — no account.json exists yet, no keychain_arg.
    altergo.accounts.configure_account("freshaccount", keychain_arg=None)

    meta = json.loads((accounts_dir / "freshaccount" / "account.json").read_text())
    assert meta.get("keychain") == "keychain", (
        f"v0.45.0 default must be 'keychain' for a fresh account with no prior meta; got {meta}"
    )


# ---------------------------------------------------------------------------
# Per-account OAuth token plumbing
#
# claude reads CLAUDE_CODE_OAUTH_TOKEN from env in preference to any keychain
# entry, which is the only auth path that survives SSH (where keychain access
# is gated behind a GUI prompt). Storing the token per-account in a flat file
# under <account_home>/.claude/.oauth-token lets each account carry its own
# Anthropic identity, and forcing the env var per-subprocess prevents a
# global shell export from cross-contaminating accounts.
#
# These tests cover the four-cell behaviour matrix:
#                    │ token file present │ token file absent
#   ────────────────┼────────────────────┼────────────────────
#   native          │ env := file token  │ inherited env preserved
#   non-native      │ env := file token  │ env var stripped
# ---------------------------------------------------------------------------


def test_oauth_token_path_native_uses_main_home(monkeypatch, mod, tmp_path):
    """Native account's canonical token path is $MAIN_HOME/.claude/.oauth-token."""
    monkeypatch.setattr(altergo.constants, "MAIN_HOME", tmp_path)
    p = mod._oauth_token_path("native")
    assert p == tmp_path / ".claude" / ".oauth-token"


def test_oauth_token_path_non_native_uses_account_home(monkeypatch, mod, tmp_path):
    """Non-native account's token path lives under <account_home>/.claude/.oauth-token."""
    accounts_dir = tmp_path / "accounts"
    (accounts_dir / "work").mkdir(parents=True)
    monkeypatch.setattr(altergo.constants, "ACCOUNTS_DIR", accounts_dir)
    p = mod._oauth_token_path("work", account_home=accounts_dir / "work")
    assert p == accounts_dir / "work" / ".claude" / ".oauth-token"


def test_oauth_token_path_resolves_account_home_when_omitted(monkeypatch, mod, tmp_path):
    """When account_home is not passed, _oauth_token_path resolves it via resolve_account."""
    accounts_dir = tmp_path / "accounts"
    (accounts_dir / "work").mkdir(parents=True)
    monkeypatch.setattr(altergo.constants, "ACCOUNTS_DIR", accounts_dir)
    p = mod._oauth_token_path("work")
    assert p == accounts_dir / "work" / ".claude" / ".oauth-token"


def test_load_oauth_token_returns_none_when_missing(monkeypatch, mod, tmp_path):
    """No file → None (callers fall back to keychain or strip the env var)."""
    monkeypatch.setattr(altergo.constants, "MAIN_HOME", tmp_path)
    assert mod._load_oauth_token("native") is None


def test_load_oauth_token_returns_none_when_empty(monkeypatch, mod, tmp_path):
    """Empty file is treated as no token (avoid setting env to '')."""
    monkeypatch.setattr(altergo.constants, "MAIN_HOME", tmp_path)
    token_file = tmp_path / ".claude" / ".oauth-token"
    token_file.parent.mkdir(parents=True)
    token_file.write_text("")
    assert mod._load_oauth_token("native") is None


def test_load_oauth_token_strips_whitespace(monkeypatch, mod, tmp_path):
    """Trailing newline (from `claude setup-token | tee`) must not poison the token."""
    monkeypatch.setattr(altergo.constants, "MAIN_HOME", tmp_path)
    token_file = tmp_path / ".claude" / ".oauth-token"
    token_file.parent.mkdir(parents=True)
    token_file.write_text("sk-ant-oat01-fake\n  \n")
    assert mod._load_oauth_token("native") == "sk-ant-oat01-fake"


def test_load_oauth_token_whitespace_only_returns_none(monkeypatch, mod, tmp_path):
    """A file that's non-empty on disk but strips to '' must yield None,
    not an empty-string env value (which would silently break claude auth
    in confusing ways)."""
    monkeypatch.setattr(altergo.constants, "MAIN_HOME", tmp_path)
    token_file = tmp_path / ".claude" / ".oauth-token"
    token_file.parent.mkdir(parents=True)
    token_file.write_text("   \n\t  \n")
    assert mod._load_oauth_token("native") is None


def test_load_oauth_token_oserror_falls_through(monkeypatch, mod, tmp_path):
    """If read_text raises OSError mid-read (permissions, FS error, racy
    delete), _load_oauth_token must skip that candidate and try the next —
    not propagate the exception up to crash _build_alt_env at launch time."""
    monkeypatch.setattr(altergo.constants, "MAIN_HOME", tmp_path)
    canonical = tmp_path / ".claude" / ".oauth-token"
    legacy = tmp_path / ".claude" / "rover-native-token"
    canonical.parent.mkdir(parents=True)
    canonical.write_text("sk-ant-oat01-canonical\n")
    legacy.write_text("sk-ant-oat01-legacy\n")

    real_read = mod.Path.read_text
    def flaky_read(self, *args, **kwargs):
        if self == canonical:
            raise OSError("simulated permissions failure on canonical")
        return real_read(self, *args, **kwargs)
    monkeypatch.setattr(mod.Path, "read_text", flaky_read)

    # Canonical path raises → _load_oauth_token must continue to legacy fallback.
    assert mod._load_oauth_token("native") == "sk-ant-oat01-legacy"


def test_load_oauth_token_native_falls_back_to_legacy_rover_path(monkeypatch, mod, tmp_path):
    """Users who set up the rover-native-token before the per-account model
    existed should not have to migrate their file manually."""
    monkeypatch.setattr(altergo.constants, "MAIN_HOME", tmp_path)
    legacy = tmp_path / ".claude" / "rover-native-token"
    legacy.parent.mkdir(parents=True)
    legacy.write_text("sk-ant-oat01-legacy\n")
    # Canonical path absent; legacy path used as fallback.
    assert mod._load_oauth_token("native") == "sk-ant-oat01-legacy"


def test_load_oauth_token_native_canonical_takes_precedence_over_legacy(monkeypatch, mod, tmp_path):
    """When both files exist, the canonical .oauth-token wins (legacy is fallback only)."""
    monkeypatch.setattr(altergo.constants, "MAIN_HOME", tmp_path)
    canonical = tmp_path / ".claude" / ".oauth-token"
    legacy = tmp_path / ".claude" / "rover-native-token"
    canonical.parent.mkdir(parents=True)
    canonical.write_text("sk-ant-oat01-canonical\n")
    legacy.write_text("sk-ant-oat01-legacy\n")
    assert mod._load_oauth_token("native") == "sk-ant-oat01-canonical"


def test_load_oauth_token_non_native_does_not_check_legacy_path(monkeypatch, mod, tmp_path):
    """The rover-native-token fallback is native-only — non-native accounts
    must NEVER read from MAIN_HOME's legacy path (would re-introduce the
    cross-account token leak this whole mechanism is designed to prevent)."""
    monkeypatch.setattr(altergo.constants, "MAIN_HOME", tmp_path)
    legacy = tmp_path / ".claude" / "rover-native-token"
    legacy.parent.mkdir(parents=True)
    legacy.write_text("sk-ant-oat01-native-token\n")
    accounts_dir = tmp_path / ".altergo" / "accounts"
    (accounts_dir / "work").mkdir(parents=True)
    monkeypatch.setattr(altergo.constants, "ACCOUNTS_DIR", accounts_dir)
    # No per-account .oauth-token file → must return None, ignoring native legacy.
    assert mod._load_oauth_token("work", account_home=accounts_dir / "work") is None


def test_apply_oauth_token_sets_env_when_file_present(monkeypatch, mod, tmp_path):
    """File present → env gets that token (overrides any inherited value)."""
    monkeypatch.setattr(altergo.constants, "MAIN_HOME", tmp_path)
    token_file = tmp_path / ".claude" / ".oauth-token"
    token_file.parent.mkdir(parents=True)
    token_file.write_text("sk-ant-oat01-fromfile\n")

    env = {"CLAUDE_CODE_OAUTH_TOKEN": "sk-ant-oat01-stale-shell-export"}
    mod._apply_oauth_token_to_env(env, "native")
    assert env["CLAUDE_CODE_OAUTH_TOKEN"] == "sk-ant-oat01-fromfile"


def test_apply_oauth_token_native_no_file_preserves_inherited_env(monkeypatch, mod, tmp_path):
    """Native + no token file → leave whatever the shell exported alone.

    Native runs with the real $HOME, so a shell-level CLAUDE_CODE_OAUTH_TOKEN
    is the user's intentional choice (e.g. .zshrc on SSH login) and altergo
    must honour it."""
    monkeypatch.setattr(altergo.constants, "MAIN_HOME", tmp_path)
    env = {"CLAUDE_CODE_OAUTH_TOKEN": "sk-ant-oat01-from-zshrc"}
    mod._apply_oauth_token_to_env(env, "native")
    assert env["CLAUDE_CODE_OAUTH_TOKEN"] == "sk-ant-oat01-from-zshrc"


def test_apply_oauth_token_non_native_no_file_strips_env(monkeypatch, mod, tmp_path):
    """Non-native + no token file → strip the env var.

    This is the cross-account-leak fix: without this strip, a global token
    set in the user's .zshrc (intended for native) would silently auth claude
    as the wrong identity under a non-native account's $HOME, corrupting that
    account's credential state on every launch."""
    accounts_dir = tmp_path / "accounts"
    (accounts_dir / "work").mkdir(parents=True)
    monkeypatch.setattr(altergo.constants, "ACCOUNTS_DIR", accounts_dir)

    env = {"CLAUDE_CODE_OAUTH_TOKEN": "sk-ant-oat01-leaked-from-shell"}
    mod._apply_oauth_token_to_env(env, "work", account_home=accounts_dir / "work")
    assert "CLAUDE_CODE_OAUTH_TOKEN" not in env


def test_apply_oauth_token_non_native_no_file_no_env_is_noop(monkeypatch, mod, tmp_path):
    """Stripping a non-existent key must not raise — pop with default."""
    accounts_dir = tmp_path / "accounts"
    (accounts_dir / "work").mkdir(parents=True)
    monkeypatch.setattr(altergo.constants, "ACCOUNTS_DIR", accounts_dir)

    env = {}  # no CLAUDE_CODE_OAUTH_TOKEN to begin with
    mod._apply_oauth_token_to_env(env, "work", account_home=accounts_dir / "work")
    assert "CLAUDE_CODE_OAUTH_TOKEN" not in env


def test_apply_oauth_token_non_native_with_file_overrides_inherited(monkeypatch, mod, tmp_path):
    """Per-account file beats whatever the user's shell exported. This is the
    case that lets a user have one CLAUDE_CODE_OAUTH_TOKEN in .zshrc for
    native, while also using altergo work-acct with a *different* identity
    stored under work-acct's home."""
    accounts_dir = tmp_path / "accounts"
    (accounts_dir / "work").mkdir(parents=True)
    monkeypatch.setattr(altergo.constants, "ACCOUNTS_DIR", accounts_dir)
    token_file = accounts_dir / "work" / ".claude" / ".oauth-token"
    token_file.parent.mkdir(parents=True)
    token_file.write_text("sk-ant-oat01-work-identity\n")

    env = {"CLAUDE_CODE_OAUTH_TOKEN": "sk-ant-oat01-native-from-zshrc"}
    mod._apply_oauth_token_to_env(env, "work", account_home=accounts_dir / "work")
    assert env["CLAUDE_CODE_OAUTH_TOKEN"] == "sk-ant-oat01-work-identity"


def test_build_alt_env_native_no_file_preserves_shell_token(monkeypatch, mod, tmp_path):
    """Integration: _build_alt_env('native') with no token file forwards
    CLAUDE_CODE_OAUTH_TOKEN from os.environ unchanged."""
    monkeypatch.setattr(altergo.constants, "MAIN_HOME", tmp_path)
    monkeypatch.setenv("CLAUDE_CODE_OAUTH_TOKEN", "sk-ant-oat01-shell-only")

    env = altergo.runner._build_alt_env("native")
    assert env["CLAUDE_CODE_OAUTH_TOKEN"] == "sk-ant-oat01-shell-only"


def test_build_alt_env_native_with_file_overrides_shell_token(monkeypatch, mod, tmp_path):
    """Integration: _build_alt_env('native') with a token file overrides
    whatever the shell had exported."""
    monkeypatch.setattr(altergo.constants, "MAIN_HOME", tmp_path)
    monkeypatch.setenv("CLAUDE_CODE_OAUTH_TOKEN", "sk-ant-oat01-shell-export")
    token_file = tmp_path / ".claude" / ".oauth-token"
    token_file.parent.mkdir(parents=True)
    token_file.write_text("sk-ant-oat01-fromfile\n")

    env = altergo.runner._build_alt_env("native")
    assert env["CLAUDE_CODE_OAUTH_TOKEN"] == "sk-ant-oat01-fromfile"


def test_build_alt_env_non_native_strips_shell_token_when_no_file(monkeypatch, mod, tmp_path, account_meta_isolated):
    """Integration regression: a CLAUDE_CODE_OAUTH_TOKEN exported by the user's
    shell must NOT propagate into a non-native subprocess unless that account
    has its own token file."""
    accounts_dir = tmp_path / "accounts"
    account_home = accounts_dir / "work"
    account_home.mkdir(parents=True)
    (account_home / "Library" / "Preferences").mkdir(parents=True)
    (account_home / "Library" / "Keychains").mkdir(parents=True)
    (account_home / "account.json").write_text(json.dumps(account_meta_isolated))
    monkeypatch.setattr(altergo.constants, "ACCOUNTS_DIR", accounts_dir)
    monkeypatch.setattr(mod.sys, "platform", "darwin")
    monkeypatch.setenv("CLAUDE_CODE_OAUTH_TOKEN", "sk-ant-oat01-shell-leak")
    # Stub _sec so the keychain reconcile doesn't shell out.
    monkeypatch.setattr(mod, "_sec", lambda *a, **kw: subprocess.CompletedProcess(args=[], returncode=0, stdout="", stderr=""))

    env = altergo.runner._build_alt_env("work")
    assert "CLAUDE_CODE_OAUTH_TOKEN" not in env, (
        "non-native subprocess must NOT inherit a shell-level CLAUDE_CODE_OAUTH_TOKEN "
        "when no per-account token file exists — that would cross-contaminate identities"
    )


def test_build_alt_env_non_native_with_file_uses_account_token(monkeypatch, mod, tmp_path, account_meta_isolated):
    """Integration: a per-account .oauth-token file is read and exported."""
    accounts_dir = tmp_path / "accounts"
    account_home = accounts_dir / "work"
    account_home.mkdir(parents=True)
    (account_home / "Library" / "Preferences").mkdir(parents=True)
    (account_home / "Library" / "Keychains").mkdir(parents=True)
    (account_home / "account.json").write_text(json.dumps(account_meta_isolated))
    token_file = account_home / ".claude" / ".oauth-token"
    token_file.parent.mkdir(parents=True)
    token_file.write_text("sk-ant-oat01-work-identity\n")

    monkeypatch.setattr(altergo.constants, "ACCOUNTS_DIR", accounts_dir)
    monkeypatch.setattr(mod.sys, "platform", "darwin")
    monkeypatch.setenv("CLAUDE_CODE_OAUTH_TOKEN", "sk-ant-oat01-shell-other-identity")
    monkeypatch.setattr(mod, "_sec", lambda *a, **kw: subprocess.CompletedProcess(args=[], returncode=0, stdout="", stderr=""))

    env = altergo.runner._build_alt_env("work")
    assert env["CLAUDE_CODE_OAUTH_TOKEN"] == "sk-ant-oat01-work-identity"


# ---------------------------------------------------------------------------
# OAuth token setup flow (interactive + CLI)
# ---------------------------------------------------------------------------


# -- _write_oauth_token_file -------------------------------------------------


def test_write_oauth_token_file_native_uses_main_home(monkeypatch, mod, tmp_path):
    """For the native account, the token is written to $MAIN_HOME/.claude/.oauth-token."""
    monkeypatch.setattr(altergo.constants, "MAIN_HOME", tmp_path)
    path = mod._write_oauth_token_file("native", None, "sk-ant-oat01-abc")
    assert path == tmp_path / ".claude" / ".oauth-token"
    assert path.read_text(encoding="utf-8") == "sk-ant-oat01-abc"


def test_write_oauth_token_file_non_native_uses_account_home(mod, tmp_path):
    """For a named account, the token is written to <account_home>/.claude/.oauth-token."""
    account_home = tmp_path / "accounts" / "work"
    account_home.mkdir(parents=True)
    path = mod._write_oauth_token_file("work", account_home, "sk-ant-oat01-xyz")
    assert path == account_home / ".claude" / ".oauth-token"
    assert path.read_text(encoding="utf-8") == "sk-ant-oat01-xyz"


def test_write_oauth_token_file_creates_parent_dir(mod, tmp_path):
    """The .claude/ parent directory is created if it does not yet exist."""
    account_home = tmp_path / "fresh"
    account_home.mkdir()
    # .claude/ is deliberately absent
    path = mod._write_oauth_token_file("work", account_home, "sk-ant-oat01-new")
    assert path.parent.is_dir()
    assert path.exists()


def test_write_oauth_token_file_mode_is_0600(mod, tmp_path):
    """Token file is created with mode 0600 (owner read/write only)."""
    account_home = tmp_path / "sectest"
    account_home.mkdir()
    path = mod._write_oauth_token_file("work", account_home, "sk-ant-oat01-sec")
    assert (path.stat().st_mode & 0o777) == 0o600


def test_write_oauth_token_file_returns_path(mod, tmp_path):
    """Return value is the Path that was written."""
    account_home = tmp_path / "rettest"
    account_home.mkdir()
    result = mod._write_oauth_token_file("work", account_home, "sk-ant-oat01-ret")
    assert isinstance(result, Path)
    assert result.exists()


# -- _run_oauth_token_setup --------------------------------------------------


def test_run_oauth_token_setup_missing_claude_returns_false(monkeypatch, mod, tmp_path, capsys):
    """When claude is not on PATH, returns False and emits an error to stderr."""
    monkeypatch.setattr(altergo.constants, "ACCOUNTS_DIR", tmp_path / "accounts")
    monkeypatch.setattr(mod.shutil, "which", lambda name: None)
    account_home = tmp_path / "accounts" / "work"
    account_home.mkdir(parents=True)

    result = mod._run_oauth_token_setup("work", account_home)

    assert result is False
    captured = capsys.readouterr()
    assert "not found" in captured.err.lower() or "claude" in captured.err.lower()
    # No token file should have been written.
    assert not (account_home / ".claude" / ".oauth-token").exists()


def test_run_oauth_token_setup_happy_path_writes_token(monkeypatch, mod, tmp_path):
    """Happy path: subprocess succeeds, user pastes a valid token; returns True and file is written."""
    account_home = tmp_path / "accounts" / "work"
    account_home.mkdir(parents=True)

    monkeypatch.setattr(mod.shutil, "which", lambda name: "/usr/local/bin/claude")
    subprocess_calls = []

    def fake_run(cmd, **kw):
        subprocess_calls.append(cmd)
        return subprocess.CompletedProcess(args=cmd, returncode=0)

    monkeypatch.setattr(mod.subprocess, "run", fake_run)
    monkeypatch.setattr("builtins.input", lambda prompt="": "sk-ant-oat01-goodtoken")
    monkeypatch.delenv("SSH_CONNECTION", raising=False)

    result = mod._run_oauth_token_setup("work", account_home)

    assert result is True
    assert subprocess_calls[0] == ["/usr/local/bin/claude", "setup-token"]
    token_file = account_home / ".claude" / ".oauth-token"
    assert token_file.exists()
    assert token_file.read_text(encoding="utf-8") == "sk-ant-oat01-goodtoken"
    assert (token_file.stat().st_mode & 0o777) == 0o600


def test_run_oauth_token_setup_rejects_bad_prefix(monkeypatch, mod, tmp_path, capsys):
    """A pasted token without the sk-ant-oat01- prefix is rejected; returns False, no file written."""
    account_home = tmp_path / "accounts" / "work"
    account_home.mkdir(parents=True)

    monkeypatch.setattr(mod.shutil, "which", lambda name: "/usr/local/bin/claude")
    monkeypatch.setattr(mod.subprocess, "run", lambda cmd, **kw: subprocess.CompletedProcess(args=cmd, returncode=0))
    monkeypatch.setattr("builtins.input", lambda prompt="": "not-a-real-token")
    monkeypatch.delenv("SSH_CONNECTION", raising=False)

    result = mod._run_oauth_token_setup("work", account_home)

    assert result is False
    captured = capsys.readouterr()
    assert "sk-ant-oat01-" in captured.err
    assert not (account_home / ".claude" / ".oauth-token").exists()


def test_run_oauth_token_setup_strips_whitespace(monkeypatch, mod, tmp_path):
    """Leading/trailing whitespace and newlines are stripped from the pasted token."""
    account_home = tmp_path / "accounts" / "work"
    account_home.mkdir(parents=True)

    monkeypatch.setattr(mod.shutil, "which", lambda name: "/usr/local/bin/claude")
    monkeypatch.setattr(mod.subprocess, "run", lambda cmd, **kw: subprocess.CompletedProcess(args=cmd, returncode=0))
    monkeypatch.setattr("builtins.input", lambda prompt="": "  sk-ant-oat01-foo \n")
    monkeypatch.delenv("SSH_CONNECTION", raising=False)

    result = mod._run_oauth_token_setup("work", account_home)

    assert result is True
    token_file = account_home / ".claude" / ".oauth-token"
    assert token_file.read_text(encoding="utf-8") == "sk-ant-oat01-foo"


def test_run_oauth_token_setup_strips_oauth_token_from_subprocess_env(monkeypatch, mod, tmp_path):
    """`claude setup-token` must NOT inherit a pre-existing CLAUDE_CODE_OAUTH_TOKEN.

    If the user has a global token exported in .zshrc (a very common state
    for anyone who used the legacy rover-native-token flow), claude detects
    the env var and short-circuits the URL/paste flow — the user never gets
    a fresh token to paste, and the whole setup silently no-ops. This test
    pins that the var is stripped from the subprocess env at the call site,
    independent of what the parent process has."""
    account_home = tmp_path / "accounts" / "work"
    account_home.mkdir(parents=True)

    monkeypatch.setattr(mod.shutil, "which", lambda name: "/usr/local/bin/claude")
    monkeypatch.setenv("CLAUDE_CODE_OAUTH_TOKEN", "sk-ant-oat01-leaked-from-shell")

    captured_env = {}

    def fake_run(cmd, **kw):
        captured_env.update(kw.get("env") or {})
        return subprocess.CompletedProcess(args=cmd, returncode=0)

    monkeypatch.setattr(mod.subprocess, "run", fake_run)
    monkeypatch.setattr("builtins.input", lambda prompt="": "sk-ant-oat01-fresh")
    monkeypatch.delenv("SSH_CONNECTION", raising=False)

    result = mod._run_oauth_token_setup("work", account_home)

    assert result is True
    assert "CLAUDE_CODE_OAUTH_TOKEN" not in captured_env, (
        "claude setup-token must not see a pre-existing CLAUDE_CODE_OAUTH_TOKEN "
        "or it short-circuits the OAuth flow"
    )


def test_run_oauth_token_setup_keyboard_interrupt_in_subprocess(monkeypatch, mod, tmp_path):
    """KeyboardInterrupt during subprocess.run → returns False, no file written."""
    account_home = tmp_path / "accounts" / "work"
    account_home.mkdir(parents=True)

    monkeypatch.setattr(mod.shutil, "which", lambda name: "/usr/local/bin/claude")

    def raising_run(cmd, **kw):
        raise KeyboardInterrupt

    monkeypatch.setattr(mod.subprocess, "run", raising_run)
    monkeypatch.delenv("SSH_CONNECTION", raising=False)

    result = mod._run_oauth_token_setup("work", account_home)

    assert result is False
    assert not (account_home / ".claude" / ".oauth-token").exists()


def test_run_oauth_token_setup_eoferror_on_input(monkeypatch, mod, tmp_path):
    """EOFError from input() (e.g. piped stdin) → returns False, no file written."""
    account_home = tmp_path / "accounts" / "work"
    account_home.mkdir(parents=True)

    monkeypatch.setattr(mod.shutil, "which", lambda name: "/usr/local/bin/claude")
    monkeypatch.setattr(mod.subprocess, "run", lambda cmd, **kw: subprocess.CompletedProcess(args=cmd, returncode=0))

    def eof_input(prompt=""):
        raise EOFError

    monkeypatch.setattr("builtins.input", eof_input)
    monkeypatch.delenv("SSH_CONNECTION", raising=False)

    result = mod._run_oauth_token_setup("work", account_home)

    assert result is False
    assert not (account_home / ".claude" / ".oauth-token").exists()


def test_run_oauth_token_setup_oserror_on_write_returns_false(monkeypatch, mod, tmp_path, capsys):
    """OSError from _write_oauth_token_file → returns False and prints error to stderr."""
    account_home = tmp_path / "accounts" / "work"
    account_home.mkdir(parents=True)

    monkeypatch.setattr(mod.shutil, "which", lambda name: "/usr/local/bin/claude")
    monkeypatch.setattr(mod.subprocess, "run", lambda cmd, **kw: subprocess.CompletedProcess(args=cmd, returncode=0))
    monkeypatch.setattr("builtins.input", lambda prompt="": "sk-ant-oat01-good")
    monkeypatch.delenv("SSH_CONNECTION", raising=False)

    def raising_write(account, account_home, token):
        raise OSError("no space left on device")

    monkeypatch.setattr(mod, "_write_oauth_token_file", raising_write)

    result = mod._run_oauth_token_setup("work", account_home)

    assert result is False
    captured = capsys.readouterr()
    assert "failed" in captured.err.lower() or "error" in captured.err.lower() or "token" in captured.err.lower()


def test_run_oauth_token_setup_over_ssh_branch(monkeypatch, mod, tmp_path, capsys):
    """When SSH_CONNECTION is set, setup-flow prints SSH-specific guidance."""
    account_home = tmp_path / "accounts" / "work"
    account_home.mkdir(parents=True)

    monkeypatch.setattr(mod.shutil, "which", lambda name: "/usr/local/bin/claude")
    monkeypatch.setattr(mod.subprocess, "run", lambda cmd, **kw: subprocess.CompletedProcess(args=cmd, returncode=0))
    monkeypatch.setattr("builtins.input", lambda prompt="": "sk-ant-oat01-sshtoken")
    monkeypatch.setenv("SSH_CONNECTION", "1.2.3.4 1234 5.6.7.8 22")

    mod._run_oauth_token_setup("work", account_home)

    captured = capsys.readouterr()
    # The SSH branch prints a URL / phone / browser instruction; confirm the branch fired.
    assert "ssh" in captured.out.lower() or "browser" in captured.out.lower() or "phone" in captured.out.lower()


# -- _maybe_offer_oauth_token_setup ------------------------------------------


@pytest.mark.parametrize("provider", ["gemini", "codex", "copilot"])
def test_maybe_offer_skips_non_claude_providers(monkeypatch, mod, tmp_path, provider):
    """Non-claude providers return False immediately without prompting."""
    account_home = tmp_path / "accounts" / "work"
    account_home.mkdir(parents=True)
    monkeypatch.setattr(altergo.constants, "ACCOUNTS_DIR", tmp_path / "accounts")

    prompt_calls = []
    monkeypatch.setattr("builtins.input", lambda p="": prompt_calls.append(p) or "y")

    result = mod._maybe_offer_oauth_token_setup("work", account_home, provider, "keychain")

    assert result is False
    assert prompt_calls == [], f"Must not prompt for provider={provider}"


def test_maybe_offer_skips_keychain_mode_none(monkeypatch, mod, tmp_path):
    """keychain_mode='none' → returns False without prompting."""
    account_home = tmp_path / "accounts" / "work"
    account_home.mkdir(parents=True)
    monkeypatch.setattr(altergo.constants, "ACCOUNTS_DIR", tmp_path / "accounts")

    prompt_calls = []
    monkeypatch.setattr("builtins.input", lambda p="": prompt_calls.append(p) or "y")

    result = mod._maybe_offer_oauth_token_setup("work", account_home, "claude", "none")

    assert result is False
    assert prompt_calls == []


def test_maybe_offer_skips_when_token_already_present(monkeypatch, mod, tmp_path):
    """When a token file already exists, returns False without prompting."""
    account_home = tmp_path / "accounts" / "work"
    token_file = account_home / ".claude" / ".oauth-token"
    token_file.parent.mkdir(parents=True)
    token_file.write_text("sk-ant-oat01-existing")
    monkeypatch.setattr(altergo.constants, "ACCOUNTS_DIR", tmp_path / "accounts")

    prompt_calls = []
    monkeypatch.setattr("builtins.input", lambda p="": prompt_calls.append(p) or "y")

    result = mod._maybe_offer_oauth_token_setup("work", account_home, "claude", "keychain")

    assert result is False
    assert prompt_calls == []


def test_maybe_offer_non_tty_prints_hint_and_returns_false(monkeypatch, mod, tmp_path, capsys):
    """Non-TTY stdin → returns False and prints a hint to stderr mentioning --setup-token."""
    account_home = tmp_path / "accounts" / "work"
    account_home.mkdir(parents=True)
    monkeypatch.setattr(altergo.constants, "ACCOUNTS_DIR", tmp_path / "accounts")
    monkeypatch.setattr(mod.sys.stdin, "isatty", lambda: False)

    result = mod._maybe_offer_oauth_token_setup("work", account_home, "claude", "keychain")

    assert result is False
    captured = capsys.readouterr()
    assert "altergo --setup-token" in captured.err


def test_maybe_offer_user_types_n_returns_false(monkeypatch, mod, tmp_path, capsys):
    """User responds 'n' → returns False, prints Skipped message, no file written."""
    account_home = tmp_path / "accounts" / "work"
    account_home.mkdir(parents=True)
    monkeypatch.setattr(altergo.constants, "ACCOUNTS_DIR", tmp_path / "accounts")
    monkeypatch.setattr(mod.sys.stdin, "isatty", lambda: True)
    monkeypatch.setattr("builtins.input", lambda p="": "n")

    result = mod._maybe_offer_oauth_token_setup("work", account_home, "claude", "keychain")

    assert result is False
    captured = capsys.readouterr()
    assert "skip" in captured.out.lower() or "later" in captured.out.lower()
    assert not (account_home / ".claude" / ".oauth-token").exists()


def test_maybe_offer_user_presses_enter_calls_run_setup(monkeypatch, mod, tmp_path):
    """Empty Enter (default Yes) → _run_oauth_token_setup is called with the correct args."""
    account_home = tmp_path / "accounts" / "work"
    account_home.mkdir(parents=True)
    monkeypatch.setattr(altergo.constants, "ACCOUNTS_DIR", tmp_path / "accounts")
    monkeypatch.setattr(mod.sys.stdin, "isatty", lambda: True)
    monkeypatch.setattr("builtins.input", lambda p="": "")

    run_setup_calls = []

    def spy_run_setup(account, ah):
        run_setup_calls.append((account, ah))
        return True

    monkeypatch.setattr(mod, "_run_oauth_token_setup", spy_run_setup)

    result = mod._maybe_offer_oauth_token_setup("work", account_home, "claude", "keychain")

    assert result is True
    assert run_setup_calls == [("work", account_home)]


def test_maybe_offer_user_types_y_calls_run_setup(monkeypatch, mod, tmp_path):
    """Explicit 'y' → _run_oauth_token_setup is called with correct args."""
    account_home = tmp_path / "accounts" / "work"
    account_home.mkdir(parents=True)
    monkeypatch.setattr(altergo.constants, "ACCOUNTS_DIR", tmp_path / "accounts")
    monkeypatch.setattr(mod.sys.stdin, "isatty", lambda: True)
    monkeypatch.setattr("builtins.input", lambda p="": "y")

    run_setup_calls = []

    def spy_run_setup(account, ah):
        run_setup_calls.append((account, ah))
        return True

    monkeypatch.setattr(mod, "_run_oauth_token_setup", spy_run_setup)

    result = mod._maybe_offer_oauth_token_setup("work", account_home, "claude", "keychain")

    assert result is True
    assert run_setup_calls == [("work", account_home)]


def test_maybe_offer_keyboard_interrupt_on_prompt_returns_false(monkeypatch, mod, tmp_path):
    """KeyboardInterrupt during the Y/n prompt is treated as 'n' → returns False."""
    account_home = tmp_path / "accounts" / "work"
    account_home.mkdir(parents=True)
    monkeypatch.setattr(altergo.constants, "ACCOUNTS_DIR", tmp_path / "accounts")
    monkeypatch.setattr(mod.sys.stdin, "isatty", lambda: True)

    def interrupt_input(p=""):
        raise KeyboardInterrupt

    monkeypatch.setattr("builtins.input", interrupt_input)

    run_setup_calls = []
    monkeypatch.setattr(mod, "_run_oauth_token_setup", lambda a, h: run_setup_calls.append((a, h)) or True)

    result = mod._maybe_offer_oauth_token_setup("work", account_home, "claude", "keychain")

    assert result is False
    assert run_setup_calls == []


# -- CLI: altergo --setup-token ----------------------------------------------


def _setup_main_env(monkeypatch, mod, tmp_path):
    """Wire MAIN_HOME, ACCOUNTS_DIR, etc. for main() CLI tests."""
    main_home = tmp_path / "main_home"
    accounts_dir = tmp_path / "accounts"
    main_home.mkdir(parents=True)
    accounts_dir.mkdir(parents=True)
    monkeypatch.setattr(altergo.constants, "MAIN_HOME", main_home)
    monkeypatch.setattr(altergo.constants, "ACCOUNTS_DIR", accounts_dir)
    monkeypatch.setattr(altergo.constants, "SETTINGS_FILE", tmp_path / "settings.json")
    monkeypatch.setattr(altergo.ui, "show_banner", lambda *a, **kw: None)
    monkeypatch.setattr(altergo.accounts, "load_settings", lambda: {})
    return accounts_dir


def test_cli_setup_token_no_account_arg_exits_1(monkeypatch, mod, tmp_path, capsys):
    """altergo --setup-token (no account) → exits 1 with usage message."""
    _setup_main_env(monkeypatch, mod, tmp_path)
    monkeypatch.setattr(mod.sys, "argv", ["altergo", "--setup-token"])

    with pytest.raises(SystemExit) as exc_info:
        altergo.cli.main()

    assert exc_info.value.code == 1
    captured = capsys.readouterr()
    assert "usage" in captured.err.lower() or "setup-token" in captured.err


def test_cli_setup_token_nonexistent_account_exits_1(monkeypatch, mod, tmp_path, capsys):
    """altergo --setup-token nonexistent → exits 1 with 'account not found' message."""
    _setup_main_env(monkeypatch, mod, tmp_path)
    monkeypatch.setattr(mod.sys, "argv", ["altergo", "--setup-token", "nosuchaccount"])

    with pytest.raises(SystemExit) as exc_info:
        altergo.cli.main()

    assert exc_info.value.code == 1
    captured = capsys.readouterr()
    assert "not found" in captured.err.lower()


def test_cli_setup_token_native_calls_run_setup(monkeypatch, mod, tmp_path):
    """altergo --setup-token native → calls _run_oauth_token_setup('native', None), exits 0 on success."""
    _setup_main_env(monkeypatch, mod, tmp_path)
    monkeypatch.setattr(mod.sys, "argv", ["altergo", "--setup-token", "native"])

    run_calls = []

    def spy_run_setup(account, ah):
        run_calls.append((account, ah))
        return True

    monkeypatch.setattr(altergo.cli, "_run_oauth_token_setup", spy_run_setup)

    with pytest.raises(SystemExit) as exc_info:
        altergo.cli.main()

    assert exc_info.value.code == 0
    assert run_calls == [("native", None)]


def test_cli_setup_token_existing_account_calls_run_setup(monkeypatch, mod, tmp_path):
    """altergo --setup-token work (account exists) → calls _run_oauth_token_setup with the account_home."""
    accounts_dir = _setup_main_env(monkeypatch, mod, tmp_path)
    work_dir = accounts_dir / "work"
    work_dir.mkdir(parents=True)
    monkeypatch.setattr(mod.sys, "argv", ["altergo", "--setup-token", "work"])

    run_calls = []

    def spy_run_setup(account, ah):
        run_calls.append((account, ah))
        return True

    monkeypatch.setattr(altergo.cli, "_run_oauth_token_setup", spy_run_setup)

    with pytest.raises(SystemExit) as exc_info:
        altergo.cli.main()

    assert exc_info.value.code == 0
    assert len(run_calls) == 1
    assert run_calls[0][0] == "work"
    assert run_calls[0][1] == work_dir


def test_cli_setup_token_exits_1_when_run_setup_returns_false(monkeypatch, mod, tmp_path):
    """When _run_oauth_token_setup returns False (user cancelled), the CLI exits 1."""
    accounts_dir = _setup_main_env(monkeypatch, mod, tmp_path)
    (accounts_dir / "work").mkdir(parents=True)
    monkeypatch.setattr(mod.sys, "argv", ["altergo", "--setup-token", "work"])
    monkeypatch.setattr(altergo.cli, "_run_oauth_token_setup", lambda a, h: False)

    with pytest.raises(SystemExit) as exc_info:
        altergo.cli.main()

    assert exc_info.value.code == 1


# -- Integration: configure_account hook -------------------------------------


def test_configure_account_claude_keychain_tty_calls_maybe_offer(monkeypatch, mod, tmp_path):
    """After configuring a claude+keychain account on a TTY, _maybe_offer_oauth_token_setup
    is called exactly once with the account name, account_home, 'claude', 'keychain'."""
    accounts_dir = _setup_configure_account_env(monkeypatch, mod, tmp_path)
    # Override the non-TTY stub from _setup_configure_account_env to simulate a TTY.
    monkeypatch.setattr(mod.sys.stdin, "isatty", lambda: True)
    monkeypatch.setattr(mod, "_sec", lambda argv, **kw: _cp(0))

    offer_calls = []

    def spy_offer(account, account_home, provider, keychain_mode):
        offer_calls.append((account, provider, keychain_mode))
        return False

    monkeypatch.setattr(altergo.accounts, "_maybe_offer_oauth_token_setup", spy_offer)
    # configure_account prompts for keychain mode on TTY; answer 'n' → none mode.
    # Use keychain_arg='keychain' to bypass the interactive prompt.
    altergo.accounts.configure_account("work", keychain_arg="keychain")

    assert len(offer_calls) == 1
    account_arg, provider_arg, kc_arg = offer_calls[0]
    assert account_arg == "work"
    assert provider_arg == "claude"
    assert kc_arg == "keychain"


def test_configure_account_claude_none_mode_offer_does_not_trigger_run_setup(monkeypatch, mod, tmp_path):
    """When keychain_arg='none', _maybe_offer_oauth_token_setup is still wired but
    the gating logic inside it prevents _run_oauth_token_setup from being called."""
    accounts_dir = _setup_configure_account_env(monkeypatch, mod, tmp_path)
    monkeypatch.setattr(mod, "_sec", lambda argv, **kw: _cp(0))

    run_setup_calls = []
    monkeypatch.setattr(mod, "_run_oauth_token_setup", lambda a, h: run_setup_calls.append((a, h)) or True)

    altergo.accounts.configure_account("work", keychain_arg="none")

    assert run_setup_calls == [], (
        "_run_oauth_token_setup must not be called when keychain_mode is 'none'"
    )


def test_configure_account_gemini_provider_offer_does_not_trigger_run_setup(monkeypatch, mod, tmp_path):
    """Non-claude provider: _run_oauth_token_setup must never be called."""
    accounts_dir = _setup_configure_account_env(monkeypatch, mod, tmp_path)
    monkeypatch.setattr(mod, "_sec", lambda argv, **kw: _cp(0))

    run_setup_calls = []
    monkeypatch.setattr(mod, "_run_oauth_token_setup", lambda a, h: run_setup_calls.append((a, h)) or True)

    altergo.accounts.configure_account("work", provider="gemini", keychain_arg="none")

    assert run_setup_calls == [], (
        "_run_oauth_token_setup must not be called for non-claude providers"
    )
