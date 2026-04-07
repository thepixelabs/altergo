#!/usr/bin/env python3
"""Altergo — multi-account session manager for Claude Code. Run 'altergo --help' for usage."""

__version__ = "0.5.0"

import curses
import json
import os
import pwd
import re
import shutil
import sys
from datetime import datetime
from pathlib import Path

# --- Terminal helpers ---


def _c(code, text):
    """Wrap text in ANSI color if stdout is a TTY."""
    if not sys.stdout.isatty():
        return text
    return f"\033[{code}m{text}\033[0m"


def _link(url, text):
    """OSC 8 terminal hyperlink — clickable in supported terminals."""
    if not sys.stdout.isatty():
        return text
    return f"\033]8;;{url}\033\\{text}\033]8;;\033\\"


def show_help():
    """Print --help output with color and OSC 8 hyperlinks when on a TTY."""

    def b(t):
        return _c("1", t)  # bold

    def h(t):
        return _c("1;36", t)  # bold cyan — section headers

    def kw(t):
        return _c("36", t)  # cyan — commands / keys

    def dim(t):
        return _c("2", t)  # dim — secondary text

    pixelabs = _link("https://pixelabs.net", "pixelabs.net")
    claude_url = _link("https://claude.ai/code", "Claude Code")

    lines = [
        "",
        f"  {b('altergo')} {dim(f'v{__version__}')}  —  Switch Claude identities. Keep your context.",
        f"  A session manager for {claude_url}.  A {pixelabs} project.",
        "",
        h("  Usage"),
        f"  {kw('altergo')} [flags...]             Launch claude with default account",
        f"  {kw('altergo <name>')} [flags...]      Launch claude with named account",
        f"  {kw('altergo --resume')}               Pick a session interactively (↑/↓/j/k, Enter, q)",
        f"  {kw('altergo --resume <id>')}          Resume a specific session directly",
        f"  {kw('altergo --list')}                 List recent sessions",
        f"  {kw('altergo --setup')}                First-time setup (default account, symlinks)",
        f"  {kw('altergo --setup --name <name>')}  Set up a named account",
        f"  {kw('altergo --teardown')}             Remove symlinks (default account)",
        f"  {kw('altergo --teardown --name <n>')}  Remove symlinks for named account",
        f"  {kw('altergo --settings')}             Configure shared credentials (interactive)",
        f"  {kw('altergo shell')}                  Open a shell inside default account HOME",
        f"  {kw('altergo <name> shell')}           Open a shell inside named account HOME",
        f"  {kw('altergo -- <cmd> [args...]')}     Run command in default account context",
        f"  {kw('altergo <name> -- <cmd> [...]')}  Run command in named account context",
        f"  {kw('altergo --version')}              Show version",
        f"  {kw('altergo -h, --help')}             Show this help",
        "",
        h("  Examples"),
        f"  {kw('altergo')}                        Start a new session (default account)",
        f"  {kw('altergo work')}                   Start a new session (work account)",
        f"  {kw('altergo --setup --name work')}    Create the work account",
        f"  {kw('altergo work shell')}             Enter work-account shell",
        f"  {kw('altergo work -- gh auth login')}  Authenticate gh CLI in work context",
        f"  {kw('altergo --resume')}               Open session picker",
        f"  {kw('altergo --dangerously-skip-permissions')}",
        f"  {dim('                                 Pass any claude flag straight through')}",
        "",
        h("  Navigation (session picker)"),
        f"  {kw('↑/k')}          Move up             {kw('PgUp/PgDn')}    Page scroll",
        f"  {kw('↓/j')}          Move down           {kw('g/G')}          Jump to top/bottom",
        f"  {kw('Enter')}        Resume session      {kw('q/Esc')}        Quit",
        "",
        dim("  altergo is an independent open-source project by pixelabs · not affiliated with Anthropic PBC"),
        dim("  Claude and Claude Code are trademarks of Anthropic PBC"),
        "",
    ]
    print("\n".join(lines))


# --- Config ---

# Resolve the real home even if HOME is overridden (e.g., running as altergo)
_pw_home = Path(pwd.getpwuid(os.getuid()).pw_dir)
if not _pw_home.exists():
    _pw_home = Path(os.environ["HOME"])

MAIN_HOME = _pw_home
MAIN_CLAUDE = MAIN_HOME / ".claude"
ACCOUNTS_DIR = MAIN_HOME / ".altergo" / "accounts"

# Reserved account names — blocked at --setup --name time
_RESERVED_NAMES = frozenset(
    [
        "default",
        "main",
        "list",
        "new",
        "rm",
        "shell",
        "setup",
        "teardown",
        "help",
        "version",
        "legacy",
        "backup",
        "migrate",
    ]
)

