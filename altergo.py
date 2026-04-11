#!/usr/bin/env python3
"""Altergo — multi-account session manager for AI coding assistants (Claude Code, Gemini CLI, Codex, Copilot). Run 'altergo --help' for usage."""

__version__ = "0.20.1"

import curses
import json
import os
import pwd
import re
import shutil
import subprocess
import sys
import threading
import time
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


# --- Themes ---
#
# A theme is a named palette that maps *logical roles* (command, arg, header,
# success, warn, brand, banner gradient, curses pairs) to concrete colors.
# All user-facing colors route through ``C(role)`` (ANSI), ``theme_banner()``
# (rich gradient) and ``_theme_curses()`` (curses pairs) so switching themes
# at runtime updates every surface uniformly.
#
# New themes just need an entry in THEMES. Readability is the hard rule —
# even the "crazy" rainbow theme must remain legible on dark *and* light
# terminals, which is why dim/version stay neutral and accents avoid pure
# yellow-on-white.

THEMES = {
    "ocean": {
        "display_name": "Ocean",
        "description":  "Calm cyan & indigo — the original altergo palette",
        "ansi": {
            "command": "38;5;39",     # blue
            "arg":     "38;5;87",     # electric cyan
            "header":  "1;38;5;39",   # bold blue
            "brand":   "38;5;105",    # indigo
            "success": "38;5;76",     # green
            "warn":    "38;5;220",    # amber
        },
        "curses": {"accent": 51, "project": 105, "amber": 220},
        "banner": ["#00d7ff", "#005fd7"],
    },
    "forest": {
        "display_name": "Forest",
        "description":  "Calming moss & sage — grounded green tones",
        "ansi": {
            "command": "38;5;78",     # mint
            "arg":     "38;5;121",    # sage
            "header":  "1;38;5;78",
            "brand":   "38;5;108",    # muted jade
            "success": "38;5;84",
            "warn":    "38;5;222",
        },
        "curses": {"accent": 78, "project": 108, "amber": 222},
        "banner": ["#5fff87", "#005f5f"],
    },
    "lavender": {
        "display_name": "Lavender",
        "description":  "Soft violet & periwinkle — gentle on the eyes",
        "ansi": {
            "command": "38;5;141",    # soft purple
            "arg":     "38;5;183",    # pale lavender
            "header":  "1;38;5;141",
            "brand":   "38;5;105",
            "success": "38;5;120",
            "warn":    "38;5;222",
        },
        "curses": {"accent": 141, "project": 105, "amber": 222},
        "banner": ["#d7afff", "#5f5fff"],
    },
    "sunset": {
        "display_name": "Sunset",
        "description":  "Warm rose & ember — dusk palette",
        "ansi": {
            "command": "38;5;209",    # coral
            "arg":     "38;5;215",    # peach
            "header":  "1;38;5;209",
            "brand":   "38;5;205",    # rose
            "success": "38;5;114",
            "warn":    "38;5;220",
        },
        "curses": {"accent": 209, "project": 205, "amber": 220},
        "banner": ["#ffaf5f", "#ff5f87"],
    },
    "mono": {
        "display_name": "Mono",
        "description":  "Grayscale — minimal, distraction-free",
        "ansi": {
            "command": "38;5;253",
            "arg":     "38;5;255",
            "header":  "1;38;5;255",
            "brand":   "38;5;245",
            "success": "38;5;250",
            "warn":    "38;5;249",
        },
        "curses": {"accent": 253, "project": 245, "amber": 249},
        "banner": ["#ffffff", "#808080"],
    },
    "rainbow": {
        "display_name": "Rainbow",
        "description":  "Every color, still readable — enables chaos mode",
        "ansi": {
            "command": "38;5;201",    # hot magenta
            "arg":     "38;5;51",     # cyan
            "header":  "1;38;5;226",  # yellow (bold, dark-term safe)
            "brand":   "38;5;165",    # violet
            "success": "38;5;46",     # lime
            "warn":    "38;5;214",    # orange
        },
        "curses": {"accent": 201, "project": 51, "amber": 214},
        # Multi-stop gradient — RichFiglet accepts N colors and interpolates.
        "banner": ["#ff005f", "#ff8700", "#ffff00", "#00ff5f", "#00d7ff", "#af5fff"],
    },
}

# Roles whose styling is intentionally theme-invariant — dim text should
# always read as dim, and the version blurb is purposely low-contrast.
_STATIC_ANSI = {
    "dim":     "2",
    "version": "2;38;5;244",
}

_DEFAULT_THEME = "ocean"

# Mutable current theme id — populated from SETTINGS_FILE at startup and
# mutated in-place when the user cycles themes in the launcher.
_CURRENT_THEME = _DEFAULT_THEME


def get_current_theme() -> str:
    """Return the id of the currently active theme."""
    return _CURRENT_THEME if _CURRENT_THEME in THEMES else _DEFAULT_THEME


def set_current_theme(name: str) -> None:
    """Update the in-process active theme (no disk write)."""
    global _CURRENT_THEME
    if name in THEMES:
        _CURRENT_THEME = name


def _gradient_color(stops: list, t: float) -> str:
    """Interpolate between hex color stops at position *t* (0.0–1.0)."""
    if len(stops) == 1 or t <= 0:
        return stops[0]
    if t >= 1:
        return stops[-1]
    segment = t * (len(stops) - 1)
    i = int(segment)
    f = segment - i
    if i >= len(stops) - 1:
        return stops[-1]
    r1, g1, b1 = int(stops[i][1:3], 16), int(stops[i][3:5], 16), int(stops[i][5:7], 16)
    r2, g2, b2 = int(stops[i+1][1:3], 16), int(stops[i+1][3:5], 16), int(stops[i+1][5:7], 16)
    r = int(r1 + (r2 - r1) * f)
    g = int(g1 + (g2 - g1) * f)
    b = int(b1 + (b2 - b1) * f)
    return f"#{r:02x}{g:02x}{b:02x}"


def _gradient_ansi(text: str, stops: list, *, bold: bool = False) -> str:
    """Render *text* with a per-character True Color ANSI gradient.

    Uses 24-bit escape sequences (``\\033[38;2;R;G;Bm``).  Falls back to
    plain text on non-TTY so piped output stays readable.
    """
    if not sys.stdout.isatty() or not stops:
        return text
    n = len(text)
    attrs = "1;" if bold else ""
    parts = []
    for i, ch in enumerate(text):
        col = _gradient_color(stops, i / max(n - 1, 1))
        r, g, b = int(col[1:3], 16), int(col[3:5], 16), int(col[5:7], 16)
        parts.append(f"\033[{attrs}38;2;{r};{g};{b}m{ch}")
    return "".join(parts) + "\033[0m"


def C(role: str) -> str:
    """Return the ANSI code for a logical role under the active theme.

    Falls back to the ocean theme for unknown themes and to an empty
    string for unknown roles so callers never crash on a typo.
    """
    if role in _STATIC_ANSI:
        return _STATIC_ANSI[role]
    theme = THEMES.get(get_current_theme(), THEMES[_DEFAULT_THEME])
    return theme["ansi"].get(role, "")


def _ansi_to_rich(code: str) -> str:
    """Translate one of altergo's ANSI color codes into a Rich style string.

    Our themes store colors as raw ANSI parameter lists (``"38;5;220"``,
    ``"1;38;5;39"``, ``"2"``) because that's what the plain-``_c`` path
    emits. Rich doesn't speak those directly, so this converts them into
    its native style string (``"color(220)"``, ``"bold color(39)"``,
    ``"dim"``) for use inside ``Text`` / ``Spinner`` styles.

    Only the subset we actually emit is handled; unrecognized codes fall
    back to empty string (Rich treats that as default).
    """
    if not code:
        return ""
    parts = code.split(";")
    out = []
    i = 0
    while i < len(parts):
        p = parts[i]
        if p == "1":
            out.append("bold")
            i += 1
        elif p == "2":
            out.append("dim")
            i += 1
        elif p == "38" and i + 2 < len(parts) and parts[i + 1] == "5":
            out.append(f"color({parts[i + 2]})")
            i += 3
        else:
            i += 1
    return " ".join(out)


def show_banner(
    account: str | None = None,
    *,
    latest_version: str | None = None,
    show_greeting: bool = False,
    animate_duration: float = 0.0,
):
    """Print the altergo banner. TTY-only.

    Parameters
    ----------
    account
        If given, the account name is rendered beneath the logo with stars
        around it so the user can see at a glance which identity the
        upcoming session will run under.
    latest_version
        The cached "latest version from PyPI" string. When strictly newer
        than the running version, the version column shows an arrow to it
        (``v0.12.0 → v0.13.0``) and a dim upgrade-action line is appended
        under the banner. Sanitized again here — defense in depth against
        a poisoned cache file.
    show_greeting
        When True, a dry time-of-day line (from :mod:`altergo_greetings`)
        is rendered below the figlet. Only set True on interactive launch
        paths (``launch_claude``/``launch_shell``/``launch_command``/
        ``interactive_launcher``). Silent on ``--help``/``--list`` etc. so
        piped and scripted output stays grep-able.
    animate_duration
        If > 0 and we're on a TTY, wrap the final render in ``rich.live.Live``
        for roughly this many seconds before returning. Used only on the
        launch handoff path so the star positions in the account line
        twinkle for ~700ms while the provider binary warms up. Capped by
        the caller to ``min(provider_cold_start, 0.7)``.
    """
    if not sys.stdout.isatty():
        suffix = f"  [{account}]" if account else ""
        print(f"  altergo {__version__}  —  Switch AI identities. Keep your context.{suffix}")
        return
    try:
        import pyfiglet
        from rich_pyfiglet import RichFiglet
        from rich.console import Console, Group
        from rich.text import Text
        from rich.table import Table
        from rich.align import Align
        from rich.spinner import Spinner
        console = Console()
        theme = THEMES.get(get_current_theme(), THEMES[_DEFAULT_THEME])
        theme_id = get_current_theme()
        grad = theme["banner"]
        figlet = RichFiglet("altergo", font="smslant", colors=grad, horizontal=True)

        # Measure the logo upfront — used both for the version column width
        # (so the version sits right next to the figlet, not on the far edge
        # of the terminal) and for centering the account name underneath.
        rendered = pyfiglet.Figlet(font="smslant").renderText("altergo")
        logo_lines = [l for l in rendered.splitlines() if l.strip()]
        logo_left = min((len(l) - len(l.lstrip()) for l in logo_lines), default=0)
        logo_right = max((len(l.rstrip()) for l in logo_lines), default=32)
        logo_width = logo_right - logo_left

        # Re-sanitize the latest version string — the cache is trusted
        # territory but we double-check before interpolating into output.
        clean_latest = _sanitize_version(latest_version)
        has_update = bool(clean_latest and _is_newer(clean_latest, __version__))

        # Build the right-column version tag. When an update is available,
        # the text becomes ``v<cur> → v<new>``, with the arrow + new version
        # in the theme's warn color so it reads as an attention beat
        # (creative-technologist's call — warn is deliberately chosen over
        # the banner gradient so it stays legible even in rainbow theme).
        version_color = grad[len(grad) // 2] if len(grad) >= 2 else grad[0]
        version_text = Text()
        version_text.append(f"v{__version__}", style=f"bold {version_color}")
        if has_update:
            warn_style = _ansi_to_rich(C("warn"))
            version_text.append(" → ", style=warn_style)
            version_text.append(f"v{clean_latest}", style=f"bold {warn_style}")

        logo_row = Table.grid(padding=(0, 1), expand=False)
        logo_row.add_column(width=logo_right, no_wrap=True)
        logo_row.add_column(no_wrap=True)
        logo_row.add_row(figlet, Align(version_text, "left", vertical="middle"))

        # Body renderables assembled top-to-bottom:
        #   [logo_row]  figlet + version tag
        #   [bottom]    * account (left) + gradient greeting (right)
        #   [upgrade]   dim pip command, only when an update is pending
        body: list = [logo_row]

        # Pre-fetch greeting so both animated and static paths share the same
        # pick — same minute seed, same result, no double-import.
        greet_icon = greet_line = ""
        if show_greeting:
            try:
                import altergo_greetings as _greet
                greet_icon, greet_line = _greet.pick_greeting()
            except Exception:
                # Greetings are a nice-to-have — never break the banner.
                pass

        # Bottom row: account name left-aligned to the logo edge (left) and
        # the greeting right of it, gradient-tinted with the theme palette.
        # During the launch-handoff animation the static '*' is replaced by a
        # Rich Spinner so the symbol visibly ticks while the provider warms up.
        if account or greet_line:
            DIM    = grad[-1]
            BRIGHT = f"bold {grad[0]}"
            MID    = grad[len(grad) // 2] if len(grad) > 2 else grad[0]

            # Greeting text with smooth per-character gradient across the message.
            greet_text = Text()
            if greet_line:
                greet_text.append(f"  {greet_icon}  ", style=MID)
                _n = len(greet_line)
                for _i, _ch in enumerate(greet_line):
                    _t = _i / max(_n - 1, 1)
                    greet_text.append(_ch, style=_gradient_color(grad, _t))

            if account:
                if animate_duration > 0:
                    try:
                        import altergo_greetings as _greet
                        spinner_name = _greet.spinner_for_theme(theme_id)
                    except Exception:
                        spinner_name = "dots"
                    from rich.padding import Padding
                    acct_inner = Table.grid(padding=(0, 0), expand=False)
                    acct_inner.add_column(no_wrap=True)
                    acct_inner.add_column(no_wrap=True)
                    acct_inner.add_row(
                        Spinner(spinner_name, style=BRIGHT),
                        Text(f"  {account}", style=BRIGHT),
                    )
                    bottom = Table.grid(padding=(0, 0), expand=False)
                    bottom.add_column(min_width=logo_right, no_wrap=True)
                    bottom.add_column(no_wrap=True)
                    bottom.add_row(Padding(acct_inner, (0, 0, 0, 2)), greet_text)
                    body.append(bottom)
                else:
                    left_text = Text()
                    left_text.append("  ")
                    left_text.append("*", style=BRIGHT)
                    left_text.append("  ", style=MID)
                    left_text.append(account, style=BRIGHT)
                    if greet_line:
                        bottom = Table.grid(padding=(0, 0), expand=False)
                        bottom.add_column(min_width=logo_right, no_wrap=True)
                        bottom.add_column(no_wrap=True)
                        bottom.add_row(left_text, greet_text)
                        body.append(bottom)
                    else:
                        body.append(left_text)
            else:
                # Greeting only (no account context).
                body.append(greet_text)

        # Upgrade action line — one dim line with the literal pip command
        # so the user knows what to type. Only when an update is pending.
        if has_update:
            upgrade_text = Text()
            upgrade_text.append("  ", style=C("dim"))
            try:
                import altergo_greetings as _greet
                upgrade_text.append(_greet.pick_icon() + "  ", style=C("dim"))
            except Exception:
                upgrade_text.append("* ", style=C("dim"))
            upgrade_text.append("upgrade: ", style=C("dim"))
            upgrade_text.append("pip install -U altergo", style=C("command"))
            body.append(upgrade_text)

        group = Group(*body)

        if animate_duration > 0:
            # Rich Live ticks the Spinner cells in a render thread while the
            # main thread sleeps the capped duration. On exit Live prints the
            # last frame as persistent output, so the terminal is left in a
            # clean state before we hand off to the provider CLI.
            from rich.live import Live
            with Live(group, console=console, refresh_per_second=12,
                      transient=False):
                time.sleep(animate_duration)
        else:
            console.print(group)
    except Exception:
        suffix = f"  [{account}]" if account else ""
        print(f"  altergo {__version__}  —  Switch AI identities. Keep your context.{suffix}")


def show_help():
    """Print --help output with color and OSC 8 hyperlinks when on a TTY."""
    grad = THEMES.get(get_current_theme(), THEMES[_DEFAULT_THEME])["banner"]

    def h(t):
        return "  " + _gradient_ansi(t, grad, bold=True)

    def kw(t):
        return _c(C("command"), t)

    def arg(t):
        return _c(C("arg"), t)

    def dim(t):
        return _c(C("dim"), t)

    def sep():
        return _c(C("dim"), "  " + "─" * 52)

    pixelabs = _link("https://pixelabs.net", _c(C("brand"), "pixelabs.net"))

    show_banner()
    print(f"  {dim('Because one personality was not causing enough bugs.')}")
    print(f"  A {pixelabs} project.")

    lines = [
        "",
        sep(),
        h("Launch"),
        f"  {kw('altergo')}                             {dim('Open launcher or start active account')}",
        f"  {kw('altergo')} {arg('<name>')}                     {dim('Launch a specific account')}",
        f"  {kw('altergo')} {arg('<name>')} {arg('<provider>')}           {dim('Launch with a specific provider')}",
        "",
        sep(),
        h("Accounts"),
        f"  {kw('altergo --setup')}                    {dim('Create or reconfigure an account')}",
        f"  {kw('altergo --setup --name')} {arg('<name>')}      {dim('Name the account')}",
        f"  {kw('altergo --setup --provider')} {arg('<p,…>')}   {dim('claude, gemini, codex, copilot')}",
        f"  {kw('altergo --use')} {arg('<name>')}               {dim('Set default account')}",
        f"  {kw('altergo --teardown')} {arg('[--name <n>]')}    {dim('Remove account symlinks')}",
        f"  {kw('altergo --settings')}                 {dim('Manage shared credentials (TUI)')}",
        "",
        sep(),
        h("Sessions"),
        f"  {kw('altergo --resume')}                   {dim('Pick session interactively')}",
        f"  {kw('altergo --resume')} {arg('<id>')}             {dim('Resume by session ID')}",
        f"  {kw('altergo --search')}                   {dim('Search conversation history')}",
        f"  {kw('altergo --list')}                     {dim('List recent sessions')}",
        "",
        sep(),
        h("Customization"),
        f"  {kw('altergo --theme')}                    {dim('Show active theme')}",
        f"  {kw('altergo --theme')} {arg('<name>')}            {dim(', '.join(THEMES.keys()))}",
        f"  {kw('altergo --update-check')} {arg('on|off')}     {dim('Enable or disable update checker')}",
        "",
        sep(),
        h("Advanced"),
        f"  {kw('altergo')} {arg('<name>')} {kw('shell')}             {dim('Shell inside account HOME')}",
        f"  {kw('altergo')} {arg('<name>')} {kw('--')} {arg('<cmd>')}         {dim('Run command in account context')}",
        "",
        sep(),
        h("Navigation"),
        f"  {kw('↑↓')} {kw('jk')}    {dim('move')}    {kw('←→')} {kw('hl')}  {dim('switch account')}    {kw('Enter')}  {dim('launch')}",
        f"  {kw('t')}       {dim('cycle theme')}   {kw('s')}      {dim('shell mode')}       {kw('d')}      {dim('set default')}",
        f"  {kw('p')} {kw('Tab')}    {dim('preview')}   {kw('/')}      {dim('search')}           {kw('g')} {kw('G')}   {dim('top / bottom')}",
        f"  {kw('q')} {kw('Esc')}    {dim('quit')}",
        "",
        dim("  altergo · open-source by pixelabs · not affiliated with Anthropic, Google, OpenAI, or GitHub"),
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
    # Step 1: take a backup BEFORE any rename so it is never self-referential.
    # The backup lives outside the altergo tree at ~/.altergo-legacy-backup/.
    backup_path = MAIN_HOME / ".altergo-legacy-backup"
    if backup_path.exists():
        print("altergo: backup already exists at ~/.altergo-legacy-backup — skipping backup step")
    else:
        shutil.copytree(str(old_root), str(backup_path), symlinks=True)
    tmp_path = Path(f"/tmp/altergo-migrate-{os.getpid()}")
    # Step 2: rename ~/.altergo → /tmp/altergo-migrate-{pid}
    old_root.rename(tmp_path)
    # Step 3: mkdir -p ~/.altergo/accounts/
    ACCOUNTS_DIR.mkdir(parents=True, exist_ok=True)
    # Step 4: rename /tmp/... → ~/.altergo/accounts/default/
    default_home = ACCOUNTS_DIR / "default"
    tmp_path.rename(default_home)
    # Step 5: write audit trail so users can verify what happened
    migrated_marker = default_home / "MIGRATED.txt"
    migrated_marker.write_text(
        f"Migrated by altergo v{__version__} on {datetime.now().isoformat(timespec='seconds')}\n"
        f"Old layout: ~/.altergo/\n"
        f"New layout: ~/.altergo/accounts/default/\n"
        f"Backup:     ~/.altergo-legacy-backup/\n"
        f"Rollback:   remove ~/.altergo/accounts/ and rename ~/.altergo-legacy-backup back to ~/.altergo\n"
        f"See:        https://altergo.pixelabs.net/docs/migration-0.5\n"
    )
    # Step 6: print a visible block — this is a one-time destructive rename, silence is wrong
    print("altergo: layout migrated for v0.5.0 N-account support")
    print("  ~/.altergo/  →  ~/.altergo/accounts/default/")
    print("  Backup preserved at ~/.altergo-legacy-backup/")
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

# Provider definitions — drives per-provider setup/teardown/launch logic.
# SYMLINK_DIRS and SYMLINK_FILES above are kept for backwards compat (teardown
# of legacy accounts that predate account.json).
PROVIDERS = {
    "claude": {
        "display_name": "Claude Code",
        "dot_dir": ".claude",
        "binary": "claude",
        "credentials_file": ".credentials.json",
        "symlink_dirs": [
            "projects", "tasks", "session-env", "file-history",
            "shell-snapshots", "agents", "plans", "cache",
        ],
        "symlink_files": ["settings.json", "CLAUDE.md", "keybindings.json"],
    },
    "gemini": {
        "display_name": "Gemini CLI",
        "dot_dir": ".gemini",
        "binary": "gemini",
        "credentials_file": "oauth_creds.json",
        "symlink_dirs": ["tmp", "commands"],
        "symlink_files": ["settings.json", "GEMINI.md"],
    },
    "codex": {
        "display_name": "Codex CLI",
        "dot_dir": ".codex",
        "binary": "codex",
        "credentials_file": "auth.json",
        "symlink_dirs": ["sessions", "rules"],
        "symlink_files": ["config.toml", "AGENTS.md", "AGENTS.override.md"],
    },
    "copilot": {
        "display_name": "GitHub Copilot",
        "dot_dir": ".copilot",
        "binary": "copilot",
        "credentials_file": "config.json",
        "symlink_dirs": ["session-state", "agents", "skills", "hooks"],
        "symlink_files": ["mcp-config.json", "lsp-config.json"],
    },
}

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


def load_account_meta(account_home: Path) -> dict:
    """Load account metadata. Returns dict with 'providers' list.

    Backwards compat: if account.json missing but .claude/ exists, returns
    {"version": 1, "providers": ["claude"]} without writing anything.
    If neither exists, returns None.
    """
    meta_file = account_home / "account.json"
    if meta_file.exists():
        try:
            return json.loads(meta_file.read_text())
        except Exception:
            return {"version": 1, "providers": ["claude"]}
    # Legacy account: .claude dir exists but no account.json
    if (account_home / ".claude").exists():
        return {"version": 1, "providers": ["claude"]}
    return None


def save_account_meta(account_home: Path, meta: dict) -> None:
    """Atomically write account.json."""
    account_home.mkdir(parents=True, exist_ok=True)
    meta_file = account_home / "account.json"
    tmp = meta_file.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(meta, indent=2))
    os.replace(str(tmp), str(meta_file))


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
    """Atomically write settings overlay to SETTINGS_FILE. Preserves other top-level keys."""
    SETTINGS_FILE.parent.mkdir(parents=True, exist_ok=True)
    data = {}
    if SETTINGS_FILE.exists():
        try:
            data = json.loads(SETTINGS_FILE.read_text())
        except Exception:
            data = {}
    data["version"] = 1
    data["shared"] = overrides
    tmp = SETTINGS_FILE.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(data, indent=2))
    os.replace(str(tmp), str(SETTINGS_FILE))


def load_persisted_theme() -> str:
    """Read the persisted theme name from SETTINGS_FILE.

    Returns the default theme id if the file is missing, malformed, or names
    a theme that no longer exists in THEMES (e.g. after a downgrade).
    """
    if not SETTINGS_FILE.exists():
        return _DEFAULT_THEME
    try:
        data = json.loads(SETTINGS_FILE.read_text())
        name = data.get("theme")
        if isinstance(name, str) and name in THEMES:
            return name
    except Exception:
        pass
    return _DEFAULT_THEME


def save_persisted_theme(name: str) -> None:
    """Persist the chosen theme name to SETTINGS_FILE without clobbering siblings."""
    if name not in THEMES:
        return
    SETTINGS_FILE.parent.mkdir(parents=True, exist_ok=True)
    data = {}
    if SETTINGS_FILE.exists():
        try:
            data = json.loads(SETTINGS_FILE.read_text())
        except Exception:
            data = {}
    data["theme"] = name
    tmp = SETTINGS_FILE.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(data, indent=2))
    os.replace(str(tmp), str(SETTINGS_FILE))


