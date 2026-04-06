#!/usr/bin/env python3
"""
Altergo — Your other Claude.

Multi-account session manager for Claude Code. Switch between Claude Code
identities without losing a thought. Uses symlinks to share session data
and a separate HOME for alt account credentials.

Usage:
  altergo                       Interactive session picker (↑/↓/j/k, Enter, q)
  altergo new                   Start a new session with alt credentials
  altergo --resume <id>         Resume a specific session directly
  altergo --list                List all sessions
  altergo --setup               First-time setup (alt home, symlinks)
  altergo --teardown            Remove symlinks and undo setup
  altergo --version             Show version
  altergo -h, --help            Show this help

Navigation (interactive picker):
  ↑/k          Move up             PgUp/PgDn    Page scroll
  ↓/j          Move down           g/G          Jump to top/bottom
  Enter        Resume session      q/Esc        Quit
"""

__version__ = "0.1.0"

import curses
import os
import pwd
import re
import sys
import subprocess
import json
from datetime import datetime
from pathlib import Path

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
    print("=== Altergo — Setup ===\n")

    # 1. Create alt home
    if not ALT_HOME.exists():
        ALT_HOME.mkdir(parents=True)
        print(f"Created alt home: {ALT_HOME}")
    else:
        print(f"  Alt home exists: {ALT_HOME}")

    # Ensure alt .claude dir exists
    ALT_CLAUDE.mkdir(parents=True, exist_ok=True)

    # 2. Symlink directories
    for name in SYMLINK_DIRS:
        src = MAIN_CLAUDE / name
        dst = ALT_CLAUDE / name

        if not src.exists():
            print(f"  Skip {name}/ (not found in main)")
            continue

        if dst.is_symlink():
            target = dst.resolve()
            if target == src.resolve():
                print(f"  {name}/ already symlinked")
            else:
                print(f"  Warning: {name}/ symlinked to {target} (expected {src})")
            continue

        if dst.exists():
            print(f"  Warning: {name}/ exists as real dir — remove it first to symlink")
            continue

        dst.symlink_to(src)
        print(f"  Symlinked {name}/")

    # 3. Symlink files
    for name in SYMLINK_FILES:
        src = MAIN_CLAUDE / name
        dst = ALT_CLAUDE / name

        if not src.exists():
            continue

        if dst.is_symlink():
            print(f"  {name} already symlinked")
            continue

        if dst.exists():
            dst.unlink()

        dst.symlink_to(src)
        print(f"  Symlinked {name}")

    # 4. Check credentials
    creds = ALT_CLAUDE / ".credentials.json"
    print()
    if creds.exists():
        print("  Alt account credentials found")
    else:
        print("  No alt account credentials found.")
        print("  Run 'altergo new' to authenticate with your alt account.\n")

    print("\nSetup complete!\n")
    print("Usage:")
    print("  altergo new                   Start a new session with alt credentials")
    print("  altergo                       Interactive session picker")
    print("  altergo --resume <session-id> Resume directly")
    print("  altergo --list                List all sessions")


def do_teardown():
    print("=== Altergo — Teardown ===\n")

    for name in SYMLINK_DIRS:
        dst = ALT_CLAUDE / name
        if dst.is_symlink():
            dst.unlink()
            print(f"  Removed symlink: {name}/")

    for name in SYMLINK_FILES:
        dst = ALT_CLAUDE / name
        if dst.is_symlink():
            dst.unlink()
            print(f"  Removed symlink: {name}")

    print("\nTeardown complete. Alt home and credentials left intact.")


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

            sessions.append({
                "id": session_id,
                "project": project_name,
                "modified": mod_dt,
                "size_mb": size_mb,
                "path": f,
                "preview": preview,
            })

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
    curses.init_pair(1, curses.COLOR_BLACK, curses.COLOR_CYAN)   # selected
    curses.init_pair(2, curses.COLOR_CYAN, -1)                    # header
    curses.init_pair(3, curses.COLOR_YELLOW, -1)                  # project name
    curses.init_pair(4, curses.COLOR_WHITE, -1)                   # session id
    curses.init_pair(5, curses.COLOR_GREEN, -1)                   # time

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
        stdscr.addnstr(2, 0, col_header[:max_x - 1], max_x - 1)
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
                preview = preview[:preview_width - 1] + "…"

            line = f"  {project:<20} {modified:<18} {size:>6}  {preview}"

            if idx == current:
                stdscr.attron(curses.color_pair(1) | curses.A_BOLD)
                stdscr.addnstr(row, 0, f"▸ {line[2:]}"[:max_x - 1].ljust(max_x - 1), max_x - 1)
                stdscr.attroff(curses.color_pair(1) | curses.A_BOLD)
            else:
                stdscr.addnstr(row, 0, line[:max_x - 1], max_x - 1)

        # Footer — show session ID of current selection
        footer_row = max_y - 2
        if current < len(sessions):
            sid = sessions[current]["id"]
            footer = f" Session: {sid}"
            stdscr.attron(curses.A_DIM)
            stdscr.addnstr(footer_row, 0, footer[:max_x - 1], max_x - 1)
            stdscr.attroff(curses.A_DIM)

        count_info = f" {current + 1}/{len(sessions)} sessions"
        stdscr.attron(curses.A_DIM)
        stdscr.addnstr(footer_row + 1, 0, count_info[:max_x - 1], max_x - 1)
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


# --- Resume ---


def resume_session(session_id, extra_args=None):
    """Launch claude with alt HOME to resume a session."""
    if not re.fullmatch(r'[a-fA-F0-9\-]{8,}', session_id):
        print(f"Error: invalid session ID format: {session_id!r}")
        sys.exit(1)

    env = os.environ.copy()
    env["HOME"] = str(ALT_HOME)

    cmd = ["claude", "--resume", session_id]
    if extra_args:
        cmd.extend(extra_args)

    print(f"Launching claude with alt credentials...")
    print(f"Session: {session_id}\n")
    os.execvpe("claude", cmd, env)


# --- Main ---


def main():
    args = sys.argv[1:]

    if not args:
        # Interactive mode
        sessions = get_sessions()
        selected = interactive_picker(sessions)
        if selected:
            resume_session(selected["id"])
        else:
            print("Cancelled.")
            sys.exit(0)

    elif args[0] in ("-h", "--help"):
        print(__doc__)
        sys.exit(0)

    elif args[0] == "--version":
        print(f"altergo {__version__}")
        sys.exit(0)

    elif args[0] == "new":
        env = os.environ.copy()
        env["HOME"] = str(ALT_HOME)
        os.execvpe("claude", ["claude"], env)

    elif args[0] == "--setup":
        do_setup()

    elif args[0] == "--teardown":
        do_teardown()

    elif args[0] == "--resume":
        if len(args) < 2:
            print("Error: provide a session ID")
            sys.exit(1)
        resume_session(args[1], args[2:])

    elif args[0] == "--list":
        sessions = get_sessions()
        if not sessions:
            print("No sessions found.")
            sys.exit(0)
        print(f"{'Project':<20} {'Modified':<18} {'Size':>6}  Session ID")
        print("-" * 80)
        for s in sessions[:30]:
            project = format_project_name(s["project"])
            modified = s["modified"].strftime("%Y-%m-%d %H:%M")
            size = f"{s['size_mb']:.1f}MB"
            print(f"{project:<20} {modified:<18} {size:>6}  {s['id']}")

    else:
        # Treat first arg as session ID for convenience
        resume_session(args[0], args[1:])


if __name__ == "__main__":
    main()