# Settings file — global (shared across all accounts)
SETTINGS_FILE = MAIN_HOME / ".altergo" / ".altergo.json"


# --- Account helpers ---


def resolve_account(name: str) -> tuple:
    """Return (account_home, account_claude) for the given account name."""
    account_home = ACCOUNTS_DIR / name
    account_claude = account_home / ".claude"
    return account_home, account_claude


def list_accounts() -> list:
    """Return sorted list of account names that exist on disk."""
    if not ACCOUNTS_DIR.exists():
        return []
    return sorted(p.name for p in ACCOUNTS_DIR.iterdir() if p.is_dir() and not p.name.startswith("."))


def validate_account_name(name: str) -> None:
    """Raise SystemExit if name is invalid (bad chars, reserved word, leading dot)."""
    if not re.match(r"^[a-zA-Z0-9][a-zA-Z0-9_-]*$", name) or len(name) > 64:
        print(
            f"altergo: invalid account name '{name}'. "
            "Use letters, digits, - or _ only; must not start with a digit or special char.",
            file=sys.stderr,
        )
        sys.exit(1)
    if name in _RESERVED_NAMES:
        print(f"altergo: '{name}' is a reserved name. Choose a different account name.", file=sys.stderr)
        sys.exit(1)


# --- Migration ---


def detect_legacy() -> bool:
    """Return True if the old ~/.altergo/.claude/ layout exists and new layout does not."""
    old_claude = MAIN_HOME / ".altergo" / ".claude"
    return old_claude.exists() and not ACCOUNTS_DIR.exists()


def migrate_legacy() -> None:
    """Migrate old single-account layout to N-account layout. Runs at most once."""
    if not detect_legacy():
        return
    old_root = MAIN_HOME / ".altergo"
    tmp_path = Path(f"/tmp/altergo-migrate-{os.getpid()}")
    # Step 1: rename ~/.altergo → /tmp/altergo-migrate-{pid}
    old_root.rename(tmp_path)
    # Step 2: mkdir -p ~/.altergo/accounts/
    ACCOUNTS_DIR.mkdir(parents=True, exist_ok=True)
    # Step 3: rename /tmp/... → ~/.altergo/accounts/default/
    default_home = ACCOUNTS_DIR / "default"
    tmp_path.rename(default_home)
    # Step 4: copy as backup (symlinks=True preserves existing symlinks)
    backup_path = MAIN_HOME / ".altergo" / ".legacy-backup"
    shutil.copytree(str(default_home), str(backup_path), symlinks=True)
    # Step 5: write audit trail so users can verify what happened
    migrated_marker = default_home / "MIGRATED.txt"
    migrated_marker.write_text(
        f"Migrated by altergo v{__version__} on {__import__('datetime').datetime.now().isoformat(timespec='seconds')}\n"
        f"Old layout: ~/.altergo/\n"
        f"New layout: ~/.altergo/accounts/default/\n"
        f"Backup:     ~/.altergo/.legacy-backup/\n"
        f"Rollback:   remove ~/.altergo/accounts/ and rename .legacy-backup back to ~/.altergo\n"
        f"See:        https://altergo.pixelabs.net/docs/migration-0.5\n"
    )
    # Step 6: print a visible block — this is a one-time destructive rename, silence is wrong
    print("altergo: layout migrated for v0.5.0 N-account support")
    print("  ~/.altergo/  →  ~/.altergo/accounts/default/")
    print("  Backup preserved at ~/.altergo/.legacy-backup/")
    print("  See https://altergo.pixelabs.net/docs/migration-0.5 for details")


# --- Symlink catalogs ---

# Directories to symlink (shared between main and alt)
SYMLINK_DIRS = [
    "projects",
    "tasks",
    "session-env",
    "file-history",
    "shell-snapshots",
    "agents",
    "plans",
    "cache",
]

# Files to symlink
SYMLINK_FILES = [
    "settings.json",
    "CLAUDE.md",
    "keybindings.json",
]