# ── Random theme helpers ──────────────────────────────────────────────────────

def _patch_settings(updates: dict) -> None:
    """Atomically merge *updates* into SETTINGS_FILE, preserving all other keys."""
    SETTINGS_FILE.parent.mkdir(parents=True, exist_ok=True)
    data: dict = {}
    if SETTINGS_FILE.exists():
        try:
            data = json.loads(SETTINGS_FILE.read_text())
        except Exception:
            data = {}
    data.update(updates)
    tmp = SETTINGS_FILE.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(data, indent=2))
    os.replace(str(tmp), str(SETTINGS_FILE))


def load_random_theme_settings() -> dict:
    """Return random_theme_enabled, random_theme_frequency, random_theme_counter."""
    defaults: dict = {
        "random_theme_enabled": False,
        "random_theme_frequency": 3,
        "random_theme_counter": 0,
    }
    if not SETTINGS_FILE.exists():
        return defaults
    try:
        data = json.loads(SETTINGS_FILE.read_text())
        enabled = data.get("random_theme_enabled")
        freq    = data.get("random_theme_frequency")
        ctr     = data.get("random_theme_counter")
        return {
            "random_theme_enabled":   enabled if isinstance(enabled, bool) else False,
            "random_theme_frequency": freq    if isinstance(freq, int) and 1 <= freq <= 5 else 3,
            "random_theme_counter":   ctr     if isinstance(ctr, int) and ctr >= 0 else 0,
        }
    except Exception:
        return defaults


def _random_theme_counter_range(freq: int) -> tuple:
    """Map frequency slot (1-5) to (min_sessions, max_sessions) range."""
    if freq <= 2:
        return (1, 5)
    elif freq == 3:
        return (5, 10)
    else:
        return (10, 20)


def maybe_rotate_random_theme() -> None:
    """Decrement the random-theme counter; rotate theme when it hits zero.

    Called once per session start, after load_persisted_theme() seeds
    _CURRENT_THEME. No-op if random_theme_enabled is False.
    """
    import random as _random
    rts = load_random_theme_settings()
    if not rts["random_theme_enabled"]:
        return

    freq    = rts["random_theme_frequency"]
    counter = rts["random_theme_counter"]

    # Counter of 0 means "not yet initialized" — seed it and return.
    if counter <= 0:
        lo, hi = _random_theme_counter_range(freq)
        _patch_settings({"random_theme_counter": _random.randint(lo, hi)})
        return

    counter -= 1
    if counter > 0:
        _patch_settings({"random_theme_counter": counter})
        return

    # Counter hit zero — pick a new theme (avoid repeating current) and reset.
    current = get_current_theme()
    choices = [t for t in THEMES if t != current]
    new_theme = _random.choice(choices) if choices else current
    lo, hi = _random_theme_counter_range(freq)
    set_current_theme(new_theme)
    _patch_settings({"theme": new_theme, "random_theme_counter": _random.randint(lo, hi)})


# --- Launch-handoff animation duration (per-provider) ---
#
# Capped by panel decision (option A) at 0.7s max so the animation never
# adds perceived latency beyond provider cold start. Codex is effectively
# instant (27ms measured) so we skip animation for it — a 700ms dance
# would finish long after codex itself is up.
_HANDOFF_ANIM_SECONDS: dict[str, float] = {
    "claude":  0.7,
    "gemini":  0.7,
    "copilot": 0.7,
    "codex":   0.0,
}


def _handoff_duration(provider: str | None) -> float:
    """Return the capped twinkle duration for the given provider id."""
    if provider is None:
        return 0.0
    return _HANDOFF_ANIM_SECONDS.get(provider, 0.0)


def _status_wrap(message: str, func, *args, **kwargs):
    """Call ``func`` while showing a Rich spinner-status line.

    Falls back to a plain synchronous call on non-TTY or if Rich is not
    importable (shouldn't happen — altergo depends on it — but we don't
    want a status wrapper to ever hide a real error). The spinner picked
    matches the active theme via ``altergo_greetings.spinner_for_theme``.
    """
    if not sys.stdout.isatty():
        return func(*args, **kwargs)
    try:
        from rich.console import Console
        try:
            import altergo_greetings as _greet
            spinner = _greet.spinner_for_theme(get_current_theme())
        except Exception:
            spinner = "dots"
        console = Console()
        with console.status(f"[dim]{message}[/dim]", spinner=spinner):
            return func(*args, **kwargs)
    except Exception:
        return func(*args, **kwargs)


# --- Update check: settings, cache, fetch ---
#
# The version checker is a stale-while-revalidate design hardened by the
# security review: a daemon-threaded fetch writes a cache file with a
# strictly validated version string; show_banner reads that cache on the
# hot path with zero network involvement. Everything fails silently.
#
# Design constraints (from panel review):
#   - Default ON, with a one-time first-launch consent line (CEO + product
#     compromise with security's "must consent before first request" rule).
#   - stdlib only — urllib.request, json, threading. No `requests`, no
#     `packaging`. altergo currently ships with only rich + pyfiglet.
#   - 3s socket timeout, 32KB response cap, 3-redirect cap.
#   - Version string allowlisted (`^[0-9a-zA-Z.\-+]{1,32}$`) both at fetch
#     (discard on mismatch) and at render (discard on mismatch). Defense in
#     depth against a poisoned cache or crafted PyPI response.
#   - User-Agent reveals version only — no hostname, no account names.
#   - Cache file lives alongside settings but is a separate file: different
#     lifecycle, avoids churning settings on every daily check.

UPDATE_CACHE_FILE = MAIN_HOME / ".altergo" / "version_check.json"
UPDATE_CACHE_TTL_SECONDS = 24 * 60 * 60  # daily refresh
UPDATE_FETCH_TIMEOUT = 3.0
UPDATE_FETCH_MAX_BYTES = 32 * 1024
UPDATE_PYPI_URL = "https://pypi.org/pypi/altergo/json"

# Regex allowlist for any version string that touches a terminal. Rejects
# anything containing whitespace, control chars, ANSI, or exotic unicode —
# all of which could corrupt the banner render if printed unsanitized.
_VERSION_RE = re.compile(r"^[0-9a-zA-Z.\-+]{1,32}$")


def _sanitize_version(v) -> str | None:
    """Return ``v`` if it is a valid, printable version string, else None.

    Must be called on every boundary where a version string enters from
    untrusted territory: PyPI response, cache file read, banner render.
    """
    if not isinstance(v, str):
        return None
    if _VERSION_RE.match(v):
        return v
    return None


def load_update_check_enabled() -> bool:
    """Return whether the user has opted into update checks.

    Default is **True** — panel consensus was that altergo is pre-adoption
    and needs users on current versions. The one-time consent line printed
    on first launch (see :func:`first_launch_notice_if_needed`) is the
    compensating control for the opt-out default.
    """
    if not SETTINGS_FILE.exists():
        return True
    try:
        data = json.loads(SETTINGS_FILE.read_text())
        v = data.get("update_check")
        if isinstance(v, bool):
            return v
    except Exception:
        pass
    return True


def save_update_check_enabled(enabled: bool) -> None:
    """Persist the update-check opt-in flag without clobbering siblings."""
    SETTINGS_FILE.parent.mkdir(parents=True, exist_ok=True)
    data = {}
    if SETTINGS_FILE.exists():
        try:
            data = json.loads(SETTINGS_FILE.read_text())
        except Exception:
            data = {}
    data["update_check"] = bool(enabled)
    tmp = SETTINGS_FILE.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(data, indent=2))
    os.replace(str(tmp), str(SETTINGS_FILE))


def _load_bool_setting(key: str, default: bool = True) -> bool:
    """Load a boolean setting from SETTINGS_FILE.

    Generic helper for the preference toggles introduced by the multi-page
    settings TUI (show_greeting, show_goodbye, launch_animation).  Also
    usable for any future boolean setting.
    """
    if not SETTINGS_FILE.exists():
        return default
    try:
        data = json.loads(SETTINGS_FILE.read_text())
        v = data.get(key)
        return v if isinstance(v, bool) else default
    except Exception:
        return default


def _get_intro_shown() -> bool:
    if not SETTINGS_FILE.exists():
        return False
    try:
        data = json.loads(SETTINGS_FILE.read_text())
        return bool(data.get("update_check_intro_shown"))
    except Exception:
        return False


def _mark_intro_shown() -> None:
    SETTINGS_FILE.parent.mkdir(parents=True, exist_ok=True)
    data = {}
    if SETTINGS_FILE.exists():
        try:
            data = json.loads(SETTINGS_FILE.read_text())
        except Exception:
            data = {}
    data["update_check_intro_shown"] = True
    tmp = SETTINGS_FILE.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(data, indent=2))
    os.replace(str(tmp), str(SETTINGS_FILE))


def _read_update_cache() -> dict:
    """Read and validate the update cache. Returns {} on any error.

    Re-sanitizes the cached version string — a local attacker who can write
    ``~/.altergo/`` can still poison the cache, but can no longer inject a
    crafted string into a future banner render. A poisoned entry is simply
    dropped and treated as a cache miss.
    """
    if not UPDATE_CACHE_FILE.exists():
        return {}
    try:
        data = json.loads(UPDATE_CACHE_FILE.read_text())
    except Exception:
        return {}
    if not isinstance(data, dict):
        return {}
    # Schema guard
    if data.get("schema_version") != 1:
        return {}
    # Sanitize on read — belt and suspenders
    v = _sanitize_version(data.get("latest_version"))
    if v is None:
        data.pop("latest_version", None)
    else:
        data["latest_version"] = v
    return data


def _write_update_cache(latest_version: str | None) -> None:
    """Atomically write the update cache. Validates before writing."""
    UPDATE_CACHE_FILE.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "schema_version": 1,
        "last_check": int(time.time()),
    }
    v = _sanitize_version(latest_version)
    if v is not None:
        payload["latest_version"] = v
    tmp = UPDATE_CACHE_FILE.with_suffix(".json.tmp")
    try:
        tmp.write_text(json.dumps(payload))
        os.replace(str(tmp), str(UPDATE_CACHE_FILE))
        try:
            os.chmod(str(UPDATE_CACHE_FILE), 0o600)
        except OSError:
            pass
    except Exception:
        # Silent failure — we never want the update checker to break launch.
        pass


def _parse_version(v: str) -> tuple:
    """Parse a MAJOR.MINOR.PATCH string into a comparable tuple.

    Strips any pre-release or local version suffix (``0.13.0rc1`` →
    ``(0, 13, 0)``) and returns an empty tuple on parse error. Intentionally
    stdlib-only — avoids adding ``packaging`` as a runtime dep.
    """
    try:
        core = v.split("+", 1)[0].split("-", 1)[0]
        parts: list[int] = []
        for p in core.split("."):
            # Trim anything non-numeric from the end of the segment to
            # tolerate trailing letters like "0rc1" → "0".
            digits = ""
            for ch in p:
                if ch.isdigit():
                    digits += ch
                else:
                    break
            if digits:
                parts.append(int(digits))
        return tuple(parts)
    except Exception:
        return ()


