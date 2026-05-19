import os
import re
import shlex
import shutil
import subprocess
import sys
import time
from pathlib import Path

import altergo.constants as _const
from altergo.accounts import (
    _ensure_symlinked_dir,
    _sync_claude_mcps,
    home_change_notice_if_needed,
    list_accounts,
    resolve_account,
)
from altergo.keychain import (
    KeychainError,
    _apply_oauth_token_to_env,
    _load_oauth_token,
    _reconcile_keychain_state,
    _unlock_account_keychain,
    _uses_keychain,
)
from altergo.persistence import (
    _ANIM_PACKS,
    _DEFAULT_ANIM_PACK,
    _handoff_duration,
    _load_bool_setting,
    first_launch_notice_if_needed,
    get_cached_latest_version,
    load_account_meta,
    load_animation_pack,
    load_native_default_provider,
    maybe_refresh_update_cache,
    save_last_session,
)
from altergo.sessions import _scan_session_head
from altergo.theme import _DEFAULT_THEME, THEMES, C, _c, _gradient_color, get_current_theme
from altergo.ui import show_banner

# ── yolo helpers ───────────────────────────────────────────────────────────────

_SESSION_ID_RE = re.compile(
    r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$",
    re.IGNORECASE,
)


def _looks_like_session_id(token: str) -> bool:
    """Return True iff ``token`` matches the canonical UUID shape."""
    return bool(_SESSION_ID_RE.match(token))


def _extract_yolo_resume(args: list[str]) -> tuple[bool, str | None, list[str]]:
    """Scan ``args`` for --yolo-resume, --yolo-resume=ID, or --yolo-resume ID."""
    present = False
    session_id: str | None = None
    out: list[str] = []
    i = 0
    while i < len(args):
        a = args[i]
        if a == "--yolo-resume":
            present = True
            # Consume the next token as the session ID whenever it isn't
            # another flag. Providers accept non-UUID identifiers too — claude's
            # named-session aliases (e.g. "delete-persona-heartbeat-wrapper")
            # are kebab-case strings, not UUIDs — so a strict UUID check would
            # turn the alias into a chat prompt instead of resuming the session.
            if i + 1 < len(args) and not args[i + 1].startswith("-"):
                session_id = args[i + 1]
                i += 2
                continue
            i += 1
            continue
        if a.startswith("--yolo-resume="):
            present = True
            value = a.split("=", 1)[1]
            # Honor whatever the user typed after the =; validating here
            # would just produce a confusing "silently ignored" behavior.
            # The provider CLI will reject a bad ID with its own error.
            if value:
                session_id = value
            i += 1
            continue
        out.append(a)
        i += 1
    return present, session_id, out


def _translate_yolo_flags(provider: str, args: list[str]) -> tuple[list[str], list[str], list[str]]:
    """Translate --yolo / --yolo-resume into provider-native flags."""
    yolo_resume, session_id, args_after_resume = _extract_yolo_resume(list(args))
    yolo = yolo_resume or "--yolo" in args_after_resume

    if not yolo:
        return [], args, []

    # Strip the remaining synthetic flag (--yolo). --yolo-resume was already
    # consumed above along with any paired ID token.
    cleaned = [a for a in args_after_resume if a != "--yolo"]

    prov_flags = _const.PROVIDERS.get(provider, {}).get("flags", {})
    prefix: list[str] = []
    suffix: list[str] = []

    if yolo_resume and session_id is not None:
        # Resume-by-id: subcommand form (codex) wins over the flag form.
        template: list[str] | None = None
        if "resume_by_id_subcommand" in prov_flags:
            template = list(prov_flags["resume_by_id_subcommand"])
        elif "resume_by_id" in prov_flags:
            template = list(prov_flags["resume_by_id"])
        if template is None:
            # Provider opted out of resume-by-id. Fail loud rather than
            # silently dropping the ID (the original bug this change fixes).
            display = _const.PROVIDERS.get(provider, {}).get("display_name", provider)
            print(
                f"altergo: {display} does not support resume-by-id via altergo. "
                f"Drop the session ID to resume the most recent session, or use "
                f"the provider CLI directly.",
                file=sys.stderr,
            )
            sys.exit(2)
        prefix = [tok.replace("{id}", session_id) for tok in template]
        if "skip_perms" in prov_flags:
            suffix = list(prov_flags["skip_perms"])
    elif yolo_resume and provider == "codex":
        # codex uses a subcommand: codex resume --last [user-args] --bypass
        prefix = list(prov_flags.get("resume_subcommand", []))
        suffix = list(prov_flags.get("skip_perms", []))
    else:
        if yolo_resume and "resume_last" in prov_flags:
            prefix = list(prov_flags["resume_last"])
        if yolo and "skip_perms" in prov_flags:
            suffix = list(prov_flags["skip_perms"])

    return prefix, cleaned, suffix