# Catalog of CLI tools whose credentials can be shared between main and alt.
# Each entry maps to one or more paths relative to $HOME that are symlinked.
# default_on=True  → shared by default (user must explicitly opt out)
# default_on=False → isolated by default (user must explicitly opt in)
# warning          → shown in the settings TUI when this entry is highlighted
CATALOG = [
    # Cloud Providers
    {
        "id": "aws",
        "name": "AWS CLI",
        "category": "Cloud Providers",
        "paths": [".aws"],
        "default_on": True,
    },
    {
        "id": "gcloud",
        "name": "Google Cloud",
        "category": "Cloud Providers",
        "paths": [".config/gcloud"],
        "default_on": True,
    },
    {
        "id": "azure",
        "name": "Azure CLI",
        "category": "Cloud Providers",
        "paths": [".azure", ".config/azure"],
        "default_on": True,
    },
    # Containers & Orchestration
    {
        "id": "docker",
        "name": "Docker",
        "category": "Containers",
        "paths": [".docker"],
        "default_on": True,
    },
    {
        "id": "kube",
        "name": "Kubernetes",
        "category": "Containers",
        "paths": [".kube"],
        "default_on": True,
    },
    # Infrastructure
    {
        "id": "terraform",
        "name": "Terraform",
        "category": "Infrastructure",
        "paths": [".terraform.d"],
        "default_on": True,
    },
    # VCS & Dev Tools
    {
        "id": "gh",
        "name": "GitHub CLI",
        "category": "VCS & Dev Tools",
        "paths": [".config/gh"],
        "default_on": True,
    },
    {
        "id": "glab",
        "name": "GitLab CLI",
        "category": "VCS & Dev Tools",
        "paths": [".config/glab"],
        "default_on": False,
    },
    # Package Managers
    {
        "id": "npm",
        "name": "npm",
        "category": "Package Managers",
        "paths": [".npmrc"],
        "default_on": False,
    },
    # Identity — off by default, high security/identity impact
    {
        "id": "ssh",
        "name": "SSH keys",
        "category": "Identity",
        "paths": [".ssh"],
        "default_on": False,
        "warning": "Shares SSH keys & known_hosts. Keep off if you use per-identity SSH keys.",
    },
    {
        "id": "gitconfig",
        "name": "Git identity",
        "category": "Identity",
        "paths": [".gitconfig"],
        "default_on": False,
        "warning": "Shares git user.name/email. Keep off for separate commit identity per account.",
    },
    {
        "id": "gnupg",
        "name": "GPG keys",
        "category": "Identity",
        "paths": [".gnupg"],
        "default_on": False,
        "warning": "Shares GPG keyring. Keep off if you use per-identity signing keys.",
    },
]

# (SETTINGS_FILE is defined in the Config section above, shared across all accounts)

# --- Settings helpers ---


def load_settings():
    """Load user settings overlay. Returns {id: bool} dict of non-default values."""
    if not SETTINGS_FILE.exists():
        return {}
    try:
        data = json.loads(SETTINGS_FILE.read_text())
        shared = data.get("shared", {})
        catalog_ids = {e["id"] for e in CATALOG}
        return {k: v for k, v in shared.items() if k in catalog_ids and isinstance(v, bool)}
    except Exception:
        return {}


def save_settings(overrides):
    """Atomically write settings overlay to SETTINGS_FILE."""
    SETTINGS_FILE.parent.mkdir(parents=True, exist_ok=True)
    data = {"version": 1, "shared": overrides}
    tmp = SETTINGS_FILE.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(data, indent=2))
    os.replace(str(tmp), str(SETTINGS_FILE))


def is_enabled(entry, overrides):
    """Return whether a catalog entry is enabled given the user's overrides."""
    return overrides.get(entry["id"], entry["default_on"])


def _ensure_nested_parent(rel, account_home):
    """For paths like .config/gh, ensure account_home/.config is a real directory.

    If it's currently a wholesale symlink to MAIN_HOME/.config (from an older
    setup), migrates it transparently: unlinks the symlink and creates a real
    directory, then individual tool symlinks will be created inside it.
    """
    p = Path(rel)
    if len(p.parts) < 2:
        return
    parent_name = p.parts[0]
    acct_parent = account_home / parent_name
    main_parent = MAIN_HOME / parent_name
    if acct_parent.is_symlink():
        if acct_parent.resolve() == main_parent.resolve():
            acct_parent.unlink()
            acct_parent.mkdir(parents=True, exist_ok=True)
            print(f"  {_c(33, '↻')} Migrated ~/{parent_name}/ from wholesale symlink to managed dir")
    elif not acct_parent.exists():
        acct_parent.mkdir(parents=True, exist_ok=True)


def _apply_entry(entry, overrides, account_home):
    """Create or remove symlinks for one catalog entry based on current settings."""
    enabled = is_enabled(entry, overrides)
    for rel in entry["paths"]:
        src = MAIN_HOME / Path(rel)
        dst = account_home / Path(rel)
        if enabled:
            if not src.exists():
                print(f"  {_c(2, 'skip')} ~/{rel} (not present in main home)")
                continue
            _ensure_nested_parent(rel, account_home)
            if dst.is_symlink():
                if dst.resolve() == src.resolve():
                    print(f"  {_c(32, '✓')} ~/{rel} already shared")
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