def _is_newer(latest: str, current: str) -> bool:
    """Return True iff ``latest`` is strictly newer than ``current``."""
    a = _parse_version(latest)
    b = _parse_version(current)
    if not a or not b:
        return False
    return a > b


def _fetch_latest_version() -> None:
    """Fetch altergo's latest version from PyPI and update the cache.

    Runs in a daemon thread — MUST never raise out of this function and
    MUST never print. All exceptions are swallowed. Hardening per security
    review: 3s timeout, 32KB response cap, 3-redirect cap, TLS enforced,
    version string allowlisted before caching.
    """
    try:
        import urllib.request
        import urllib.error

        class _CappedRedirect(urllib.request.HTTPRedirectHandler):
            """Redirect handler that caps at 3 hops."""
            max_redirections = 3

        ua = f"altergo/{__version__} Python/{sys.version_info.major}.{sys.version_info.minor}"
        req = urllib.request.Request(UPDATE_PYPI_URL, headers={"User-Agent": ua})
        opener = urllib.request.build_opener(_CappedRedirect())
        with opener.open(req, timeout=UPDATE_FETCH_TIMEOUT) as resp:
            raw = resp.read(UPDATE_FETCH_MAX_BYTES + 1)
            if len(raw) > UPDATE_FETCH_MAX_BYTES:
                # Response unexpectedly large — reject, don't partial-parse.
                _write_update_cache(None)
                return
            data = json.loads(raw.decode("utf-8", errors="replace"))
        info = data.get("info") if isinstance(data, dict) else None
        raw_v = info.get("version") if isinstance(info, dict) else None
        sanitized = _sanitize_version(raw_v)
        _write_update_cache(sanitized)
    except Exception:
        # Write a timestamp-only record so we don't hammer a broken endpoint
        # on every launch — still retried after the TTL.
        try:
            _write_update_cache(None)
        except Exception:
            pass


def maybe_refresh_update_cache() -> None:
    """Kick off a background refresh if the cache is stale and opt-in is on.

    Called from the launch path. First launch (no cache file at all) writes
    a timestamp-only record and skips the network entirely — first runs
    feel instant, and the consent line has already been printed by the
    time any real fetch fires.
    """
    if not load_update_check_enabled():
        return
    cache = _read_update_cache()
    # First launch ever: write a stub, skip the network.
    if not cache:
        _write_update_cache(None)
        return
    last = cache.get("last_check", 0)
    now = int(time.time())
    # Clock-skew guard: if last_check is in the future by more than a
    # minute, treat it as stale and refresh.
    if now < last - 60:
        pass
    elif now - last < UPDATE_CACHE_TTL_SECONDS:
        return
    # Daemon thread so it never blocks exit. Product-engineer chose this
    # over os.fork() after the architect conceded on macOS fork-safety.
    t = threading.Thread(target=_fetch_latest_version, daemon=True)
    t.start()


def get_cached_latest_version() -> str | None:
    """Return the last-known sanitized latest version, or None."""
    cache = _read_update_cache()
    return _sanitize_version(cache.get("latest_version"))


def first_launch_notice_if_needed() -> None:
    """Print the one-time consent notice if the user hasn't seen it yet.

    This is the compensating control the security review demanded for the
    opt-out default. Printed once, then never again, regardless of whether
    a nag ever fires. Satisfies informed-consent-before-first-request.
    """
    if _get_intro_shown():
        return
    if sys.stdout.isatty():
        print(
            "  " + _c(C("dim"),
                       "Version checks are enabled by default. "
                       "Disable with: altergo --update-check off")
        )
    _mark_intro_shown()


def get_active_account() -> str | None:
    """Return the persisted active account name, or None if not set / no longer valid."""
    if not SETTINGS_FILE.exists():
        return None
    try:
        data = json.loads(SETTINGS_FILE.read_text())
        name = data.get("active_account")
        if name and isinstance(name, str) and (ACCOUNTS_DIR / name).is_dir():
            return name
        return None
    except Exception:
        return None


def set_active_account(name: str) -> None:
    """Persist active_account to SETTINGS_FILE without clobbering other keys."""
    SETTINGS_FILE.parent.mkdir(parents=True, exist_ok=True)
    data = {}
    if SETTINGS_FILE.exists():
        try:
            data = json.loads(SETTINGS_FILE.read_text())
        except Exception:
            data = {}
    data["active_account"] = name
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


# --- Setup / Teardown ---


def _ensure_symlinked_dir(name: str, src: Path, dst: Path, account_claude: Path) -> bool:
    """Ensure dst is a symlink pointing to src, auto-migrating real dirs if needed.

    Returns True if any change was made (symlink created or content moved).

    Cases:
      (a) dst is already a symlink to src         -> no-op, return False
      (b) dst does not exist                      -> create src + symlink, return True
      (c) dst is a real empty dir                 -> rmdir + symlink, return True
      (d) dst is real non-empty, src empty/absent -> move content to src, symlink, return True
      (e) both have content                       -> merge; conflict items go to quarantine dir
    """
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
        # (d) src absent or empty — move dst content wholesale
        src.parent.mkdir(parents=True, exist_ok=True)
        if not src.exists():
            shutil.move(str(dst), str(src))
        else:
            # src exists but is empty: move each entry in
            for entry in list(dst.iterdir()):
                shutil.move(str(entry), str(src / entry.name))
            dst.rmdir()
        dst.symlink_to(src)
        print(f"  Promoted {name}/ to shared store")
        return True

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


def do_setup(account: str = "default", providers: list[str] | None = None):
    if providers is None:
        providers = ["claude"]
    account_home, account_claude = resolve_account(account)
    show_banner(account)
    header = f"altergo v{__version__} · " + _link("https://pixelabs.net", "pixelabs.net")
    print(_c(C("dim"), header))
    print(_c(C("header"), f"=== Altergo — Setup ({account}) ==="))
    print()

    # Load existing metadata for created timestamp preservation
    meta = load_account_meta(account_home)

    # 1. Create account home
    if not account_home.exists():
        account_home.mkdir(parents=True)
        print(f"  {_c(32, '✓')} Created account home: {account_home}")
    else:
        print(f"  {_c(32, '✓')} Account home exists: {account_home}")

    # 2. Wire each provider
    for pid in providers:
        prov = PROVIDERS[pid]
        main_dot_dir = MAIN_HOME / prov["dot_dir"]
        acct_dot_dir = account_home / prov["dot_dir"]

        print()
        print(_c(1, _c(36, f"=== Provider: {prov['display_name']} ===")))

        # Ensure provider dot-dir exists
        acct_dot_dir.mkdir(parents=True, exist_ok=True)

        # Symlink directories
        for name in prov["symlink_dirs"]:
            src = main_dot_dir / name
            dst = acct_dot_dir / name

            if dst.is_symlink():
                target = dst.resolve()
                if target == src.resolve():
                    print(f"  {_c(32, '✓')} {name}/ already symlinked")
                else:
                    print(f"  {_c(33, '⚠')} {name}/ symlinked to {target} (expected {src})")
                continue

            # _ensure_symlinked_dir handles all real-dir migration cases (empty
            # real dir, non-empty real dir, merge conflicts).  It prints its own
            # richer messages for promotion/merge/conflict cases.  For the normal
            # fresh-install path (dst absent) it silently creates the symlink and
            # returns True, so we print the standard checkmark here.
            was_absent = not dst.exists()
            _ensure_symlinked_dir(name, src, dst, acct_dot_dir)
            if was_absent and dst.is_symlink():
                print(f"  {_c(32, '✓')} Symlinked {name}/")

        # Symlink files
        for name in prov["symlink_files"]:
            src = main_dot_dir / name
            dst = acct_dot_dir / name

            if not src.exists():
                continue

            if dst.is_symlink():
                print(f"  {_c(32, '✓')} {name} already symlinked")
                continue

            if dst.exists():
                dst.unlink()

            dst.symlink_to(src)
            print(f"  {_c(32, '✓')} Symlinked {name}")

        # Check credentials for this provider
        creds = acct_dot_dir / prov["credentials_file"]
        print()
        if creds.exists():
            print(f"  {_c(32, '✓')} {prov['display_name']} credentials found")
        else:
            print(f"  {_c(33, '⚠')} No {prov['display_name']} credentials found.")
            cmd = f"altergo {account}" if account != "default" else "altergo"
            print(f"     Run '{cmd}' to authenticate.\n")

    # 3. Apply catalog entries (shared CLI tool credentials) at account_home level
    overrides = load_settings()

    def _apply_catalog_entries():
        for entry in CATALOG:
            _apply_entry(entry, overrides, account_home)

    _status_wrap("Linking shared credentials…", _apply_catalog_entries)

    # 4. Save account metadata
    save_account_meta(account_home, {
        "version": 1,
        "providers": providers,
        "created": (meta.get("created") if meta else None) or datetime.now().isoformat(timespec="seconds"),
    })

    launch_cmd = f"altergo {account}" if account != "default" else "altergo"
    print()
    print(_c(32, "Setup complete!"))
    print(f"  Run {_c(1, launch_cmd)} to start a session  ·  {_c(1, 'altergo --resume')} to pick one")
    print()
    print(_c(2, "  Isolates credentials per provider. Shares AWS, GCP, Docker, and kubectl by default."))
    print(_c(2, f"  Change sharing settings: {_c(0, 'altergo --settings')}"))


def do_teardown(account: str = "default"):
    account_home, account_claude = resolve_account(account)
    header = f"altergo v{__version__} · " + _link("https://pixelabs.net", "pixelabs.net")
    print(_c(2, header))
    print(_c(1, _c(36, f"=== Altergo — Teardown ({account}) ===")))
    print()

    meta = load_account_meta(account_home)

    if meta is not None and "providers" in meta:
        # Modern account with account.json — tear down per-provider symlinks
        for pid in meta["providers"]:
            prov = PROVIDERS.get(pid)
            if prov is None:
                continue
            acct_dot_dir = account_home / prov["dot_dir"]

            for name in prov["symlink_dirs"]:
                dst = acct_dot_dir / name
                if dst.is_symlink():
                    dst.unlink()
                    print(f"  {_c(33, '✓')} Removed symlink: {prov['dot_dir']}/{name}/")

            for name in prov["symlink_files"]:
                dst = acct_dot_dir / name
                if dst.is_symlink():
                    dst.unlink()
                    print(f"  {_c(33, '✓')} Removed symlink: {prov['dot_dir']}/{name}")
    else:
        # Legacy account (no account.json) — fall back to SYMLINK_DIRS + SYMLINK_FILES
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

    # Catalog entries (shared CLI tool credentials) — always at account_home level
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
    """Find all sessions across all projects, return sorted by modification time.

    Cheap pass: stat + first-user-message extraction only. Full preview content
    is loaded on demand by ``load_session_preview`` when the user opens the
    preview pane.
    """
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

            try:
                st = f.stat()
            except OSError:
                continue

            session_id = f.stem
            mod_dt = datetime.fromtimestamp(st.st_mtime)
            size_mb = st.st_size / (1024 * 1024)

            topic, cwd = _scan_session_head(f)

            sessions.append(
                {
                    "id": session_id,
                    "project": project_name,
                    "cwd": cwd,
                    "modified": mod_dt,
                    "size_mb": size_mb,
                    "path": f,
                    "topic": topic,
                }
            )

    sessions.sort(key=lambda s: s["modified"], reverse=True)
    return sessions


def _extract_text(content):
    """Flatten a Claude Code message ``content`` field into plain text.

    ``content`` may be a string, or a list of blocks (text, tool_use,
    tool_result, image, ...). Only ``text`` blocks contribute. Returns "".
    """
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        out = []
        for block in content:
            if not isinstance(block, dict):
                continue
            btype = block.get("type")
            if btype == "text" and isinstance(block.get("text"), str):
                out.append(block["text"])
            elif btype == "tool_result":
                tc = block.get("content")
                if isinstance(tc, str):
                    out.append(tc)
                elif isinstance(tc, list):
                    for sub in tc:
                        if isinstance(sub, dict) and sub.get("type") == "text":
                            out.append(sub.get("text", ""))
        return "\n".join(out)
    return ""


_CODE_FENCE_RE = re.compile(r"```[^\n]*\n.*?```", re.DOTALL)
_INLINE_CODE_RE = re.compile(r"`([^`]*)`")
_MD_LINK_RE = re.compile(r"\[([^\]]+)\]\([^)]*\)")
_WS_RE = re.compile(r"\s+")


def _clean_topic(text: str) -> str:
    """Strip code fences, collapse whitespace, return single-line summary."""
    if not text:
        return ""
    text = _CODE_FENCE_RE.sub(" [code] ", text)
    text = _MD_LINK_RE.sub(r"\1", text)
    text = _INLINE_CODE_RE.sub(r"\1", text)
    text = _WS_RE.sub(" ", text).strip()
    return text


def _is_real_user_message(obj) -> bool:
    """Return True for genuine human user turns (not tool_result-only echoes)."""
    if obj.get("type") != "user":
        return False
    msg = obj.get("message")
    if not isinstance(msg, dict):
        return False
    content = msg.get("content")
    if isinstance(content, str):
        return bool(content.strip())
    if isinstance(content, list):
        # Skip turns that are only tool_result blocks (Claude Code injects these)
        for block in content:
            if isinstance(block, dict) and block.get("type") == "text":
                return bool(block.get("text", "").strip())
        return False
    return False


def _scan_session_head(jsonl_path, max_lines: int = 40) -> tuple:
    """Cheap scan: return (topic, cwd) from the first ``max_lines`` of a session."""
    topic = ""
    cwd = ""
    try:
        with open(jsonl_path, "r", encoding="utf-8", errors="replace") as f:
            for i, line in enumerate(f):
                if i >= max_lines and topic:
                    break
                line = line.strip()
                if not line:
                    continue
                try:
                    obj = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if not cwd and isinstance(obj.get("cwd"), str):
                    cwd = obj["cwd"]
                if not topic and _is_real_user_message(obj):
                    text = _extract_text(obj["message"].get("content"))
                    topic = _clean_topic(text)
    except OSError:
        pass
    return topic, cwd


def load_session_preview(jsonl_path, max_messages: int = 4, max_lines: int = 400) -> dict:
    """Load opening prompt + first few message turns for the preview pane.

    Reads at most ``max_lines`` lines and returns once ``max_messages`` real
    user/assistant turns have been collected. ``truncated`` is True if the
    session has more content than was returned.
    """
    messages = []
    cwd = ""
    total_lines = 0
    truncated = False
    try:
        with open(jsonl_path, "r", encoding="utf-8", errors="replace") as f:
            for line in f:
                total_lines += 1
                if total_lines > max_lines:
                    truncated = True
                    break
                line = line.strip()
                if not line:
                    continue
                try:
                    obj = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if not cwd and isinstance(obj.get("cwd"), str):
                    cwd = obj["cwd"]
                t = obj.get("type")
                msg = obj.get("message") if isinstance(obj.get("message"), dict) else None
                if t == "user" and _is_real_user_message(obj):
                    text = _extract_text(msg.get("content"))
                    if text.strip():
                        messages.append(("user", text.strip()))
                elif t == "assistant" and msg:
                    text = _extract_text(msg.get("content"))
                    if text.strip():
                        messages.append(("assistant", text.strip()))
                if len(messages) >= max_messages:
                    # Peek one more line to know if there's more content
                    if f.readline():
                        truncated = True
                    break
    except OSError as e:
        return {"messages": [], "cwd": "", "truncated": False, "error": str(e)}
    return {"messages": messages, "cwd": cwd, "truncated": truncated, "error": None}


def decode_project_path(encoded: str) -> str:
    """Decode Claude Code's project dir name back into a readable path.

    ``-Users-netz-Documents-git-altergo`` -> ``/home/user/Documents/git/altergo``.
    Best-effort: dashes inside path components are indistinguishable from
    separators in this encoding scheme, so we return the most likely form.
    """
    if not encoded:
        return ""
    s = encoded
    if s.startswith("-"):
        s = "/" + s[1:].replace("-", "/")
    else:
        s = s.replace("-", "/")
    return s


def format_project_name(encoded):
    """Short, readable project name (last path component)."""
    if not encoded:
        return ""
    decoded = decode_project_path(encoded)
    name = decoded.rstrip("/").rsplit("/", 1)[-1]
    return name or encoded


def relative_time(dt: datetime, now: datetime = None) -> str:
    """Return a compact relative-time string ('2h ago', 'yesterday', '3d ago')."""
    if now is None:
        now = datetime.now()
    delta = now - dt
    secs = int(delta.total_seconds())
    if secs < 0:
        return "just now"
    if secs < 60:
        return f"{secs}s ago"
    mins = secs // 60
    if mins < 60:
        return f"{mins}m ago"
    hrs = mins // 60
    if hrs < 24:
        return f"{hrs}h ago"
    days = hrs // 24
    if days == 1:
        return "yesterday"
    if days < 7:
        return f"{days}d ago"
    if days < 30:
        return f"{days // 7}w ago"
    if days < 365:
        return f"{days // 30}mo ago"
    return f"{days // 365}y ago"


# --- Interactive Menu ---


def interactive_picker(sessions):
    """Arrow-key driven session picker using curses."""
    if not sessions:
        print("No sessions found.")
        sys.exit(1)

    selected = curses.wrapper(_draw_picker, sessions)
    return selected