# ── account disambiguation ─────────────────────────────────────────────────────

_KNOWN_COMMANDS = frozenset(
    [
        "shell",
        "use",
        "portal",
        "--resume",
        "--recall",
        "--search",
        "--config",
        "--rename",
        "--teardown",
        "--settings",
        "--version",
        "--use",
        "--launch",
        "--theme",
        "--star",
        "-h",
        "--help",
        "--",
    ]
)


def _looks_like_account(token: str) -> bool:
    """Return True if token could be an account name (not a flag, not a known command)."""
    if token.startswith("-"):
        return False
    if token in _KNOWN_COMMANDS:
        return False
    # Must look like a valid account name (alphanumeric start, no spaces)
    return bool(re.match(r"^[a-zA-Z0-9][a-zA-Z0-9_-]*$", token))


# ── session recording ──────────────────────────────────────────────────────────


def _record_last_session_after_exit(provider: str, launch_time: float) -> None:
    """Scan for the newest JSONL session file and write it to LAST_SESSION_FILE."""
    projects_dir = _const.MAIN_CLAUDE / "projects"
    if not projects_dir.exists():
        return

    # Subtract a buffer to tolerate filesystem timestamp imprecision.
    cutoff = launch_time - 2.0

    newest_path = None
    newest_mtime = 0.0

    try:
        for proj_dir in projects_dir.iterdir():
            if not proj_dir.is_dir():
                continue
            try:
                for f in proj_dir.iterdir():
                    if f.suffix != ".jsonl" or f.parent.name == "subagents":
                        continue
                    try:
                        mtime = f.stat().st_mtime
                        if mtime >= cutoff and mtime > newest_mtime:
                            newest_mtime = mtime
                            newest_path = f
                    except OSError:
                        pass
            except OSError:
                pass
    except OSError:
        return

    if newest_path is None:
        return

    session_id = newest_path.stem
    topic, _ = _scan_session_head(newest_path)
    save_last_session(session_id, provider, newest_path.parent.name, topic or "")


# ── binary discovery ───────────────────────────────────────────────────────────


def _find_claude() -> str | None:
    """Find the claude binary, checking PATH and common install locations."""
    path = shutil.which("claude")
    if path:
        return path
    fallbacks = [
        _const._pw_home / ".local" / "bin" / "claude",  # claude install default
        _const._pw_home / ".npm-global" / "bin" / "claude",  # npm --global-prefix
        Path("/opt/homebrew/bin/claude"),  # Homebrew on Apple Silicon
        Path("/usr/local/bin/claude"),  # Homebrew on Intel / manual
    ]
    for p in fallbacks:
        if p.exists() and os.access(p, os.X_OK):
            return str(p)
    return None


# ── account sweep ──────────────────────────────────────────────────────────────


def _sweep_existing_accounts() -> bool:
    """Repair any accounts that still have real dirs where symlinks are expected."""
    changed = False
    for acct in list_accounts():
        account_home, account_claude = resolve_account(acct)
        meta = load_account_meta(account_home)

        if meta is not None:
            for pid in meta["providers"]:
                prov = _const.PROVIDERS.get(pid)
                if prov is None:
                    continue
                main_dot = _const.MAIN_HOME / prov["dot_dir"]
                acct_dot = account_home / prov["dot_dir"]
                for name in prov["symlink_dirs"]:
                    src = main_dot / name
                    dst = acct_dot / name
                    if _ensure_symlinked_dir(name, src, dst, acct_dot):
                        changed = True
        else:
            # Legacy account (no account.json at all) — fall back to Claude-only
            for name in _const.SYMLINK_DIRS:
                src = _const.MAIN_CLAUDE / name
                dst = account_claude / name
                if _ensure_symlinked_dir(name, src, dst, account_claude):
                    changed = True
    return changed


# ── environment construction ───────────────────────────────────────────────────