# --- Setup / Teardown ---


def do_setup(account: str = "default"):
    account_home, account_claude = resolve_account(account)
    header = f"altergo v{__version__} · " + _link("https://pixelabs.net", "pixelabs.net")
    print(_c(2, header))
    print(_c(1, _c(36, f"=== Altergo — Setup ({account}) ===")))
    print()

    # 1. Create account home
    if not account_home.exists():
        account_home.mkdir(parents=True)
        print(f"  {_c(32, '✓')} Created account home: {account_home}")
    else:
        print(f"  {_c(32, '✓')} Account home exists: {account_home}")

    # Ensure .claude dir exists
    account_claude.mkdir(parents=True, exist_ok=True)

    # 2. Symlink directories inside .claude/
    for name in SYMLINK_DIRS:
        src = MAIN_CLAUDE / name
        dst = account_claude / name

        if not src.exists():
            print(f"  {_c(2, 'skip')} {name}/ (not found in main)")
            continue

        if dst.is_symlink():
            target = dst.resolve()
            if target == src.resolve():
                print(f"  {_c(32, '✓')} {name}/ already symlinked")
            else:
                print(f"  {_c(33, '⚠')} {name}/ symlinked to {target} (expected {src})")
            continue

        if dst.exists():
            print(f"  {_c(33, '⚠')} {name}/ exists as real dir — remove it first to symlink")
            continue

        dst.symlink_to(src)
        print(f"  {_c(32, '✓')} Symlinked {name}/")

    # 3. Symlink files inside .claude/
    for name in SYMLINK_FILES:
        src = MAIN_CLAUDE / name
        dst = account_claude / name

        if not src.exists():
            continue

        if dst.is_symlink():
            print(f"  {_c(32, '✓')} {name} already symlinked")
            continue

        if dst.exists():
            dst.unlink()

        dst.symlink_to(src)
        print(f"  {_c(32, '✓')} Symlinked {name}")

    # 4. Apply catalog entries (shared CLI tool credentials) at account_home level
    overrides = load_settings()
    for entry in CATALOG:
        _apply_entry(entry, overrides, account_home)

    # 5. Check credentials
    creds = account_claude / ".credentials.json"
    print()
    if creds.exists():
        print(f"  {_c(32, '✓')} Account credentials found")
    else:
        print(f"  {_c(33, '⚠')} No account credentials found.")
        cmd = f"altergo {account}" if account != "default" else "altergo"
        print(f"     Run '{cmd}' to authenticate.\n")

    launch_cmd = f"altergo {account}" if account != "default" else "altergo"
    print()
    print(_c(32, "Setup complete!"))
    print(f"  Run {_c(1, launch_cmd)} to start a session  ·  {_c(1, 'altergo --resume')} to pick one")
    print()
    print(_c(2, "  Isolates Claude credentials. Shares AWS, GCP, Docker, and kubectl by default."))
    print(_c(2, f"  Change sharing settings: {_c(0, 'altergo --settings')}"))


def do_teardown(account: str = "default"):
    account_home, account_claude = resolve_account(account)
    header = f"altergo v{__version__} · " + _link("https://pixelabs.net", "pixelabs.net")
    print(_c(2, header))
    print(_c(1, _c(36, f"=== Altergo — Teardown ({account}) ===")))
    print()

    for name in SYMLINK_DIRS:
        dst = account_claude / name
        if dst.is_symlink():
            dst.unlink()
            print(f"  {_c(33, '✓')} Removed symlink: {name}/")

    for name in SYMLINK_FILES:
        dst = account_claude / name
        if dst.is_symlink():
            dst.unlink()
            print(f"  {_c(33, '✓')} Removed symlink: {name}")

    for entry in CATALOG:
        for rel in entry["paths"]:
            dst = account_home / Path(rel)
            src = MAIN_HOME / Path(rel)
            if dst.is_symlink() and dst.resolve() == src.resolve():
                dst.unlink()
                print(f"  {_c(33, '✓')} Removed symlink: ~/{rel}")

    print()
    print(_c(32, "Teardown complete.") + " Account home and credentials left intact.")


# --- Session Discovery ---


def get_sessions():
    """Find all sessions across all projects, return sorted by modification time."""
    sessions = []
    projects_dir = MAIN_CLAUDE / "projects"

    if not projects_dir.exists():
        return sessions

    for project_dir in projects_dir.iterdir():
        if not project_dir.is_dir():
            continue

        project_name = project_dir.name

        for f in project_dir.iterdir():
            if f.suffix != ".jsonl" or f.parent.name == "subagents":
                continue

            session_id = f.stem
            mod_time = f.stat().st_mtime
            mod_dt = datetime.fromtimestamp(mod_time)
            size_mb = f.stat().st_size / (1024 * 1024)

            # Try to extract last user message as a preview
            preview = get_session_preview(f)

            sessions.append(
                {
                    "id": session_id,
                    "project": project_name,
                    "modified": mod_dt,
                    "size_mb": size_mb,
                    "path": f,
                    "preview": preview,
                }
            )

    sessions.sort(key=lambda s: s["modified"], reverse=True)
    return sessions


