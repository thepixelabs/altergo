#!/usr/bin/env python3
"""
Altergo — Your other Claude.

Multi-account session manager for Claude Code. Switch between Claude Code
identities without losing a thought. Uses symlinks to share session data
and a separate HOME for alt account credentials.

Usage:
  altergo [claude flags...]      Launch claude with alt credentials (pass-through)
  altergo --resume               Pick a session interactively (↑/↓/j/k, Enter, q)
  altergo --resume <id>          Resume a specific session directly
  altergo --list                 List recent sessions
  altergo --setup                First-time setup (alt home, symlinks)
  altergo --teardown             Remove symlinks and undo setup
  altergo shell                  Open an interactive shell inside alt HOME
  altergo -- <cmd> [args...]     Run any command with HOME set to alt directory
  altergo --version              Show version
  altergo -h, --help             Show this help

Examples:
  altergo                        Start a new session (same as: claude)
  altergo --resume               Open session picker
  altergo shell                  Enter alt-HOME shell (run 'gh auth login' here)
  altergo -- gh auth login       Authenticate gh CLI in alt HOME context
  altergo -- git config --global user.email me@work.com
  altergo --dangerously-skip-permissions
                                 Pass any claude flag straight through

Navigation (session picker):
  ↑/k          Move up             PgUp/PgDn    Page scroll
  ↓/j          Move down           g/G          Jump to top/bottom
  Enter        Resume session      q/Esc        Quit
"""

__version__ = "0.4.0"

import curses
import json
import os
import pwd
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


# --- Config ---

# Resolve the real home even if HOME is overridden (e.g., running as altergo)
_pw_home = Path(pwd.getpwuid(os.getuid()).pw_dir)
if not _pw_home.exists():
    _pw_home = Path(os.environ["HOME"])

MAIN_HOME = _pw_home
ALT_HOME = MAIN_HOME / ".altergo"
MAIN_CLAUDE = MAIN_HOME / ".claude"
ALT_CLAUDE = ALT_HOME / ".claude"

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

# --- Setup / Teardown ---


def do_setup():
    header = f"altergo v{__version__} · " + _link("https://pixelabs.net", "pixelabs.net")
    print(_c(2, header))
    print(_c(1, _c(36, "=== Altergo — Setup ===")))
    print()

    # 1. Create alt home
    if not ALT_HOME.exists():
        ALT_HOME.mkdir(parents=True)
        print(f"  {_c(32, '✓')} Created alt home: {ALT_HOME}")
    else:
        print(f"  {_c(32, '✓')} Alt home exists: {ALT_HOME}")

    # Ensure alt .claude dir exists
    ALT_CLAUDE.mkdir(parents=True, exist_ok=True)

    # 2. Symlink directories
    for name in SYMLINK_DIRS:
        src = MAIN_CLAUDE / name
        dst = ALT_CLAUDE / name

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

    # 3. Symlink files
    for name in SYMLINK_FILES:
        src = MAIN_CLAUDE / name
        dst = ALT_CLAUDE / name

        if not src.exists():
            continue

        if dst.is_symlink():
            print(f"  {_c(32, '✓')} {name} already symlinked")
            continue

        if dst.exists():
            dst.unlink()

        dst.symlink_to(src)
        print(f"  {_c(32, '✓')} Symlinked {name}")

    # 4. Check credentials
    creds = ALT_CLAUDE / ".credentials.json"
    print()
    if creds.exists():
        print(f"  {_c(32, '✓')} Alt account credentials found")
    else:
        print(f"  {_c(33, '⚠')} No alt account credentials found.")
        print("     Run 'altergo' to authenticate with your alt account.\n")

    print()
    print(_c(32, "Setup complete!"))
    print()
    print(_c(36, "Usage:"))
    print(f"  {_c(1, 'altergo')}                       Start a new session with alt credentials")
    print(f"  {_c(1, 'altergo --resume')}              Open interactive session picker")
    print(f"  {_c(1, 'altergo --resume <session-id>')} Resume directly")
    print(f"  {_c(1, 'altergo --list')}                List recent sessions")


