import json
import os
import re
import shutil
import sys
import time
from datetime import datetime
from pathlib import Path

import altergo.constants as _const
from altergo._version import __version__
from altergo.keychain import (
    _KC_SERVICE,
    KeychainError,
    _apply_keychain_mode,
    _delete_account_keychain,
    _keychain_path,
    _keychain_prefs_path,
    _maybe_offer_oauth_token_setup,
    _reconcile_keychain_state,
    _sec,
)
from altergo.persistence import (
    _get_home_notice_shown,
    _mark_home_notice_shown,
    load_account_meta,
    load_last_session,
    load_settings,
    save_account_meta,
    star_session,
)
from altergo.theme import C, _c, _gradient_color, _link


def resolve_account(name: str) -> tuple:
    """Return (account_home, account_claude) for the given account name."""
    if name == _const._NATIVE_ACCOUNT:
        return _const.MAIN_HOME, _const.MAIN_CLAUDE
    account_home = _const.ACCOUNTS_DIR / name
    account_claude = account_home / ".claude"
    return account_home, account_claude


def list_accounts() -> list:
    """Return sorted list of account names that exist on disk."""
    if not _const.ACCOUNTS_DIR.exists():
        return []
    return sorted(p.name for p in _const.ACCOUNTS_DIR.iterdir() if p.is_dir() and not p.name.startswith("."))


def validate_account_name(name: str) -> None:
    """Raise SystemExit if name is invalid (bad chars, reserved word, leading dot)."""
    if not re.match(r"^[a-zA-Z0-9][a-zA-Z0-9_-]*$", name) or len(name) > 64:
        print(
            f"altergo: invalid account name '{name}'. "
            "Use letters, digits, - or _ only; must not start with a digit or special char.",
            file=sys.stderr,
        )
        sys.exit(1)
    if name in _const._RESERVED_NAMES:
        print(f"altergo: '{name}' is a reserved name. Choose a different account name.", file=sys.stderr)
        sys.exit(1)