def _picker_attrs():
    """Initialize color pairs for the picker. Returns an attrs dict.

    Falls back to monochrome (A_BOLD/A_REVERSE/A_DIM) when colors aren't
    available so the picker degrades gracefully on dumb terminals.
    """
    has_color = False
    try:
        if curses.has_colors():
            curses.start_color()
            curses.use_default_colors()
            has_color = True
    except curses.error:
        has_color = False

    attrs = {}
    if has_color:
        # Palette comes from the active theme. Each theme pre-declares the
        # three accent ids it wants for 256-color terminals; we degrade to
        # the nearest ANSI-16 color on poor terminals so the picker stays
        # usable on tmux/ssh sessions with low color depth.
        theme = THEMES.get(get_current_theme(), THEMES[_DEFAULT_THEME])
        tc = theme["curses"]
        if curses.COLORS >= 256:
            accent = tc["accent"]
            project = tc["project"]
            amber = tc["amber"]
            gray = 244
            white = 231
        else:
            accent = curses.COLOR_CYAN
            project = curses.COLOR_BLUE
            amber = curses.COLOR_YELLOW
            gray = curses.COLOR_WHITE
            white = curses.COLOR_WHITE
        try:
            curses.init_pair(1, curses.COLOR_BLACK, accent)  # selected row
            curses.init_pair(2, accent, -1)  # header / accent / shine mid
            curses.init_pair(3, project, -1)  # project col / brand
            curses.init_pair(4, gray, -1)  # time col
            curses.init_pair(5, accent, -1)  # preview pane border
            curses.init_pair(6, white, -1)  # shine peak
            curses.init_pair(7, amber, -1)  # size warning / theme hint
        except curses.error:
            has_color = False

    if has_color:
        attrs["selected"] = curses.color_pair(1) | curses.A_BOLD
        attrs["header"] = curses.color_pair(2) | curses.A_BOLD | curses.A_UNDERLINE
        attrs["title"] = curses.color_pair(2) | curses.A_BOLD
        attrs["project"] = curses.color_pair(3)
        attrs["time"] = curses.color_pair(4) | curses.A_DIM
        attrs["topic"] = curses.A_NORMAL
        attrs["dim"] = curses.A_DIM
        attrs["accent"] = curses.color_pair(2)
        attrs["nav_base"] = curses.A_NORMAL
        attrs["brand"] = curses.color_pair(3) | curses.A_BOLD
        attrs["shine_peak"] = curses.color_pair(6) | curses.A_BOLD
        attrs["shine_mid"] = curses.color_pair(2) | curses.A_BOLD
        attrs["size_warn"] = curses.color_pair(7) | curses.A_DIM
    else:
        attrs["selected"] = curses.A_REVERSE | curses.A_BOLD
        attrs["header"] = curses.A_BOLD | curses.A_UNDERLINE
        attrs["title"] = curses.A_BOLD
        attrs["project"] = curses.A_BOLD
        attrs["time"] = curses.A_DIM
        attrs["topic"] = curses.A_NORMAL
        attrs["dim"] = curses.A_DIM
        attrs["accent"] = curses.A_BOLD
        attrs["nav_base"] = curses.A_NORMAL
        attrs["brand"] = curses.A_BOLD
        attrs["shine_peak"] = curses.A_BOLD | curses.A_REVERSE
        attrs["shine_mid"] = curses.A_BOLD
        attrs["size_warn"] = curses.A_DIM
    return attrs


def _compute_columns(max_x: int) -> dict:
    """Responsive column widths. Topic gets the leftover space."""
    proj_w = 18 if max_x >= 100 else (14 if max_x >= 80 else 10)
    time_w = 11  # "yesterday  " / "12h ago    "
    size_w = 7   # " 1.2MB " right-aligned
    gutter = 2   # leading "▸ "
    spacing = 2  # between cols
    used = gutter + proj_w + spacing + time_w + spacing + size_w + spacing
    topic_w = max(20, max_x - used - 1)
    topic_w = min(topic_w, max(40, max_x - used - 1))
    return {"gutter": gutter, "proj": proj_w, "time": time_w, "size": size_w, "topic": topic_w}


def _truncate(text: str, width: int) -> str:
    if width <= 0:
        return ""
    if len(text) <= width:
        return text
    if width == 1:
        return "…"
    return text[: width - 1] + "…"


def _safe_addnstr(stdscr, y, x, text, n, attr=0):
    """addnstr that swallows curses.error at the bottom-right cell."""
    try:
        stdscr.addnstr(y, x, text, n, attr)
    except curses.error:
        pass


def _safe_addch(stdscr, y, x, ch, attr=0):
    """Single-char writer that swallows curses.error."""
    try:
        stdscr.addstr(y, x, ch, attr)
    except curses.error:
        pass


def _draw_animated_nav(stdscr, row, text, max_width, phase, attrs):
    """Render the footer nav line with a BBS-style shine sweep + twinkling
    separators. The word 'pixelabs' is rendered in brand indigo (bold).

    phase increments every ~80ms; shine sweeps across width then pauses,
    separator dots twinkle on a staggered per-position cycle.
    """
    if max_width <= 0:
        return
    width = min(len(text), max_width)
    if width <= 0:
        return

    # Shine sweep position (extends past width to create a pause between sweeps)
    cycle_len = width + 24
    shine_pos = phase % cycle_len

    # Locate "pixelabs" substring for brand coloring
    lower = text.lower()
    pix_start = lower.find("pixelabs")
    pix_end = pix_start + len("pixelabs") if pix_start >= 0 else -1

    for i in range(width):
        ch = text[i]
        # 1. Base attribute: brand color for "pixelabs", otherwise normal
        if pix_start <= i < pix_end:
            attr = attrs["brand"]
        else:
            attr = attrs["nav_base"]

        # 2. Shine sweep overlay (wave of bright chars sliding right)
        dist = i - shine_pos
        if -1 <= dist <= 1:
            attr = attrs["shine_peak"]
        elif -3 <= dist <= 3:
            attr = attrs["shine_mid"]
        elif -5 <= dist <= 5:
            attr = attrs["shine_mid"] | curses.A_DIM

        # 3. Twinkle effect on separator dots (independent per-position phase)
        if ch == "·":
            twinkle = (phase * 2 + i * 7) % 48
            if twinkle < 2:
                attr = attrs["shine_peak"]
            elif twinkle < 5:
                attr = attrs["shine_mid"]

        _safe_addch(stdscr, row, i, ch, attr)


def _session_matches(s, query):
    """Return True if *query* (lowercase) matches any searchable field."""
    q = query.lower()
    for field in (format_project_name(s["project"]), s.get("topic") or "",
                  s.get("cwd") or "", s.get("id") or ""):
        if q in field.lower():
            return True
    return False


def _draw_picker(stdscr, sessions):
    curses.curs_set(0)
    attrs = _picker_attrs()
    stdscr.timeout(80)  # ~12fps animation tick — getch() returns -1 on timeout

    current = 0
    scroll_offset = 0
    preview_cache = {}  # session_id -> loaded preview dict
    phase = 0
    search_query = ""     # active filter text ("" = show all)
    search_mode = False   # True while typing in the / search bar
    filtered = sessions   # visible subset

    while True:
        stdscr.erase()
        max_y, max_x = stdscr.getmaxyx()
        cols = _compute_columns(max_x)

        # Title bar
        if search_query:
            title = f" altergo — pick a session  ·  {len(filtered)}/{len(sessions)} matching"
        else:
            title = f" altergo — pick a session  ·  {len(sessions)} total"
        _safe_addnstr(stdscr, 0, 0, title.ljust(max_x), max_x - 1, attrs["title"])

        # Column header row
        proj_h = "Project".ljust(cols["proj"])
        time_h = "When".ljust(cols["time"])
        size_h = "Size".rjust(cols["size"])
        topic_h = "Topic"
        col_header = f"  {proj_h}  {time_h}  {size_h}  {topic_h}"
        _safe_addnstr(stdscr, 2, 0, col_header.ljust(max_x), max_x - 1, attrs["header"])

        # Visible area: title(1) + blank(1) + col_header(2) + footer(2)
        visible_rows = max(1, max_y - 6)

        if current < scroll_offset:
            scroll_offset = current
        elif current >= scroll_offset + visible_rows:
            scroll_offset = current - visible_rows + 1

        for i in range(visible_rows):
            idx = scroll_offset + i
            if idx >= len(filtered):
                break
            s = filtered[idx]
            row = i + 3
            is_sel = idx == current

            project = _truncate(format_project_name(s["project"]), cols["proj"])
            when = _truncate(relative_time(s["modified"]), cols["time"])
            topic = s.get("topic") or ""
            topic_is_empty = not topic
            if topic_is_empty:
                topic = "(no prompt)"
            topic = _truncate(topic, cols["topic"])

            size_str = f"{s.get('size_mb', 0):.1f}MB".rjust(cols["size"])
            size_attr = attrs["size_warn"] if s.get("size_mb", 0) > 10 else attrs["time"]

            if is_sel:
                line = f"▸ {project.ljust(cols['proj'])}  {when.ljust(cols['time'])}  {size_str}  {topic}"
                _safe_addnstr(stdscr, row, 0, line.ljust(max_x), max_x - 1, attrs["selected"])
            else:
                # Render columns separately so each gets its own color
                _safe_addnstr(stdscr, row, 0, "  ", 2)
                _safe_addnstr(stdscr, row, 2, project.ljust(cols["proj"]), cols["proj"], attrs["project"])
                x = 2 + cols["proj"] + 2
                _safe_addnstr(stdscr, row, x, when.ljust(cols["time"]), cols["time"], attrs["time"])
                x += cols["time"] + 2
                _safe_addnstr(stdscr, row, x, size_str, cols["size"], size_attr)
                x += cols["size"] + 2
                topic_attr = attrs["dim"] if topic_is_empty else attrs["topic"]
                _safe_addnstr(stdscr, row, x, topic, max_x - x - 1, topic_attr)

        # Footer
        footer_row = max_y - 2
        if search_mode:
            # Search input bar
            prompt = f" /{search_query}"
            _safe_addnstr(stdscr, footer_row, 0, prompt.ljust(max_x), max_x - 1, attrs["topic"])
            curses.curs_set(1)
            try:
                stdscr.move(footer_row, min(len(prompt), max_x - 1))
            except curses.error:
                pass
        else:
            curses.curs_set(0)
            if search_query:
                foot = f" /{search_query}"
                _safe_addnstr(stdscr, footer_row, 0, _truncate(foot, max_x - 1), max_x - 1, attrs["topic"])
            elif 0 <= current < len(filtered):
                s = filtered[current]
                sid = s["id"]
                cwd = s.get("cwd") or decode_project_path(s["project"])
                foot = f" {sid}  ·  {cwd}"
                _safe_addnstr(stdscr, footer_row, 0, _truncate(foot, max_x - 1), max_x - 1, attrs["topic"])
        nav = " ↑↓/jk move  ·  / search  ·  g/G top/bot  ·  p/Tab preview  ·  Enter resume  ·  q quit  ·  pixelabs"
        _draw_animated_nav(stdscr, footer_row + 1, nav, max_x - 1, phase, attrs)

        stdscr.refresh()
        key = stdscr.getch()

        # Animation tick: getch timed out (no key pressed) — advance phase and redraw
        if key == -1:
            phase += 1
            continue

        # -- Search mode input handling --
        if search_mode:
            if key == 27:  # Esc — cancel search, restore full list
                search_mode = False
                search_query = ""
                filtered = sessions
                current = 0
                scroll_offset = 0
            elif key in (curses.KEY_ENTER, 10, 13):  # Enter — accept filter
                search_mode = False
            elif key in (curses.KEY_BACKSPACE, 127, 8):
                search_query = search_query[:-1]
                if search_query:
                    filtered = [s for s in sessions if _session_matches(s, search_query)]
                else:
                    filtered = sessions
                current = min(current, max(len(filtered) - 1, 0))
                scroll_offset = 0
            elif 32 <= key <= 126:  # printable character
                search_query += chr(key)
                filtered = [s for s in sessions if _session_matches(s, search_query)]
                current = min(current, max(len(filtered) - 1, 0))
                scroll_offset = 0
            continue

        # -- Normal mode input handling --
        if key in (curses.KEY_UP, ord("k")):
            current = max(0, current - 1)
        elif key in (curses.KEY_DOWN, ord("j")):
            current = min(len(filtered) - 1, current + 1)
        elif key == curses.KEY_PPAGE:
            current = max(0, current - visible_rows)
        elif key == curses.KEY_NPAGE:
            current = min(len(filtered) - 1, current + visible_rows)
        elif key == ord("g"):
            current = 0
        elif key == ord("G"):
            current = max(len(filtered) - 1, 0)
        elif key in (curses.KEY_ENTER, 10, 13):
            if filtered:
                return filtered[current]
        elif key in (ord("p"), ord(" "), 9):  # p, space, Tab → preview
            if 0 <= current < len(filtered):
                s = filtered[current]
                if s["id"] not in preview_cache:
                    preview_cache[s["id"]] = load_session_preview(s["path"])
                action = _draw_preview(stdscr, attrs, s, preview_cache[s["id"]])
                if action == "resume":
                    return s
                # else: just return to picker
        elif key == ord("/"):
            search_mode = True
            search_query = ""
        elif key in (ord("q"), 27):
            return None
        elif key == curses.KEY_RESIZE:
            continue


def _wrap_text(text: str, width: int):
    """Simple word-wrap that also breaks on existing newlines."""
    if width <= 0:
        return [text]
    out = []
    for raw_line in text.splitlines() or [""]:
        if not raw_line:
            out.append("")
            continue
        line = ""
        for word in raw_line.split(" "):
            if not line:
                candidate = word
            else:
                candidate = line + " " + word
            if len(candidate) <= width:
                line = candidate
            else:
                if line:
                    out.append(line)
                # Hard-break very long tokens
                while len(word) > width:
                    out.append(word[:width])
                    word = word[width:]
                line = word
        out.append(line)
    return out


def _draw_preview(stdscr, attrs, session, preview):
    """Modal preview pane. Returns 'resume' if user hit Enter, else 'back'."""
    scroll = 0
    while True:
        stdscr.erase()
        max_y, max_x = stdscr.getmaxyx()

        title = f" Preview — {format_project_name(session['project'])} "
        _safe_addnstr(stdscr, 0, 0, title.ljust(max_x), max_x - 1, attrs["title"])

        # Metadata block
        meta_lines = [
            f"Session : {session['id']}",
            f"Project : {session.get('cwd') or decode_project_path(session['project'])}",
            f"Modified: {session['modified'].strftime('%Y-%m-%d %H:%M:%S')}  ({relative_time(session['modified'])})",
            f"Size    : {session['size_mb']:.2f} MB",
        ]
        if preview.get("error"):
            meta_lines.append(f"Error   : {preview['error']}")

        # Build the body lines (metadata + messages)
        body = []
        for ml in meta_lines:
            body.append(("meta", ml))
        body.append(("blank", ""))
        body.append(("sep", "─" * max(10, max_x - 4)))
        body.append(("blank", ""))

        msgs = preview.get("messages") or []
        if not msgs:
            body.append(("dim", "(no readable messages found in this session)"))
        else:
            wrap_w = max(20, max_x - 4)
            for role, text in msgs:
                label = "You" if role == "user" else "Assistant"
                role_attr = "accent" if role == "user" else "project"
                body.append((role_attr, f"▸ {label}"))
                # Cap each message preview to ~12 wrapped lines so the pane stays scrollable
                wrapped = _wrap_text(text, wrap_w)
                for line in wrapped[:12]:
                    body.append(("text", "  " + line))
                if len(wrapped) > 12:
                    body.append(("dim", f"  … ({len(wrapped) - 12} more lines)"))
                body.append(("blank", ""))
            if preview.get("truncated"):
                body.append(("dim", "… session continues beyond preview"))

        # Scrollable region: rows 2..max_y-3
        view_h = max(1, max_y - 4)
        max_scroll = max(0, len(body) - view_h)
        scroll = max(0, min(scroll, max_scroll))

        for i in range(view_h):
            bi = scroll + i
            if bi >= len(body):
                break
            kind, text = body[bi]
            row = 2 + i
            if kind == "meta":
                _safe_addnstr(stdscr, row, 2, _truncate(text, max_x - 3), max_x - 3, attrs["dim"])
            elif kind == "sep":
                _safe_addnstr(stdscr, row, 2, _truncate(text, max_x - 3), max_x - 3, attrs["dim"])
            elif kind == "blank":
                pass
            elif kind == "dim":
                _safe_addnstr(stdscr, row, 2, _truncate(text, max_x - 3), max_x - 3, attrs["dim"])
            elif kind in ("accent", "project"):
                _safe_addnstr(stdscr, row, 2, _truncate(text, max_x - 3), max_x - 3, attrs[kind])
            else:
                _safe_addnstr(stdscr, row, 2, _truncate(text, max_x - 3), max_x - 3, attrs["topic"])

        nav = " ↑↓/jk scroll · PgUp/PgDn page · Enter resume · q/Esc back"
        _safe_addnstr(stdscr, max_y - 1, 0, _truncate(nav, max_x - 1), max_x - 1, attrs["dim"])

        stdscr.refresh()
        key = stdscr.getch()
        if key in (curses.KEY_UP, ord("k")):
            scroll -= 1
        elif key in (curses.KEY_DOWN, ord("j")):
            scroll += 1
        elif key == curses.KEY_PPAGE:
            scroll -= view_h
        elif key == curses.KEY_NPAGE:
            scroll += view_h
        elif key in (curses.KEY_ENTER, 10, 13):
            return "resume"
        elif key in (ord("q"), 27, ord("p"), 9, ord(" ")):
            return "back"
        elif key == curses.KEY_RESIZE:
            continue


# --- Full-Text Session Search ---


def _parse_search_query(raw: str):
    """Parse a search query, supporting quoted exact phrases and bare terms.

    Returns a list of lowercase terms/phrases to match. All must match (AND).
    Example: 'fix "please go ahead" bug' -> ['fix', 'please go ahead', 'bug']
    """
    terms = []
    i = 0
    while i < len(raw):
        if raw[i] in ('"', "'"):
            quote = raw[i]
            j = raw.find(quote, i + 1)
            if j == -1:
                j = len(raw)
            phrase = raw[i + 1 : j].strip()
            if phrase:
                terms.append(phrase.lower())
            i = j + 1
        elif raw[i] == " ":
            i += 1
        else:
            j = i
            while j < len(raw) and raw[j] != " ":
                j += 1
            terms.append(raw[i:j].lower())
            i = j
    return terms