def do_teardown():
    header = f"altergo v{__version__} · " + _link("https://pixelabs.net", "pixelabs.net")
    print(_c(2, header))
    print(_c(1, _c(36, "=== Altergo — Teardown ===")))
    print()

    for name in SYMLINK_DIRS:
        dst = ALT_CLAUDE / name
        if dst.is_symlink():
            dst.unlink()
            print(f"  {_c(33, '✓')} Removed symlink: {name}/")

    for name in SYMLINK_FILES:
        dst = ALT_CLAUDE / name
        if dst.is_symlink():
            dst.unlink()
            print(f"  {_c(33, '✓')} Removed symlink: {name}")

    print()
    print(_c(32, "Teardown complete.") + " Alt home and credentials left intact.")


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


# --- Launch ---


def launch_claude(args=None):
    """Launch claude with alt HOME, passing args through unchanged."""
    claude_path = shutil.which("claude")
    if not claude_path:
        sys.exit("altergo: 'claude' not found in PATH")
    env = os.environ.copy()
    env["HOME"] = str(ALT_HOME)
    cmd = [claude_path] + (args or [])
    os.execvpe(claude_path, cmd, env)


def launch_shell():
    """Open an interactive shell with HOME set to alt directory."""
    env = os.environ.copy()
    env["HOME"] = str(ALT_HOME)
    # Prompt hint so users know they are in the alt context
    shell = env.get("SHELL", "/bin/sh")
    shell_name = Path(shell).name
    # Prepend a marker to PS1 / PROMPT so the user sees they are in altergo context.
    # We set it in env; the shell will use it if no .bashrc/.zshrc overrides it.
    if shell_name in ("bash", "sh"):
        env["PS1"] = env.get("PS1", r"\u@\h:\w\$ ").lstrip()
        env["PS1"] = f"(altergo) {env['PS1']}"
    elif shell_name == "zsh":
        env["PROMPT"] = f"(altergo) {env.get('PROMPT', '%n@%m %~ %# ')}"
    print(_c(36, f"Entering altergo shell (HOME={ALT_HOME})"))
    print(_c(2, "Run 'exit' or Ctrl-D to return to your primary account.\n"))
    os.execvpe(shell, [shell], env)


def launch_command(cmd_args):
    """Run an arbitrary command with HOME set to alt directory."""
    if not cmd_args:
        print(_c(31, "altergo -- requires a command. Example: altergo -- gh auth login"), file=sys.stderr)
        sys.exit(1)
    env = os.environ.copy()
    env["HOME"] = str(ALT_HOME)
    os.execvpe(cmd_args[0], cmd_args, env)


# --- Main ---


def main():
    args = sys.argv[1:]

    # ── Altergo-owned commands (not passed to claude) ──────────────────────────

    if args and args[0] in ("-h", "--help"):
        print(__doc__)
        sys.exit(0)

    if args and args[0] == "--version":
        print(f"altergo {__version__}")
        sys.exit(0)

    if args and args[0] == "--setup":
        do_setup()
        sys.exit(0)

    if args and args[0] == "--teardown":
        do_teardown()
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
            launch_claude(["--resume", selected["id"]])
        else:
            print("Cancelled.")
        sys.exit(0)

    # altergo shell → interactive shell in alt HOME
    if args and args[0] == "shell":
        launch_shell()

    # altergo -- <cmd> [args...] → run arbitrary command in alt HOME
    if args and args[0] == "--":
        launch_command(args[1:])

    # ── Everything else → pass straight through to claude with alt HOME ────────
    # altergo            → claude
    # altergo --resume x → claude --resume x
    # altergo --dangerously-skip-permissions → claude --dangerously-skip-permissions
    launch_claude(args)


if __name__ == "__main__":
    main()