def home_change_notice_if_needed() -> None:
    """One-time animated notice explaining the HOME isolation model."""
    if _get_home_notice_shown():
        return
    if not sys.stdout.isatty():
        _mark_home_notice_shown()
        return

    # Mark immediately so a crash or Ctrl-C never replays the animation.
    _mark_home_notice_shown()

    def _animated():
        import pyfiglet
        from rich.console import Console

        console = Console()
        cols = console.width
        rows = console.height

        # Fixed warm-orange gradient — intentionally theme-independent.
        GRAD = ["#ff6600", "#ffcc00"]

        # colour helpers
        def _rgb(h):
            return int(h[1:3], 16), int(h[3:5], 16), int(h[5:7], 16)

        _DARK = (5, 2, 0)  # warm near-black

        def _blend(hex_col, alpha):
            r2, g2, b2 = _rgb(hex_col)
            return (
                int(_DARK[0] + (r2 - _DARK[0]) * alpha),
                int(_DARK[1] + (g2 - _DARK[1]) * alpha),
                int(_DARK[2] + (b2 - _DARK[2]) * alpha),
            )

        def _render_text(text, stops, alpha, bold=False):
            n = len(text)
            pfx = "1;" if bold else ""
            parts = []
            for i, ch in enumerate(text):
                col = _gradient_color(stops, i / max(n - 1, 1))
                r, g, b = _blend(col, alpha)
                parts.append(f"\033[{pfx}38;2;{r};{g};{b}m{ch}")
            return "".join(parts) + "\033[0m"

        def _cpad(w):
            """Spaces to visually centre text of display-width w."""
            return " " * max(0, (cols - w) // 2)

        def _w(s):
            sys.stdout.write(s)
            sys.stdout.flush()

        # build figlet "Welcome"
        raw = None
        for font in ("slant", "standard", "smslant"):
            try:
                raw = pyfiglet.Figlet(font=font).renderText("Welcome")
                break
            except Exception:
                pass
        fig_lines = [ln for ln in (raw or "Welcome\n").splitlines() if ln.strip()]
        fig_w = max(len(ln.rstrip()) for ln in fig_lines)
        fig_total = sum(1 for ln in fig_lines for ch in ln if ch != " ")

        def _render_figlet(alpha):
            idx = 0
            out = []
            for ln in fig_lines:
                s = _cpad(fig_w)
                for ch in ln.rstrip():
                    if ch == " ":
                        s += " "
                    else:
                        t = idx / max(fig_total - 1, 1)
                        col = _gradient_color(GRAD, t)
                        r, g, b = _blend(col, alpha)
                        s += f"\033[1;38;2;{r};{g};{b}m{ch}\033[0m"
                        idx += 1
                out.append(s)
            return out

        # notice content
        NOTICE = [
            ("Each account runs in its own HOME folder —", False),
            ("like a separate desk for each AI identity.", False),
            ("", False),
            ("Tools like pip, cargo, gem, and yarn won't", False),
            ("see packages from your main account.", False),
            ("", False),
            ("altergo --settings  →  Credentials tab", True),
        ]
        HINT = "shown once  ·  press any key to continue"

        # vertical layout
        # rows: 1 emoji + 2 blank + figlet + 1 blank + NOTICE + 2 blank+hint
        content_h = 3 + len(fig_lines) + 1 + len(NOTICE) + 2
        top = max(1, (rows - content_h) // 2)

        # clear + hide cursor
        _w("\033[2J\033[H\033[?25l")

        # ── track terminal row (1-indexed) of every section for fade-out ────
        cur = 1

        if top > 0:
            _w("\n" * top)
            cur += top

        emoji_row = cur
        _w(f"\r{_cpad(2)}🏠\n\n")
        cur += 2  # emoji line + two \n → cursor now two below

        fig_row = cur

        # Print initial dark figlet (alpha=0) so lines occupy their rows.
        for ln in _render_figlet(0.0):
            _w(f"\r{ln}\033[K\n")
        cur += len(fig_lines)

        _w("\n")  # blank between figlet and notice
        cur += 1

        # Print blank placeholder rows for notice (filled by fade-in loop).
        notice_items = []
        n_lines = len(NOTICE)
        for li, (text, bold) in enumerate(NOTICE):
            item_row = cur
            cur += 1
            if not text:
                _w("\n")
                notice_items.append(None)
                continue
            t0 = 0.05 + 0.85 * (li / max(n_lines - 1, 1))
            stops = [
                _gradient_color(GRAD, max(0.0, t0 - 0.2)),
                _gradient_color(GRAD, min(1.0, t0 + 0.2)),
            ]
            notice_items.append({"row": item_row, "text": text, "stops": stops, "bold": bold})
            _w(f"\r{_cpad(len(text))}\033[K\n")  # blank placeholder

        _w("\n")
        cur += 1

        hint_row = cur
        hr, hg, hb = _blend(_gradient_color(GRAD, 0.5), 0.20)
        _w(f"\r{_cpad(len(HINT))}\033[38;2;{hr};{hg};{hb}m{HINT}\033[0m\n")
        cur += 1

        # Phase 1: figlet fades in (slow — 36 frames × 30 ms ≈ 1.1 s)
        FIG_IN = 36
        for step in range(1, FIG_IN + 1):
            alpha = step / FIG_IN
            _w(f"\033[{fig_row};1H")
            for ln in _render_figlet(alpha):
                _w(f"\r{ln}\033[K\n")
            time.sleep(0.030)

        # Phase 2: notice lines fade in one by one
        LINE_IN = 14
        for item in notice_items:
            if item is None:
                continue
            _w(f"\033[{item['row']};1H")
            for step in range(LINE_IN + 1):
                alpha = step / LINE_IN
                rendered = _render_text(item["text"], item["stops"], alpha, item["bold"])
                _w(f"\r{_cpad(len(item['text']))}{rendered}\033[K")
                time.sleep(0.018)

        # Phase 3: hold — wait up to 8 s for keypress
        import select
        import termios
        import tty

        fd = sys.stdin.fileno()
        try:
            old = termios.tcgetattr(fd)
            tty.setraw(fd)
            try:
                rdy, _, _ = select.select([sys.stdin], [], [], 8.0)
                if rdy:
                    sys.stdin.read(1)
            finally:
                termios.tcsetattr(fd, termios.TCSADRAIN, old)
        except Exception:
            time.sleep(8.0)

        # ── Phase 4: cascading top-to-bottom fade-out ─────────────────────────
        # Build ordered section list (top → bottom).
        fade_sections = [{"type": "emoji", "row": emoji_row}, {"type": "figlet"}]
        for item in notice_items:
            if item is None:
                continue
            fade_sections.append({"type": "text", **item})
        fade_sections.append({"type": "hint", "row": hint_row})

        WAVE_FRAMES = 32  # total frames for the whole wave
        STAGGER = 3  # frames between each section starting its fade
        FRAME_DT = 0.038

        for frame in range(WAVE_FRAMES):
            for si, sec in enumerate(fade_sections):
                start = si * STAGGER
                if frame < start:
                    continue
                alpha = max(0.0, 1.0 - (frame - start) / max(WAVE_FRAMES - start, 1))

                if sec["type"] == "emoji":
                    # Emoji colour can't be faded, so dim then blank it.
                    if alpha < 0.5:
                        _w(f"\033[{sec['row']};1H\r{_cpad(2)}  \033[K")
                    # else leave it visible

                elif sec["type"] == "figlet":
                    _w(f"\033[{fig_row};1H")
                    for ln in _render_figlet(alpha):
                        _w(f"\r{ln}\033[K\n")

                elif sec["type"] == "text":
                    rendered = _render_text(sec["text"], sec["stops"], alpha, sec["bold"])
                    _w(f"\033[{sec['row']};1H\r{_cpad(len(sec['text']))}{rendered}\033[K")

                elif sec["type"] == "hint":
                    hr2, hg2, hb2 = _blend(_gradient_color(GRAD, 0.5), 0.20 * alpha)
                    hint_s = f"\033[38;2;{hr2};{hg2};{hb2}m{HINT}\033[0m"
                    _w(f"\033[{sec['row']};1H\r{_cpad(len(HINT))}{hint_s}\033[K")

            time.sleep(FRAME_DT)

        # clear → banner
        _w("\033[2J\033[H")

    try:
        _animated()
    except Exception:
        # Plain fallback — never let the notice crash the launch path.
        dim, warn, cmd = C("dim"), C("warn"), C("command")
        print()
        print("  " + _c(warn, "Heads up (shown once):"))
        print("  " + _c(dim, "Each account runs in its own HOME folder — tools like pip, cargo,"))
        print("  " + _c(dim, "gem, and yarn won't see packages from your main account."))
        print()
        suffix = _c(dim, "  →  Credentials  →  Package Managers")
        print("  " + _c(dim, "Fix:  ") + _c(cmd, "altergo --settings") + suffix)
        print()
    finally:
        sys.stdout.write("\033[?25h")  # always restore cursor
        sys.stdout.flush()


def get_active_account() -> str | None:
    """Return the persisted active account name, or None if not set / no longer valid."""
    if not _const.SETTINGS_FILE.exists():
        return None
    try:
        data = json.loads(_const.SETTINGS_FILE.read_text())
        name = data.get("active_account")
        if name and isinstance(name, str):
            if name == _const._NATIVE_ACCOUNT:
                return name
            if (_const.ACCOUNTS_DIR / name).is_dir():
                return name
        return None
    except Exception:
        return None


def _native_supports_provider(provider_id: str) -> bool:
    """Return True if the native passthrough can launch ``provider_id`` right now.

    Native is a no-isolation passthrough — it can only launch a provider whose
    binary already exists on the user's real $PATH.
    """
    spec = _const.PROVIDERS.get(provider_id)
    return bool(spec and shutil.which(spec["binary"]))


def _account_for_provider(provider_id: str) -> str | None:
    """Return an account name suitable for launching sessions of ``provider_id``."""
    active = get_active_account()
    # Honor `altergo --use native` for auto-pick paths (--recall, --yolo-resume
    # case 1). Without this, setting native as the default account had no effect
    # on resume flows because list_accounts() never includes the native sentinel.
    if active == _const._NATIVE_ACCOUNT and _native_supports_provider(provider_id):
        return _const._NATIVE_ACCOUNT

    accounts = list_accounts()
    if not accounts:
        return None

    def _has_provider(acct_name: str) -> bool:
        meta = load_account_meta(_const.ACCOUNTS_DIR / acct_name)
        if meta is None:
            return provider_id == "claude"
        return provider_id in meta["providers"]

    if active and active in accounts and _has_provider(active):
        return active
    for acct in accounts:
        if _has_provider(acct):
            return acct
    return None


def set_active_account(name: str) -> None:
    """Persist active_account to SETTINGS_FILE without clobbering other keys."""
    _const.SETTINGS_FILE.parent.mkdir(parents=True, exist_ok=True)
    data = {}
    if _const.SETTINGS_FILE.exists():
        try:
            data = json.loads(_const.SETTINGS_FILE.read_text())
        except Exception:
            data = {}
    data["active_account"] = name
    tmp = _const.SETTINGS_FILE.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(data, indent=2))
    os.replace(str(tmp), str(_const.SETTINGS_FILE))


def _is_enabled(entry, overrides):
    """Return whether a catalog entry is enabled given the user's overrides."""
    return overrides.get(entry["id"], entry["default_on"])


def _ensure_nested_parent(rel, account_home):
    """For paths like .config/gh, ensure account_home/.config is a real directory."""
    p = Path(rel)
    if len(p.parts) < 2:
        return
    parent_name = p.parts[0]
    acct_parent = account_home / parent_name
    main_parent = _const.MAIN_HOME / parent_name
    if acct_parent.is_symlink():
        if acct_parent.resolve() == main_parent.resolve():
            acct_parent.unlink()
            acct_parent.mkdir(parents=True, exist_ok=True)
            print(f"  {_c(33, '↻')} Migrated ~/{parent_name}/ from wholesale symlink to managed dir")
    elif not acct_parent.exists():
        acct_parent.mkdir(parents=True, exist_ok=True)


def _apply_entry(entry, overrides, account_home):
    """Create or remove symlinks for one catalog entry based on current settings."""
    enabled = _is_enabled(entry, overrides)
    for rel in entry["paths"]:
        src = _const.MAIN_HOME / Path(rel)
        dst = account_home / Path(rel)
        if enabled:
            if not src.exists():
                continue
            _ensure_nested_parent(rel, account_home)
            if dst.is_symlink():
                if dst.resolve() == src.resolve():
                    pass
                else:
                    print(f"  {_c(33, '⚠')} ~/{rel} symlinked elsewhere — skipping")
                continue
            if dst.exists():
                print(f"  {_c(33, '⚠')} ~/{rel} has local data — remove it first to share")
                continue
            dst.symlink_to(src)
            print(f"  {_c(32, '✓')} Sharing ~/{rel}")
        else:
            if dst.is_symlink() and dst.resolve() == src.resolve():
                dst.unlink()
                print(f"  {_c(33, '✓')} Unshared ~/{rel}")


def _ensure_symlinked_dir(name: str, src: Path, dst: Path, account_claude: Path) -> bool:
    """Ensure dst is a symlink pointing to src, auto-migrating real dirs if needed."""
    # (a) Already correct symlink
    if dst.is_symlink():
        if dst.resolve() == src.resolve():
            return False
        # Symlinked elsewhere — leave alone (don't clobber user's intentional link)
        return False

    # (b) dst does not exist
    if not dst.exists():
        src.mkdir(parents=True, exist_ok=True)
        dst.parent.mkdir(parents=True, exist_ok=True)
        dst.symlink_to(src)
        return True

    # dst is a real directory (or file) at this point
    if not dst.is_dir():
        # It's a real file named the same as a dir entry — skip it safely
        return False

    dst_entries = list(dst.iterdir())

    # (c) Real empty dir
    if not dst_entries:
        dst.rmdir()
        src.mkdir(parents=True, exist_ok=True)
        dst.symlink_to(src)
        print(f"  Converted empty {name}/ to symlink")
        return True

    # dst is non-empty
    src_exists_and_nonempty = src.exists() and any(True for _ in src.iterdir())

    if not src_exists_and_nonempty:
        # (d) dst is real non-empty but src is absent/empty.
        # This should not happen for correctly set-up accounts (--config always
        # creates src first, then symlinks dst).  Silently moving would risk
        # data loss.  Warn and leave both untouched — run --config to repair.
        print(
            f"  warning: {name}/ is a real directory but shared store ({src}) is absent/empty. "
            f"Run 'altergo --config' to repair."
        )
        return False

    # (e) Both src and dst have content — merge with conflict quarantine
    quarantine_base = account_claude / f"{name}.altergo-conflict"
    for entry in list(dst.iterdir()):
        target = src / entry.name
        if not target.exists():
            shutil.move(str(entry), str(target))
        else:
            # Conflict: move to quarantine.
            # Ensure the quarantine base dir exists but do NOT pre-create the
            # entry's subdirectory — shutil.move needs the destination path to
            # not already exist as a directory (otherwise it moves inside it).
            quarantine_base.mkdir(parents=True, exist_ok=True)
            shutil.move(str(entry), str(quarantine_base / entry.name))
            print(f"  warning: conflict: {name}/{entry.name} preserved in {name}.altergo-conflict/")

    # Check if dst is now empty after moves
    remaining = list(dst.iterdir())
    if not remaining:
        dst.rmdir()
        dst.symlink_to(src)
        print(f"  Merged {name}/ into shared store")
        return True
    else:
        print(f"  warning: {name}/ has unresolved conflicts; not symlinked")
        return False


def _ensure_home_file_symlink(name: str, src: Path, dst: Path) -> None:
    """Ensure dst (account_home/<name>) is a symlink pointing to src (MAIN_HOME/<name>)."""
    if dst.is_symlink():
        if dst.resolve() == src.resolve():
            print(f"  {_c(32, '✓')} {name} already symlinked")
        else:
            print(f"  {_c(33, '⚠')} {name} symlinked elsewhere — skipping")
        return
    if not dst.exists():
        if src.exists():
            dst.symlink_to(src)
            print(f"  {_c(32, '✓')} Symlinked {name}")
        return
    # dst is a real file
    if not src.exists():
        # (d) Promote account file to main home so all accounts share it
        src.parent.mkdir(parents=True, exist_ok=True)
        shutil.move(str(dst), str(src))
        dst.symlink_to(src)
        print(f"  {_c(32, '✓')} Promoted {name} to shared location")
    else:
        # (e) Conflict — both are real files; don't clobber either
        print(f"  {_c(33, '⚠')} {name} exists in both account home and main home — remove one to share")


def _sync_claude_mcps(account_home: Path) -> None:
    """Sync mcpServers between MAIN_HOME/.claude.json and account_home/.claude.json."""
    main_cfg = _const.MAIN_HOME / ".claude.json"
    acct_cfg = account_home / ".claude.json"

    # Migration from symlink_home_files (v0.21.1): unsymlink, preserving content
    if acct_cfg.is_symlink():
        try:
            content = acct_cfg.read_text()
        except (OSError, FileNotFoundError):
            content = "{}"
        acct_cfg.unlink()
        acct_cfg.write_text(content)

    def _load(p):
        if not p.exists():
            return {}
        try:
            return json.loads(p.read_text())
        except (json.JSONDecodeError, OSError):
            return {}

    main_data = _load(main_cfg)
    acct_data = _load(acct_cfg)

    main_mcps = main_data.get("mcpServers", {})
    acct_mcps = acct_data.get("mcpServers", {})

    if not main_mcps and not acct_mcps:
        return

    # Union: main provides the base, account overrides on key conflict
    merged = {**main_mcps, **acct_mcps}

    if merged == main_mcps and merged == acct_mcps:
        return  # already in sync

    changed = False
    if main_mcps != merged:
        main_data["mcpServers"] = merged
        tmp = main_cfg.with_suffix(".tmp")
        with open(tmp, "w") as f:
            json.dump(main_data, f, indent=2)
            f.write("\n")
        os.replace(tmp, main_cfg)
        changed = True

    if acct_mcps != merged:
        acct_data["mcpServers"] = merged
        acct_cfg.parent.mkdir(parents=True, exist_ok=True)
        tmp = acct_cfg.with_suffix(".tmp")
        with open(tmp, "w") as f:
            json.dump(acct_data, f, indent=2)
            f.write("\n")
        os.replace(tmp, acct_cfg)
        changed = True

    if changed:
        count = len(merged)
        print(f"  {_c(32, '✓')} Synced {count} MCP server{'s' if count != 1 else ''}")


def do_star(session_id: str | None = None) -> None:
    """Star a session by ID, or the last exited session if no ID given."""
    if session_id is not None:
        from altergo.sessions import get_sessions

        sessions = get_sessions()
        match = next((s for s in sessions if s["id"] == session_id), None)
        if match is None:
            print(f"altergo: session '{session_id}' not found.", file=sys.stderr)
            sys.exit(1)
        star_session(match["id"], match.get("provider", "claude"), match["project"], match.get("topic") or "")
        topic_hint = match.get("topic") or "(no topic)"
        print(f"  {_c(C('accent'), '★')} Starred {_c(C('command'), match['id'])} [{match.get('provider', 'claude')}]")
        print(_c(C("dim"), f"  {topic_hint}"))
        return

    last = load_last_session()
    if last is None:
        print(
            "altergo: no recent session found.\n"
            "  Run a conversation first, or provide a session ID:\n"
            "  altergo --star <session-id>",
            file=sys.stderr,
        )
        sys.exit(1)

    star_session(last["id"], last.get("provider", "claude"), last.get("project", ""), last.get("topic") or "")
    topic_hint = last.get("topic") or "(no topic)"
    print(f"  {_c(C('accent'), '★')} Starred {_c(C('command'), last['id'])} [{last.get('provider', 'claude')}]")
    print(_c(C("dim"), f"  {topic_hint}"))


def _apply_provider_setup(
    account_home: Path, provider_id: str, *, account_name: str = "", silent: bool = False
) -> None:
    """Idempotently install symlinks + credential check for one provider under account_home."""
    prov = _const.PROVIDERS.get(provider_id)
    if prov is None:
        raise ValueError(f"unknown provider id: {provider_id!r}")

    main_dot_dir = _const.MAIN_HOME / prov["dot_dir"]
    acct_dot_dir = account_home / prov["dot_dir"]

    if not silent:
        print()
        print(_c(1, _c(36, f"=== Provider: {prov['display_name']} ===")))

    acct_dot_dir.mkdir(parents=True, exist_ok=True)

    for name in prov["symlink_dirs"]:
        src = main_dot_dir / name
        dst = acct_dot_dir / name

        if dst.is_symlink():
            target = dst.resolve()
            if not silent:
                if target == src.resolve():
                    print(f"  {_c(32, '✓')} {name}/ already symlinked")
                else:
                    print(f"  {_c(33, '⚠')} {name}/ symlinked to {target} (expected {src})")
            continue

        was_absent = not dst.exists()
        _ensure_symlinked_dir(name, src, dst, acct_dot_dir)
        if was_absent and dst.is_symlink() and not silent:
            print(f"  {_c(32, '✓')} Symlinked {name}/")

    for name in prov["symlink_files"]:
        src = main_dot_dir / name
        dst = acct_dot_dir / name

        if not src.exists():
            continue

        if dst.is_symlink():
            if not silent:
                print(f"  {_c(32, '✓')} {name} already symlinked")
            continue

        if dst.exists():
            dst.unlink()

        dst.symlink_to(src)
        if not silent:
            print(f"  {_c(32, '✓')} Symlinked {name}")

    for name in prov.get("symlink_home_files", []):
        _ensure_home_file_symlink(name, _const.MAIN_HOME / name, account_home / name)

    creds = acct_dot_dir / prov["credentials_file"]
    if not silent:
        print()
        if creds.exists():
            print(f"  {_c(32, '✓')} {prov['display_name']} credentials found")
        else:
            print(f"  {_c(33, '⚠')} No {prov['display_name']} credentials found.")
            hint_cmd = f"altergo {account_name}" if account_name and account_name != "default" else "altergo"
            print(f"     Run '{hint_cmd}' to authenticate.\n")

    if provider_id == "claude":
        _sync_claude_mcps(account_home)


def _remove_provider_setup(account_home: Path, provider_id: str, *, silent: bool = False) -> None:
    """Remove the symlinks installed by :func:`_apply_provider_setup` for one provider."""
    prov = _const.PROVIDERS.get(provider_id)
    if prov is None:
        return

    acct_dot_dir = account_home / prov["dot_dir"]

    for name in prov["symlink_dirs"]:
        dst = acct_dot_dir / name
        if dst.is_symlink():
            dst.unlink()
            if not silent:
                print(f"  {_c(33, '✓')} Removed symlink: {prov['dot_dir']}/{name}/")

    for name in prov["symlink_files"]:
        dst = acct_dot_dir / name
        if dst.is_symlink():
            dst.unlink()
            if not silent:
                print(f"  {_c(33, '✓')} Removed symlink: {prov['dot_dir']}/{name}")

    for name in prov.get("symlink_home_files", []):
        dst = account_home / name
        src = _const.MAIN_HOME / name
        try:
            if dst.is_symlink() and dst.resolve() == src.resolve():
                dst.unlink()
                if not silent:
                    print(f"  {_c(33, '✓')} Removed symlink: {name}")
        except OSError:
            pass


def _warn_none_mode_cancel(*, interactive: bool) -> None:
    """Print the 'none' mode Cancel warning.

    In interactive sessions (after the picker confirms the choice) the full
    3-line warning is printed to stdout in warn color.  In non-interactive /
    scripted invocations a single-line version goes to stderr so it appears in
    CI logs without polluting stdout pipelines.
    """
    if interactive:
        print()
        print(_c(C("warn"), "  ⚠  In 'none' mode, macOS may prompt apps for a keychain password"))
        print(_c(C("warn"), '     they don\'t have. ALWAYS click Cancel — never "Reset To Defaults"'))
        print(_c(C("warn"), "     (that nukes your real login keychain — totally unrelated, very destructive)."))
        print()
    else:
        print(
            _c(
                C("warn"),
                "altergo: none mode — if macOS prompts for a keychain password, "
                "click Cancel (never Reset To Defaults — that deletes your real login keychain).",
            ),
            file=sys.stderr,
        )


def configure_account(account: str = "default", provider: str = "claude", *, keychain_arg: str | None = None):
    """Configure (or reconfigure) an altergo account."""
    from altergo.ui import _status_wrap, show_banner

    if account == _const._NATIVE_ACCOUNT:
        print(
            f"altergo: '{_const._NATIVE_ACCOUNT}' is a reserved passthrough account that uses the real $HOME. "
            "It cannot be configured.",
            file=sys.stderr,
        )
        sys.exit(1)
    account_home, account_claude = resolve_account(account)
    show_banner(account)
    header = f"altergo v{__version__} · " + _link("https://pixelabs.net", "pixelabs.net")
    print(_c(C("dim"), header))
    print(_c(C("header"), f"=== Altergo — Config ({account}) ==="))
    print()

    # Load existing metadata for created timestamp preservation
    meta = load_account_meta(account_home)

    # Surface current keychain mode so the user knows what they're changing.
    if sys.platform == "darwin":
        current_kc = (meta or {}).get("keychain") or "keychain"  # default = keychain
        if current_kc == "keychain":
            label = "keychain (per-account keychain)"
        else:
            label = "none (flat files only)"
        print(_c(C("dim"), f"  Current keychain: {label}"))

    # 1. Create account home
    if not account_home.exists():
        account_home.mkdir(parents=True)
        print(f"  {_c(32, '✓')} Created account home: {account_home}")
    else:
        print(f"  {_c(32, '✓')} Account home exists: {account_home}")

    # 2. Wire the requested provider
    _apply_provider_setup(account_home, provider, account_name=account)

    # 3. Apply catalog entries (shared CLI tool credentials) at account_home level
    overrides = load_settings()

    def _apply_catalog_entries():
        for entry in _const.CATALOG:
            _apply_entry(entry, overrides, account_home)

    _status_wrap("Linking shared credentials…", _apply_catalog_entries)

    # 5. Keychain mode (macOS only). Default: keychain (per-account keychain).
    keychain_mode = "keychain"  # default since v0.45.0
    if sys.platform == "darwin":
        if keychain_arg is not None:
            # v0.46.0: only "keychain" and "none" are accepted. The CLI parser
            # already rejects old names with an error, but callers that bypass
            # the parser (e.g. tests using configure_account directly) should still
            # receive a hard failure so misuse is caught early.
            if keychain_arg not in ("keychain", "none"):
                print(
                    f"altergo: invalid keychain mode '{keychain_arg}' — "
                    "must be 'keychain' or 'none' (v0.46.0 removed old aliases)",
                    file=sys.stderr,
                )
                sys.exit(1)
            keychain_mode = keychain_arg
        elif sys.stdin.isatty():
            # Interactive prompt. Re-running --config always re-prompts so the
            # user can switch modes; the current value (or "keychain" for a
            # new account) is the default. The explanation merges keychain
            # semantics with the SSH-access implications so the user can pick
            # with full context — no second SSH-vs-keychain prompt later.
            current_mode = (meta or {}).get("keychain") or "keychain"
            print()
            print(_c(C("header"), "  Keychain mode (macOS)"))
            print(_c(2, "  ─────────────────────"))
            print(_c(2, "  How this account stores credentials:"))
            print()
            print(_c(2, "    keychain  per-account macOS keychain. Tokens encrypted at rest."))
            print(_c(2, "             altergo stores the unlock password in your main login"))
            print(_c(2, "             keychain. First launch at the desk may show a one-time"))
            print(_c(2, "             'Always Allow' macOS dialog — click Always Allow once"))
            print(_c(2, "             and you won't see it again. Over SSH, altergo will offer"))
            print(_c(2, "             to set up an OAuth token bridge after this prompt."))
            print()
            print(_c(2, "    none     flat files in the account home (mode 0600). The"))
            print(_c(2, "             per-account keychain is intentionally locked, so when"))
            print(_c(2, "             a provider tries to write to it macOS will pop an"))
            print(_c(2, "             'Allow access' dialog asking for a keychain password."))
            print(_c(2, "             Always click Cancel — never 'Reset To Defaults'."))
            print(_c(2, "             Providers fall back to flat files and your session"))
            print(_c(2, "             continues. Works over SSH and on the desk identically."))
            print()
            print(_c(C("dim"), "  Details: https://github.com/thepixelabs/altergo/blob/main/docs/ssh-auth.md"))
            print()
            if current_mode == "keychain":
                # Default = stay in keychain mode. [Y/n] convention.
                prompt = f"  Current: {_c(1, 'keychain')}.  Use keychain mode? [Y/n] "
                default_is_keychain = True
            else:
                # Default = stay none. [y/N] convention so the highlighted
                # default matches the user's existing choice.
                prompt = f"  Current: {_c(1, 'none')}.  Switch to keychain mode? [y/N] "
                default_is_keychain = False
            try:
                answer = input(prompt).strip().lower()
            except (KeyboardInterrupt, EOFError):
                answer = ""
            if answer in ("y", "yes"):
                keychain_mode = "keychain"
            elif answer in ("n", "no"):
                keychain_mode = "none"
            else:
                keychain_mode = "keychain" if default_is_keychain else "none"
        elif meta and meta.get("keychain") == "none":
            # Non-interactive re-config of a none account — preserve.
            keychain_mode = "none"

        # Show Cancel warning when none mode is chosen (interactive or non-interactive).
        if keychain_mode == "none":
            _warn_none_mode_cancel(interactive=sys.stdin.isatty())

        # Repair any pre-existing drift before applying the user's intent.
        # desired=None is cheap when state is consistent (no security calls).
        try:
            _reconcile_keychain_state(account_home, account, desired=None)
            # Reload meta in case the reconciler updated A.
            meta = load_account_meta(account_home)
        except KeychainError as e:
            print(f"  {_c(33, '⚠')} Keychain reconcile warning: {e}", file=sys.stderr)

        try:
            _apply_keychain_mode(account_home, account, keychain_mode, prior_meta=meta)
        except KeychainError as e:
            print(f"  {_c(33, '⚠')} Keychain setup failed: {e}", file=sys.stderr)
            print("    Continuing with none mode (flat-file credentials).", file=sys.stderr)
            keychain_mode = "none"
        else:
            if keychain_mode == "keychain":
                print(f"  {_c(32, '✓')} Per-account keychain created/verified")
                print(
                    _c(
                        2,
                        "  NOTE: keychain mode requires your login keychain to be unlocked "
                        "(standard on GUI login; check Keychain Access → Preferences if auto-lock is aggressive)",
                    )
                )

    # 4. Save account metadata.  New writes emit v3 (providers list + default).
    #    Existing v3 accounts preserve extra providers beyond the single one
    #    passed into configure_account — configure_account only rewrites the default.
    prior_providers: list = []
    if meta is not None:
        prior_providers = list(meta.get("providers", []))
    providers_list = [provider] + [p for p in prior_providers if p != provider]
    meta_to_save: dict = {
        "version": 3,
        "providers": providers_list,
        "default_provider": provider,
        "created": (meta.get("created") if meta else None) or datetime.now().isoformat(timespec="seconds"),
    }
    # Always record keychain key so A is never absent after first --config touch.
    meta_to_save["keychain"] = keychain_mode  # "none" or "keychain"
    save_account_meta(account_home, meta_to_save)

    # Offer SSH-friendly OAuth token setup now that the account is fully
    # configured. Only fires for claude + keychain mode + no existing token +
    # interactive TTY; silently no-ops in every other case.
    _maybe_offer_oauth_token_setup(account, account_home, provider, keychain_mode)

    launch_cmd = f"altergo {account}" if account != "default" else "altergo"
    print()
    print(_c(32, "Config complete!"))
    print(f"  Run {_c(1, launch_cmd)} to start a session  ·  {_c(1, 'altergo --resume')} to pick one")
    print()
    print(_c(2, "  Isolates credentials per provider. Shares AWS, GCP, Docker, and kubectl by default."))
    print(_c(2, f"  Change sharing settings: {_c(0, 'altergo --settings')}"))


def _reconcile_orphan_dot_dir(account_home: Path, provider_id: str) -> None:
    """Merge SHAREABLE orphan data from an account-local provider dot-dir into MAIN_HOME."""
    prov = _const.PROVIDERS.get(provider_id)
    if prov is None:
        return
    acct_dot = account_home / prov["dot_dir"]
    if acct_dot.is_symlink() or not acct_dot.exists():
        return
    if not acct_dot.is_dir():
        return

    # Only entries that will be symlinked belong in the shared MAIN store.
    # Everything else is per-account state — particularly the credentials file.
    shareable = set(prov.get("symlink_dirs", [])) | set(prov.get("symlink_files", []))

    main_dot = _const.MAIN_HOME / prov["dot_dir"]
    main_dot.mkdir(parents=True, exist_ok=True)

    orphan_root = account_home / f"{prov['dot_dir']}.orphaned" / datetime.now().strftime("%Y%m%dT%H%M%S")
    moved = 0
    archived = 0

    def _move_recursive(src: Path, dst: Path, rel: Path) -> None:
        nonlocal moved, archived
        if dst.exists():
            # Target already exists in MAIN — archive the account-local loser.
            archive_dst = orphan_root / rel
            archive_dst.parent.mkdir(parents=True, exist_ok=True)
            try:
                src.rename(archive_dst)
            except OSError:
                # Cross-device fallback: copy + remove
                import shutil as _sh

                try:
                    if src.is_dir():
                        _sh.copytree(src, archive_dst, symlinks=True, dirs_exist_ok=True)
                        _sh.rmtree(src)
                    else:
                        _sh.copy2(src, archive_dst)
                        src.unlink()
                except Exception:
                    return
            archived += 1
            return
        try:
            dst.parent.mkdir(parents=True, exist_ok=True)
            src.rename(dst)
            moved += 1
        except OSError:
            import shutil as _sh

            try:
                if src.is_dir():
                    _sh.copytree(src, dst, symlinks=True)
                    _sh.rmtree(src)
                else:
                    _sh.copy2(src, dst)
                    src.unlink()
                moved += 1
            except Exception:
                return

    for child in list(acct_dot.iterdir()):
        if child.name not in shareable:
            # Leave in place: credentials, local state, unknown children.
            continue
        rel = Path(child.name)
        target = main_dot / rel
        _move_recursive(child, target, rel)

    # Do NOT remove the local dot-dir — it still holds credentials and
    # per-account state. The subsequent _apply_provider_setup will install
    # symlinks for catalog entries INSIDE this dir.

    if moved or archived:
        print(
            f"  {_c(32, '✓')} Reconciled orphan {prov['dot_dir']}/  "
            f"({moved} merged into MAIN, {archived} archived to {prov['dot_dir']}.orphaned/)"
        )
        print(
            _c(
                C("dim"),
                f"     Credentials and local state in {prov['dot_dir']}/ were NOT moved — they stay per-account.",
            )
        )


def do_add_provider(account: str, provider_id: str) -> int:
    """Install an additional provider on an existing altergo account."""
    account_home, _ = resolve_account(account)
    meta = load_account_meta(account_home)
    if meta is None:
        print(
            f"altergo: account '{account}' has no account.json. Run 'altergo --config {account}' first.",
            file=sys.stderr,
        )
        return 1

    if provider_id in meta["providers"]:
        print(_c(C("dim"), f"  altergo: account '{account}' already has provider '{provider_id}'."))
        return 0

    print(_c(C("header"), f"=== Altergo — add provider '{provider_id}' to '{account}' ==="))
    print()

    _reconcile_orphan_dot_dir(account_home, provider_id)
    _apply_provider_setup(account_home, provider_id, account_name=account)

    new_meta = dict(meta)
    new_meta["version"] = 3
    new_meta["providers"] = list(meta["providers"]) + [provider_id]
    new_meta["default_provider"] = meta["default_provider"]
    save_account_meta(account_home, new_meta)

    print()
    print(_c(32, f"Added provider '{provider_id}' to account '{account}'."))
    launch = f"altergo {account} {provider_id}" if provider_id != new_meta["default_provider"] else f"altergo {account}"
    print(_c(C("dim"), f"  Launch: {launch}"))
    return 0


def do_remove_provider(account: str, provider_id: str, *, assume_yes: bool = False) -> int:
    """Remove a provider from an altergo account."""
    account_home, _ = resolve_account(account)
    meta = load_account_meta(account_home)
    if meta is None:
        print(f"altergo: account '{account}' has no account.json.", file=sys.stderr)
        return 1

    if provider_id not in meta["providers"]:
        print(_c(C("dim"), f"  altergo: account '{account}' does not have provider '{provider_id}'."))
        return 0

    if len(meta["providers"]) == 1:
        print(
            f"altergo: cannot remove last provider from '{account}'.\n"
            f"  Use 'altergo --delete {account}' to remove the whole account instead.",
            file=sys.stderr,
        )
        return 2

    if not assume_yes and sys.stdin.isatty():
        print(_c(C("header"), f"=== Remove provider '{provider_id}' from '{account}' ==="))
        print()
        print(_c(C("dim"), f"  Session data under MAIN_HOME/.{provider_id}/ is preserved."))
        try:
            answer = input(f"  Remove '{provider_id}' from '{account}'? [y/N] ").strip().lower()
        except (KeyboardInterrupt, EOFError):
            answer = ""
        if answer not in ("y", "yes"):
            print("Cancelled.")
            return 0

    _remove_provider_setup(account_home, provider_id)

    remaining = [p for p in meta["providers"] if p != provider_id]
    new_default = meta["default_provider"]
    if new_default == provider_id:
        new_default = remaining[0]
        print(_c(C("dim"), f"  Default provider rebound to '{new_default}'."))

    new_meta = dict(meta)
    new_meta["version"] = 3
    new_meta["providers"] = remaining
    new_meta["default_provider"] = new_default
    save_account_meta(account_home, new_meta)

    print()
    print(_c(32, f"Removed provider '{provider_id}' from account '{account}'."))
    return 0


def do_default_provider(account: str, provider_id: str) -> int:
    """Change the default provider for an account."""
    account_home, _ = resolve_account(account)
    meta = load_account_meta(account_home)
    if meta is None:
        print(f"altergo: account '{account}' has no account.json.", file=sys.stderr)
        return 1

    if provider_id not in meta["providers"]:
        print(
            f"altergo: account '{account}' does not have provider '{provider_id}' installed.\n"
            f"  Available: {', '.join(meta['providers'])}\n"
            f"  Add it with: altergo {account} --add-provider {provider_id}",
            file=sys.stderr,
        )
        return 1

    if meta["default_provider"] == provider_id:
        print(_c(C("dim"), f"  altergo: default provider is already '{provider_id}'."))
        return 0

    new_meta = dict(meta)
    new_meta["version"] = 3
    new_meta["default_provider"] = provider_id
    save_account_meta(account_home, new_meta)
    print(_c(32, f"Default provider for '{account}' is now '{provider_id}'."))
    return 0


def do_teardown(account: str = "default"):
    if account == _const._NATIVE_ACCOUNT:
        print(
            f"altergo: '{_const._NATIVE_ACCOUNT}' is a reserved passthrough account — there is nothing to tear down.",
            file=sys.stderr,
        )
        sys.exit(1)
    account_home, account_claude = resolve_account(account)
    header = f"altergo v{__version__} · " + _link("https://pixelabs.net", "pixelabs.net")
    print(_c(2, header))
    print(_c(1, _c(36, f"=== Altergo — Teardown ({account}) ===")))
    print()

    meta = load_account_meta(account_home)

    if meta is not None:
        # Modern account with account.json — tear down each provider's symlinks
        for pid in meta["providers"]:
            _remove_provider_setup(account_home, pid)
    else:
        # Legacy account (no account.json) — fall back to SYMLINK_DIRS + SYMLINK_FILES
        for name in _const.SYMLINK_DIRS:
            dst = account_claude / name
            if dst.is_symlink():
                dst.unlink()
                print(f"  {_c(33, '✓')} Removed symlink: {name}/")

        for name in _const.SYMLINK_FILES:
            dst = account_claude / name
            if dst.is_symlink():
                dst.unlink()
                print(f"  {_c(33, '✓')} Removed symlink: {name}")

    # Catalog entries (shared CLI tool credentials) — always at account_home level
    for entry in _const.CATALOG:
        for rel in entry["paths"]:
            dst = account_home / Path(rel)
            src = _const.MAIN_HOME / Path(rel)
            if dst.is_symlink() and dst.resolve() == src.resolve():
                dst.unlink()
                print(f"  {_c(33, '✓')} Removed symlink: ~/{rel}")

    print()
    print(_c(32, "Teardown complete.") + " Account home and credentials left intact.")


def do_delete_account(account: str) -> bool:
    """Fully delete an account: tear down symlinks, remove the home dir, clear active."""
    if account == _const._NATIVE_ACCOUNT:
        print(
            f"altergo: '{_const._NATIVE_ACCOUNT}' is a reserved passthrough account — it cannot be deleted.",
            file=sys.stderr,
        )
        return False

    account_home, _ = resolve_account(account)
    if not account_home.exists():
        print(f"altergo: account '{account}' does not exist.", file=sys.stderr)
        return False

    # Remove symlinks first so we don't follow them into the main $HOME when
    # rmtree walks the tree. do_teardown prints its own progress.
    try:
        do_teardown(account)
    except SystemExit:
        # Teardown exits on the reserved-native case; already guarded above.
        pass

    # Keychain teardown — must happen before rmtree removes the keychain file,
    # but security delete-keychain also deregisters from the system db.
    # Use file/entry/plist presence as the source of truth — not account.json
    # meta — so preserved-but-system-mode keychains are also torn down on delete.
    # Covers B+C+D to satisfy invariant §5.5.
    if sys.platform == "darwin":
        _kc_file_exists = _keychain_path(account_home).exists()
        _kc_plist_exists = _keychain_prefs_path(account_home).exists()
        _kc_entry_exists = (
            _sec(["find-generic-password", "-s", _KC_SERVICE, "-a", account], check=False).returncode == 0
        )
        if _kc_file_exists or _kc_plist_exists or _kc_entry_exists:
            try:
                _delete_account_keychain(account_home, account)
                print(f"  {_c(33, '✓')} Removed per-account keychain")
            except KeychainError as e:
                print(f"altergo: warning during keychain teardown: {e}", file=sys.stderr)
                # proceed with rmtree anyway

    try:
        shutil.rmtree(account_home)
    except Exception as e:
        print(f"altergo: failed to remove {account_home}: {e}", file=sys.stderr)
        return False
    print(f"  {_c(31, '✗')} Removed account home: {account_home}")

    if get_active_account() == account:
        try:
            if _const.SETTINGS_FILE.exists():
                data = json.loads(_const.SETTINGS_FILE.read_text())
                if data.get("active_account") == account:
                    data.pop("active_account", None)
                    tmp = _const.SETTINGS_FILE.with_suffix(".json.tmp")
                    tmp.write_text(json.dumps(data, indent=2))
                    os.replace(str(tmp), str(_const.SETTINGS_FILE))
                    print(f"  {_c(33, '✓')} Cleared active-account pointer")
        except Exception:
            pass

    print()
    print(_c(32, f"Account '{account}' deleted."))
    return True


def do_rename(old_name: str, new_name: str):
    old_home = _const.ACCOUNTS_DIR / old_name
    new_home = _const.ACCOUNTS_DIR / new_name
    if not old_home.is_dir():
        print(f"altergo: account '{old_name}' not found.", file=sys.stderr)
        sys.exit(1)
    validate_account_name(new_name)
    if new_home.exists():
        print(f"altergo: account '{new_name}' already exists.", file=sys.stderr)
        sys.exit(1)
    old_home.rename(new_home)
    print(f"  {_c(32, '✓')} Renamed account '{old_name}' → '{new_name}'")
