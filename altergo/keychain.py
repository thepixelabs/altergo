import json
import os
import plistlib
import secrets
import shutil
import subprocess
import sys
from pathlib import Path

import altergo.constants as _const
from altergo.persistence import load_account_meta, save_account_meta
from altergo.theme import C, _c

SECURITY_CMD = "/usr/bin/security"
_KC_SERVICE = "com.altergo.account-unlock"
_KC_GUID = "{87191ca3-0fc9-11d4-849a-000502b52122}"
_KC_SUBSERVICE_TYPE = 6


class KeychainError(Exception):
    """Raised when a /usr/bin/security operation fails in an unexpected way."""


def _sec(argv: list, *, check: bool = True, timeout: int = 10) -> subprocess.CompletedProcess:
    try:
        r = subprocess.run(
            [SECURITY_CMD] + argv,
            capture_output=True,
            text=True,
            timeout=timeout,
        )
    except FileNotFoundError:
        raise KeychainError("/usr/bin/security not found — macOS Security framework unavailable")
    if check and r.returncode != 0:
        raise KeychainError(f"security {argv[0]} failed (exit {r.returncode}): {r.stderr.strip()}")
    return r


def _keychain_path(account_home: Path) -> Path:
    return account_home / "Library" / "Keychains" / "login.keychain-db"


def _keychain_prefs_path(account_home: Path) -> Path:
    return account_home / "Library" / "Preferences" / "com.apple.security.plist"


def _write_keychain_prefs(account_home: Path) -> None:
    prefs_path = _keychain_prefs_path(account_home)
    prefs_path.parent.mkdir(parents=True, exist_ok=True)
    plist_data = {
        "DLDBSearchList": [
            {
                "GUID": _KC_GUID,
                "DbName": "~/Library/Keychains/login.keychain",
                "SubserviceType": _KC_SUBSERVICE_TYPE,
            }
        ]
    }
    with open(prefs_path, "wb") as f:
        plistlib.dump(plist_data, f, fmt=plistlib.FMT_XML)


def _sec_create_keychain(kc_path: Path, password: str) -> None:
    result = _sec(["list-keychains", "-d", "user"], check=False)
    original = [p.strip().strip('"') for p in result.stdout.splitlines() if p.strip()] if result.returncode == 0 else []
    _sec(["create-keychain", "-p", password, str(kc_path)])
    if original:
        _sec(["list-keychains", "-d", "user", "-s"] + original, check=False)


def _create_account_keychain(account_home: Path, slug: str, *, plant_unlock_entry: bool = True) -> None:
    kc_path = _keychain_path(account_home)
    kc_path.parent.mkdir(parents=True, exist_ok=True)

    c_present = kc_path.exists()
    d_result = _sec(["find-generic-password", "-s", _KC_SERVICE, "-a", slug, "-w"], check=False)
    d_present = d_result.returncode == 0

    if not plant_unlock_entry:
        if c_present:
            if d_present:
                _sec(["delete-generic-password", "-s", _KC_SERVICE, "-a", slug], check=False)
            _write_keychain_prefs(account_home)
            return
        if d_present:
            _sec(["delete-generic-password", "-s", _KC_SERVICE, "-a", slug], check=False)
        P = secrets.token_bytes(32).hex()
        _sec_create_keychain(kc_path, P)
        _sec(["set-keychain-settings", str(kc_path)])
        _write_keychain_prefs(account_home)
        return

    if c_present and d_present:
        P_probe = d_result.stdout.rstrip("\n")
        probe = _sec(["unlock-keychain", "-p", P_probe, str(kc_path)], check=False)
        if probe.returncode == 0:
            print(_c(2, "  Keychain already exists, reusing"))
            _write_keychain_prefs(account_home)
            return
        print(_c(2, "  Keychain password mismatch — rebuilding"), file=sys.stderr)
        _sec(["delete-keychain", str(kc_path)], check=False)
        _sec(["delete-generic-password", "-s", _KC_SERVICE, "-a", slug], check=False)

    elif c_present and not d_present:
        print(
            _c(2, "  Orphaned keychain file found — rebuilding (any tokens inside are lost; re-auth required)"),
            file=sys.stderr,
        )
        _sec(["delete-keychain", str(kc_path)], check=False)

    elif not c_present and d_present:
        _sec(["delete-generic-password", "-s", _KC_SERVICE, "-a", slug], check=False)

    P = secrets.token_bytes(32).hex()
    _sec_create_keychain(kc_path, P)
    _sec(["set-keychain-settings", str(kc_path)])
    _sec(["add-generic-password", "-s", _KC_SERVICE, "-a", slug, "-w", P, "-T", SECURITY_CMD])
    _write_keychain_prefs(account_home)