def _build_alt_env(account: str = "default") -> dict:
    """Return a copy of the environment with HOME set to the account home."""
    if account == _const._NATIVE_ACCOUNT:
        env = os.environ.copy()
        _apply_oauth_token_to_env(env, _const._NATIVE_ACCOUNT, account_home=None)
        return env
    account_home, _ = resolve_account(account)

    # Decide up front whether to do *any* keychain ops. When the account is
    # in keychain mode AND has an OAuth token bridge in place, claude reads
    # the token from env and never touches the keychain — so reconcile and
    # unlock are both wasted work. Worse, both can trigger
    # "user interaction is not allowed" errors in non-GUI contexts (rover-
    # spawned tmux sessions, SSH, headless launches) when the partition
    # list isn't pinned (we removed that pin in v1.2.1 to avoid a forced
    # macOS-password prompt during --config).
    meta = load_account_meta(account_home)
    has_oauth_token = _load_oauth_token(account, account_home) is not None
    keychain_mode = _uses_keychain(meta)
    skip_keychain_ops = sys.platform == "darwin" and keychain_mode and has_oauth_token

    # Launch-time drift repair: silently reconcile (A,B,C,D) before unlocking.
    # No-op when state is consistent; shells out only when drift is detected.
    # Invariants §5.1–§5.4 are established here for every non-native launch.
    if sys.platform == "darwin" and not skip_keychain_ops:
        try:
            _reconcile_keychain_state(account_home, account, desired=None)
        except KeychainError as e:
            print(f"altergo: keychain reconcile error: {e}", file=sys.stderr)
            # Continue — _unlock_account_keychain below will give a better error
            # if isolation is still expected.
        # Reload meta in case reconcile coerced legacy A or rewrote it.
        meta = load_account_meta(account_home)
        keychain_mode = _uses_keychain(meta)

    if sys.platform == "darwin" and keychain_mode and not has_oauth_token:
        try:
            _unlock_account_keychain(account_home, account)
        except KeychainError as e:
            print(f"altergo: {e}", file=sys.stderr)
            sys.exit(1)
    env = os.environ.copy()
    env["HOME"] = str(account_home)
    acct_local_bin = account_home / ".local" / "bin"
    if acct_local_bin.exists():
        acct_local_bin_str = str(acct_local_bin)
        path_dirs = env.get("PATH", "").split(":")
        if acct_local_bin_str not in path_dirs:
            env["PATH"] = acct_local_bin_str + ":" + env.get("PATH", "")
    _apply_oauth_token_to_env(env, account, account_home=account_home)
    return env


# ── tmux helpers ───────────────────────────────────────────────────────────────


def _tmux_available() -> bool:
    """Return True if tmux is installed and reachable on PATH."""
    return shutil.which("tmux") is not None


_TMUX_UNSAFE_RE = re.compile(r"[^A-Za-z0-9_\-/]")


def _sanitize_tmux_segment(raw: str) -> str:
    """Return a tmux-safe version of a single name segment."""
    if not raw:
        return "unknown"
    cleaned = _TMUX_UNSAFE_RE.sub("-", raw).strip("-")
    return cleaned or "unknown"


def _tmux_session_name(account: str, provider: str, project: str | None = None) -> str:
    """Return a tmux session name ``<project>/<account>/<provider>``.

    Matches rover's _derive_session_name so sessions started directly via
    altergo line up with sessions started via rover.
    """
    if project is None:
        project = Path.cwd().name or "project"
    return f"{_sanitize_tmux_segment(project)}/{_sanitize_tmux_segment(account)}/{_sanitize_tmux_segment(provider)}"


def _tmux_unique_session_name(base: str) -> str:
    """Return a tmux session name that does not collide with any existing session."""
    try:
        result = subprocess.run(
            ["tmux", "list-sessions", "-F", "#{session_name}"],
            capture_output=True,
            text=True,
        )
        existing = set(result.stdout.splitlines())
    except Exception:
        return base

    if base not in existing:
        return base

    n = 2
    while True:
        candidate = f"{base}-{n}"
        if candidate not in existing:
            return candidate
        n += 1