def _search_sessions(sessions, terms, project_filter=None, on_progress=None):
    """Search full conversation text in session JSONL files.

    Returns list of dicts: {session, matches: [{line_text, line_no, role}], ...}
    sorted newest-to-oldest. ``terms`` is a list of lowercase strings (AND logic).
    ``project_filter`` is an optional lowercase project name substring.
    ``on_progress(done, total)`` is called after each file.
    """
    results = []
    targets = sessions
    if project_filter:
        pf = project_filter.lower()
        targets = [s for s in sessions
                   if pf in format_project_name(s["project"]).lower()
                   or pf in decode_project_path(s["project"]).lower()]

    for idx, s in enumerate(targets):
        if on_progress:
            on_progress(idx, len(targets))
        matches = []
        try:
            with open(s["path"], "r", encoding="utf-8", errors="replace") as f:
                for line_no, raw_line in enumerate(f, 1):
                    raw_line = raw_line.strip()
                    if not raw_line:
                        continue
                    try:
                        obj = json.loads(raw_line)
                    except json.JSONDecodeError:
                        continue
                    msg = obj.get("message") if isinstance(obj.get("message"), dict) else None
                    if not msg:
                        continue
                    text = _extract_text(msg.get("content"))
                    if not text:
                        continue
                    text_lower = text.lower()
                    if all(t in text_lower for t in terms):
                        role = "you" if obj.get("type") == "user" else "claude"
                        # Build a snippet around the first term occurrence
                        first_pos = text_lower.find(terms[0])
                        snippet_start = max(0, first_pos - 60)
                        snippet_end = min(len(text), first_pos + len(terms[0]) + 120)
                        snippet = text[snippet_start:snippet_end].replace("\n", " ")
                        if snippet_start > 0:
                            snippet = "…" + snippet
                        if snippet_end < len(text):
                            snippet = snippet + "…"
                        matches.append({
                            "line_no": line_no,
                            "role": role,
                            "snippet": snippet,
                            "terms": terms,
                        })
        except OSError:
            continue
        if matches:
            results.append({"session": s, "matches": matches})

    # Already sorted newest-to-oldest since sessions come sorted by modified desc
    if on_progress:
        on_progress(len(targets), len(targets))
    return results


def interactive_search(sessions):
    """Full-text search across all conversation sessions."""
    if not sessions:
        print("No sessions found.")
        return None
    return curses.wrapper(_draw_search, sessions)


def _draw_search(stdscr, sessions):
    curses.curs_set(1)
    attrs = _picker_attrs()
    stdscr.timeout(80)

    # Phases: "project_filter" → "query_input" → "scanning" → "results"
    phase_anim = 0
    ui_phase = "project_filter"
    project_input = ""
    query_input = ""
    results = []
    result_cursor = 0
    result_scroll = 0
    scan_done = 0
    scan_total = 0

    # Collect unique project names for hint
    project_names = sorted(set(format_project_name(s["project"]) for s in sessions))

    while True:
        stdscr.erase()
        max_y, max_x = stdscr.getmaxyx()

        # Title bar
        title = " altergo — search conversations"
        _safe_addnstr(stdscr, 0, 0, title.ljust(max_x), max_x - 1, attrs["title"])

        if ui_phase == "project_filter":
            # Project filter input screen
            _safe_addnstr(stdscr, 2, 2, "Filter by project (optional — Enter to skip, search all):",
                          max_x - 3, attrs["accent"])

            # Show input
            prompt = f"  project: {project_input}"
            _safe_addnstr(stdscr, 4, 0, prompt, max_x - 1, attrs["topic"])
            curses.curs_set(1)
            try:
                stdscr.move(4, min(len(prompt), max_x - 1))
            except curses.error:
                pass

            # Show available projects as hints
            hint_row = 6
            _safe_addnstr(stdscr, hint_row, 2, "Available projects:", max_x - 3, attrs["dim"])
            hint_row += 1
            visible_projects = project_names
            if project_input:
                pi = project_input.lower()
                visible_projects = [p for p in project_names if pi in p.lower()]
            for i, pname in enumerate(visible_projects):
                if hint_row + i >= max_y - 2:
                    break
                _safe_addnstr(stdscr, hint_row + i, 4, pname, max_x - 5, attrs["project"])

            # Nav
            nav = " Enter accept  ·  Esc cancel  ·  type to filter  ·  pixelabs"
            _draw_animated_nav(stdscr, max_y - 1, nav, max_x - 1, phase_anim, attrs)

        elif ui_phase == "query_input":
            # Search query input
            proj_label = project_input if project_input else "all projects"
            _safe_addnstr(stdscr, 2, 2, f"Searching in: {proj_label}",
                          max_x - 3, attrs["project"])
            _safe_addnstr(stdscr, 3, 2, "Case-insensitive. Use \"quotes\" for exact phrases.",
                          max_x - 3, attrs["dim"])

            prompt = f"  search: {query_input}"
            if not query_input:
                # Placeholder
                _safe_addnstr(stdscr, 5, 0, "  search: ", max_x - 1, attrs["topic"])
                _safe_addnstr(stdscr, 5, 10, "type to search conversations…", max_x - 11, attrs["dim"])
            else:
                _safe_addnstr(stdscr, 5, 0, prompt, max_x - 1, attrs["topic"])
            curses.curs_set(1)
            try:
                cursor_x = 10 + len(query_input) if query_input else 10
                stdscr.move(5, min(cursor_x, max_x - 1))
            except curses.error:
                pass

            nav = " Enter search  ·  Esc back  ·  pixelabs"
            _draw_animated_nav(stdscr, max_y - 1, nav, max_x - 1, phase_anim, attrs)

        elif ui_phase == "scanning":
            curses.curs_set(0)
            proj_label = project_input if project_input else "all projects"
            _safe_addnstr(stdscr, 2, 2, f"Searching in: {proj_label}",
                          max_x - 3, attrs["project"])

            # Animated scanning bar
            bar_w = max(10, max_x - 8)
            if scan_total > 0:
                pct = scan_done / scan_total
                filled = int(bar_w * pct)
            else:
                filled = 0
            bar = "█" * filled + "░" * (bar_w - filled)
            _safe_addnstr(stdscr, 4, 4, bar, max_x - 5, attrs["accent"])

            # Scanning animation frames
            spinner_frames = ["⠋", "⠙", "⠹", "⠸", "⠼", "⠴", "⠦", "⠧", "⠇", "⠏"]
            spinner = spinner_frames[phase_anim % len(spinner_frames)]
            status = f"  {spinner} Scanning session {scan_done}/{scan_total}…"
            _safe_addnstr(stdscr, 6, 2, status, max_x - 3, attrs["topic"])

            query_echo = f'  query: "{query_input}"'
            _safe_addnstr(stdscr, 8, 2, query_echo, max_x - 3, attrs["dim"])

        elif ui_phase == "results":
            curses.curs_set(0)
            total_matches = sum(len(r["matches"]) for r in results)
            proj_label = project_input if project_input else "all projects"
            summary = f"  {total_matches} match{'es' if total_matches != 1 else ''} in {len(results)} session{'s' if len(results) != 1 else ''}  ·  {proj_label}"
            _safe_addnstr(stdscr, 2, 2, summary, max_x - 3, attrs["accent"])

            query_echo = f'  query: "{query_input}"'
            _safe_addnstr(stdscr, 3, 2, query_echo, max_x - 3, attrs["dim"])

            if not results:
                _safe_addnstr(stdscr, 5, 4, "No matches found.", max_x - 5, attrs["dim"])
                _safe_addnstr(stdscr, 6, 4, "Try different terms or broaden the project filter.",
                              max_x - 5, attrs["dim"])
            else:
                # Build flat display lines from results
                display_lines = []
                for ri, r in enumerate(results):
                    s = r["session"]
                    proj = format_project_name(s["project"])
                    when = relative_time(s["modified"])
                    match_count = len(r["matches"])
                    header = f"  {proj}  ·  {when}  ·  {match_count} match{'es' if match_count != 1 else ''}"
                    display_lines.append(("result_header", header, ri))
                    # Show up to 3 snippet previews per session
                    for mi, m in enumerate(r["matches"][:3]):
                        role_icon = "▸" if m["role"] == "you" else "◂"
                        snip = _truncate(m["snippet"], max(20, max_x - 12))
                        display_lines.append(("snippet", f"    {role_icon} {snip}", ri))
                    if match_count > 3:
                        display_lines.append(("dim_line", f"    … and {match_count - 3} more matches", ri))
                    display_lines.append(("blank", "", ri))

                # Scrollable results view
                view_start = 5
                view_h = max(1, max_y - view_start - 2)

                # Find the line range for the current result cursor
                # Each result group starts at a header line
                header_positions = [i for i, (kind, _, _) in enumerate(display_lines) if kind == "result_header"]
                if result_cursor >= len(header_positions):
                    result_cursor = max(0, len(header_positions) - 1)

                # Auto-scroll to keep cursor visible
                if header_positions:
                    cursor_line = header_positions[result_cursor]
                    if cursor_line < result_scroll:
                        result_scroll = cursor_line
                    elif cursor_line >= result_scroll + view_h:
                        result_scroll = cursor_line - view_h + 1

                result_scroll = max(0, min(result_scroll, max(0, len(display_lines) - view_h)))

                for i in range(view_h):
                    li = result_scroll + i
                    if li >= len(display_lines):
                        break
                    kind, text, ri = display_lines[li]
                    row = view_start + i
                    is_selected = (kind == "result_header" and ri == result_cursor)
                    if kind == "result_header":
                        attr = attrs["selected"] if is_selected else attrs["project"]
                        _safe_addnstr(stdscr, row, 0, text.ljust(max_x), max_x - 1, attr)
                    elif kind == "snippet":
                        # Highlight matching terms in the snippet
                        if ri == result_cursor:
                            _safe_addnstr(stdscr, row, 0, text, max_x - 1, attrs["topic"])
                        else:
                            _safe_addnstr(stdscr, row, 0, text, max_x - 1, attrs["dim"])
                    elif kind == "dim_line":
                        _safe_addnstr(stdscr, row, 0, text, max_x - 1, attrs["dim"])

            # Footer nav
            nav = " ↑↓/jk move  ·  Enter resume  ·  / new search  ·  Esc back  ·  q quit  ·  pixelabs"
            _draw_animated_nav(stdscr, max_y - 1, nav, max_x - 1, phase_anim, attrs)

        stdscr.refresh()
        key = stdscr.getch()

        if key == -1:
            phase_anim += 1
            # Drive scanning in the background during animation ticks
            if ui_phase == "scanning":
                if not hasattr(_draw_search, "_scan_gen"):
                    pass  # generator set up below on Enter
            continue

        # -- Input handling per phase --

        if ui_phase == "project_filter":
            if key == 27:  # Esc
                return None
            elif key in (curses.KEY_ENTER, 10, 13):
                ui_phase = "query_input"
            elif key in (curses.KEY_BACKSPACE, 127, 8):
                project_input = project_input[:-1]
            elif 32 <= key <= 126:
                project_input += chr(key)

        elif ui_phase == "query_input":
            if key == 27:  # Esc → back to project filter
                ui_phase = "project_filter"
            elif key in (curses.KEY_ENTER, 10, 13):
                if query_input.strip():
                    terms = _parse_search_query(query_input)
                    if terms:
                        ui_phase = "scanning"
                        # Run the search synchronously — update progress via the draw loop
                        pf = project_input if project_input.strip() else None
                        scan_total = len(sessions)
                        if pf:
                            pfl = pf.lower()
                            scan_total = sum(1 for s in sessions
                                             if pfl in format_project_name(s["project"]).lower()
                                             or pfl in decode_project_path(s["project"]).lower())
                        scan_done = 0

                        def _progress(done, total):
                            nonlocal scan_done, scan_total
                            scan_done = done
                            scan_total = max(total, 1)

                        results = _search_sessions(sessions, terms,
                                                   project_filter=pf,
                                                   on_progress=_progress)
                        result_cursor = 0
                        result_scroll = 0
                        ui_phase = "results"
            elif key in (curses.KEY_BACKSPACE, 127, 8):
                query_input = query_input[:-1]
            elif 32 <= key <= 126:
                query_input += chr(key)

        elif ui_phase == "results":
            if key in (curses.KEY_UP, ord("k")):
                result_cursor = max(0, result_cursor - 1)
            elif key in (curses.KEY_DOWN, ord("j")):
                result_cursor = min(len(results) - 1, result_cursor + 1)
            elif key == curses.KEY_PPAGE:
                result_cursor = max(0, result_cursor - 5)
            elif key == curses.KEY_NPAGE:
                result_cursor = min(len(results) - 1, result_cursor + 5)
            elif key == ord("g"):
                result_cursor = 0
            elif key == ord("G"):
                result_cursor = max(0, len(results) - 1)
            elif key in (curses.KEY_ENTER, 10, 13):
                if results and 0 <= result_cursor < len(results):
                    return results[result_cursor]["session"]
            elif key == ord("/"):
                # New search — reset
                query_input = ""
                results = []
                result_cursor = 0
                result_scroll = 0
                ui_phase = "query_input"
            elif key == 27:  # Esc → back to query input
                ui_phase = "query_input"
            elif key == ord("q"):
                return None
            elif key == curses.KEY_RESIZE:
                continue


# --- Settings TUI ---

# Page definitions — index matches page number (0-based)
_SETTINGS_PAGES = [
    {
        "title": "Appearance",
        "subtitle": "Theme and visual preferences",
    },
    {
        "title": "Behavior",
        "subtitle": "Launch and session message settings",
    },
    {
        "title": "Credentials",
        "subtitle": "Share CLI credentials between accounts",
    },
]

# Color swatch characters for theme preview (3 blocks per theme stop)
_SWATCH_BLOCK = "\u2588"  # █


def _hex_to_curses_256(hex_color: str) -> int:
    """Approximate a hex color to the nearest xterm-256 color index.

    Uses the 6x6x6 color cube (indices 16–231) for best coverage. This is
    a simple nearest-neighbor approximation — good enough for swatches.
    """
    r = int(hex_color[1:3], 16)
    g = int(hex_color[3:5], 16)
    b = int(hex_color[5:7], 16)
    # Map each channel to the nearest 6-step cube value (0,95,135,175,215,255)
    _steps = [0, 95, 135, 175, 215, 255]

    def nearest(v):
        return min(range(6), key=lambda i: abs(_steps[i] - v))

    ri, gi, bi = nearest(r), nearest(g), nearest(b)
    return 16 + 36 * ri + 6 * gi + bi