def _create_account_keychain_dedicated(account_home: Path, slug: str) -> None:
    _create_account_keychain(account_home, slug, plant_unlock_entry=True)


def _create_account_keychain_isolated(account_home: Path, slug: str) -> None:
    _create_account_keychain(account_home, slug, plant_unlock_entry=False)


def _prune_altergo_keychains_from_search_list() -> None:
    result = _sec(["list-keychains", "-d", "user"], check=False)
    if result.returncode != 0:
        return
    current = [p.strip().strip('"') for p in result.stdout.splitlines() if p.strip()]
    altergo_root = str(_const.ACCOUNTS_DIR)
    cleaned = [p for p in current if altergo_root not in p and "/pytest-" not in p]
    if len(cleaned) < len(current):
        _sec(["list-keychains", "-d", "user", "-s"] + cleaned, check=False)


def _unlock_account_keychain(account_home: Path, slug: str) -> None:
    r = _sec(["find-generic-password", "-s", _KC_SERVICE, "-a", slug, "-w"], check=False)
    if r.returncode != 0:
        stderr = r.stderr.strip()
        if "interaction is not allowed" in stderr or "errSecInteractionNotAllowed" in stderr:
            raise KeychainError(
                "login keychain is locked — open Keychain Access and unlock 'login', or disable its auto-lock timer"
            )
        if "could not be found" in stderr or "The specified item could not be found" in stderr:
            raise KeychainError(
                f"no unlock entry found for account '{slug}' — run 'altergo --config {slug}' to re-create"
            )
        raise KeychainError(f"failed to read unlock entry: {stderr}")

    P = r.stdout.rstrip("\n")
    try:
        _sec(["unlock-keychain", "-p", P, str(_keychain_path(account_home))])
    except KeychainError as e:
        if "errSecAuthFailed" in str(e) or "authorization failed" in str(e).lower():
            raise KeychainError(
                f"keychain password mismatch for account '{slug}' — "
                f"run 'altergo --config {slug}' to re-create the keychain"
            ) from e
        raise


def _delete_account_keychain(account_home: Path, slug: str) -> None:
    _sec(["delete-keychain", str(_keychain_path(account_home))], check=False)
    _sec(["delete-generic-password", "-s", _KC_SERVICE, "-a", slug], check=False)
    _keychain_prefs_path(account_home).unlink(missing_ok=True)


def _uses_keychain(meta: dict | None) -> bool:
    if not meta:
        return True
    kc = meta.get("keychain")
    if kc is None:
        return True
    return kc == "keychain"


def _is_keychain_none(meta: dict | None) -> bool:
    if not meta:
        return False
    kc = meta.get("keychain")
    if kc is None:
        return False
    return kc == "none"


def _read_raw_account_keychain_key(account_home: Path) -> str | None:
    try:
        meta_file = account_home / "account.json"
        if not meta_file.exists():
            return None
        data = json.loads(meta_file.read_text())
        return data.get("keychain")
    except Exception:
        return None


def _save_meta_keychain(account_home: Path, current_meta: dict | None, new_value: str) -> None:
    merged = dict(current_meta) if current_meta else {}
    merged["keychain"] = new_value
    save_account_meta(account_home, merged)