def get_session_preview(jsonl_path):
    """Read the last few user messages from a session file for preview."""
    try:
        last_msg = ""
        with open(jsonl_path, "rb") as f:
            # Read last 8KB to find recent messages
            f.seek(0, 2)
            size = f.tell()
            f.seek(max(0, size - 8192))
            tail = f.read().decode("utf-8", errors="replace")

        for line in tail.strip().split("\n"):
            try:
                obj = json.loads(line)
                if obj.get("type") == "human" and isinstance(obj.get("message"), dict):
                    content = obj["message"].get("content", "")
                    if isinstance(content, str) and content.strip():
                        last_msg = content.strip()
                    elif isinstance(content, list):
                        for block in content:
                            if isinstance(block, dict) and block.get("type") == "text":
                                last_msg = block["text"].strip()
            except (json.JSONDecodeError, KeyError):
                continue

        return last_msg[:80] if last_msg else ""
    except Exception:
        return ""


def format_project_name(encoded):
    """Convert encoded project path back to readable name."""
    # -Users-netz-Documents-git-dispatch → dispatch
    parts = encoded.strip("-").split("-")
    # Return last meaningful part
    return parts[-1] if parts else encoded


# --- Interactive Menu ---


def interactive_picker(sessions):
    """Arrow-key driven session picker using curses."""
    if not sessions:
        print("No sessions found.")
        sys.exit(1)

    selected = curses.wrapper(_draw_picker, sessions)
    return selected


def _draw_picker(stdscr, sessions):
    curses.curs_set(0)
    curses.use_default_colors()

    # Init color pairs
    curses.init_pair(1, curses.COLOR_BLACK, curses.COLOR_CYAN)  # selected
    curses.init_pair(2, curses.COLOR_CYAN, -1)  # header
    curses.init_pair(3, curses.COLOR_YELLOW, -1)  # project name
    curses.init_pair(4, curses.COLOR_WHITE, -1)  # session id
    curses.init_pair(5, curses.COLOR_GREEN, -1)  # time

    current = 0
    scroll_offset = 0

    while True:
        stdscr.clear()
        max_y, max_x = stdscr.getmaxyx()

        # Header
        header = " Altergo — Pick a session (↑/↓ navigate, Enter select, q quit)"
        stdscr.attron(curses.color_pair(2) | curses.A_BOLD)
        stdscr.addnstr(0, 0, header.ljust(max_x), max_x - 1)
        stdscr.attroff(curses.color_pair(2) | curses.A_BOLD)

        # Column headers
        col_header = f"  {'Project':<20} {'Modified':<18} {'Size':>6}  {'Last message'}"
        stdscr.attron(curses.A_DIM)
        stdscr.addnstr(2, 0, col_header[: max_x - 1], max_x - 1)
        stdscr.attroff(curses.A_DIM)

        # Visible area
        visible_rows = max_y - 5  # header + col header + footer + padding
        if visible_rows < 1:
            visible_rows = 1

        # Adjust scroll
        if current < scroll_offset:
            scroll_offset = current
        elif current >= scroll_offset + visible_rows:
            scroll_offset = current - visible_rows + 1

        # Draw sessions
        for i in range(visible_rows):
            idx = scroll_offset + i
            if idx >= len(sessions):
                break

            s = sessions[idx]
            row = i + 3  # after header rows

            project = format_project_name(s["project"])
            modified = s["modified"].strftime("%Y-%m-%d %H:%M")
            size = f"{s['size_mb']:.1f}MB"
            preview = s["preview"]

            # Truncate preview to fit
            preview_width = max(0, max_x - 50)
            if len(preview) > preview_width:
                preview = preview[: preview_width - 1] + "…"

            line = f"  {project:<20} {modified:<18} {size:>6}  {preview}"

            if idx == current:
                stdscr.attron(curses.color_pair(1) | curses.A_BOLD)
                stdscr.addnstr(row, 0, f"▸ {line[2:]}"[: max_x - 1].ljust(max_x - 1), max_x - 1)
                stdscr.attroff(curses.color_pair(1) | curses.A_BOLD)
            else:
                stdscr.addnstr(row, 0, line[: max_x - 1], max_x - 1)

        # Footer — show session ID of current selection
        footer_row = max_y - 2
        if current < len(sessions):
            sid = sessions[current]["id"]
            footer = f" Session: {sid}"
            stdscr.attron(curses.A_DIM)
            stdscr.addnstr(footer_row, 0, footer[: max_x - 1], max_x - 1)
            stdscr.attroff(curses.A_DIM)

        count_info = f" {current + 1}/{len(sessions)} sessions"
        stdscr.attron(curses.A_DIM)
        stdscr.addnstr(footer_row + 1, 0, count_info[: max_x - 1], max_x - 1)
        stdscr.attroff(curses.A_DIM)

        stdscr.refresh()

        # Input
        key = stdscr.getch()

        if key == curses.KEY_UP or key == ord("k"):
            current = max(0, current - 1)
        elif key == curses.KEY_DOWN or key == ord("j"):
            current = min(len(sessions) - 1, current + 1)
        elif key == curses.KEY_PPAGE:  # Page Up
            current = max(0, current - visible_rows)
        elif key == curses.KEY_NPAGE:  # Page Down
            current = min(len(sessions) - 1, current + visible_rows)
        elif key == ord("g"):  # Home
            current = 0
        elif key == ord("G"):  # End
            current = len(sessions) - 1
        elif key in (curses.KEY_ENTER, 10, 13):
            return sessions[current]
        elif key in (ord("q"), 27):  # q or Escape
            return None