def _build_tmux_cmd(inner_cmd: list, env: dict, session_name: str, cwd: str | None = None) -> list:
    """Wrap *inner_cmd* in a ``tmux new-session`` call."""
    # Build a POSIX shell wrapper: run the command, then pause for Enter before
    # the tmux session closes so the provider's exit screen stays visible until
    # the user dismisses it. Signal exits (130/131) skip the prompt.
    inner_shell = " ".join(shlex.quote(arg) for arg in inner_cmd)
    wrapper = (
        # Disable tmux mouse capture so clicks/scrolls pass through to the UI
        # behind the terminal (e.g. browser-based Claude chat).
        "tmux set-option mouse off 2>/dev/null; "
        f"{inner_shell}; _ret=$?; "
        # On clean exit (0): pause so the provider's exit page stays visible
        # before tmux tears down the alternate screen and returns to the caller.
        'if [ "$_ret" -eq 0 ]; then '
        r'printf "\n\033[2m  ↩  Press Enter to return to your terminal\033[0m" >&2; '
        "read _ag_dummy; "
        # On signal exits (130 = Ctrl-C, 131 = SIGQUIT): return immediately —
        # the user is bailing out and doesn't want a prompt.
        'elif [ "$_ret" -ne 130 ] && [ "$_ret" -ne 131 ]; then '
        r'printf "\n\033[0;31m  Session exited with code %d — press Enter to close\033[0m\n" "$_ret" >&2; '
        "read _ag_dummy; "
        'fi; exit "$_ret"'
    )
    tmux_cmd = ["tmux", "new-session", "-s", session_name]
    if cwd:
        tmux_cmd += ["-c", cwd]
    for key in ("HOME", "PATH"):
        if key in env:
            tmux_cmd += ["-e", f"{key}={env[key]}"]
    tmux_cmd += ["--", "sh", "-c", wrapper]
    return tmux_cmd


# ── launch functions ───────────────────────────────────────────────────────────