def _reconcile_keychain_state(account_home: Path, slug: str, desired: str | None = None) -> None:
    meta = load_account_meta(account_home)
    b_present = _keychain_prefs_path(account_home).exists()
    c_present = _keychain_path(account_home).exists()
    d_result = _sec(["find-generic-password", "-s", _KC_SERVICE, "-a", slug, "-w"], check=False)
    d_present = d_result.returncode == 0

    a_raw = _read_raw_account_keychain_key(account_home)
    a_coerced = (meta or {}).get("keychain")
    a_needs_persist = a_raw != a_coerced

    if desired == "keychain":
        _create_account_keychain(account_home, slug, plant_unlock_entry=True)
        _save_meta_keychain(account_home, meta, "keychain")
        return

    if desired == "none":
        if d_present:
            _sec(["delete-generic-password", "-s", _KC_SERVICE, "-a", slug], check=False)
        _create_account_keychain(account_home, slug, plant_unlock_entry=False)
        _save_meta_keychain(account_home, meta, "none")
        return

    current = a_coerced or "keychain"

    if current == "keychain":
        if not b_present:
            print(
                _c(2, f"  altergo: repairing keychain state for '{slug}'"),
                file=sys.stderr,
            )
            _create_account_keychain(account_home, slug, plant_unlock_entry=True)
            _save_meta_keychain(account_home, meta, "keychain")
            return
        if not c_present or not d_present:
            print(
                _c(2, f"  altergo: repairing keychain state for '{slug}'"),
                file=sys.stderr,
            )
            _create_account_keychain(account_home, slug, plant_unlock_entry=True)
            _save_meta_keychain(account_home, meta, "keychain")
            return
        P_probe = d_result.stdout.rstrip("\n")
        probe = _sec(["unlock-keychain", "-p", P_probe, str(_keychain_path(account_home))], check=False)
        if probe.returncode != 0:
            print(
                _c(2, f"  altergo: repairing keychain state for '{slug}'"),
                file=sys.stderr,
            )
            _create_account_keychain(account_home, slug, plant_unlock_entry=True)
            _save_meta_keychain(account_home, meta, "keychain")
            return
        if a_needs_persist:
            _save_meta_keychain(account_home, meta, "keychain")
        return

    elif current == "none":
        if not b_present:
            _write_keychain_prefs(account_home)
        if a_needs_persist or a_coerced != "none":
            _save_meta_keychain(account_home, meta, "none")
        return

    else:
        if not b_present:
            _write_keychain_prefs(account_home)
        _save_meta_keychain(account_home, meta, "keychain")


def _apply_keychain_mode(account_home: Path, slug: str, mode: str, *, prior_meta: dict | None) -> None:
    _save_meta_keychain(account_home, prior_meta, mode)

    if mode == "keychain":
        _create_account_keychain_dedicated(account_home, slug)
    else:
        d_result = _sec(["find-generic-password", "-s", _KC_SERVICE, "-a", slug, "-w"], check=False)
        if d_result.returncode == 0:
            _sec(["delete-generic-password", "-s", _KC_SERVICE, "-a", slug], check=False)
        _create_account_keychain_isolated(account_home, slug)


# ---------------------------------------------------------------------------
# OAuth token helpers (used by runner.py)
# ---------------------------------------------------------------------------


def _oauth_token_path(account: str, account_home: "Path | None" = None) -> "Path":
    if account == _const._NATIVE_ACCOUNT:
        return _const.MAIN_HOME / ".claude" / ".oauth-token"
    if account_home is None:
        account_home = _const.ACCOUNTS_DIR / account
    return account_home / ".claude" / ".oauth-token"


def _load_oauth_token(account: str, account_home: "Path | None" = None) -> "str | None":
    candidates = [_oauth_token_path(account, account_home)]
    if account == _const._NATIVE_ACCOUNT:
        candidates.append(_const.MAIN_HOME / ".claude" / "rover-native-token")
    for path in candidates:
        try:
            if path.exists():
                token = path.read_text().strip()
                if token:
                    return token
        except Exception:
            pass
    return None


def _write_oauth_token_file(account: str, account_home: "Path | None", token: str) -> "Path":
    path = _oauth_token_path(account, account_home)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(token, encoding="utf-8")
    try:
        import os

        os.chmod(str(path), 0o600)
    except OSError:
        pass
    return path