# --- Settings TUI ---


def interactive_settings():
    """Open the settings TUI, save on confirm, and apply changes immediately."""
    overrides = curses.wrapper(_draw_settings, CATALOG, load_settings())
    if overrides is None:
        print("Cancelled.")
        return
    save_settings(overrides)
    print()
    print(_c(1, _c(36, "=== Applying settings ===")))
    print()
    for acct_name in list_accounts() or ["default"]:
        acct_home, _ = resolve_account(acct_name)
        if acct_home.exists():
            for entry in CATALOG:
                _apply_entry(entry, overrides, acct_home)
    print()
    print(_c(32, "Settings saved and applied."))


def _draw_settings(stdscr, catalog, overrides):
    """Settings TUI. Returns overlay {id: bool} on save, None on cancel."""
    curses.curs_set(0)
    curses.use_default_colors()
    curses.init_pair(1, curses.COLOR_BLACK, curses.COLOR_CYAN)  # selected row
    curses.init_pair(2, curses.COLOR_CYAN, -1)  # title bar
    curses.init_pair(6, curses.COLOR_GREEN, -1)  # enabled item
    curses.init_pair(7, curses.COLOR_YELLOW, -1)  # warning text

    local = dict(overrides)  # mutable working copy

    # Build flat row list: headers + entries in catalog order
    rows = []
    seen_cats = []
    for entry in catalog:
        cat = entry["category"]
        if cat not in seen_cats:
            seen_cats.append(cat)
            rows.append({"type": "header", "text": cat})
        rows.append({"type": "entry", "entry": entry})

    selectable = [i for i, r in enumerate(rows) if r["type"] == "entry"]
    defaults = {e["id"]: e["default_on"] for e in catalog}
    sel_pos = 0
    scroll_offset = 0

    while True:
        stdscr.clear()
        max_y, max_x = stdscr.getmaxyx()

        # Title bar
        title = " Altergo — Shared Credentials  ·  Space toggle  ·  s save  ·  Esc cancel"
        stdscr.attron(curses.color_pair(2) | curses.A_BOLD)
        stdscr.addnstr(0, 0, title.ljust(max_x), max_x - 1)
        stdscr.attroff(curses.color_pair(2) | curses.A_BOLD)

        subtitle = "  Share CLI credentials between accounts. Only Claude login stays separate."
        stdscr.attron(curses.A_DIM)
        stdscr.addnstr(1, 0, subtitle[: max_x - 1], max_x - 1)
        stdscr.attroff(curses.A_DIM)

        visible_rows = max(1, max_y - 5)
        current_row_idx = selectable[sel_pos]

        # Scroll to keep selection visible
        if current_row_idx < scroll_offset:
            scroll_offset = current_row_idx
        elif current_row_idx >= scroll_offset + visible_rows:
            scroll_offset = current_row_idx - visible_rows + 1

        for i in range(visible_rows):
            row_idx = scroll_offset + i
            if row_idx >= len(rows):
                break
            screen_row = i + 3
            row = rows[row_idx]

            if row["type"] == "header":
                stdscr.attron(curses.A_BOLD)
                stdscr.addnstr(screen_row, 2, row["text"][: max_x - 3], max_x - 3)
                stdscr.attroff(curses.A_BOLD)
            else:
                entry = row["entry"]
                enabled = is_enabled(entry, local)
                is_current = row_idx == current_row_idx
                has_warn = "warning" in entry

                check = "[x]" if enabled else "[ ]"
                warn_tag = " !" if has_warn else "  "
                name_part = f"  {check} {entry['name']:<22}{warn_tag}"
                path_hint = "  " + ", ".join(f"~/{p}" for p in entry["paths"])

                if is_current:
                    full = f"▸ {check} {entry['name']:<22}{warn_tag}{path_hint.strip()}"
                    stdscr.attron(curses.color_pair(1) | curses.A_BOLD)
                    stdscr.addnstr(screen_row, 0, full[: max_x - 1].ljust(max_x - 1), max_x - 1)
                    stdscr.attroff(curses.color_pair(1) | curses.A_BOLD)
                else:
                    if enabled:
                        stdscr.attron(curses.color_pair(6))
                    stdscr.addnstr(screen_row, 0, name_part[: max_x - 1], max_x - 1)
                    if enabled:
                        stdscr.attroff(curses.color_pair(6))
                    nc = len(name_part)
                    if nc < max_x - 1:
                        stdscr.attron(curses.A_DIM)
                        stdscr.addnstr(screen_row, nc, path_hint[: max_x - nc - 1], max_x - nc - 1)
                        stdscr.attroff(curses.A_DIM)

        # Footer
        footer_row = max_y - 2
        current_entry = rows[current_row_idx].get("entry", {})
        if current_entry.get("warning"):
            stdscr.attron(curses.color_pair(7))
            stdscr.addnstr(footer_row, 0, f"  ! {current_entry['warning']}"[: max_x - 1], max_x - 1)
            stdscr.attroff(curses.color_pair(7))

        nav = "  Space toggle  ·  ↑↓ / j k navigate  ·  s save & apply  ·  Esc cancel"
        stdscr.attron(curses.A_DIM)
        stdscr.addnstr(footer_row + 1, 0, nav[: max_x - 1], max_x - 1)
        stdscr.attroff(curses.A_DIM)

        stdscr.refresh()

        key = stdscr.getch()
        if key in (curses.KEY_UP, ord("k")):
            sel_pos = max(0, sel_pos - 1)
        elif key in (curses.KEY_DOWN, ord("j")):
            sel_pos = min(len(selectable) - 1, sel_pos + 1)
        elif key == curses.KEY_PPAGE:
            sel_pos = max(0, sel_pos - visible_rows)
        elif key == curses.KEY_NPAGE:
            sel_pos = min(len(selectable) - 1, sel_pos + visible_rows)
        elif key == ord(" "):
            entry = rows[selectable[sel_pos]]["entry"]
            local[entry["id"]] = not is_enabled(entry, local)
        elif key == ord("s"):
            # Only write non-default values to keep the file minimal
            overlay = {k: v for k, v in local.items() if defaults.get(k) != v}
            return overlay
        elif key in (ord("q"), 27):
            return None