def launch_claude(
    account: str = "default",
    args=None,
    provider: str | None = None,
    force_tmux: bool = False,
    cwd: "str | Path | None" = None,
):
    """Launch a provider CLI with account HOME, passing args through unchanged."""
    account_home, _ = resolve_account(account)

    # Resolve provider
    if provider is None:
        if account == _const._NATIVE_ACCOUNT:
            # For native, prefer a persisted choice (altergo native --default-provider <id>)
            # if its binary is still on PATH; otherwise fall back to detecting the first
            # provider whose binary is on PATH and whose dot-dir exists in MAIN_HOME.
            # This matches build_launcher_menu's presence check so launcher and CLI agree,
            # and avoids reading ~/account.json which belongs to the user, not to altergo.
            _pinned = load_native_default_provider()
            if _pinned is not None:
                _pp = _const.PROVIDERS.get(_pinned)
                if _pp and shutil.which(_pp["binary"]):
                    provider = _pinned
            if provider is None:
                for _pid, _prov in _const.PROVIDERS.items():
                    if (_const.MAIN_HOME / _prov["dot_dir"]).exists() and shutil.which(_prov["binary"]):
                        provider = _pid
                        break
            if provider is None:
                sys.exit(
                    "altergo: no provider detected in the real $HOME.\n"
                    "  Specify one explicitly: altergo native <provider>\n"
                    f"  Known providers: {', '.join(_const.PROVIDERS)}"
                )
        else:
            meta = load_account_meta(account_home)
            provider = meta["default_provider"] if meta is not None else "claude"
    elif account != _const._NATIVE_ACCOUNT:
        # Explicit provider requested — reject if the account hasn't installed it.
        meta = load_account_meta(account_home)
        if meta is not None and provider not in meta["providers"]:
            sys.exit(
                f"altergo: account '{account}' does not have provider '{provider}' installed.\n"
                f"  Available: {', '.join(meta['providers'])}\n"
                f"  Add it with: altergo {account} --add-provider {provider}"
            )

    # Find the binary
    if provider == "claude":
        binary_path = _find_claude()
        if not binary_path:
            sys.exit(
                "altergo: 'claude' not found in PATH or common install locations.\n"
                "  If you just opened this terminal, your shell may still be initializing.\n"
                "  Wait a moment and try again, or open a new tab."
            )
    else:
        prov = _const.PROVIDERS.get(provider)
        if prov is None:
            print(f"altergo: unknown provider '{provider}'.", file=sys.stderr)
            sys.exit(1)
        binary_path = shutil.which(prov["binary"])
        if not binary_path:
            sys.exit(f"altergo: '{prov['binary']}' not found in PATH.\n  Install {prov['display_name']} and try again.")

    env = _build_alt_env(account)

    # Validate cwd early so we can emit the notice before the banner.
    launch_cwd: str | None = None
    if cwd is not None:
        _cwd_path = Path(cwd)
        if _cwd_path.is_dir():
            launch_cwd = str(_cwd_path)
        else:
            print(_c(C("dim"), f"  altergo: session cwd '{cwd}' no longer exists — launching from current directory"))

    # Translate --yolo / --yolo-resume into provider-native flags.
    extra_prefix, raw_args, extra_suffix = _translate_yolo_flags(provider, list(args or []))
    cmd = [binary_path] + extra_prefix + raw_args + extra_suffix
    # Kick off the background PyPI check (no-op if opt-out or not yet due)
    # BEFORE the banner so the cache from a previous run drives the nag.
    maybe_refresh_update_cache()
    first_launch_notice_if_needed()
    # Native account runs with the real $HOME — the HOME isolation notice
    # doesn't apply and would be misleading.
    if account != _const._NATIVE_ACCOUNT:
        home_change_notice_if_needed()
    _pack_name = load_animation_pack()
    _pack_cfg = _ANIM_PACKS.get(_pack_name, _ANIM_PACKS[_DEFAULT_ANIM_PACK])
    # "off" or providers that don't support animation (codex) → no twinkle
    _anim = 0.0 if _pack_name == "off" or _handoff_duration(provider) == 0.0 else _pack_cfg["duration"]
    show_banner(
        account,
        latest_version=get_cached_latest_version(),
        show_greeting=_load_bool_setting("show_greeting"),
        animate_duration=_anim,
        spinner_override=_pack_cfg.get("spinner"),
    )
    # For native, account_home == MAIN_HOME, so _sync_claude_mcps would merge
    # a file with itself — skip it.
    if provider == "claude" and account != _const._NATIVE_ACCOUNT:
        _sync_claude_mcps(account_home)

    print(_c(C("dim"), f"  Launching {_const.PROVIDERS[provider]['display_name']}..."))

    # Wrap in a tmux session when the setting is on and we're not already inside tmux.
    run_env = env
    use_tmux = force_tmux or _load_bool_setting("tmux_session", default=False)
    if force_tmux and os.environ.get("TMUX"):
        print(_c(C("dim"), "  altergo portal: already inside a tmux session — launching directly"))
    if use_tmux and not os.environ.get("TMUX"):
        if _tmux_available():
            sname = _tmux_unique_session_name(_tmux_session_name(account, provider))
            cmd = _build_tmux_cmd(cmd, env, sname, cwd=launch_cwd)
            run_env = None  # tmux runs in the caller's real env; account env is in -e flags
            # When tmux owns the cwd (-c flag), subprocess.run must not also set
            # it — the outer tmux process runs from the caller's directory.
            launch_cwd = None
            print(_c(C("dim"), f"  tmux session: {sname}  (detach: Ctrl-b d  ·  quit: type 'exit' or Ctrl-C)"))
        else:
            print(
                _c(
                    C("dim"),
                    "  altergo: tmux not found — running without session persistence.\n"
                    "  Install with: brew install tmux",
                ),
                file=sys.stderr,
            )

    launch_wall = time.time()
    result = subprocess.run(cmd, env=run_env, cwd=launch_cwd)
    # Record the last session so `altergo --star` works with no ID argument.
    try:
        _record_last_session_after_exit(provider, launch_wall)
    except Exception:
        pass  # never fail the user's exit due to tracking
    _print_launch_message()
    return result.returncode