def _run_oauth_token_setup(account: str, account_home: "Path | None") -> bool:
    """Run the interactive OAuth token setup flow for *account*.

    Launches ``claude setup-token`` in a subprocess (stripped of any existing
    CLAUDE_CODE_OAUTH_TOKEN so the fresh-issuance flow is not short-circuited),
    then prompts the user to paste the printed token. Validates the token prefix
    before writing it to disk. Returns True on success, False on any failure or
    cancellation.
    """
    account_home_path = account_home or (_const.ACCOUNTS_DIR / account)

    claude_bin = shutil.which("claude")
    if not claude_bin:
        print(file=sys.stderr)
        print(_c(C("error"), "  claude binary not found on PATH."), file=sys.stderr)
        print(_c(C("dim"), "  Install Claude Code first: https://claude.com/code"), file=sys.stderr)
        return False

    over_ssh = bool(os.environ.get("SSH_CONNECTION"))
    print()
    print(_c(C("header"), "  Generating an SSH-friendly OAuth token"))
    if over_ssh:
        print(_c(2, "  You're over SSH — claude setup-token will print a URL."))
        print(_c(2, "  Open it in your phone or another browser, approve, and paste"))
        print(_c(2, "  the token back here when it prints to the terminal."))
    else:
        print(_c(2, "  A browser window will open for confirmation. After the token"))
        print(_c(2, "  prints to the terminal, copy it and paste it when prompted below."))
    print()

    # Strip CLAUDE_CODE_OAUTH_TOKEN from the subprocess env: an existing
    # shell-exported token would short-circuit the URL/paste flow inside
    # `claude setup-token`, preventing a fresh token from being issued.
    setup_env = {k: v for k, v in os.environ.items() if k != "CLAUDE_CODE_OAUTH_TOKEN"}
    try:
        subprocess.run([claude_bin, "setup-token"], env=setup_env)
    except KeyboardInterrupt:
        print(_c(C("dim"), "\n  cancelled"), file=sys.stderr)
        return False
    except OSError as exc:
        print(_c(C("error"), f"\n  claude setup-token failed: {exc}"), file=sys.stderr)
        return False

    print()
    print(_c(1, "  Paste the token below ") + _c(C("dim"), "(starts with sk-ant-oat01-…):"))
    try:
        raw = input("  token: ")
    except (EOFError, KeyboardInterrupt):
        print(_c(C("dim"), "\n  cancelled"), file=sys.stderr)
        return False

    token = raw.strip()
    if not token.startswith("sk-ant-oat01-"):
        print(file=sys.stderr)
        print(_c(C("error"), "  That doesn't look like a Claude OAuth token."), file=sys.stderr)
        print(_c(C("dim"), "  Expected prefix: sk-ant-oat01-…"), file=sys.stderr)
        print(_c(C("dim"), "  Nothing was written. Re-run when you have the right value."), file=sys.stderr)
        return False

    try:
        path = _write_oauth_token_file(account, account_home_path, token)
    except OSError as exc:
        print(_c(C("error"), f"\n  failed to write token file: {exc}"), file=sys.stderr)
        return False

    print()
    print(_c(C("success"), "  ✓ token saved   ") + _c(C("dim"), str(path)))
    print(_c(2, "  Subsequent altergo launches for this account will use this token"))
    print(_c(2, "  even when the macOS keychain is unavailable (e.g. over SSH)."))
    print()
    return True


def _maybe_offer_oauth_token_setup(
    account: str,
    account_home: "Path | None",
    provider: str,
    keychain_mode: str,
) -> bool:
    if provider != "claude":
        return False
    if keychain_mode != "keychain":
        return False
    if _load_oauth_token(account, account_home) is not None:
        return False
    if not sys.stdin.isatty():
        print(
            f"  {_c(C('dim'), 'note: this account uses a keychain.')}\n"
            f"  {_c(C('dim'), 'Over SSH, run')} {_c(0, f'altergo --setup-token {account}')} "
            f"{_c(C('dim'), 'to enable token-based auth.')}",
            file=sys.stderr,
        )
        return False
    print()
    print(_c(C("header"), "  OAuth token (SSH bridge)"))
    print(_c(2, "  Generating one now lets claude auth over SSH without"))
    print(_c(2, "  hitting the keychain. You can run this any time later"))
    print(_c(2, "  with: ") + _c(0, f"altergo --setup-token {account}"))
    prompt = "  Generate an OAuth token now? [Y/n] "
    try:
        answer = input(prompt).strip().lower()
    except (KeyboardInterrupt, EOFError):
        answer = "n"
    if answer in ("n", "no"):
        print(
            _c(C("dim"), "  Skipped. Run ")
            + _c(0, f"altergo --setup-token {account}")
            + _c(C("dim"), " any time to enable it later.")
        )
        return False
    return _run_oauth_token_setup(account, account_home)


def _apply_oauth_token_to_env(env: dict, account: str, account_home: "Path | None" = None) -> None:
    """Mutate *env* to set or strip ``CLAUDE_CODE_OAUTH_TOKEN`` for *account*.

    - Token file exists → set env to that token (overrides shell export).
    - No token file, native account → leave env var untouched (shell export is
      the user's intentional choice for native).
    - No token file, non-native account → strip the env var to prevent a
      shell-exported token from silently authing claude as the wrong identity
      under the non-native account's $HOME.
    """
    token = _load_oauth_token(account, account_home)
    if token is not None:
        env["CLAUDE_CODE_OAUTH_TOKEN"] = token
    elif account != _const._NATIVE_ACCOUNT:
        env.pop("CLAUDE_CODE_OAUTH_TOKEN", None)