# --- Launch ---


def _build_alt_env(account: str = "default") -> dict:
    """Return a copy of the environment with HOME set to the account home.

    If account_home/.local/bin exists, it is prepended to PATH so that Claude
    Code's startup PATH check (which resolves relative to $HOME) doesn't warn
    about a missing native-installation directory.  The guard on existence is
    intentional: we only inject the directory when something has actually been
    installed there (e.g. via `claude update` inside an altergo session).
    Without the guard we would prepend a ghost path on every launch and give
    an uncontrolled write target higher precedence than all system binaries.
    """
    account_home, _ = resolve_account(account)
    env = os.environ.copy()
    env["HOME"] = str(account_home)
    acct_local_bin = account_home / ".local" / "bin"
    if acct_local_bin.exists():
        acct_local_bin_str = str(acct_local_bin)
        path_dirs = env.get("PATH", "").split(":")
        if acct_local_bin_str not in path_dirs:
            env["PATH"] = acct_local_bin_str + ":" + env.get("PATH", "")
    return env


def _find_claude() -> str | None:
    """Find the claude binary, checking PATH and common install locations.

    PATH may be incomplete if the user invokes altergo before their shell rc
    has finished loading (e.g., typing very quickly in a new terminal window).
    The fallbacks cover the most common Claude Code install locations.
    """
    path = shutil.which("claude")
    if path:
        return path
    fallbacks = [
        _pw_home / ".local" / "bin" / "claude",  # claude install default
        _pw_home / ".npm-global" / "bin" / "claude",  # npm --global-prefix
        Path("/opt/homebrew/bin/claude"),  # Homebrew on Apple Silicon
        Path("/usr/local/bin/claude"),  # Homebrew on Intel / manual
    ]
    for p in fallbacks:
        if p.exists() and os.access(p, os.X_OK):
            return str(p)
    return None