def launch_shell(account: str = "default"):
    """Open an interactive shell with HOME set to account directory."""
    account_home, _ = resolve_account(account)
    env = _build_alt_env(account)
    # Prompt hint so users know they are in the alt context
    shell = env.get("SHELL", "/bin/sh")
    shell_name = Path(shell).name
    # Prepend a marker to PS1 / PROMPT so the user sees they are in altergo context.
    # We set it in env; the shell will use it if no .bashrc/.zshrc overrides it.
    label = f"altergo:{account}"
    if shell_name in ("bash", "sh"):
        env["PS1"] = env.get("PS1", r"\u@\h:\w\$ ").lstrip()
        env["PS1"] = f"({label}) {env['PS1']}"
    elif shell_name == "zsh":
        env["PROMPT"] = f"({label}) {env.get('PROMPT', '%n@%m %~ %# ')}"
    maybe_refresh_update_cache()
    first_launch_notice_if_needed()
    # Native account runs with the real $HOME — the HOME isolation notice
    # doesn't apply and would be misleading.
    if account != _const._NATIVE_ACCOUNT:
        home_change_notice_if_needed()
    # Shell starts effectively instantly, so no twinkle animation — but
    # keep the greeting + update nag for consistency with other launch paths.
    show_banner(
        account,
        latest_version=get_cached_latest_version(),
        show_greeting=_load_bool_setting("show_greeting"),
    )
    if account == _const._NATIVE_ACCOUNT:
        print(_c(C("command"), "Entering altergo shell [native] — real $HOME, no isolation"))
    else:
        print(_c(C("command"), f"Entering altergo shell [{account}] (HOME={account_home})"))
    print(_c(C("dim"), "Run 'exit' or Ctrl-D to return to your primary account.\n"))

    shell_cmd = [shell]
    print(_c(C("dim"), f"  Starting shell ({shell_name})..."))
    run_env = env
    if _load_bool_setting("tmux_session", default=False) and not os.environ.get("TMUX"):
        if _tmux_available():
            sname = _tmux_unique_session_name(_tmux_session_name(account, "shell"))
            shell_cmd = _build_tmux_cmd(shell_cmd, env, sname)
            run_env = None
            print(_c(C("dim"), f"  tmux session: {sname}  (detach: Ctrl-b d  ·  quit: type 'exit' or Ctrl-C)"))
        else:
            print(
                _c(
                    C("dim"),
                    "  altergo: tmux not found — running without session persistence.\n"
                    "  Install with: brew install tmux",
                ),
                file=sys.stderr,
            )

    result = subprocess.run(shell_cmd, env=run_env)
    _print_launch_message()
    return result.returncode


def launch_command(account: str = "default", cmd_args=None):
    """Run an arbitrary command with HOME set to account directory."""
    if not cmd_args:
        print(_c(31, "altergo -- requires a command. Example: altergo -- gh auth login"), file=sys.stderr)
        sys.exit(1)
    cmd_path = shutil.which(cmd_args[0])
    if not cmd_path:
        print(_c(31, f"altergo: '{cmd_args[0]}' not found in PATH"), file=sys.stderr)
        sys.exit(1)
    env = _build_alt_env(account)
    # Native account runs with the real $HOME — the HOME isolation notice
    # doesn't apply and would be misleading.
    if account != _const._NATIVE_ACCOUNT:
        home_change_notice_if_needed()

    inner_cmd = [cmd_path] + cmd_args[1:]
    print(_c(C("dim"), f"  Running {Path(cmd_path).name}..."))
    run_env = env
    if _load_bool_setting("tmux_session", default=False) and not os.environ.get("TMUX"):
        if _tmux_available():
            sname = _tmux_unique_session_name(_tmux_session_name(account, Path(cmd_path).name))
            inner_cmd = _build_tmux_cmd(inner_cmd, env, sname)
            run_env = None
            print(_c(C("dim"), f"  tmux session: {sname}  (detach: Ctrl-b d  ·  quit: type 'exit' or Ctrl-C)"))
        else:
            print(
                _c(
                    C("dim"),
                    "  altergo: tmux not found — running without session persistence.\n"
                    "  Install with: brew install tmux",
                ),
                file=sys.stderr,
            )

    result = subprocess.run(inner_cmd, env=run_env)
    _print_launch_message()
    return result.returncode


def _print_launch_message():
    """Print a witty handoff line to stderr before handing off to an AI session."""
    if not sys.stderr.isatty():
        return
    if not _load_bool_setting("show_goodbye"):
        return
    import altergo_greetings as _greet

    emoji, msg = _greet.pick_goodbye()
    grad = THEMES.get(get_current_theme(), THEMES[_DEFAULT_THEME])["banner"]
    parts = []
    n = len(msg)
    for i, ch in enumerate(msg):
        t = i / max(n - 1, 1)
        col = _gradient_color(grad, t)
        parts.append(f"\033[38;2;{int(col[1:3], 16)};{int(col[3:5], 16)};{int(col[5:7], 16)}m{ch}")
    colored = "".join(parts) + "\033[0m"
    print(f"\n  {emoji}  {colored}\n", file=sys.stderr)