def _draw_settings(stdscr):
    """Multi-page settings TUI. Returns dict of all changes on save, None on cancel."""
    curses.curs_set(0)
    attrs = _picker_attrs()

    # Snapshot original theme so we can restore on cancel
    original_theme = get_current_theme()

    # ── Working state for all three pages ────────────────────────────────────

    # Page 0: Appearance
    theme_names = list(THEMES.keys())
    current_theme_idx = theme_names.index(get_current_theme()) if get_current_theme() in theme_names else 0
    launch_anim = _load_bool_setting("launch_animation")
    _rts = load_random_theme_settings()
    random_theme_on   = _rts["random_theme_enabled"]
    random_theme_freq = _rts["random_theme_frequency"]   # 1–5

    # Page 1: Behavior
    update_check = load_update_check_enabled()
    show_greeting = _load_bool_setting("show_greeting")
    show_goodbye = _load_bool_setting("show_goodbye")

    # Page 2: Credentials
    cred_overrides = dict(load_settings())
    cred_defaults = {e["id"]: e["default_on"] for e in CATALOG}

    # Build credential rows (headers + entries)
    cred_rows = []
    seen_cats: list = []
    for entry in CATALOG:
        cat = entry["category"]
        if cat not in seen_cats:
            seen_cats.append(cat)
            cred_rows.append({"type": "header", "text": cat})
        cred_rows.append({"type": "entry", "entry": entry})
    cred_selectable = [i for i, r in enumerate(cred_rows) if r["type"] == "entry"]

    # ── Navigation state ──────────────────────────────────────────────────────
    current_page = 0
    n_pages = len(_SETTINGS_PAGES)

    # Per-page cursor positions
    # Page 0: rows = [theme_0..theme_N-1, launch_anim, random_toggle, freq_slider] → cursor 0..N+2
    page0_cursor = current_theme_idx
    page0_n = len(theme_names) + 3   # themes + launch_anim + random toggle + freq slider

    # Page 1: rows = [update_check, show_greeting, show_goodbye]
    page1_cursor = 0
    page1_n = 3

    # Page 2: credential entries (selectable positions in cred_selectable)
    page2_cursor = 0
    page2_scroll = 0

    # ── Swatch color pairs — pairs 20+ reserved for swatches ─────────────────
    # We allocate one pair per theme stop (up to 6 stops × 6 themes = 36 pairs)
    # starting at pair index 20. If terminal lacks 256 colors we skip swatches.
    swatch_pairs: dict = {}  # (theme_id, stop_idx) → curses pair number
    _swatch_pair_base = 20
    _pair_counter = _swatch_pair_base
    if curses.COLORS >= 256:
        for tid, tdata in THEMES.items():
            for si, stop in enumerate(tdata["banner"]):
                try:
                    fg = _hex_to_curses_256(stop)
                    curses.init_pair(_pair_counter, fg, -1)
                    swatch_pairs[(tid, si)] = _pair_counter
                    _pair_counter += 1
                except curses.error:
                    pass

    # ── Helper: draw one tab bar line ─────────────────────────────────────────
    def _draw_tab_bar(max_x):
        x = 0
        for pi, page in enumerate(_SETTINGS_PAGES):
            tab_text = f"  {page['title']}  "
            if pi == current_page:
                _safe_addnstr(stdscr, 0, x, tab_text[:max_x - x], max_x - x,
                              attrs["title"] | curses.A_REVERSE | curses.A_BOLD)
            else:
                _safe_addnstr(stdscr, 0, x, tab_text[:max_x - x], max_x - x,
                              attrs["dim"])
            x += len(tab_text)
            if pi < n_pages - 1 and x < max_x - 1:
                _safe_addnstr(stdscr, 0, x, "\u2502", 1, attrs["dim"])  # │
                x += 1

    # ── Helper: draw page 0 (Appearance) ─────────────────────────────────────
    def _draw_page0(max_y, max_x, attrs_local):
        content_start = 3
        row = content_start

        # Section header: Theme
        section = "Theme " + "\u2500" * max(0, 34)  # ─
        _safe_addnstr(stdscr, row, 2, section[:max_x - 3], max_x - 3,
                      attrs_local["accent"] | curses.A_BOLD)
        row += 1

        for ti, tid in enumerate(theme_names):
            if row >= max_y - 3:
                break
            tdata = THEMES[tid]
            is_focused = (ti == page0_cursor)
            is_selected = (ti == current_theme_idx)

            # Marker glyph
            if is_selected:
                marker = "\u25c6"  # ◆
                marker_attr = attrs_local["accent"] | curses.A_BOLD
            else:
                marker = "\u00b7"  # ·
                marker_attr = attrs_local["dim"]

            prefix = "\u25b8 " if is_focused else "  "  # ▸
            prefix_attr = attrs_local["accent"] | curses.A_BOLD if is_focused else curses.A_NORMAL

            _safe_addnstr(stdscr, row, 0, prefix, 2, prefix_attr)
            _safe_addnstr(stdscr, row, 2, marker, 1, marker_attr)
            _safe_addnstr(stdscr, row, 4, " ", 1, curses.A_NORMAL)

            name_str = tdata["display_name"].ljust(12)
            name_attr = attrs_local["accent"] | curses.A_BOLD if is_selected else curses.A_NORMAL
            _safe_addnstr(stdscr, row, 5, name_str[:12], 12, name_attr)

            # Color swatch: draw up to 3 stops of the banner gradient
            sx = 18
            stops = tdata["banner"]
            n_swatches = min(3, len(stops))
            for si in range(n_swatches):
                pair_key = (tid, si)
                if pair_key in swatch_pairs and sx < max_x - 2:
                    _safe_addnstr(stdscr, row, sx, _SWATCH_BLOCK * 2, 2,
                                  curses.color_pair(swatch_pairs[pair_key]))
                    sx += 2

            # Description
            desc = "  " + tdata["description"]
            if sx < max_x - 4:
                _safe_addnstr(stdscr, row, sx, desc[:max_x - sx - 1], max_x - sx - 1,
                              attrs_local["dim"])

            row += 1

        row += 1  # blank line before next section

        # Section header: Launch
        if row < max_y - 3:
            section2 = "Launch " + "\u2500" * max(0, 33)
            _safe_addnstr(stdscr, row, 2, section2[:max_x - 3], max_x - 3,
                          attrs_local["accent"] | curses.A_BOLD)
            row += 1

        anim_row_idx = len(theme_names)
        if row < max_y - 3:
            is_focused = (page0_cursor == anim_row_idx)
            prefix = "\u25b8 " if is_focused else "  "
            prefix_attr = attrs_local["accent"] | curses.A_BOLD if is_focused else curses.A_NORMAL
            _safe_addnstr(stdscr, row, 0, prefix, 2, prefix_attr)

            if launch_anim:
                dot = "\u25c9"   # ◉
                dot_attr = attrs_local["accent"] | curses.A_BOLD
            else:
                dot = "\u25cb"   # ○
                dot_attr = attrs_local["dim"]
            _safe_addnstr(stdscr, row, 2, dot, 1, dot_attr)
            label = "  Launch animation    "
            _safe_addnstr(stdscr, row, 3, label[:max_x - 4], max_x - 4, curses.A_NORMAL)
            hint = "Star spinner while provider warms up"
            lx = 3 + len(label)
            if lx < max_x - 4:
                _safe_addnstr(stdscr, row, lx, hint[:max_x - lx - 1], max_x - lx - 1, attrs_local["dim"])
            row += 1

        row += 1  # blank line before Randomize section

        # Section header: Randomize
        if row < max_y - 3:
            section3 = "Randomize " + "\u2500" * max(0, 30)
            _safe_addnstr(stdscr, row, 2, section3[:max_x - 3], max_x - 3,
                          attrs_local["accent"] | curses.A_BOLD)
            row += 1

        # ── Random theme toggle ───────────────────────────────────────────────
        rand_toggle_idx = len(theme_names) + 1
        if row < max_y - 3:
            is_focused = (page0_cursor == rand_toggle_idx)
            prefix = "\u25b8 " if is_focused else "  "
            prefix_attr = attrs_local["accent"] | curses.A_BOLD if is_focused else curses.A_NORMAL
            _safe_addnstr(stdscr, row, 0, prefix, 2, prefix_attr)

            if random_theme_on:
                dot = "\u25c9"   # ◉
                dot_attr = attrs_local["accent"] | curses.A_BOLD
            else:
                dot = "\u25cb"   # ○
                dot_attr = attrs_local["dim"]
            _safe_addnstr(stdscr, row, 2, dot, 1, dot_attr)
            label2 = "  Random theme       "
            _safe_addnstr(stdscr, row, 3, label2[:max_x - 4], max_x - 4, curses.A_NORMAL)
            hint2 = "Pick a new theme automatically every few sessions"
            lx2 = 3 + len(label2)
            if lx2 < max_x - 4:
                _safe_addnstr(stdscr, row, lx2, hint2[:max_x - lx2 - 1], max_x - lx2 - 1,
                              attrs_local["dim"])
            row += 1

        # ── Frequency slider ─────────────────────────────────────────────────
        freq_slider_idx = len(theme_names) + 2
        if row < max_y - 3:
            is_focused = (page0_cursor == freq_slider_idx)
            # 20-char track: █ filled, ◆ thumb, ░ empty
            TRACK_LEN = 20
            thumb_pos = int((random_theme_freq - 1) / 4 * (TRACK_LEN - 1))
            if random_theme_on:
                track = ""
                for i in range(TRACK_LEN):
                    if i < thumb_pos:
                        track += "\u2588"   # █
                    elif i == thumb_pos:
                        track += "\u25c6"   # ◆
                    else:
                        track += "\u2591"   # ░
                slider_attr = (attrs_local["accent"] | curses.A_BOLD) if is_focused else curses.A_NORMAL
                left_label  = "often "
                right_label = " rarely"
                label_attr  = attrs_local["dim"]
                prefix_sl   = "\u25b8 " if is_focused else "  "
                prefix_sl_attr = (attrs_local["accent"] | curses.A_BOLD) if is_focused else curses.A_NORMAL
            else:
                track       = "\u2592" * (TRACK_LEN - 1) + "\u00b7"   # ▒▒▒▒▒·
                slider_attr = attrs_local["dim"]
                left_label  = "----- "
                right_label = " -----"
                label_attr  = attrs_local["dim"]
                prefix_sl   = "  "
                prefix_sl_attr = attrs_local["dim"]

            cx = 0
            _safe_addnstr(stdscr, row, cx, prefix_sl, 2, prefix_sl_attr)
            cx = 2
            _safe_addnstr(stdscr, row, cx, left_label, len(left_label), label_attr)
            cx += len(left_label)
            _safe_addnstr(stdscr, row, cx, "[", 1, attrs_local["dim"])
            cx += 1
            _safe_addnstr(stdscr, row, cx, track, TRACK_LEN, slider_attr)
            cx += TRACK_LEN
            _safe_addnstr(stdscr, row, cx, "]", 1, attrs_local["dim"])
            cx += 1
            _safe_addnstr(stdscr, row, cx, right_label, len(right_label), label_attr)
            row += 1

        # Explanation lines (shown when random theme is on)
        if random_theme_on and row < max_y - 4:
            _freq_descriptions = {
                1: ("Changes nearly every session",    "Expect a new look very frequently"),
                2: ("Changes every few sessions",      "Plenty of variety"),
                3: ("Changes occasionally",            "Balanced \u2014 noticeable but not constant"),
                4: ("Changes infrequently",            "Mostly consistent, occasional surprise"),
                5: ("Changes rarely",                  "Stable look with rare surprises"),
            }
            line1, line2 = _freq_descriptions.get(random_theme_freq, _freq_descriptions[3])
            _safe_addnstr(stdscr, row, 4, ("\u25c6 " + line1)[:max_x - 5], max_x - 5,
                          attrs_local["dim"])
            row += 1
            if row < max_y - 3:
                _safe_addnstr(stdscr, row, 4, ("\u00b7 " + line2)[:max_x - 5], max_x - 5,
                              attrs_local["dim"])
        elif not random_theme_on and row < max_y - 3:
            _safe_addnstr(stdscr, row, 4,
                          "\u00b7 Enable \u201cRandom theme\u201d to configure frequency"[:max_x - 5],
                          max_x - 5, attrs_local["dim"])

    # ── Helper: draw page 1 (Behavior) ───────────────────────────────────────
    def _draw_page1(max_y, max_x):
        content_start = 3
        row = content_start

        section = "Launch behavior " + "\u2500" * max(0, 24)
        _safe_addnstr(stdscr, row, 2, section[:max_x - 3], max_x - 3,
                      attrs["accent"] | curses.A_BOLD)
        row += 1

        toggles = [
            ("update_check",  update_check,  "Update check",      "Check PyPI for new altergo versions"),
            ("show_greeting", show_greeting, "Greeting messages", "Time-of-day greeting on launch"),
            ("show_goodbye",  show_goodbye,  "Goodbye messages",  "Witty message after each session"),
        ]

        for ti, (key, val, label, hint) in enumerate(toggles):
            if row >= max_y - 3:
                break
            is_focused = (ti == page1_cursor)
            prefix = "\u25b8 " if is_focused else "  "
            prefix_attr = attrs["accent"] | curses.A_BOLD if is_focused else curses.A_NORMAL
            _safe_addnstr(stdscr, row, 0, prefix, 2, prefix_attr)

            if val:
                dot = "\u25c9"   # ◉
                dot_attr = attrs["accent"] | curses.A_BOLD
            else:
                dot = "\u25cb"   # ○
                dot_attr = attrs["dim"]
            _safe_addnstr(stdscr, row, 2, dot, 1, dot_attr)

            label_str = "  " + label.ljust(22)
            _safe_addnstr(stdscr, row, 3, label_str[:max_x - 4], max_x - 4, curses.A_NORMAL)
            lx = 3 + len(label_str)
            if lx < max_x - 4:
                _safe_addnstr(stdscr, row, lx, hint[:max_x - lx - 1], max_x - lx - 1, attrs["dim"])
            row += 1

    # ── Helper: draw page 2 (Credentials) ────────────────────────────────────
    def _draw_page2(max_y, max_x):
        nonlocal page2_scroll
        content_start = 3
        visible_rows = max(1, max_y - 5 - content_start)
        current_row_idx = cred_selectable[page2_cursor]

        # Scroll
        if current_row_idx < page2_scroll:
            page2_scroll = current_row_idx
        elif current_row_idx >= page2_scroll + visible_rows:
            page2_scroll = current_row_idx - visible_rows + 1

        for i in range(visible_rows):
            row_idx = page2_scroll + i
            if row_idx >= len(cred_rows):
                break
            screen_row = content_start + i
            if screen_row >= max_y - 2:
                break
            crow = cred_rows[row_idx]

            if crow["type"] == "header":
                section = crow["text"] + "  " + "\u2500" * max(0, 36 - len(crow["text"]))
                _safe_addnstr(stdscr, screen_row, 2, section[:max_x - 3], max_x - 3,
                              attrs["accent"] | curses.A_BOLD)
            else:
                entry = crow["entry"]
                enabled = is_enabled(entry, cred_overrides)
                is_current = (row_idx == current_row_idx)
                has_warn = "warning" in entry

                warn_tag = " \u26a0" if has_warn else "  "
                path_hint = ", ".join(f"~/{p}" for p in entry["paths"])

                prefix = "\u25b8 " if is_current else "  "
                prefix_attr = attrs["accent"] | curses.A_BOLD if is_current else curses.A_NORMAL
                _safe_addnstr(stdscr, screen_row, 0, prefix, 2, prefix_attr)

                if enabled:
                    dot = "\u25c9"   # ◉
                    dot_attr = attrs["accent"] | curses.A_BOLD
                else:
                    dot = "\u25cb"   # ○
                    dot_attr = attrs["dim"]
                _safe_addnstr(stdscr, screen_row, 2, dot, 1, dot_attr)

                name_str = "  " + entry["name"].ljust(22) + warn_tag
                _safe_addnstr(stdscr, screen_row, 3, name_str[:max_x - 4], max_x - 4,
                              curses.A_BOLD if is_current else curses.A_NORMAL)
                nx = 3 + len(name_str)
                if nx < max_x - 4:
                    _safe_addnstr(stdscr, screen_row, nx, path_hint[:max_x - nx - 1],
                                  max_x - nx - 1, attrs["dim"])

    # ── Helper: draw footer ───────────────────────────────────────────────────
    def _draw_footer(max_y, max_x):
        footer_row = max_y - 2

        if current_page == 0:
            # Show contextual hint for the focused row
            _rand_toggle_idx = len(theme_names) + 1
            _freq_slider_idx = len(theme_names) + 2
            if page0_cursor < len(theme_names):
                tid = theme_names[page0_cursor]
                hint = "  " + THEMES[tid]["description"]
            elif page0_cursor == len(theme_names):
                hint = "  Spin the star animation while the provider binary starts up"
            elif page0_cursor == _rand_toggle_idx:
                hint = "  Picks a different theme automatically every few sessions"
            else:
                hint = "  Use \u2190 \u2192 to set how often the theme rotates"
            _safe_addnstr(stdscr, footer_row, 0, hint[:max_x - 1], max_x - 1, attrs["dim"])

        elif current_page == 1:
            hints_behavior = [
                "  Default on. Checks PyPI daily — can be disabled for air-gapped setups",
                "  Friendly time-of-day line shown beneath the banner on launch",
                "  Witty one-liner printed to stderr after every session ends",
            ]
            if 0 <= page1_cursor < len(hints_behavior):
                _safe_addnstr(stdscr, footer_row, 0, hints_behavior[page1_cursor][:max_x - 1],
                              max_x - 1, attrs["dim"])

        elif current_page == 2:
            current_row_idx = cred_selectable[page2_cursor]
            crow = cred_rows[current_row_idx]
            if crow["type"] == "entry" and crow["entry"].get("warning"):
                warn_line = "  \u26a0  " + crow["entry"]["warning"]
                _safe_addnstr(stdscr, footer_row, 0, warn_line[:max_x - 1], max_x - 1,
                              curses.color_pair(7) | curses.A_DIM)

        _on_freq_slider = (current_page == 0
                           and page0_cursor == len(theme_names) + 2
                           and random_theme_on)
        if _on_freq_slider:
            nav = "  \u2191\u2193/jk navigate  \u2190\u2192/hl adjust  Space toggle  Tab page  s save  q/Esc cancel"
        else:
            nav = "  \u2191\u2193/jk navigate  Space toggle  \u2190\u2192/hl/Tab page  s save  q/Esc cancel"
        _safe_addnstr(stdscr, max_y - 1, 0, nav[:max_x - 1], max_x - 1, attrs["dim"])

    # ── Main event loop ───────────────────────────────────────────────────────
    while True:
        stdscr.erase()
        max_y, max_x = stdscr.getmaxyx()

        # Reload attrs in case theme changed (live preview)
        attrs = _picker_attrs()

        # Tab bar (row 0)
        _draw_tab_bar(max_x)

        # Page subtitle (row 1)
        subtitle = "  " + _SETTINGS_PAGES[current_page]["subtitle"]
        _safe_addnstr(stdscr, 1, 0, subtitle[:max_x - 1], max_x - 1, attrs["dim"])

        # Separator (row 2) — accent fade: first 8 chars in theme accent, rest dim
        sep_full = "\u2500" * (max_x - 1)
        accent_len = min(8, max_x - 1)
        _safe_addnstr(stdscr, 2, 0, sep_full[:accent_len], accent_len, attrs["accent"])
        if accent_len < max_x - 1:
            _safe_addnstr(stdscr, 2, accent_len, sep_full[accent_len:max_x - 1],
                          max_x - 1 - accent_len, attrs["dim"])

        # Page content
        if current_page == 0:
            _draw_page0(max_y, max_x, attrs)
        elif current_page == 1:
            _draw_page1(max_y, max_x)
        elif current_page == 2:
            _draw_page2(max_y, max_x)

        # Footer
        _draw_footer(max_y, max_x)

        stdscr.refresh()

        key = stdscr.getch()

        # ── Page navigation ──────────────────────────────────────────────────
        # Page 0 owns ←/→ for the freq slider; other pages use them for tab switching.
        if key in (curses.KEY_LEFT, ord("h")) and current_page != 0:
            current_page = (current_page - 1) % n_pages
            continue
        elif key in (curses.KEY_RIGHT, ord("l")) and current_page != 0:
            current_page = (current_page + 1) % n_pages
            continue
        elif key == ord("\t"):   # Tab → next page
            current_page = (current_page + 1) % n_pages
            continue
        elif key == curses.KEY_BTAB:  # Shift-Tab → prev page
            current_page = (current_page - 1) % n_pages
            continue

        # ── Global keys ──────────────────────────────────────────────────────
        elif key in (ord("q"), 27):  # Esc / q → cancel
            # Restore original theme on cancel
            set_current_theme(original_theme)
            _picker_attrs()  # reinit color pairs for restored theme
            return None

        elif key == ord("s"):  # Save
            return {
                "theme": theme_names[current_theme_idx],
                "launch_animation": launch_anim,
                "update_check": update_check,
                "show_greeting": show_greeting,
                "show_goodbye": show_goodbye,
                "random_theme_enabled": random_theme_on,
                "random_theme_frequency": random_theme_freq,
                "shared": {k: v for k, v in cred_overrides.items()
                           if cred_defaults.get(k) != v},
            }

        elif key == curses.KEY_RESIZE:
            continue

        # ── Per-page navigation & toggling ──────────────────────────────────
        elif current_page == 0:
            _rand_idx = len(theme_names) + 1
            _freq_idx = len(theme_names) + 2

            if key in (curses.KEY_UP, ord("k")):
                new_cur = page0_cursor - 1
                # Skip freq slider when random theme is off
                if new_cur == _freq_idx and not random_theme_on:
                    new_cur -= 1
                page0_cursor = max(0, new_cur)
            elif key in (curses.KEY_DOWN, ord("j")):
                new_cur = page0_cursor + 1
                # Skip freq slider when random theme is off
                if new_cur == _freq_idx and not random_theme_on:
                    new_cur += 1
                page0_cursor = min(page0_n - 1, new_cur)
            elif key == ord(" "):
                if page0_cursor == len(theme_names):
                    launch_anim = not launch_anim
                elif page0_cursor == _rand_idx:
                    random_theme_on = not random_theme_on
            elif key in (curses.KEY_LEFT, ord("h")):
                if page0_cursor == _freq_idx and random_theme_on:
                    random_theme_freq = max(1, random_theme_freq - 1)
                else:
                    current_page = (current_page - 1) % n_pages
            elif key in (curses.KEY_RIGHT, ord("l")):
                if page0_cursor == _freq_idx and random_theme_on:
                    random_theme_freq = min(5, random_theme_freq + 1)
                else:
                    current_page = (current_page + 1) % n_pages

            # Theme selection follows cursor — live preview IS the selection
            if page0_cursor < len(theme_names) and current_theme_idx != page0_cursor:
                current_theme_idx = page0_cursor
                set_current_theme(theme_names[current_theme_idx])

        elif current_page == 1:
            if key in (curses.KEY_UP, ord("k")):
                page1_cursor = max(0, page1_cursor - 1)
            elif key in (curses.KEY_DOWN, ord("j")):
                page1_cursor = min(page1_n - 1, page1_cursor + 1)
            elif key == ord(" "):
                if page1_cursor == 0:
                    update_check = not update_check
                elif page1_cursor == 1:
                    show_greeting = not show_greeting
                elif page1_cursor == 2:
                    show_goodbye = not show_goodbye

        elif current_page == 2:
            if key in (curses.KEY_UP, ord("k")):
                page2_cursor = max(0, page2_cursor - 1)
            elif key in (curses.KEY_DOWN, ord("j")):
                page2_cursor = min(len(cred_selectable) - 1, page2_cursor + 1)
            elif key == curses.KEY_PPAGE:
                page2_cursor = max(0, page2_cursor - 5)
            elif key == curses.KEY_NPAGE:
                page2_cursor = min(len(cred_selectable) - 1, page2_cursor + 5)
            elif key == ord(" "):
                entry = cred_rows[cred_selectable[page2_cursor]]["entry"]
                new_val = not is_enabled(entry, cred_overrides)
                cred_overrides[entry["id"]] = new_val
                if new_val and entry["id"] in ("gh", "glab"):
                    cred_overrides["gitconfig"] = True