def launch_claude(account: str = "default", args=None):
    """Launch claude with account HOME, passing args through unchanged."""
    claude_path = _find_claude()
    if not claude_path:
        sys.exit(
            "altergo: 'claude' not found in PATH or common install locations.\n"
            "  If you just opened this terminal, your shell may still be initializing.\n"
            "  Wait a moment and try again, or open a new tab."
        )
    env = _build_alt_env(account)
    cmd = [claude_path] + (args or [])
    os.execvpe(claude_path, cmd, env)


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
    print(_c(36, f"Entering altergo shell [{account}] (HOME={account_home})"))
    print(_c(2, "Run 'exit' or Ctrl-D to return to your primary account.\n"))
    os.execvpe(shell, [shell], env)


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
    os.execvpe(cmd_path, [cmd_path] + cmd_args[1:], env)


# --- Account name disambiguation helper ---


_KNOWN_COMMANDS = frozenset(
    ["shell", "--resume", "--list", "--setup", "--teardown", "--settings", "--version", "-h", "--help", "--"]
)


def _looks_like_account(token: str) -> bool:
    """Return True if token could be an account name (not a flag, not a known command)."""
    if token.startswith("-"):
        return False
    if token in _KNOWN_COMMANDS:
        return False
    # Must look like a valid account name (alphanumeric start, no spaces)
    return bool(re.match(r"^[a-zA-Z0-9][a-zA-Z0-9_-]*$", token))


# --- Main ---


def main():
    # Auto-migrate legacy layout before any other processing
    migrate_legacy()

    args = sys.argv[1:]

    # ── Altergo-owned commands (not passed to claude) ──────────────────────────

    if args and args[0] in ("-h", "--help"):
        show_help()
        sys.exit(0)

    if args and args[0] == "--version":
        print(f"altergo {__version__}")
        sys.exit(0)

    if args and args[0] == "--setup":
        # Support: --setup --name <name>
        name = "default"
        if len(args) >= 3 and args[1] == "--name":
            name = args[2]
            validate_account_name(name)
        do_setup(name)
        sys.exit(0)

    if args and args[0] == "--teardown":
        # Support: --teardown --name <name>
        name = "default"
        if len(args) >= 3 and args[1] == "--name":
            name = args[2]
        do_teardown(name)
        sys.exit(0)

    if args and args[0] == "--settings":
        interactive_settings()
        sys.exit(0)

    if args and args[0] == "--list":
        sessions = get_sessions()
        if not sessions:
            print("No sessions found.")
            sys.exit(0)
        header_row = f"{'Project':<20} {'Modified':<18} {'Size':>6}  Session ID"
        print(_c(2, header_row))
        print(_c(2, "-" * 80))
        for s in sessions[:30]:
            project = format_project_name(s["project"])
            modified = s["modified"].strftime("%Y-%m-%d %H:%M")
            size = f"{s['size_mb']:.1f}MB"
            print(f"{_c(36, f'{project:<20}')} {_c(2, f'{modified:<18}')} {_c(33, f'{size:>6}')}  {s['id']}")
        sys.exit(0)

    # --resume with no ID → open interactive picker
    if args and args[0] == "--resume" and len(args) == 1:
        sessions = get_sessions()
        selected = interactive_picker(sessions)
        if selected:
            launch_claude("default", ["--resume", selected["id"]])
        else:
            print("Cancelled.")
        sys.exit(0)

    # ── Account name as first positional arg ──────────────────────────────────
    # altergo <name> [sub-command | claude flags...]
    account = "default"
    if args and _looks_like_account(args[0]):
        candidate = args[0]
        acct_home = ACCOUNTS_DIR / candidate
        if not acct_home.is_dir():
            print(
                f"altergo: account '{candidate}' not found. Run 'altergo --setup --name {candidate}' to create it.",
                file=sys.stderr,
            )
            sys.exit(1)
        account = candidate
        args = args[1:]

    # ── Sub-commands (after optional account prefix) ──────────────────────────

    # altergo [<name>] shell
    if args and args[0] == "shell":
        launch_shell(account)

    # altergo [<name>] -- <cmd> [args...]
    if args and args[0] == "--":
        launch_command(account, args[1:])

    # ── Everything else → pass straight through to claude ────────────────────
    # altergo                    → claude (default account)
    # altergo work               → claude (work account, args=[])
    # altergo --resume x         → claude --resume x
    # altergo --dangerously-...  → claude --dangerously-...
    launch_claude(account, args)


if __name__ == "__main__":
    main()