def interactive_settings():
    """Open the multi-page settings TUI, save on confirm, and apply changes."""
    show_banner()
    result = curses.wrapper(_draw_settings)
    if result is None:
        print("Cancelled.")
        return

    # ── Persist all settings in a single atomic write ──────────────────────────
    new_theme = result.get("theme", get_current_theme())
    if new_theme in THEMES:
        set_current_theme(new_theme)

    shared_overrides = result.get("shared", {})

    SETTINGS_FILE.parent.mkdir(parents=True, exist_ok=True)
    data = {}
    if SETTINGS_FILE.exists():
        try:
            data = json.loads(SETTINGS_FILE.read_text())
        except Exception:
            data = {}
    data["theme"] = new_theme
    data["launch_animation"] = result.get("launch_animation", True)
    data["update_check"] = result.get("update_check", True)
    data["show_greeting"] = result.get("show_greeting", True)
    data["show_goodbye"] = result.get("show_goodbye", True)
    data["random_theme_enabled"]   = result.get("random_theme_enabled", False)
    data["random_theme_frequency"] = result.get("random_theme_frequency", 3)
    # random_theme_counter is managed by maybe_rotate_random_theme — do not touch it here
    data["version"] = 1
    cred_defaults = {e["id"]: e["default_on"] for e in CATALOG}
    data["shared"] = {k: v for k, v in shared_overrides.items()
                      if cred_defaults.get(k) != v}
    tmp = SETTINGS_FILE.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(data, indent=2))
    os.replace(str(tmp), str(SETTINGS_FILE))

    print()
    print(_c(C("header"), "=== Applying settings ==="))
    print()

    def _apply_all():
        for acct_name in list_accounts() or ["default"]:
            acct_home, _ = resolve_account(acct_name)
            if acct_home.exists():
                for entry in CATALOG:
                    _apply_entry(entry, shared_overrides, acct_home)

    _status_wrap("Applying shared credentials…", _apply_all)
    print()
    print(_c(C("success"), "Settings saved and applied."))


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


def _sweep_existing_accounts() -> bool:
    """Repair any accounts that still have real dirs where symlinks are expected.

    Runs automatically after migrate_legacy() and at the start of launch_claude()
    so that existing 0.6.0 users are repaired on next launch without needing
    to run --setup manually.  Silent unless something actually changes.
    """
    changed = False
    for acct in list_accounts():
        _, account_claude = resolve_account(acct)
        for name in SYMLINK_DIRS:
            src = MAIN_CLAUDE / name
            dst = account_claude / name
            if _ensure_symlinked_dir(name, src, dst, account_claude):
                changed = True
    return changed


def launch_claude(account: str = "default", args=None, provider: str | None = None):
    """Launch a provider CLI with account HOME, passing args through unchanged.

    If provider is None, reads account.json to determine which provider to use.
    Single-provider accounts auto-select; multi-provider accounts require a
    positional provider argument (e.g. altergo work gemini).
    """
    _sweep_existing_accounts()

    account_home, _ = resolve_account(account)

    # Resolve provider
    if provider is None:
        meta = load_account_meta(account_home)
        if meta is not None and "providers" in meta:
            prov_list = meta["providers"]
        else:
            prov_list = ["claude"]

        if len(prov_list) == 1:
            provider = prov_list[0]
        else:
            names = ", ".join(prov_list)
            print(
                f"altergo: account '{account}' has multiple providers ({names}).\n"
                f"  Specify one: altergo {account} <provider>",
                file=sys.stderr,
            )
            sys.exit(1)

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
        prov = PROVIDERS.get(provider)
        if prov is None:
            print(f"altergo: unknown provider '{provider}'.", file=sys.stderr)
            sys.exit(1)
        binary_path = shutil.which(prov["binary"])
        if not binary_path:
            sys.exit(
                f"altergo: '{prov['binary']}' not found in PATH.\n"
                f"  Install {prov['display_name']} and try again."
            )

    env = _build_alt_env(account)
    cmd = [binary_path] + (args or [])
    # Kick off the background PyPI check (no-op if opt-out or not yet due)
    # BEFORE the banner so the cache from a previous run drives the nag.
    maybe_refresh_update_cache()
    first_launch_notice_if_needed()
    _anim = _handoff_duration(provider) if _load_bool_setting("launch_animation") else 0.0
    show_banner(
        account,
        latest_version=get_cached_latest_version(),
        show_greeting=_load_bool_setting("show_greeting"),
        animate_duration=_anim,
    )
    result = subprocess.run(cmd, env=env)
    _print_launch_message()
    sys.exit(result.returncode)


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
    # Shell starts effectively instantly, so no twinkle animation — but
    # keep the greeting + update nag for consistency with other launch paths.
    show_banner(
        account,
        latest_version=get_cached_latest_version(),
        show_greeting=_load_bool_setting("show_greeting"),
    )
    print(_c(C("command"), f"Entering altergo shell [{account}] (HOME={account_home})"))
    print(_c(C("dim"), "Run 'exit' or Ctrl-D to return to your primary account.\n"))
    result = subprocess.run([shell], env=env)
    _print_launch_message()
    sys.exit(result.returncode)


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
    result = subprocess.run([cmd_path] + cmd_args[1:], env=env)
    _print_launch_message()
    sys.exit(result.returncode)


# --- Account name disambiguation helper ---


_KNOWN_COMMANDS = frozenset(
    ["shell", "--resume", "--list", "--search", "--setup", "--teardown", "--settings", "--version", "--use", "--launch", "--theme", "--update-check", "-h", "--help", "--"]
)


def _looks_like_account(token: str) -> bool:
    """Return True if token could be an account name (not a flag, not a known command)."""
    if token.startswith("-"):
        return False
    if token in _KNOWN_COMMANDS:
        return False
    # Must look like a valid account name (alphanumeric start, no spaces)
    return bool(re.match(r"^[a-zA-Z0-9][a-zA-Z0-9_-]*$", token))


# --- Interactive prompt helpers ---


def _prompt_account_name() -> str:
    """Interactively prompt for account name. Shows existing accounts."""
    existing = list_accounts()
    if existing:
        print(f"  Existing accounts: {', '.join(_c(36, a) for a in existing)}")
    while True:
        raw = input("  Account name: ").strip()
        if not raw:
            print("  Please enter an account name.")
            continue
        try:
            validate_account_name(raw)
            return raw
        except SystemExit:
            print(f"  Invalid name '{raw}'. Use letters, digits, - or _ only.")


def _prompt_provider_selection(current_providers: list[str] | None = None) -> list[str]:
    """Prompt user to select which AI providers this account uses.

    Detects installed provider binaries and pre-checks them.
    current_providers: if set, pre-check these instead of detecting.
    Returns list of provider IDs (at least one).
    """
    # Build ordered list: installed ones first, then others
    installed = [pid for pid, p in PROVIDERS.items() if shutil.which(p["binary"])]
    all_providers = list(PROVIDERS.keys())
    ordered = installed + [p for p in all_providers if p not in installed]

    pre_checked = current_providers if current_providers is not None else installed
    # Always ensure claude is pre-checked if nothing is installed
    if not pre_checked:
        pre_checked = ["claude"]

    print()
    print("  Select AI providers for this account (space to toggle, enter to confirm):")
    print()

    selected = set(pre_checked)
    items = ordered

    # Simple interactive: show numbered list, ask for comma-separated selection
    for i, pid in enumerate(items):
        p = PROVIDERS[pid]
        check_mark = _c(32, "\u2713")
        checked = check_mark if pid in selected else " "
        installed_hint = _c(2, " (installed)") if shutil.which(p["binary"]) else _c(31, " (not found)")
        print(f"  [{checked}] {i+1}. {p['display_name']}{installed_hint}")

    print()
    pre_nums = [str(items.index(p) + 1) for p in pre_checked if p in items]
    default_str = ",".join(pre_nums) or "1"
    raw = input(f"  Enter numbers separated by commas [{_c(36, default_str)}]: ").strip()

    if not raw:
        chosen_indices = [int(n) - 1 for n in default_str.split(",")]
    else:
        try:
            chosen_indices = [int(n.strip()) - 1 for n in raw.split(",")]
        except ValueError:
            chosen_indices = [int(n) - 1 for n in default_str.split(",")]

    result = []
    for i in chosen_indices:
        if 0 <= i < len(items):
            result.append(items[i])

    # Deduplicate while preserving order
    seen = set()
    deduped = []
    for pid in result:
        if pid not in seen:
            seen.add(pid)
            deduped.append(pid)

    if not deduped:
        warn = _c(33, "\u26a0")
        print(f"  {warn} No provider selected \u2014 defaulting to Claude Code.")
        deduped = ["claude"]

    return deduped


# --- Goodbye messages ---

_GOODBYE = [
    ("👋", "Back to reality. Good luck with the next bug."),
    ("🚪", "Session closed. The context window has left the building."),
    ("🤔", "That was productive, ah?"),
    ("💬", "The chat is over. Your git blame remains."),
    ("🧠", "All that intelligence, and it still couldn't push to main for you."),
    ("⏱️", "See you in 5 minutes when the next edge case appears."),
    ("🔮", "The model has spoken. Whether it was right is your problem."),
    ("💸", "Tokens spent. Wisdom optional."),
    ("📝", "Another session closed. Another PR description that writes itself."),
    ("🤷", "Done. The AI did the thinking. You take the blame."),
    ("✅", "Clean exit. The work continues."),
    ("🍀", "Until next time. May your tests be green."),
    ("📌", "Context preserved. You know where to find it."),
    ("🚀", "Ship it."),
    ("💾", "Commit early, commit often. You know the drill."),
]

def _print_launch_message():
    """Print a witty handoff line to stderr before handing off to an AI session."""
    if not sys.stderr.isatty():
        return
    if not _load_bool_setting("show_goodbye"):
        return
    import random
    emoji, msg = random.choice(_GOODBYE)
    grad = THEMES.get(get_current_theme(), THEMES[_DEFAULT_THEME])["banner"]
    parts = []
    n = len(msg)
    for i, ch in enumerate(msg):
        t = i / max(n - 1, 1)
        col = _gradient_color(grad, t)
        parts.append(f"\033[38;2;{int(col[1:3],16)};{int(col[3:5],16)};{int(col[5:7],16)}m{ch}")
    colored = "".join(parts) + "\033[0m"
    print(f"\n  {emoji}  {colored}\n", file=sys.stderr)


# --- Interactive provider+account launcher ---

_LAUNCHER_PROVIDERS = [
    {"id": "claude",  "label": "anthropic", "binary": "claude"},
    {"id": "gemini",  "label": "gemini",    "binary": "gemini"},
    {"id": "codex",   "label": "openai",    "binary": "codex"},
    {"id": "copilot", "label": "github",    "binary": "copilot"},
]


def build_launcher_menu() -> list:
    """Build provider-grouped account menu for the interactive launcher.

    Returns a list of provider dicts:
        [{"provider_id": str, "label": str, "accounts": [{"name": str, "age": str, "available": bool}]}]
    """
    accounts = list_accounts()
    # Group accounts by their primary provider from account.json
    provider_accounts: dict = {}
    for acct in accounts:
        acct_home = ACCOUNTS_DIR / acct
        meta = load_account_meta(acct_home)
        providers_for_acct = meta["providers"] if meta else ["claude"]
        primary = providers_for_acct[0] if providers_for_acct else "claude"
        provider_accounts.setdefault(primary, []).append(acct)

    # Resolve most-recent session age per account (best-effort) — wrapped
    # in a spinner because JSONL scanning can be 1–2s for heavy users.
    all_sessions = _status_wrap("Scanning sessions…", get_sessions)
    acct_ages: dict = {}
    for s in all_sessions:
        # Sessions live under MAIN_CLAUDE/projects — not per-account, so use
        # the first session encountered as a proxy for "recently active"
        for acct in accounts:
            if acct not in acct_ages:
                acct_ages[acct] = relative_time(s["modified"])
        if len(acct_ages) == len(accounts):
            break

    # Build ordered menu following _LAUNCHER_PROVIDERS order, then any extras
    seen_providers = set()
    menu = []
    ordered_ids = [p["id"] for p in _LAUNCHER_PROVIDERS] + list(provider_accounts.keys())
    for pid in ordered_ids:
        if pid in seen_providers or pid not in provider_accounts:
            continue
        seen_providers.add(pid)
        label = next((p["label"] for p in _LAUNCHER_PROVIDERS if p["id"] == pid), pid)
        binary = next((p["binary"] for p in _LAUNCHER_PROVIDERS if p["id"] == pid), pid)
        available = bool(shutil.which(binary))
        chips = []
        for acct in provider_accounts[pid]:
            chips.append({
                "name": acct,
                "age": acct_ages.get(acct, ""),
                "available": available,
            })
        menu.append({"provider_id": pid, "label": label, "accounts": chips})
    return menu


def _draw_launcher(stdscr, menu):
    """Two-axis curses TUI: ↑↓ providers, ←→ account chips. Returns (account, shell_mode)."""
    curses.curs_set(0)
    attrs = _picker_attrs()
    stdscr.timeout(80)

    cursor_row = 0
    cursor_col = 0
    phase = 0

    # Sanitize initial cursor position
    def clamp_col(row, col):
        if not menu:
            return 0
        return min(col, max(0, len(menu[row]["accounts"]) - 1))

    while True:
        stdscr.erase()
        max_y, max_x = stdscr.getmaxyx()

        total_accounts = sum(len(p["accounts"]) for p in menu)
        n_providers = len(menu)

        # Header
        title = " altergo — launch"
        right = f"{n_providers} provider{'s' if n_providers != 1 else ''} · {total_accounts} account{'s' if total_accounts != 1 else ''} "
        header = title.ljust(max_x - len(right)) + right
        _safe_addnstr(stdscr, 0, 0, header[:max_x], max_x - 1, attrs["title"])

        # Separator
        _safe_addnstr(stdscr, 1, 0, ("─" * (max_x - 1))[:max_x - 1], max_x - 1, attrs["dim"])

        # Provider rows (start at row 3, blank row between each)
        row = 3
        for pi, prov in enumerate(menu):
            if row >= max_y - 3:
                break
            label = prov["label"][:12].ljust(12)
            is_focused_row = pi == cursor_row
            label_attr = attrs["project"] | curses.A_BOLD if is_focused_row else attrs["project"]
            _safe_addnstr(stdscr, row, 2, label, 12, label_attr)

            x = 16
            for ci, chip in enumerate(prov["accounts"]):
                if x >= max_x - 5:
                    _safe_addnstr(stdscr, row, x, "…", 1, attrs["dim"])
                    break
                name = chip["name"][:10]
                age = chip["age"][:5] if chip["age"] else ""
                chip_text = f"{name} · {age}" if age else name
                is_selected = is_focused_row and ci == cursor_col

                if not chip["available"]:
                    chip_str = f"✗ {chip_text}  "
                    _safe_addnstr(stdscr, row, x, chip_str[:max_x - x - 1], max_x - x - 1, attrs["dim"])
                elif is_selected:
                    chip_str = f"▓ {chip_text} ▓ "
                    _safe_addnstr(stdscr, row, x, chip_str[:max_x - x - 1], max_x - x - 1, attrs["selected"])
                elif is_focused_row:
                    chip_str = f"░ {chip_text} ░ "
                    _safe_addnstr(stdscr, row, x, chip_str[:max_x - x - 1], max_x - x - 1, attrs["time"])
                else:
                    chip_str = f"  {chip_text}   "
                    _safe_addnstr(stdscr, row, x, chip_str[:max_x - x - 1], max_x - x - 1, attrs["dim"])
                x += len(chip_str)

            row += 2  # blank line between providers

        # Active account indicator (shown in header area if set)
        active_acct = get_active_account()
        if active_acct and max_y > 2:
            active_hint = f" active: {active_acct} "
            _safe_addnstr(stdscr, 0, max(0, max_x - len(active_hint) - 1), active_hint, len(active_hint), attrs["accent"])

        # Nav footer
        theme_hint = f" · theme: {THEMES[get_current_theme()]['display_name']} (t)"
        nav = " ↑↓/jk provider · ←→/hl account · Enter launch · s shell · d set active · q quit" + theme_hint
        _draw_animated_nav(stdscr, max_y - 1, nav, max_x - 1, phase, attrs)

        stdscr.refresh()
        key = stdscr.getch()

        if key == -1:
            phase += 1
            continue

        if key in (curses.KEY_UP, ord("k")):
            cursor_row = max(0, cursor_row - 1)
            cursor_col = clamp_col(cursor_row, 0)
        elif key in (curses.KEY_DOWN, ord("j")):
            cursor_row = min(len(menu) - 1, cursor_row + 1)
            cursor_col = clamp_col(cursor_row, 0)
        elif key in (curses.KEY_LEFT, ord("h")):
            cursor_col = max(0, cursor_col - 1)
        elif key in (curses.KEY_RIGHT, ord("l")):
            cursor_col = clamp_col(cursor_row, cursor_col + 1)
        elif key in (curses.KEY_ENTER, 10, 13):
            if menu and menu[cursor_row]["accounts"]:
                chip = menu[cursor_row]["accounts"][cursor_col]
                if chip["available"]:
                    return chip["name"], False
        elif key == ord("s"):
            if menu and menu[cursor_row]["accounts"]:
                chip = menu[cursor_row]["accounts"][cursor_col]
                if chip["available"]:
                    return chip["name"], True
        elif key == ord("d"):
            if menu and menu[cursor_row]["accounts"]:
                chip = menu[cursor_row]["accounts"][cursor_col]
                set_active_account(chip["name"])
                # Show brief flash on the footer so user sees confirmation
                confirm = f" ✓ '{chip['name']}' set as active account "
                _safe_addnstr(stdscr, max_y - 1, 0, confirm[:max_x - 1].ljust(max_x - 1), max_x - 1, attrs["accent"])
                stdscr.refresh()
                curses.napms(800)
        elif key == ord("t"):
            # Cycle to the next theme, re-initialize curses color pairs so
            # the current draw picks up the new palette, and persist the
            # choice immediately — feels more responsive than committing
            # on exit, and a crashed session still remembers the pick.
            theme_ids = list(THEMES.keys())
            cur = get_current_theme()
            nxt = theme_ids[(theme_ids.index(cur) + 1) % len(theme_ids)] if cur in theme_ids else theme_ids[0]
            set_current_theme(nxt)
            save_persisted_theme(nxt)
            attrs = _picker_attrs()
            confirm = f" ✓ theme: {THEMES[nxt]['display_name']} — {THEMES[nxt]['description']} "
            _safe_addnstr(stdscr, max_y - 1, 0, confirm[:max_x - 1].ljust(max_x - 1), max_x - 1, attrs["accent"])
            stdscr.refresh()
            curses.napms(700)
        elif key in (ord("q"), 27):
            return None, False
        elif key == curses.KEY_RESIZE:
            continue


def _first_run_onboarding():
    """Full-screen onboarding for brand-new users with zero accounts configured.

    Shows a thin-font logo, two lines of copy, a setup-options hint, and an
    inline name prompt. On a valid name the function runs do_setup() then drops
    straight into interactive_launcher() so the user never has to type a second
    command. On empty input or Ctrl-C it prints a hint and exits cleanly.
    """
    # Rich is always present (show_banner uses it); import locally so the
    # function is self-contained and mirrors the pattern in show_banner().
    try:
        from rich.console import Console
        from rich.text import Text
        from rich.prompt import Prompt
        console = Console()
    except Exception:
        # Extremely degraded environment — fall back to plain text and bail.
        print("altergo: no accounts found. Run 'altergo --setup' first.", file=sys.stderr)
        sys.exit(1)

    # ── Logo ──────────────────────────────────────────────────────────────────
    # Use pyfiglet's "thin" font (onboarding-only — show_banner stays smslant).
    # Apply the current theme's banner gradient character-by-character across
    # all non-whitespace glyphs so it reads as a gradient sweep.
    theme = THEMES.get(get_current_theme(), THEMES[_DEFAULT_THEME])
    grad = theme["banner"]

    logo_lines = []
    try:
        import pyfiglet
        rendered = pyfiglet.Figlet(font="thin").renderText("altergo")
        logo_lines = [l for l in rendered.splitlines() if l.strip()]
    except Exception:
        logo_lines = ["altergo"]

    # Count non-space characters to spread the gradient smoothly across them.
    total = sum(1 for line in logo_lines for ch in line if ch != " ")
    total = max(total, 1)

    char_idx = 0
    for line_idx, line in enumerate(logo_lines):
        text = Text()
        for ch in line:
            if ch == " ":
                text.append(" ")
            else:
                _t = char_idx / max(total - 1, 1)
                text.append(ch, style=_gradient_color(grad, _t))
                char_idx += 1

        # Append version tag dim-styled to the right of the last logo line.
        if line_idx == len(logo_lines) - 1:
            text.append(f"  v{__version__}", style="dim")

        console.print(text)

    # ── Copy ──────────────────────────────────────────────────────────────────
    console.print()
    console.print(Text(
        "  altergo \u2014 multiple AI identities from one terminal.",
        style="dim",
    ))
    console.print()
    console.print(Text("  You don't have any accounts yet. Let's fix that.", style="dim"))
    console.print()

    # ── Setup-options hint ────────────────────────────────────────────────────
    console.print(Text("  run altergo --setup to configure interactively", style="dim"))
    console.print(Text("  or altergo --setup --name <name> to skip the prompts", style="dim"))
    console.print()

    # ── Name prompt loop ──────────────────────────────────────────────────────
    while True:
        try:
            raw = Prompt.ask(
                "  Account name (e.g., personal, work, sideproject)"
                " [or press Enter to run --setup]",
                default="",
                show_default=False,
                console=console,
            ).strip()
        except KeyboardInterrupt:
            console.print()
            console.print("  \u2192 run: altergo --setup --name <name> when ready")
            sys.exit(0)

        if not raw:
            console.print()
            console.print("  \u2192 run: altergo --setup")
            sys.exit(0)

        # Inline validation — we cannot call validate_account_name() here
        # because it calls sys.exit(1) on failure, which would kill the loop.
        if not re.match(r"^[a-zA-Z0-9][a-zA-Z0-9_-]*$", raw) or len(raw) > 64:
            console.print(Text(
                f"  Invalid name '{raw}'. Use letters, digits, - or _ only; "
                "must not start with a digit or special char.",
                style="dim",
            ))
            continue

        if raw in _RESERVED_NAMES:
            console.print(Text(
                f"  '{raw}' is a reserved name. Choose a different account name.",
                style="dim",
            ))
            continue

        # Valid name — proceed.
        break

    # ── Provider detection (silent — no prompt) ───────────────────────────────
    # Mirror the logic in _prompt_provider_selection() but skip the interactive
    # bits: detect what's installed and default to ["claude"] if nothing is.
    detected = [pid for pid, p in PROVIDERS.items() if shutil.which(p["binary"])]
    if not detected:
        detected = ["claude"]

    # ── Run setup then drop into the launcher ────────────────────────────────
    console.print()
    do_setup(raw, detected)
    interactive_launcher()


def interactive_launcher():
    """Show the provider+account picker and launch the selected account."""
    menu = build_launcher_menu()
    if not menu:
        print("altergo: no accounts found. Run 'altergo --setup' first.", file=sys.stderr)
        sys.exit(1)
    result = curses.wrapper(_draw_launcher, menu)
    account, shell_mode = result if result else (None, False)
    if not account:
        sys.exit(0)
    if shell_mode:
        launch_shell(account)
    else:
        launch_claude(account)


# --- Main ---


def main():
    # Load the user's persisted theme before anything prints so the banner,
    # help output, and curses screens all share one palette from the first
    # character onward.
    set_current_theme(load_persisted_theme())
    maybe_rotate_random_theme()
    # Auto-migrate legacy layout before any other processing
    migrate_legacy()
    # Repair any accounts that still have real dirs instead of symlinks
    # (covers the default account after legacy migration, and any 0.6.0 users
    # whose accounts/default/.claude/projects/ was left as a real dir).
    _sweep_existing_accounts()

    args = sys.argv[1:]

    # ── Altergo-owned commands (not passed to claude) ──────────────────────────

    if args and args[0] in ("-h", "--help"):
        show_help()
        sys.exit(0)

    if args and args[0] == "--version":
        print(f"altergo {__version__}")
        sys.exit(0)

    if args and args[0] == "--setup":
        # Parse --name and --provider flags
        # Supported forms:
        #   altergo --setup                              (interactive)
        #   altergo --setup --name work                  (named, interactive provider)
        #   altergo --setup --name work --provider claude,gemini  (fully specified)
        #   altergo --setup --provider gemini            (interactive name, specified provider)
        remaining = args[1:]
        name = None
        provider_arg = None
        i = 0
        while i < len(remaining):
            if remaining[i] == "--name" and i + 1 < len(remaining):
                name = remaining[i + 1]
                validate_account_name(name)
                i += 2
            elif remaining[i] == "--provider" and i + 1 < len(remaining):
                provider_arg = remaining[i + 1]
                i += 2
            else:
                i += 1

        # Resolve name
        if name is None:
            if sys.stdin.isatty():
                name = _prompt_account_name()
            else:
                name = "default"

        # Resolve providers
        if provider_arg is not None:
            providers = [p.strip() for p in provider_arg.split(",")]
            unknown = [p for p in providers if p not in PROVIDERS]
            if unknown:
                print(f"altergo: unknown provider(s): {', '.join(unknown)}. Known: {', '.join(PROVIDERS)}", file=sys.stderr)
                sys.exit(1)
        else:
            if sys.stdin.isatty():
                account_home, _ = resolve_account(name)
                meta = load_account_meta(account_home)
                current = meta["providers"] if meta else None
                providers = _prompt_provider_selection(current)
            else:
                # Non-interactive: default to claude (backwards compat)
                account_home, _ = resolve_account(name)
                meta = load_account_meta(account_home)
                providers = meta["providers"] if meta else ["claude"]

        do_setup(name, providers)
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

    if args and args[0] == "--launch":
        interactive_launcher()
        sys.exit(0)

    if args and args[0] == "--update-check":
        # `altergo --update-check`          → show current state + last known
        # `altergo --update-check on|off`   → persist
        show_banner()
        if len(args) == 1:
            enabled = load_update_check_enabled()
            state = _c(C("success"), "on") if enabled else _c(C("warn"), "off")
            print(f"  update check: {state}")
            cache = _read_update_cache()
            if cache:
                last = cache.get("last_check", 0)
                if last:
                    ago = int(time.time() - last)
                    print(_c(C("dim"),
                              f"  last checked: {ago // 60} min ago"))
                latest = _sanitize_version(cache.get("latest_version"))
                if latest:
                    marker = _c(C("warn"), "newer") if _is_newer(latest, __version__) else _c(C("success"), "current")
                    print(_c(C("dim"), f"  latest known: v{latest}  ({marker})")
                          if latest else "")
            print()
            print(_c(C("dim"),
                      "  Toggle with: altergo --update-check on|off"))
            sys.exit(0)
        choice = args[1].lower()
        if choice in ("on", "true", "1", "yes"):
            save_update_check_enabled(True)
            print(_c(C("success"), "  update check enabled"))
        elif choice in ("off", "false", "0", "no"):
            save_update_check_enabled(False)
            print(_c(C("warn"), "  update check disabled"))
        else:
            print(
                f"altergo: --update-check takes 'on' or 'off', got '{args[1]}'",
                file=sys.stderr,
            )
            sys.exit(1)
        sys.exit(0)

    if args and args[0] == "--theme":
        # `altergo --theme`         → print current + catalog
        # `altergo --theme <name>`  → set persistently
        if len(args) == 1:
            show_banner()
            cur = get_current_theme()
            print(f"  current: {_c(C('command'), THEMES[cur]['display_name'])}  ({cur})")
            print()
            print(_c(C("header"), "  Available themes"))
            for tid, t in THEMES.items():
                marker = _c(C("success"), "●") if tid == cur else " "
                name = _c(C("command"), t["display_name"].ljust(10))
                print(f"  {marker} {name}  {_c(C('dim'), t['description'])}")
            print()
            print(_c(C("dim"), "  Set with: altergo --theme <name>   ·   or press 't' in the launcher"))
            sys.exit(0)
        name = args[1]
        if name not in THEMES:
            print(
                f"altergo: unknown theme '{name}'. Known: {', '.join(THEMES.keys())}",
                file=sys.stderr,
            )
            sys.exit(1)
        set_current_theme(name)
        save_persisted_theme(name)
        show_banner()
        print(
            f"  theme set to {_c(C('command'), THEMES[name]['display_name'])}  "
            f"{_c(C('dim'), '— ' + THEMES[name]['description'])}"
        )
        sys.exit(0)

    if args and args[0] == "--list":
        show_banner()
        sessions = _status_wrap("Scanning sessions…", get_sessions)
        if not sessions:
            print("  No sessions found.")
            sys.exit(0)
        header_row = f"{'Project':<20} {'Modified':<18} {'Size':>6}  Session ID"
        print(_c(C("dim"), header_row))
        print(_c(C("dim"), "-" * 80))
        for s in sessions[:30]:
            project = format_project_name(s["project"])
            modified = s["modified"].strftime("%Y-%m-%d %H:%M")
            size = f"{s['size_mb']:.1f}MB"
            print(
                f"{_c(C('command'), f'{project:<20}')} "
                f"{_c(C('dim'), f'{modified:<18}')} "
                f"{_c(C('warn'), f'{size:>6}')}  {s['id']}"
            )
        sys.exit(0)

    if args and args[0] == "--use":
        if len(args) < 2:
            print("altergo: --use requires an account name. Example: altergo --use work", file=sys.stderr)
            sys.exit(1)
        use_name = args[1]
        use_home = ACCOUNTS_DIR / use_name
        if not use_home.is_dir():
            print(
                f"altergo: account '{use_name}' not found. Run 'altergo --setup --name {use_name}' to create it.",
                file=sys.stderr,
            )
            sys.exit(1)
        set_active_account(use_name)
        print(f"altergo: active account set to {_c(C('command'), use_name)}")
        print(_c(C('dim'), f"  Bare 'altergo' will now launch '{use_name}' by default."))
        sys.exit(0)

    # --search → full-text conversation search
    if args and args[0] == "--search":
        show_banner()
        sessions = _status_wrap("Scanning sessions…", get_sessions)
        selected = interactive_search(sessions)
        if selected:
            accounts = list_accounts()
            if len(accounts) == 1:
                search_account = accounts[0]
            else:
                active = get_active_account()
                search_account = active if active else accounts[0]
            launch_claude(search_account, ["--resume", selected["id"]])
        else:
            print("Cancelled.")
        sys.exit(0)

    # --resume with no ID → open interactive picker
    if args and args[0] == "--resume" and len(args) == 1:
        accounts = list_accounts()
        if not accounts:
            print("altergo: no accounts found. Run 'altergo --setup' first.", file=sys.stderr)
            sys.exit(1)
        if len(accounts) == 1:
            resume_account = accounts[0]
        else:
            active = get_active_account()
            if active:
                resume_account = active
            else:
                print(
                    f"altergo: multiple accounts exist ({', '.join(accounts)}).\n"
                    f"  Use 'altergo <name> --resume' to pick an account, or\n"
                    f"  'altergo --use <name>' to set an active account.",
                    file=sys.stderr,
                )
                sys.exit(1)
        sessions = _status_wrap("Scanning sessions…", get_sessions)
        selected = interactive_picker(sessions)
        if selected:
            launch_claude(resume_account, ["--resume", selected["id"]])
        else:
            print("Cancelled.")
        sys.exit(0)

    # ── Account name as first positional arg ──────────────────────────────────
    # altergo <name> [sub-command | claude flags...]
    account = None
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

    # ── Implicit account resolution (no positional name given) ───────────────
    if account is None:
        _all_accounts = list_accounts()
        _active = get_active_account()
        if _active:
            account = _active
            # The banner printed by launch_claude/launch_shell already shows
            # the account name beneath the logo, so no extra prefix line.
        elif len(_all_accounts) == 1:
            account = _all_accounts[0]
        elif len(_all_accounts) > 1 and sys.stdout.isatty():
            interactive_launcher()
            sys.exit(0)
        elif not _all_accounts:
            if sys.stdout.isatty():
                _first_run_onboarding()
                sys.exit(0)
            else:
                print("altergo: no accounts found. Run 'altergo --setup' first.", file=sys.stderr)
                sys.exit(1)
        else:
            # Multiple accounts, non-interactive — cannot pick one silently
            print(
                f"altergo: multiple accounts exist ({', '.join(_all_accounts)}).\n"
                f"  Run 'altergo <name>' to launch a specific account, or\n"
                f"  'altergo --use <name>' to set an active account for bare 'altergo'.",
                file=sys.stderr,
            )
            sys.exit(1)

    # ── Sub-commands (after optional account prefix) ──────────────────────────

    # altergo [<name>] shell
    if args and args[0] == "shell":
        launch_shell(account)

    # altergo [<name>] -- <cmd> [args...]
    if args and args[0] == "--":
        launch_command(account, args[1:])

    # ── Everything else → pass straight through to claude ────────────────────
    # altergo                    → claude (active account)
    # altergo work               → claude (work account, args=[])
    # altergo --resume x         → claude --resume x
    # altergo --dangerously-...  → claude --dangerously-...

    # Extract positional provider name if present (consumed by altergo, not passed to provider CLI)
    # Syntax: altergo <account> <provider> [args...]
    provider = None
    if args and args[0] in PROVIDERS:
        provider = args[0]
        args = args[1:]
    launch_claude(account, args, provider=provider)


if __name__ == "__main__":
    main()
