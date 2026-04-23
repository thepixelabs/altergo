#!/usr/bin/env python3
"""Altergo — multi-account session manager for AI coding assistants. Run 'altergo --help' for usage."""

__version__ = "0.43.0"

import curses
import json
import os
import plistlib
import pwd
import re
import secrets
import shlex
import shutil
import subprocess
import sys
import threading
import time
from datetime import datetime
from pathlib import Path

# Terminal helpers


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


# Themes
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
        "description": "Calm cyan & indigo — the original altergo palette",
        "ansi": {
            "command": "38;5;39",  # blue
            "arg": "38;5;87",  # electric cyan
            "header": "1;38;5;39",  # bold blue
            "brand": "38;5;105",  # indigo
            "success": "38;5;76",  # green
            "warn": "38;5;220",  # amber
        },
        "curses": {"accent": 51, "project": 105, "amber": 220},
        "banner": ["#00d7ff", "#005fd7"],
    },
    "forest": {
        "display_name": "Forest",
        "description": "Calming moss & sage — grounded green tones",
        "ansi": {
            "command": "38;5;78",  # mint
            "arg": "38;5;121",  # sage
            "header": "1;38;5;78",
            "brand": "38;5;108",  # muted jade
            "success": "38;5;84",
            "warn": "38;5;222",
        },
        "curses": {"accent": 78, "project": 108, "amber": 222},
        "banner": ["#5fff87", "#005f5f"],
    },
    "lavender": {
        "display_name": "Lavender",
        "description": "Soft violet & periwinkle — gentle on the eyes",
        "ansi": {
            "command": "38;5;141",  # soft purple
            "arg": "38;5;183",  # pale lavender
            "header": "1;38;5;141",
            "brand": "38;5;105",
            "success": "38;5;120",
            "warn": "38;5;222",
        },
        "curses": {"accent": 141, "project": 105, "amber": 222},
        "banner": ["#d7afff", "#5f5fff"],
    },
    "sunset": {
        "display_name": "Sunset",
        "description": "Warm rose & ember — dusk palette",
        "ansi": {
            "command": "38;5;209",  # coral
            "arg": "38;5;215",  # peach
            "header": "1;38;5;209",
            "brand": "38;5;205",  # rose
            "success": "38;5;114",
            "warn": "38;5;220",
        },
        "curses": {"accent": 209, "project": 205, "amber": 220},
        "banner": ["#ffaf5f", "#ff5f87"],
    },
    "mono": {
        "display_name": "Mono",
        "description": "Grayscale — minimal, distraction-free",
        "ansi": {
            "command": "38;5;253",
            "arg": "38;5;255",
            "header": "1;38;5;255",
            "brand": "38;5;245",
            "success": "38;5;250",
            "warn": "38;5;249",
        },
        "curses": {"accent": 253, "project": 245, "amber": 249},
        "banner": ["#ffffff", "#808080"],
    },
    "rainbow": {
        "display_name": "Rainbow",
        "description": "Every color, still readable — enables chaos mode",
        "ansi": {
            "command": "38;5;201",  # hot magenta
            "arg": "38;5;51",  # cyan
            "header": "1;38;5;226",  # yellow (bold, dark-term safe)
            "brand": "38;5;165",  # violet
            "success": "38;5;46",  # lime
            "warn": "38;5;214",  # orange
        },
        "curses": {"accent": 201, "project": 51, "amber": 214},
        # Multi-stop gradient — RichFiglet accepts N colors and interpolates.
        "banner": ["#ff005f", "#ff8700", "#ffff00", "#00ff5f", "#00d7ff", "#af5fff"],
    },
}

# Roles whose styling is intentionally theme-invariant — dim text should
# always read as dim, and the version blurb is purposely low-contrast.
_STATIC_ANSI = {
    "dim": "2",
    "version": "2",  # faint only — lets terminal/p10k/iterm theme control the hue
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
    r2, g2, b2 = int(stops[i + 1][1:3], 16), int(stops[i + 1][3:5], 16), int(stops[i + 1][5:7], 16)
    r = int(r1 + (r2 - r1) * f)
    g = int(g1 + (g2 - g1) * f)
    b = int(b1 + (b2 - b1) * f)
    return f"#{r:02x}{g:02x}{b:02x}"


def _gradient_ansi(text: str, stops: list, *, bold: bool = False) -> str:
    """Render *text* with a per-character True Color ANSI gradient."""
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
    """Return the ANSI code for a logical role under the active theme."""
    if role in _STATIC_ANSI:
        return _STATIC_ANSI[role]
    theme = THEMES.get(get_current_theme(), THEMES[_DEFAULT_THEME])
    return theme["ansi"].get(role, "")


def _ansi_to_rich(code: str) -> str:
    """Translate one of altergo's ANSI color codes into a Rich style string."""
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
    spinner_override: str | None = None,
):
    """Print the altergo banner. TTY-only."""
    if not sys.stdout.isatty():
        suffix = f"  [{account}]" if account else ""
        print(f"  altergo {__version__}  —  Don't break flow. Switch accounts.{suffix}")
        return
    try:
        import pyfiglet
        from rich.align import Align
        from rich.console import Console, Group
        from rich.spinner import Spinner
        from rich.table import Table
        from rich.text import Text
        from rich_pyfiglet import RichFiglet

        console = Console()
        theme = THEMES.get(get_current_theme(), THEMES[_DEFAULT_THEME])
        theme_id = get_current_theme()
        grad = theme["banner"]
        _banner_font = load_persisted_banner_font()
        figlet = RichFiglet("altergo", font=_banner_font, colors=grad, horizontal=True)

        # Measure the logo upfront — used both for the version column width
        # (so the version sits right next to the figlet, not on the far edge
        # of the terminal) and for centering the account name underneath.
        rendered = pyfiglet.Figlet(font=_banner_font).renderText("altergo")
        logo_lines = [ln for ln in rendered.splitlines() if ln.strip()]
        logo_right = max((len(ln.rstrip()) for ln in logo_lines), default=32)

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
            BRIGHT = f"bold {grad[0]}"
            MID = grad[len(grad) // 2] if len(grad) > 2 else grad[0]

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
                    if spinner_override:
                        spinner_name = spinner_override
                    else:
                        try:
                            import altergo_greetings as _greet

                            spinner_name = _greet.spinner_for_theme(theme_id)
                        except Exception:
                            spinner_name = "dots"
                    from rich.padding import Padding

                    acct_inner = Table.grid(padding=(0, 0), expand=False)
                    acct_inner.add_column(no_wrap=True)
                    acct_inner.add_column(no_wrap=True)
                    acct_label = Text()
                    acct_label.append(f"  {account}", style=BRIGHT)
                    _email = _read_account_email(account)
                    if _email:
                        acct_label.append("  ", style=MID)
                        acct_label.append(_email, style=f"dim {MID}")
                    acct_inner.add_row(
                        Spinner(spinner_name, style=BRIGHT),
                        acct_label,
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
                    _email = _read_account_email(account)
                    if _email:
                        left_text.append("  ", style=MID)
                        left_text.append(_email, style=f"dim {MID}")
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

            with Live(group, console=console, refresh_per_second=12, transient=False):
                time.sleep(animate_duration)
        else:
            console.print(group)
    except Exception:
        suffix = f"  [{account}]" if account else ""
        print(f"  altergo {__version__}  —  Don't break flow. Switch accounts.{suffix}")


def show_help():
    """Print --help output in a two-column layout."""
    grad = THEMES.get(get_current_theme(), THEMES[_DEFAULT_THEME])["banner"]

    def h(t):
        return _gradient_ansi(t, grad, bold=True)

    def kw(t):
        return _c(C("command"), t)

    def arg(t):
        return _c(C("arg"), t)

    def dim(t):
        return _c(C("dim"), t)

    # layout constants
    # Each column is COL_W visible chars wide (content only, no divider space).
    # Description offset within a column: _COL2 chars from column start.
    # Minimum terminal width for two-column mode: MIN_W.
    COL_W = 56  # visible width per column
    _COL2 = 32  # description offset inside a column (raw cmd + padding)
    MIN_W = 118  # fall back to single-column below this

    # detect terminal width
    try:
        _tw = os.get_terminal_size().columns
    except OSError:
        _tw = 0
    two_col = sys.stdout.isatty() and _tw >= MIN_W

    # ── strip ANSI for visible-length calculation ──────────────────────────────
    _ansi_re = re.compile(r"\033(?:\[[^m]*m|\][^\033]*\033\\|[^[\\])")

    def _vis(s: str) -> int:
        return len(_ansi_re.sub("", s))

    # row builder (single column, COL_W wide)
    def row(raw: str, colored: str, description: str) -> str:
        pad = " " * max(1, _COL2 - 2 - _vis(colored))
        content = f"  {colored}{pad}{description}"
        # Pad to COL_W so the divider lines up regardless of description length
        vis = _vis(content)
        if vis < COL_W:
            content += " " * (COL_W - vis)
        return content

    # ── section-header builder ─────────────────────────────────────────────────
    def sec(title: str) -> str:
        content = f"  {h(title)}"
        vis = _vis(content)
        if vis < COL_W:
            content += " " * (COL_W - vis)
        return content

    # ── thin separator (single-column width) ──────────────────────────────────
    def sep_line() -> str:
        return _c(C("dim"), "  " + "─" * (COL_W - 2))

    # blank row padded to COL_W
    def blank() -> str:
        return " " * COL_W

    # section data
    # Each section is a list of (raw_cmd, colored_cmd, description) tuples,
    # or the sentinel string "" for a blank spacer row.
    SEC_LAUNCH = [
        ("altergo", kw("altergo"), "Open launcher / active account"),
        ("altergo <account>", f"{kw('altergo')} {arg('<account>')}", "Launch a named account"),
        (
            "altergo <account> <prov>",
            f"{kw('altergo')} {arg('<account>')} {arg('<prov>')}",
            "Launch with specific provider",
        ),
    ]
    SEC_ACCOUNTS = [
        ("altergo --config", kw("altergo --config"), "Create or reconfigure account"),
        (
            "altergo --config <account>",
            f"{kw('altergo --config')} {arg('<account>')}",
            "Create/reconfigure named account",
        ),
        (
            "altergo --rename <old> <new>",
            f"{kw('altergo --rename')} {arg('<old>')} {arg('<new>')}",
            "Rename an account",
        ),
        (
            "altergo --config --provider",
            f"{kw('altergo --config --provider')} {arg('<p>')}",
            "claude gemini codex copilot",
        ),
        ("altergo --use <account>", f"{kw('altergo --use')} {arg('<account>')}", "Set as default account"),
        ("altergo --teardown", f"{kw('altergo --teardown')} {arg('[--name <n>]')}", "Remove account + symlinks"),
        ("altergo --settings", kw("altergo --settings"), "Manage shared credentials"),
    ]
    SEC_MULTI_PROVIDER = [
        (
            "altergo <account> --add-provider",
            f"{kw('altergo')} {arg('<account>')} {kw('--add-provider')} {arg('<id>')}",
            "Add another provider to account",
        ),
        (
            "altergo <account> --remove-provider",
            f"{kw('altergo')} {arg('<account>')} {kw('--remove-provider')} {arg('<id>')}",
            "Remove a provider from account",
        ),
        (
            "altergo <account> --default-provider",
            f"{kw('altergo')} {arg('<account>')} {kw('--default-provider')} {arg('<id>')}",
            "Set default provider for account",
        ),
    ]
    SEC_SESSIONS = [
        ("altergo --recall", kw("altergo --recall"), "Pick session interactively"),
        ("altergo --resume", kw("altergo --resume"), "Provider's native resume"),
        ("altergo --resume <id>", f"{kw('altergo --resume')} {arg('<id>')}", "Resume by session ID"),
        ("altergo --search", kw("altergo --search"), "Search conversation history"),
        ("altergo --star", kw("altergo --star"), "Star the last session"),
        ("altergo --star <id>", f"{kw('altergo --star')} {arg('<id>')}", "Star a session by ID"),
    ]
    _portal = kw("portal")
    SEC_PORTAL = [
        ("altergo portal", f"{kw('altergo')} {_portal}", "Open portal, active account"),
        ("altergo portal <account>", f"{kw('altergo')} {_portal} {arg('<account>')}", "Open portal, named account"),
        (
            "altergo portal <account> <prov>",
            f"{kw('altergo')} {_portal} {arg('<account>')} {arg('<prov>')}",
            "Open portal, specific provider",
        ),
        (
            "altergo portal <account> --resume",
            f"{kw('altergo')} {_portal} {arg('<account>')} {kw('--resume')}",
            "Reconnect to last session",
        ),
        (
            "altergo portal <account> --resume <id>",
            f"{kw('altergo')} {_portal} {arg('<account>')} {kw('--resume')} {arg('<id>')}",
            "Reconnect specific session",
        ),
    ]
    SEC_CUSTOM = [
        ("altergo --theme", kw("altergo --theme"), "Show active theme"),
        (
            "altergo --theme <theme>",
            f"{kw('altergo --theme')} {arg('<theme>')}",
            f"Set theme  ({', '.join(THEMES.keys())})",
        ),
    ]
    SEC_ADVANCED = [
        ("altergo native", f"{kw('altergo')} {arg('native')}", "Launch real $HOME (no isolation)"),
        ("altergo native <prov>", f"{kw('altergo')} {arg('native')} {arg('<prov>')}", "Launch provider, real $HOME"),
        ("altergo <account> shell", f"{kw('altergo')} {arg('<account>')} {kw('shell')}", "Shell inside account HOME"),
        (
            "altergo <account> -- <cmd>",
            f"{kw('altergo')} {arg('<account>')} {kw('--')} {arg('<cmd>')}",
            "Run command in account context",
        ),
        ("altergo --yolo", kw("altergo --yolo"), "Skip all provider permission prompts"),
        ("altergo --yolo-resume", kw("altergo --yolo-resume"), "Skip prompts + resume last session"),
        (
            "altergo --yolo-resume <id>",
            f"{kw('altergo --yolo-resume')} {arg('<id>')}",
            "Skip prompts + resume a specific session",
        ),
    ]

    # render a section into a list of padded strings
    def render_sec(title: str, items) -> list:
        out = [sec(title)]
        for entry in items:
            if entry == "":
                out.append(blank())
            else:
                out.append(row(entry[0], entry[1], entry[2]))
        return out

    # build the two columns
    left_sections: list[list] = [
        render_sec("Launch", SEC_LAUNCH),
        render_sec("Accounts", SEC_ACCOUNTS),
        render_sec("Multi-provider", SEC_MULTI_PROVIDER),
        render_sec("Sessions", SEC_SESSIONS),
    ]
    right_sections: list[list] = [
        render_sec("Portal  ·  tmux-backed", SEC_PORTAL),
        render_sec("Customization", SEC_CUSTOM),
        render_sec("Advanced", SEC_ADVANCED),
    ]

    def _interleave_blank(sections: list[list]) -> list:
        """Join sections with a single blank row between them."""
        out: list = []
        for i, s in enumerate(sections):
            if i:
                out.append(blank())
            out.extend(s)
        return out

    left_rows = _interleave_blank(left_sections)
    right_rows = _interleave_blank(right_sections)

    # print header
    pixelabs = _link("https://pixelabs.net", _c(C("brand"), "pixelabs.net"))
    show_banner()
    print(f"  {dim('Because one personality was not causing enough bugs.')}")
    print(f"  A {pixelabs} project.\n")

    # ── single-column fallback ─────────────────────────────────────────────────
    if not two_col:

        def sep():
            return _c(C("dim"), "  " + "─" * 54)

        def row1(raw, colored, description):
            vis_cmd = _vis(f"  {colored}")
            pad = " " * max(2, 40 - vis_cmd)
            return f"  {colored}{pad}{description}"

        lines = []
        for title, items in [
            ("Launch", SEC_LAUNCH),
            ("Accounts", SEC_ACCOUNTS),
            ("Multi-provider", SEC_MULTI_PROVIDER),
            ("Sessions", SEC_SESSIONS),
            ("Portal  ·  tmux-backed, reconnect from anywhere", SEC_PORTAL),
            ("Customization", SEC_CUSTOM),
            ("Advanced", SEC_ADVANCED),
        ]:
            lines += ["", sep(), "  " + h(title)]
            for entry in items:
                lines.append(row1(entry[0], entry[1], entry[2]))
        lines += [
            "",
            dim("  altergo · open-source by pixelabs · not affiliated with Anthropic, Google, OpenAI, or GitHub"),
            "",
        ]
        print("\n".join(lines))
        return

    # ── two-column layout ──────────────────────────────────────────────────────
    # Pad the shorter column with blank rows so both are the same height.
    n_left = len(left_rows)
    n_right = len(right_rows)
    n_rows = max(n_left, n_right)
    left_rows += [blank()] * (n_rows - n_left)
    right_rows += [blank()] * (n_rows - n_right)

    _div_char = _c(C("dim"), "│")

    # Pad every left row to the widest left row so the divider column is
    # straight even when individual rows exceed COL_W.
    left_width = max(_vis(L) for L in left_rows)

    output_lines = []
    for L, R in zip(left_rows, right_rows):
        gap = left_width - _vis(L)
        output_lines.append(f"{L}{' ' * gap} {_div_char} {R}")

    print("\n".join(output_lines))

    # Footer
    print()
    print(dim("  altergo · open-source by pixelabs · not affiliated with Anthropic, Google, OpenAI, or GitHub"))
    print()


# Config

# Resolve the real home even if HOME is overridden (e.g., running as altergo)
_pw_home = Path(pwd.getpwuid(os.getuid()).pw_dir)
if not _pw_home.exists():
    _pw_home = Path(os.environ["HOME"])

MAIN_HOME = _pw_home
MAIN_CLAUDE = MAIN_HOME / ".claude"
ACCOUNTS_DIR = MAIN_HOME / ".altergo" / "accounts"

# The "native" account launches the provider with the real $HOME unchanged —
# no HOME isolation, no altergo-managed dot-dirs.  Useful when the user's
# real home already has a provider installed (e.g. the claude they normally
# use) and they want to reach it from altergo (e.g. via portal/tmux).
_NATIVE_ACCOUNT = "native"

# Reserved account names — blocked at --config time
_RESERVED_NAMES = frozenset(
    [
        "main",
        "list",
        "new",
        "rm",
        "shell",
        "config",
        "setup",
        "teardown",
        "help",
        "version",
        "legacy",
        "backup",
        "migrate",
        "use",
        "native",
    ]
)

# Settings file — global (shared across all accounts)
SETTINGS_FILE = MAIN_HOME / ".altergo" / ".altergo.json"

# Starred conversations — separate from main config
STARRED_FILE = MAIN_HOME / ".altergo" / "starred.json"

# Last exited session — written after each provider subprocess exits
LAST_SESSION_FILE = MAIN_HOME / ".altergo" / "last_session.json"

# Account helpers


def resolve_account(name: str) -> tuple:
    """Return (account_home, account_claude) for the given account name."""
    if name == _NATIVE_ACCOUNT:
        return MAIN_HOME, MAIN_CLAUDE
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


# Migration

# Symlink catalogs

# Directories to symlink (shared between main and alt)
SYMLINK_DIRS = [
    "projects",
    "tasks",
    "session-env",
    "file-history",
    "shell-snapshots",
    "agents",
    "commands",
    "skills",
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
            "projects",
            "tasks",
            "session-env",
            "file-history",
            "shell-snapshots",
            "agents",
            "commands",
            "skills",
            "plans",
            "cache",
        ],
        "symlink_files": ["settings.json", "CLAUDE.md", "keybindings.json"],
        # .claude.json is intentionally NOT in symlink_home_files — it is managed
        # by _sync_claude_mcps which does a bidirectional MCP merge while keeping
        # per-account oauthAccount metadata isolated.
        "flags": {
            "skip_perms": ["--dangerously-skip-permissions"],
            "resume_last": ["--continue"],
            "resume_by_id": ["--resume", "{id}"],
        },
    },
    "gemini": {
        "display_name": "Gemini CLI",
        "dot_dir": ".gemini",
        "binary": "gemini",
        "credentials_file": "oauth_creds.json",
        "symlink_dirs": ["tmp", "commands"],
        "symlink_files": ["settings.json", "GEMINI.md"],
        "flags": {
            "skip_perms": ["--yolo"],
            "resume_last": ["--resume", "latest"],
            "resume_by_id": ["--resume", "{id}"],
        },
    },
    "codex": {
        "display_name": "Codex CLI",
        "dot_dir": ".codex",
        "binary": "codex",
        "credentials_file": "auth.json",
        "symlink_dirs": ["sessions", "rules"],
        "symlink_files": ["config.toml", "AGENTS.md", "AGENTS.override.md"],
        "flags": {
            "skip_perms": ["--dangerously-bypass-approvals-and-sandbox"],
            # resume_last is a subcommand, handled specially in launch_claude
            "resume_subcommand": ["resume", "--last"],
            # resume-by-id is also a subcommand: `codex resume <ID>`
            "resume_by_id_subcommand": ["resume", "{id}"],
        },
    },
    "copilot": {
        "display_name": "GitHub Copilot",
        "dot_dir": ".copilot",
        "binary": "copilot",
        "credentials_file": "config.json",
        "symlink_dirs": ["session-state", "agents", "skills", "hooks"],
        "symlink_files": ["mcp-config.json", "lsp-config.json"],
        "flags": {
            "skip_perms": ["--yolo", "--autopilot"],
            "resume_last": ["--continue"],
            # copilot CLI: `copilot --resume <SESSION-ID>` jumps to a specific session.
            # Source: GitHub Copilot CLI docs (docs.github.com/en/copilot/how-tos/copilot-cli/chronicle).
            "resume_by_id": ["--resume", "{id}"],
        },
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
    {
        "id": "pip",
        "name": "pip (Python)",
        "category": "Package Managers",
        "paths": [".pip", ".config/pip", ".pypirc", ".local/lib", ".local/bin"],
        "default_on": False,
        "warning": "Shares pip config, PyPI credentials, and user-installed packages/scripts (~/.local/lib & bin).",
    },
    {
        "id": "cargo",
        "name": "cargo (Rust)",
        "category": "Package Managers",
        "paths": [".cargo"],
        "default_on": False,
        "warning": "Shares the entire ~/.cargo dir: registry cache, installed binaries, and credentials.",
    },
    {
        "id": "gem",
        "name": "gem (Ruby)",
        "category": "Package Managers",
        "paths": [".gem", ".gemrc"],
        "default_on": False,
    },
    {
        "id": "yarn",
        "name": "yarn",
        "category": "Package Managers",
        "paths": [".yarn", ".yarnrc.yml", ".yarnrc"],
        "default_on": False,
    },
    {
        "id": "pnpm",
        "name": "pnpm",
        "category": "Package Managers",
        "paths": [".pnpmrc", ".local/share/pnpm"],
        "default_on": False,
    },
    {
        "id": "composer",
        "name": "composer (PHP)",
        "category": "Package Managers",
        "paths": [".composer"],
        "default_on": False,
        "warning": "Shares Composer auth tokens, config, and globally installed packages.",
    },
    {
        "id": "go",
        "name": "go modules",
        "category": "Package Managers",
        "paths": ["go", ".config/go"],
        "default_on": False,
        "warning": "Shares the Go module cache (~/go) and go env config. Can be large.",
    },
    {
        "id": "maven",
        "name": "Maven (Java)",
        "category": "Package Managers",
        "paths": [".m2"],
        "default_on": False,
        "warning": "Shares the ~/.m2 directory including settings.xml credentials and local repo cache.",
    },
    {
        "id": "gradle",
        "name": "Gradle (Java)",
        "category": "Package Managers",
        "paths": [".gradle"],
        "default_on": False,
    },
    {
        "id": "bundler",
        "name": "Bundler (Ruby)",
        "category": "Package Managers",
        "paths": [".bundle"],
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

# Settings helpers


def load_account_meta(account_home: Path) -> dict:
    """Load account metadata. Returns v3-shape dict in memory regardless of on-disk form."""
    meta_file = account_home / "account.json"
    if meta_file.exists():
        try:
            data = json.loads(meta_file.read_text())
        except Exception:
            return _coerce_meta_v3({})
        return _coerce_meta_v3(data)
    if (account_home / ".claude").exists():
        return _coerce_meta_v3({"provider": "claude"})
    return None


def _coerce_meta_v3(data: dict) -> dict:
    """Return a v3-shape dict from v2 single-string or v3 list input."""
    out: dict = {k: v for k, v in data.items() if k not in ("version", "provider", "providers", "default_provider")}
    if data.get("version") == 3 and isinstance(data.get("providers"), list) and data["providers"]:
        seen: set[str] = set()
        providers: list[str] = []
        for p in data["providers"]:
            if isinstance(p, str) and p in PROVIDERS and p not in seen:
                seen.add(p)
                providers.append(p)
        if not providers:
            providers = ["claude"]
        default = data.get("default_provider")
        if not isinstance(default, str) or default not in providers:
            default = providers[0]
    else:
        provider = data.get("provider") if isinstance(data.get("provider"), str) else "claude"
        if provider not in PROVIDERS:
            provider = "claude"
        providers = [provider]
        default = provider
    out["version"] = 3
    out["providers"] = providers
    out["default_provider"] = default
    return out


def _read_account_email(account_name: str) -> str | None:
    """Return the email address for *account_name*, or None if unavailable."""
    try:
        account_home = ACCOUNTS_DIR / account_name
        # Claude: oauthAccount.emailAddress in .claude.json
        claude_json = account_home / ".claude.json"
        if claude_json.exists():
            data = json.loads(claude_json.read_text())
            email = data.get("oauthAccount", {}).get("emailAddress")
            if email and isinstance(email, str) and "@" in email:
                return email
        # Codex / OpenAI: email claim inside the id_token JWT in auth.json
        codex_auth = account_home / ".codex" / "auth.json"
        if codex_auth.exists():
            import base64

            auth = json.loads(codex_auth.read_text())
            id_token = auth.get("tokens", {}).get("id_token", "")
            if id_token:
                parts = id_token.split(".")
                if len(parts) >= 2:
                    padding = (-len(parts[1])) % 4
                    payload = json.loads(base64.urlsafe_b64decode(parts[1] + "=" * padding))
                    email = payload.get("email")
                    if email and isinstance(email, str) and "@" in email:
                        return email
        # Gemini: id_token in oauth_creds.json (same JWT pattern)
        gemini_creds = account_home / ".gemini" / "oauth_creds.json"
        if gemini_creds.exists():
            import base64

            creds = json.loads(gemini_creds.read_text())
            id_token = creds.get("id_token", "")
            if id_token:
                parts = id_token.split(".")
                if len(parts) >= 2:
                    padding = (-len(parts[1])) % 4
                    payload = json.loads(base64.urlsafe_b64decode(parts[1] + "=" * padding))
                    email = payload.get("email")
                    if email and isinstance(email, str) and "@" in email:
                        return email
    except Exception:
        pass
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


# Starred conversations


def load_starred_entries() -> list:
    """Return the full list of starred session entry dicts."""
    if not STARRED_FILE.exists():
        return []
    try:
        data = json.loads(STARRED_FILE.read_text())
        return [e for e in data.get("starred", []) if isinstance(e.get("id"), str)]
    except Exception:
        return []


def load_starred_ids() -> set:
    """Return the set of starred session IDs (cheap for membership tests)."""
    return {e["id"] for e in load_starred_entries()}


def _save_starred(entries: list) -> None:
    """Atomically persist starred entries to STARRED_FILE."""
    STARRED_FILE.parent.mkdir(parents=True, exist_ok=True)
    data = {"version": 1, "starred": entries}
    tmp = STARRED_FILE.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(data, indent=2))
    os.replace(str(tmp), str(STARRED_FILE))


def star_session(session_id: str, provider: str, project: str, topic: str) -> None:
    """Add a session to the starred list (no-op if already starred)."""
    entries = load_starred_entries()
    if any(e["id"] == session_id for e in entries):
        return
    entries.append(
        {
            "id": session_id,
            "provider": provider,
            "project": project,
            "topic": topic or "",
            "starred_at": datetime.now().isoformat(timespec="seconds"),
        }
    )
    _save_starred(entries)


def unstar_session(session_id: str) -> None:
    """Remove a session from the starred list."""
    _save_starred([e for e in load_starred_entries() if e["id"] != session_id])


def toggle_starred_session(session_id: str, provider: str, project: str, topic: str) -> bool:
    """Toggle star on a session. Returns True if now starred, False if now unstarred."""
    entries = load_starred_entries()
    if any(e["id"] == session_id for e in entries):
        _save_starred([e for e in entries if e["id"] != session_id])
        return False
    entries.append(
        {
            "id": session_id,
            "provider": provider,
            "project": project,
            "topic": topic or "",
            "starred_at": datetime.now().isoformat(timespec="seconds"),
        }
    )
    _save_starred(entries)
    return True


# --- Last-session tracking ---


def save_last_session(session_id: str, provider: str, project: str, topic: str) -> None:
    """Persist the last exited session info for ``altergo --star`` to read."""
    data = {
        "id": session_id,
        "provider": provider,
        "project": project,
        "topic": topic or "",
        "timestamp": datetime.now().isoformat(timespec="seconds"),
    }
    LAST_SESSION_FILE.parent.mkdir(parents=True, exist_ok=True)
    tmp = LAST_SESSION_FILE.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(data, indent=2))
    os.replace(str(tmp), str(LAST_SESSION_FILE))


def load_last_session() -> dict | None:
    """Return the last exited session dict, or None if unavailable."""
    if not LAST_SESSION_FILE.exists():
        return None
    try:
        return json.loads(LAST_SESSION_FILE.read_text())
    except Exception:
        return None


def _record_last_session_after_exit(provider: str, launch_time: float) -> None:
    """Scan for the newest JSONL session file and write it to LAST_SESSION_FILE."""
    projects_dir = MAIN_CLAUDE / "projects"
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


def load_persisted_theme() -> str:
    """Read the persisted theme name from SETTINGS_FILE."""
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


# Banner font

# Curated list of pyfiglet fonts that look good in a terminal banner.
# Filtered at runtime to those actually available in the installed pyfiglet
# *and* that render "altergo" in ≤ 5 non-empty rows.
_BANNER_FONT_CATALOG: list[str] = [
    "smslant",  # default — clean italic, 5 rows
    "shadow",  # soft outline, very legible, 5 rows
    "small",  # compact upright, good for narrow terminals, 5 rows
    "thin",  # delicate line art, 5 rows (used in onboarding)
    "chunky",  # bold blocky, strong presence, 5 rows
    "avatar",  # clean slightly condensed, 5 rows
    "trek",  # retro sci-fi, 5 rows
    "rowancap",  # elegant wide, 5 rows
    "elite",  # block-shade half-block chars, 5 rows
    "smblock",  # compact block art, 4 rows
    "double",  # double-line ASCII, 4 rows
    "bulbhead",  # rounded uppercase, 4 rows
    "tombstone",  # western-flavored, 4 rows
    "calvin_s",  # box-drawing chars, 3 rows
    "future",  # box-drawing variant, 3 rows
    "digital",  # +-+-+ geometric, 3 rows
    "pagga",  # block-shade, solid, 3 rows
]

_DEFAULT_BANNER_FONT = "smslant"

# Lazily populated by _get_valid_banner_fonts() — avoids importing pyfiglet
# at module load time.
_valid_banner_fonts_cache: list[str] | None = None


def _get_valid_banner_fonts() -> list[str]:
    """Return the subset of _BANNER_FONT_CATALOG that is available and ≤5 rows."""
    global _valid_banner_fonts_cache
    if _valid_banner_fonts_cache is not None:
        return _valid_banner_fonts_cache
    try:
        import pyfiglet

        available = set(pyfiglet.FigletFont.getFonts())
        valid = []
        for font_name in _BANNER_FONT_CATALOG:
            if font_name not in available:
                continue
            try:
                rendered = pyfiglet.Figlet(font=font_name).renderText("altergo")
                rows = len([ln for ln in rendered.splitlines() if ln.strip()])
                if rows <= 5:
                    valid.append(font_name)
            except Exception:
                pass
        _valid_banner_fonts_cache = valid if valid else [_DEFAULT_BANNER_FONT]
    except Exception:
        _valid_banner_fonts_cache = [_DEFAULT_BANNER_FONT]
    return _valid_banner_fonts_cache


def load_persisted_banner_font() -> str:
    """Read the banner font name from SETTINGS_FILE. Falls back to the default."""
    if not SETTINGS_FILE.exists():
        return _DEFAULT_BANNER_FONT
    try:
        data = json.loads(SETTINGS_FILE.read_text())
        font = data.get("banner_font")
        if isinstance(font, str) and font in _BANNER_FONT_CATALOG:
            return font
    except Exception:
        pass
    return _DEFAULT_BANNER_FONT


def save_persisted_banner_font(name: str) -> None:
    """Persist the chosen banner font to SETTINGS_FILE."""
    if name not in _BANNER_FONT_CATALOG:
        return
    _patch_settings({"banner_font": name})


# Animation packs

# Each pack drives the twinkle duration and spinner style for the provider
# handoff animation. "off" disables animation entirely.
_ANIM_PACKS: dict[str, dict] = {
    "off": {"duration": 0.0, "spinner": None, "label": "Off", "hint": "No animation — instant launch"},  # noqa: E501
    "minimal": {"duration": 0.4, "spinner": None, "label": "Minimal", "hint": "Brief star pulse, quiet and fast"},  # noqa: E501
    "smooth": {
        "duration": 0.7,
        "spinner": "boxBounce2",
        "label": "Smooth",
        "hint": "Fat block sweeping around a rectangle",
    },  # noqa: E501
    "retro": {"duration": 0.5, "spinner": "line", "label": "Retro", "hint": "Classic |/-\\ spinner, quick twinkle"},  # noqa: E501
    "wave": {
        "duration": 0.6,
        "spinner": "growVertical",
        "label": "Wave",
        "hint": "Growing vertical bars — rise and fall",
    },  # noqa: E501
    "orbit": {"duration": 0.6, "spinner": "arc", "label": "Orbit", "hint": "Smooth arc rotation — elegant and calm"},  # noqa: E501
    "pulse": {"duration": 0.8, "spinner": "dots", "label": "Pulse", "hint": "Soft braille dots — gentle and focused"},  # noqa: E501
    "matrix": {"duration": 0.9, "spinner": "noise", "label": "Matrix", "hint": "Block-fill noise — deep focus mode"},  # noqa: E501
}
_VALID_ANIM_PACKS: tuple[str, ...] = tuple(_ANIM_PACKS.keys())
_DEFAULT_ANIM_PACK = "minimal"


# Cache for Rich spinner registry (frames + intervals)
_RICH_SPINNER_DATA_CACHE: dict | None = None


def _get_rich_spinner_data() -> dict:
    """Return Rich's SPINNERS registry, cached after first call."""
    global _RICH_SPINNER_DATA_CACHE
    if _RICH_SPINNER_DATA_CACHE is None:
        try:
            from rich._spinners import SPINNERS as _RS  # type: ignore[import-untyped]

            _RICH_SPINNER_DATA_CACHE = _RS
        except Exception:
            _RICH_SPINNER_DATA_CACHE = {}
    return _RICH_SPINNER_DATA_CACHE


def load_animation_pack() -> str:
    """Return the active animation pack name."""
    if not SETTINGS_FILE.exists():
        return _DEFAULT_ANIM_PACK
    try:
        data = json.loads(SETTINGS_FILE.read_text())
        pack = data.get("animation_pack")
        if isinstance(pack, str) and pack in _VALID_ANIM_PACKS:
            return pack
        # Migrate from old boolean key
        la = data.get("launch_animation")
        if la is False:
            return "off"
    except Exception:
        pass
    return _DEFAULT_ANIM_PACK


# Random theme helpers


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
        freq = data.get("random_theme_frequency")
        ctr = data.get("random_theme_counter")
        return {
            "random_theme_enabled": enabled if isinstance(enabled, bool) else False,
            "random_theme_frequency": freq if isinstance(freq, int) and 1 <= freq <= 5 else 3,
            "random_theme_counter": ctr if isinstance(ctr, int) and ctr >= 0 else 0,
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
    """Decrement the random-theme counter; rotate theme when it hits zero."""
    import random as _random

    rts = load_random_theme_settings()
    if not rts["random_theme_enabled"]:
        return

    freq = rts["random_theme_frequency"]
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
    "claude": 0.7,
    "gemini": 0.7,
    "copilot": 0.7,
    "codex": 0.0,
}


def _handoff_duration(provider: str | None) -> float:
    """Return the capped twinkle duration for the given provider id."""
    if provider is None:
        return 0.0
    return _HANDOFF_ANIM_SECONDS.get(provider, 0.0)


def _status_wrap(message: str, func, *args, **kwargs):
    """Call ``func`` while showing a Rich spinner-status line."""
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


# Update check: settings, cache, fetch
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
    """Return ``v`` if it is a valid, printable version string, else None."""
    if not isinstance(v, str):
        return None
    if _VERSION_RE.match(v):
        return v
    return None


def load_update_check_enabled() -> bool:
    """Return whether the user has opted into update checks."""
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
    """Load a boolean setting from SETTINGS_FILE."""
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
    """Read and validate the update cache. Returns {} on any error."""
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
    """Parse a MAJOR.MINOR.PATCH string into a comparable tuple."""
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


# Session IDs as produced by Claude Code, Gemini CLI, Codex, and Copilot are
# all canonical UUIDs. We match case-insensitively and allow an optional
# surrounding = sign from the --yolo-resume=ID form (handled before this regex
# is consulted). Kept loose-ish to tolerate any future provider that emits a
# UUID-shaped token; we deliberately do NOT accept arbitrary strings, so that
# "altergo --yolo-resume 'write me a poem'" still sends the poem as a prompt.
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
            # Consume next arg as ID only if it actually looks like one.
            if i + 1 < len(args) and _looks_like_session_id(args[i + 1]):
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

    prov_flags = PROVIDERS.get(provider, {}).get("flags", {})
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
            display = PROVIDERS.get(provider, {}).get("display_name", provider)
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


def _fetch_latest_version() -> None:
    """Fetch altergo's latest version from PyPI and update the cache."""
    try:
        import urllib.error
        import urllib.request

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
    """Kick off a background refresh if the cache is stale and opt-in is on."""
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
    """Print the one-time consent notice if the user hasn't seen it yet."""
    if _get_intro_shown():
        return
    _mark_intro_shown()


def _get_home_notice_shown() -> bool:
    if not SETTINGS_FILE.exists():
        return False
    try:
        data = json.loads(SETTINGS_FILE.read_text())
        return bool(data.get("home_notice_shown"))
    except Exception:
        return False


def _mark_home_notice_shown() -> None:
    SETTINGS_FILE.parent.mkdir(parents=True, exist_ok=True)
    data = {}
    if SETTINGS_FILE.exists():
        try:
            data = json.loads(SETTINGS_FILE.read_text())
        except Exception:
            data = {}
    data["home_notice_shown"] = True
    tmp = SETTINGS_FILE.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(data, indent=2))
    os.replace(str(tmp), str(SETTINGS_FILE))


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
    if not SETTINGS_FILE.exists():
        return None
    try:
        data = json.loads(SETTINGS_FILE.read_text())
        name = data.get("active_account")
        if name and isinstance(name, str):
            if name == _NATIVE_ACCOUNT:
                return name
            if (ACCOUNTS_DIR / name).is_dir():
                return name
        return None
    except Exception:
        return None


def _account_for_provider(provider_id: str) -> str | None:
    """Return an account name suitable for launching sessions of ``provider_id``."""
    accounts = list_accounts()
    if not accounts:
        return None

    def _has_provider(acct_name: str) -> bool:
        meta = load_account_meta(ACCOUNTS_DIR / acct_name)
        if meta is None:
            return provider_id == "claude"
        return provider_id in meta["providers"]

    active = get_active_account()
    if active and active in accounts and _has_provider(active):
        return active
    for acct in accounts:
        if _has_provider(acct):
            return acct
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
    enabled = _is_enabled(entry, overrides)
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


# Config / Teardown


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
    main_cfg = MAIN_HOME / ".claude.json"
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
        # Look the session up in the live session list so we have full metadata.
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
    prov = PROVIDERS.get(provider_id)
    if prov is None:
        raise ValueError(f"unknown provider id: {provider_id!r}")

    main_dot_dir = MAIN_HOME / prov["dot_dir"]
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
        _ensure_home_file_symlink(name, MAIN_HOME / name, account_home / name)

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
    prov = PROVIDERS.get(provider_id)
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
        src = MAIN_HOME / name
        try:
            if dst.is_symlink() and dst.resolve() == src.resolve():
                dst.unlink()
                if not silent:
                    print(f"  {_c(33, '✓')} Removed symlink: {name}")
        except OSError:
            pass


def do_config(account: str = "default", provider: str = "claude", *, keychain_arg: str | None = None):
    """Configure (or reconfigure) an altergo account."""
    if account == _NATIVE_ACCOUNT:
        print(
            f"altergo: '{_NATIVE_ACCOUNT}' is a reserved passthrough account that uses the real $HOME. "
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
        current_kc = (meta or {}).get("keychain", "system")
        label = "isolated" if current_kc == "isolated" else "system (default)"
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
        for entry in CATALOG:
            _apply_entry(entry, overrides, account_home)

    _status_wrap("Linking shared credentials…", _apply_catalog_entries)

    # 5. Keychain isolation (macOS only, opt-in)
    keychain_mode = "system"  # default: no isolation
    if sys.platform == "darwin":
        if keychain_arg is not None:
            # Non-interactive: honour explicit flag from CLI.
            keychain_mode = keychain_arg
        elif meta and meta.get("keychain") == "isolated":
            # Re-config of an existing isolated account — keep isolation by default.
            keychain_mode = "isolated"
        elif sys.stdin.isatty():
            # Interactive prompt — default No.
            print()
            print(_c(C("header"), "  Keychain isolation (macOS)"))
            print(_c(2, "  Isolate this account's AI-provider tokens in a per-account macOS keychain."))
            try:
                answer = input("  Keychain isolation? [y/N] ").strip().lower()
            except (KeyboardInterrupt, EOFError):
                answer = ""
            keychain_mode = "isolated" if answer in ("y", "yes") else "system"

        # Repair any pre-existing drift before applying the user's intent.
        # desired=None is cheap when state is consistent (no security calls).
        try:
            _reconcile_keychain_state(account_home, account, desired=None)
            # Reload meta in case the reconciler updated A.
            meta = load_account_meta(account_home)
        except KeychainError as e:
            print(f"  {_c(33, '⚠')} Keychain reconcile warning: {e}", file=sys.stderr)

        if keychain_mode == "isolated":
            # §4.4 pre-flight write: stamp A="isolated" before touching B/C/D.
            # If the process crashes mid-create, the reconciler on next launch
            # sees A=isolated and re-enters the create path.  The confirm-write
            # below (save_account_meta) is idempotent.
            _preflight_meta = dict(meta) if meta else {}
            _preflight_meta["keychain"] = "isolated"
            save_account_meta(account_home, _preflight_meta)
            try:
                _create_account_keychain(account_home, account)
            except KeychainError as e:
                print(f"  {_c(33, '⚠')} Keychain setup failed: {e}", file=sys.stderr)
                print("    Continuing with system keychain.", file=sys.stderr)
                keychain_mode = "system"
            else:
                print(f"  {_c(32, '✓')} Per-account keychain created/verified")
                print(
                    _c(
                        2,
                        "  NOTE: keychain isolation requires your login keychain to be unlocked "
                        "(standard on GUI login; check Keychain Access → Preferences if auto-lock is aggressive)",
                    )
                )

    # Downgrade: if the account was previously isolated but is now moving to
    # system mode, remove only the routing plist so Security.framework falls
    # back to the real user's keychain.  The keychain file and unlock entry are
    # preserved so a re-upgrade can reuse them without losing stored tokens.
    # Gate on B (plist present) OR A (meta says isolated) so a crash between
    # A-write and B-write (state #1) is healed on the next --config system run.
    if keychain_mode == "system" and (
        _keychain_prefs_path(account_home).exists() or (meta or {}).get("keychain") == "isolated"
    ):
        _keychain_prefs_path(account_home).unlink(missing_ok=True)
        print(_c(2, "  Keychain set to system (per-account keychain preserved for re-enable)"))

    # 4. Save account metadata.  New writes emit v3 (providers list + default).
    #    Existing v3 accounts preserve extra providers beyond the single one
    #    passed into do_config — do_config only rewrites the default.
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
    # Legacy files without the key continue to work: _is_keychain_isolated treats
    # anything != "isolated" as system, so absent → system is preserved until the
    # next --config normalises it here.  (Invariant §5.1)
    meta_to_save["keychain"] = "isolated" if keychain_mode == "isolated" else "system"
    save_account_meta(account_home, meta_to_save)

    launch_cmd = f"altergo {account}" if account != "default" else "altergo"
    print()
    print(_c(32, "Config complete!"))
    print(f"  Run {_c(1, launch_cmd)} to start a session  ·  {_c(1, 'altergo --resume')} to pick one")
    print()
    print(_c(2, "  Isolates credentials per provider. Shares AWS, GCP, Docker, and kubectl by default."))
    print(_c(2, f"  Change sharing settings: {_c(0, 'altergo --settings')}"))


def _reconcile_orphan_dot_dir(account_home: Path, provider_id: str) -> None:
    """Merge SHAREABLE orphan data from an account-local provider dot-dir into MAIN_HOME."""
    prov = PROVIDERS.get(provider_id)
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

    main_dot = MAIN_HOME / prov["dot_dir"]
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
    if account == _NATIVE_ACCOUNT:
        print(
            f"altergo: '{_NATIVE_ACCOUNT}' is a reserved passthrough account — there is nothing to tear down.",
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


def do_delete_account(account: str) -> bool:
    """Fully delete an account: tear down symlinks, remove the home dir, clear active."""
    if account == _NATIVE_ACCOUNT:
        print(
            f"altergo: '{_NATIVE_ACCOUNT}' is a reserved passthrough account — it cannot be deleted.",
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
            if SETTINGS_FILE.exists():
                data = json.loads(SETTINGS_FILE.read_text())
                if data.get("active_account") == account:
                    data.pop("active_account", None)
                    tmp = SETTINGS_FILE.with_suffix(".json.tmp")
                    tmp.write_text(json.dumps(data, indent=2))
                    os.replace(str(tmp), str(SETTINGS_FILE))
                    print(f"  {_c(33, '✓')} Cleared active-account pointer")
        except Exception:
            pass

    print()
    print(_c(32, f"Account '{account}' deleted."))
    return True


def do_rename(old_name: str, new_name: str):
    old_home = ACCOUNTS_DIR / old_name
    new_home = ACCOUNTS_DIR / new_name
    if not old_home.is_dir():
        print(f"altergo: account '{old_name}' not found.", file=sys.stderr)
        sys.exit(1)
    validate_account_name(new_name)
    if new_home.exists():
        print(f"altergo: account '{new_name}' already exists.", file=sys.stderr)
        sys.exit(1)
    old_home.rename(new_home)
    print(f"  {_c(32, '✓')} Renamed account '{old_name}' → '{new_name}'")


# Session Discovery


def _build_provider_map() -> dict:
    """Return a dict mapping session JSONL path → provider id string."""
    path_to_provider: dict = {}
    if not ACCOUNTS_DIR.exists():
        return path_to_provider

    for acct_name in list_accounts():
        acct_home = ACCOUNTS_DIR / acct_name
        meta = load_account_meta(acct_home)
        provider_ids = meta["providers"] if meta is not None else ["claude"]

        for provider_id in provider_ids:
            prov = PROVIDERS.get(provider_id)
            if prov is None:
                continue
            acct_projects = acct_home / prov["dot_dir"] / "projects"
            try:
                resolved_projects = acct_projects.resolve()
            except OSError:
                continue
            if not resolved_projects.is_dir():
                continue

            try:
                for proj_dir in resolved_projects.iterdir():
                    if not proj_dir.is_dir():
                        continue
                    try:
                        for sf in proj_dir.iterdir():
                            if sf.suffix == ".jsonl":
                                try:
                                    path_to_provider[sf.resolve()] = provider_id
                                except OSError:
                                    pass
                    except OSError:
                        continue
            except OSError:
                continue

    return path_to_provider


# Per-provider session discoverers

_CODEX_TOPIC_SENTINELS = ("<permissions ", "<collaboration_mode>", "<skills_instructions>")


def _discover_claude_sessions(starred_ids: set) -> list:
    """Yield session dicts for Claude Code (~/.claude/projects/*/*.jsonl)."""
    sessions = []
    projects_dir = MAIN_CLAUDE / "projects"
    if not projects_dir.exists():
        return sessions

    provider_map = _build_provider_map()

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
            try:
                resolved_path = f.resolve()
            except OSError:
                resolved_path = f
            provider_id = provider_map.get(resolved_path, "claude")
            sessions.append(
                {
                    "id": session_id,
                    "project": project_name,
                    "cwd": cwd,
                    "modified": mod_dt,
                    "size_mb": size_mb,
                    "path": f,
                    "topic": topic,
                    "provider": provider_id,
                    "starred": session_id in starred_ids,
                }
            )
    return sessions


def _discover_codex_sessions(starred_ids: set) -> list:
    """Yield session dicts for Codex CLI (~/.codex/sessions/YYYY/MM/DD/*.jsonl)."""
    sessions = []
    codex_sessions_dir = MAIN_HOME / ".codex" / "sessions"
    if not codex_sessions_dir.exists():
        return sessions

    # Walk YYYY/MM/DD sub-directories
    try:
        year_dirs = sorted(codex_sessions_dir.iterdir())
    except OSError:
        return sessions

    for year_dir in year_dirs:
        if not year_dir.is_dir():
            continue
        try:
            month_dirs = sorted(year_dir.iterdir())
        except OSError:
            continue
        for month_dir in month_dirs:
            if not month_dir.is_dir():
                continue
            try:
                day_dirs = sorted(month_dir.iterdir())
            except OSError:
                continue
            for day_dir in day_dirs:
                if not day_dir.is_dir():
                    continue
                try:
                    files = list(day_dir.iterdir())
                except OSError:
                    continue
                for f in files:
                    if f.suffix != ".jsonl":
                        continue
                    try:
                        st = f.stat()
                    except OSError:
                        continue
                    mod_dt = datetime.fromtimestamp(st.st_mtime)
                    size_mb = st.st_size / (1024 * 1024)
                    session_id, topic, cwd = _scan_codex_session_head(f)
                    if not session_id:
                        # Fall back to filename stem UUID portion
                        session_id = f.stem
                    project = cwd.rstrip("/").rsplit("/", 1)[-1] if cwd else f.stem
                    sessions.append(
                        {
                            "id": session_id,
                            "project": project,
                            "cwd": cwd,
                            "modified": mod_dt,
                            "size_mb": size_mb,
                            "path": f,
                            "topic": topic,
                            "provider": "codex",
                            "starred": session_id in starred_ids,
                        }
                    )
    return sessions


def _discover_gemini_sessions(starred_ids: set) -> list:
    """Yield session dicts for Gemini CLI (~/.gemini/tmp/<proj>/chats/*.json)."""
    sessions = []
    gemini_tmp_dir = MAIN_HOME / ".gemini" / "tmp"
    if not gemini_tmp_dir.exists():
        return sessions

    try:
        proj_dirs = list(gemini_tmp_dir.iterdir())
    except OSError:
        return sessions

    for proj_dir in proj_dirs:
        if not proj_dir.is_dir():
            continue
        chats_dir = proj_dir / "chats"
        if not chats_dir.is_dir():
            continue

        # Try to read the canonical project root from .project_root sentinel file
        project_root_file = proj_dir / ".project_root"
        cwd_base = ""
        if project_root_file.is_file():
            try:
                cwd_base = project_root_file.read_text(encoding="utf-8").strip()
            except OSError:
                pass
        if not cwd_base:
            cwd_base = proj_dir.name  # dirname as fallback (relative hint)

        project_label = proj_dir.name

        try:
            chat_files = list(chats_dir.iterdir())
        except OSError:
            continue

        for f in chat_files:
            if f.suffix != ".json":
                continue
            try:
                st = f.stat()
            except OSError:
                continue
            mod_dt = datetime.fromtimestamp(st.st_mtime)
            size_mb = st.st_size / (1024 * 1024)
            session_id, topic, cwd = _scan_gemini_session(f, cwd_base)
            if not session_id:
                session_id = f.stem
            sessions.append(
                {
                    "id": session_id,
                    "project": project_label,
                    "cwd": cwd or cwd_base,
                    "modified": mod_dt,
                    "size_mb": size_mb,
                    "path": f,
                    "topic": topic,
                    "provider": "gemini",
                    "starred": session_id in starred_ids,
                }
            )
    return sessions


def _discover_copilot_sessions(starred_ids: set) -> list:
    """Yield session dicts for GitHub Copilot (~/.copilot/session-state/<uuid>/)."""
    sessions = []
    copilot_state_dir = MAIN_HOME / ".copilot" / "session-state"
    if not copilot_state_dir.exists():
        return sessions

    try:
        session_dirs = list(copilot_state_dir.iterdir())
    except OSError:
        return sessions

    for session_dir in session_dirs:
        if not session_dir.is_dir():
            continue
        session_id = session_dir.name
        workspace_yaml = session_dir / "workspace.yaml"
        events_jsonl = session_dir / "events.jsonl"

        # Prefer workspace.yaml — tiny key:value file, fast to parse
        meta = _parse_copilot_workspace_yaml(workspace_yaml)
        if meta:
            cwd = meta.get("cwd", "")
            topic = meta.get("summary", "")
            # Try to get a more accurate mtime from updated_at
            mod_dt = None
            updated_at = meta.get("updated_at", "")
            if updated_at:
                try:
                    mod_dt = datetime.fromisoformat(updated_at.replace("Z", "+00:00")).replace(tzinfo=None)
                except (ValueError, AttributeError):
                    pass
            sid = meta.get("id", session_id)
        else:
            # Fall back to events.jsonl
            sid, cwd, topic, mod_dt = _scan_copilot_events_head(events_jsonl)
            if not sid:
                sid = session_id

        # Compute size: total bytes under session dir
        size_bytes = 0
        try:
            for entry in session_dir.iterdir():
                try:
                    size_bytes += entry.stat().st_size
                except OSError:
                    pass
        except OSError:
            pass

        if mod_dt is None:
            try:
                st = session_dir.stat()
                mod_dt = datetime.fromtimestamp(st.st_mtime)
            except OSError:
                mod_dt = datetime.fromtimestamp(0)

        project = cwd.rstrip("/").rsplit("/", 1)[-1] if cwd else session_dir.name

        sessions.append(
            {
                "id": sid,
                "project": project,
                "cwd": cwd,
                "modified": mod_dt,
                "size_mb": size_bytes / (1024 * 1024),
                "path": session_dir,
                "topic": topic,
                "provider": "copilot",
                "starred": sid in starred_ids,
            }
        )
    return sessions


def get_sessions():
    """Find all sessions across all projects, return sorted by modification time."""
    starred_ids = load_starred_ids()
    sessions = []
    sessions.extend(_discover_claude_sessions(starred_ids))
    sessions.extend(_discover_codex_sessions(starred_ids))
    sessions.extend(_discover_gemini_sessions(starred_ids))
    sessions.extend(_discover_copilot_sessions(starred_ids))
    sessions.sort(key=lambda s: s["modified"], reverse=True)
    return sessions


def _extract_text(content):
    """Flatten a Claude Code message ``content`` field into plain text."""
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


def _scan_codex_session_head(jsonl_path, max_lines: int = 80) -> tuple:
    """Return (session_id, topic, cwd) from the head of a Codex session JSONL."""
    session_id = ""
    topic = ""
    cwd = ""
    try:
        with open(jsonl_path, "r", encoding="utf-8", errors="replace") as fh:
            for i, line in enumerate(fh):
                if i >= max_lines and session_id and topic:
                    break
                line = line.strip()
                if not line:
                    continue
                try:
                    obj = json.loads(line)
                except json.JSONDecodeError:
                    continue
                t = obj.get("type")
                payload = obj.get("payload") if isinstance(obj.get("payload"), dict) else {}
                if t == "session_meta" and not session_id:
                    session_id = payload.get("id", "")
                    cwd = payload.get("cwd", "")
                if not topic and t == "response_item":
                    if payload.get("type") == "message" and payload.get("role") == "user":
                        content_items = payload.get("content", [])
                        for item in content_items:
                            if not isinstance(item, dict):
                                continue
                            if item.get("type") != "input_text":
                                continue
                            text = item.get("text", "")
                            if any(text.startswith(s) for s in _CODEX_TOPIC_SENTINELS):
                                continue
                            topic = _clean_topic(text)
                            break
    except OSError:
        pass
    return session_id, topic, cwd


def _scan_gemini_session(json_path, cwd_fallback: str = "") -> tuple:
    """Return (session_id, topic, cwd) by parsing a Gemini session JSON file."""
    session_id = ""
    topic = ""
    cwd = cwd_fallback
    try:
        raw = json_path.read_text(encoding="utf-8", errors="replace")
        data = json.loads(raw)
    except (OSError, json.JSONDecodeError):
        return session_id, topic, cwd

    session_id = data.get("sessionId", "")
    # cwd: use .project_root content (already passed as cwd_fallback)
    # Topic: first user message
    messages = data.get("messages", [])
    for msg in messages:
        if not isinstance(msg, dict):
            continue
        if msg.get("type") != "user":
            continue
        content = msg.get("content", "")
        if isinstance(content, str):
            text = content
        elif isinstance(content, list):
            parts = []
            for c in content:
                if isinstance(c, dict) and isinstance(c.get("text"), str):
                    parts.append(c["text"])
                elif isinstance(c, str):
                    parts.append(c)
            text = " ".join(parts)
        else:
            continue
        text = text.strip()
        if text:
            topic = _clean_topic(text)
            break

    return session_id, topic, cwd


def _parse_copilot_workspace_yaml(yaml_path) -> dict:
    """Parse a minimal Copilot workspace.yaml into a plain dict."""
    result = {}
    try:
        text = yaml_path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return result
    for line in text.splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        if ":" not in line:
            continue
        key, _, val = line.partition(":")
        key = key.strip()
        val = val.strip()
        # Strip surrounding quotes if present
        if len(val) >= 2 and val[0] in ('"', "'") and val[-1] == val[0]:
            val = val[1:-1]
        result[key] = val
    return result


def _scan_copilot_events_head(jsonl_path, max_lines: int = 40) -> tuple:
    """Return (session_id, cwd, topic, mod_dt) from events.jsonl head."""
    session_id = ""
    cwd = ""
    topic = ""
    mod_dt = None
    try:
        with open(jsonl_path, "r", encoding="utf-8", errors="replace") as fh:
            for i, line in enumerate(fh):
                if i >= max_lines and session_id and topic:
                    break
                line = line.strip()
                if not line:
                    continue
                try:
                    obj = json.loads(line)
                except json.JSONDecodeError:
                    continue
                t = obj.get("type", "")
                data = obj.get("data") if isinstance(obj.get("data"), dict) else {}
                if t == "session.start" and not session_id:
                    session_id = data.get("sessionId", "")
                    ctx = data.get("context") if isinstance(data.get("context"), dict) else {}
                    cwd = ctx.get("cwd", "") or ctx.get("gitRoot", "")
                    ts = data.get("timestamp", "")
                    if ts:
                        try:
                            mod_dt = datetime.fromisoformat(ts.replace("Z", "+00:00")).replace(tzinfo=None)
                        except (ValueError, AttributeError):
                            pass
                elif t == "user.message" and not topic:
                    content = data.get("content", "")
                    if isinstance(content, str) and content.strip():
                        topic = _clean_topic(content)
    except OSError:
        pass
    return session_id, cwd, topic, mod_dt


def load_session_preview(
    session_or_path, max_messages: int = 4, max_lines: int = 400, provider: str = "claude"
) -> dict:
    """Load opening prompt + first few message turns for the preview pane."""
    if provider == "gemini":
        return _load_gemini_preview(session_or_path, max_messages=max_messages)
    if provider == "codex":
        return _load_codex_preview(session_or_path, max_messages=max_messages, max_lines=max_lines)
    if provider == "copilot":
        return _load_copilot_preview(session_or_path, max_messages=max_messages)
    # Default: Claude JSONL
    return _load_claude_preview(session_or_path, max_messages=max_messages, max_lines=max_lines)


def _load_claude_preview(jsonl_path, max_messages: int = 4, max_lines: int = 400) -> dict:
    """Load preview for a Claude Code JSONL session."""
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


def _load_codex_preview(jsonl_path, max_messages: int = 4, max_lines: int = 400) -> dict:
    """Load preview for a Codex CLI JSONL session."""
    messages = []
    cwd = ""
    total_lines = 0
    truncated = False
    try:
        with open(jsonl_path, "r", encoding="utf-8", errors="replace") as fh:
            for line in fh:
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
                t = obj.get("type")
                payload = obj.get("payload") if isinstance(obj.get("payload"), dict) else {}
                if t == "session_meta" and not cwd:
                    cwd = payload.get("cwd", "")
                if t == "response_item" and payload.get("type") == "message":
                    role = payload.get("role", "")
                    content_items = payload.get("content", [])
                    text_parts = []
                    for item in content_items:
                        if isinstance(item, dict) and item.get("type") in ("input_text", "output_text"):
                            text_parts.append(item.get("text", ""))
                        elif isinstance(item, str):
                            text_parts.append(item)
                    text = " ".join(text_parts).strip()
                    if role == "user" and text:
                        if not any(text.startswith(s) for s in _CODEX_TOPIC_SENTINELS):
                            messages.append(("user", text))
                    elif role == "assistant" and text:
                        messages.append(("assistant", text))
                if len(messages) >= max_messages:
                    truncated = bool(fh.readline())
                    break
    except OSError as e:
        return {"messages": [], "cwd": "", "truncated": False, "error": str(e)}
    return {"messages": messages, "cwd": cwd, "truncated": truncated, "error": None}


def _load_gemini_preview(json_path, max_messages: int = 4) -> dict:
    """Load preview for a Gemini CLI JSON session file."""
    messages = []
    cwd = ""
    truncated = False
    try:
        raw = json_path.read_text(encoding="utf-8", errors="replace")
        data = json.loads(raw)
    except (OSError, json.JSONDecodeError) as e:
        return {"messages": [], "cwd": "", "truncated": False, "error": str(e)}

    msg_list = data.get("messages", [])
    for msg in msg_list:
        if not isinstance(msg, dict):
            continue
        msg_type = msg.get("type", "")
        content = msg.get("content", "")
        if isinstance(content, str):
            text = content.strip()
        elif isinstance(content, list):
            parts = []
            for c in content:
                if isinstance(c, dict) and isinstance(c.get("text"), str):
                    parts.append(c["text"])
                elif isinstance(c, str):
                    parts.append(c)
            text = " ".join(parts).strip()
        else:
            text = ""
        if not text:
            continue
        if msg_type == "user":
            messages.append(("user", text))
        elif msg_type in ("assistant", "gemini", "model"):
            messages.append(("assistant", text))
        if len(messages) >= max_messages:
            truncated = True
            break

    return {"messages": messages, "cwd": cwd, "truncated": truncated, "error": None}


def _load_copilot_preview(session_dir, max_messages: int = 4) -> dict:
    """Load preview for a GitHub Copilot session directory."""
    messages = []
    cwd = ""
    truncated = False

    # Try workspace.yaml for cwd
    workspace_yaml = session_dir / "workspace.yaml"
    meta = _parse_copilot_workspace_yaml(workspace_yaml)
    if meta:
        cwd = meta.get("cwd", "")

    # Read events.jsonl for messages
    events_jsonl = session_dir / "events.jsonl"
    try:
        with open(events_jsonl, "r", encoding="utf-8", errors="replace") as fh:
            for line in fh:
                line = line.strip()
                if not line:
                    continue
                try:
                    obj = json.loads(line)
                except json.JSONDecodeError:
                    continue
                t = obj.get("type", "")
                data = obj.get("data") if isinstance(obj.get("data"), dict) else {}
                if t == "session.start" and not cwd:
                    ctx = data.get("context") if isinstance(data.get("context"), dict) else {}
                    cwd = ctx.get("cwd", "") or ctx.get("gitRoot", "")
                elif t == "user.message":
                    content = data.get("content", "")
                    if isinstance(content, str) and content.strip():
                        messages.append(("user", content.strip()))
                elif t in ("assistant.message", "copilot.message"):
                    content = data.get("content", "")
                    if isinstance(content, str) and content.strip():
                        messages.append(("assistant", content.strip()))
                if len(messages) >= max_messages:
                    truncated = True
                    break
    except OSError:
        # events.jsonl may not exist; fall back to summary from workspace.yaml
        summary = meta.get("summary", "") if meta else ""
        if summary:
            messages = [("user", summary)]

    return {"messages": messages, "cwd": cwd, "truncated": truncated, "error": None}


def decode_project_path(encoded: str) -> str:
    """Decode Claude Code's project dir name back into a readable path."""
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
    # Non-Claude providers store a plain label or basename — return it directly.
    if "/" in encoded or not encoded.startswith("-"):
        return encoded.rstrip("/").rsplit("/", 1)[-1] or encoded
    # Claude dash-encoded path
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


# Interactive Menu


def interactive_picker(sessions):
    """Arrow-key driven session picker using curses."""
    if not sessions:
        print("No sessions found.")
        sys.exit(1)

    selected = curses.wrapper(_draw_picker, sessions)
    return selected


# Per-page tint offsets: each page picks a different point on the theme's
# banner gradient for its nav sweep base color, giving each screen a subtly
# distinct shade while sharing the same palette.
_PAGE_TINTS = {
    "resume": 0.0,
    "settings": 0.15,
    "launcher": 0.3,
    "onboarding": 0.45,
    "search": 0.6,
    "default": 0.0,
}

# Curses pair index reserved for the per-page nav tint (allocated once per
# _picker_attrs call; safe to re-init because curses allows re-init of pairs).
_NAV_TINT_PAIR = 10


def _picker_attrs(page: str = "default"):
    """Initialize color pairs for the picker. Returns an attrs dict."""
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
        attrs["brand"] = curses.color_pair(3) | curses.A_BOLD
        attrs["shine_peak"] = curses.color_pair(6) | curses.A_BOLD
        attrs["shine_mid"] = curses.color_pair(2) | curses.A_BOLD
        attrs["size_warn"] = curses.color_pair(7) | curses.A_DIM

        # Per-page nav tint: pick a point on the gradient and approximate to
        # the nearest xterm-256 color so the nav bar has a page-specific shade.
        nav_base_attr = curses.A_NORMAL
        if curses.COLORS >= 256:
            tint_t = _PAGE_TINTS.get(page, 0.0)
            theme_full = THEMES.get(get_current_theme(), THEMES[_DEFAULT_THEME])
            tint_hex = _gradient_color(theme_full["banner"], tint_t)
            try:
                tint_idx = _hex_to_curses_256(tint_hex)
                curses.init_pair(_NAV_TINT_PAIR, tint_idx, -1)
                nav_base_attr = curses.color_pair(_NAV_TINT_PAIR)
            except (curses.error, Exception):
                pass
        attrs["nav_base"] = nav_base_attr
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
    size_w = 7  # " 1.2MB " right-aligned
    gutter = 2  # leading "▸ "
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
    """Render the footer nav line with a BBS-style shine sweep + twinkling."""
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
    for field in (format_project_name(s["project"]), s.get("topic") or "", s.get("cwd") or "", s.get("id") or ""):
        if q in field.lower():
            return True
    return False


_RESUME_PROVIDER_CYCLE = [None, "claude", "gemini", "codex", "copilot"]
_RESUME_SORT_MODES = ["time", "project", "provider"]


def _apply_resume_view(sessions, filter_provider, sort_mode, search_query, starred_only: bool = False):
    """Return the sorted+filtered session list for the resume picker."""
    result = sessions

    # Starred-only filter
    if starred_only:
        result = [s for s in result if s.get("starred")]

    # Provider filter
    if filter_provider is not None:
        result = [s for s in result if s.get("provider") == filter_provider]

    # Text search filter
    if search_query:
        result = [s for s in result if _session_matches(s, search_query)]

    # Sort
    if sort_mode == "project":
        result = sorted(result, key=lambda s: (format_project_name(s["project"]).lower(), -s["modified"].timestamp()))
    elif sort_mode == "provider":
        result = sorted(result, key=lambda s: (s.get("provider", ""), -s["modified"].timestamp()))
    # "time" is the default (already sorted by get_sessions)
    return result


def _draw_picker(stdscr, sessions):
    curses.curs_set(0)
    attrs = _picker_attrs("resume")

    current = 0
    scroll_offset = 0
    preview_cache = {}  # session_id -> loaded preview dict
    search_query = ""  # active filter text ("" = show all)
    search_mode = False  # True while typing in the / search bar

    # Provider filter + sort state (Feature 1)
    filter_provider = None  # None = all; or a provider id string
    sort_mode = "time"  # "time" | "project" | "provider"
    group_mode = False  # True = insert divider lines between project+provider groups
    starred_only = False  # True = show only starred sessions

    filtered = _apply_resume_view(sessions, filter_provider, sort_mode, search_query, starred_only)

    # Starred state is live-edited inside the picker without restarting.
    # sessions dicts carry a "starred" bool that we mutate in place on toggle.

    while True:
        stdscr.erase()
        max_y, max_x = stdscr.getmaxyx()
        cols = _compute_columns(max_x)

        # Title bar (row 0) — left: label, right: counts
        n_all = len([s for s in sessions if (filter_provider is None or s.get("provider") == filter_provider)])
        title_left = " altergo — recall session"
        if search_query:
            title_right = f"{len(filtered)}/{n_all} matching "
        elif starred_only and filter_provider:
            title_right = f"{len(filtered)} starred {filter_provider} "
        elif starred_only:
            title_right = f"{len(filtered)} starred "
        elif filter_provider:
            title_right = f"{len(filtered)} {filter_provider} sessions "
        else:
            title_right = f"{len(sessions)} total "
        header_row = title_left.ljust(max(0, max_x - len(title_right))) + title_right
        _safe_addnstr(stdscr, 0, 0, header_row[:max_x], max_x - 1, attrs["title"])

        # Separator under the title (row 1) — matches the launcher's header look
        _safe_addnstr(stdscr, 1, 0, ("─" * (max_x - 1))[: max_x - 1], max_x - 1, attrs["dim"])

        # Status bar: provider filter + sort mode + key hints (row 2)
        prov_label = filter_provider if filter_provider else "all"
        sort_label = sort_mode
        group_label = "on" if group_mode else "off"
        starred_label = "on" if starred_only else "off"
        status = (
            f" provider: {prov_label}  sort: {sort_label}  group: {group_label}"
            f"  starred: {starred_label}  [f]ilter [s]ort [g]roup [*]starred [b]ookmark"
        )
        _safe_addnstr(stdscr, 2, 0, _truncate(status, max_x - 1), max_x - 1, attrs["dim"])

        # Column header row (row 3)
        proj_h = "Project".ljust(cols["proj"])
        time_h = "When".ljust(cols["time"])
        size_h = "Size".rjust(cols["size"])
        topic_h = "Topic"
        col_header = f"  {proj_h}  {time_h}  {size_h}  {topic_h}"
        _safe_addnstr(stdscr, 3, 0, col_header.ljust(max_x), max_x - 1, attrs["header"])

        # Visible area: title(1) + sep(1) + status(1) + col_header(1) + footer(2) = 6 used
        visible_rows = max(1, max_y - 6)

        # Build display items: a session entry or a group divider string
        # Dividers are only inserted when group_mode is on.
        display_items = []  # list of session dict OR None (divider)
        if group_mode and filtered:
            last_group_key = None
            for s in filtered:
                gk = (s.get("provider", ""), format_project_name(s["project"]))
                if gk != last_group_key:
                    if last_group_key is not None:
                        display_items.append(None)  # divider
                    last_group_key = gk
                display_items.append(s)
        else:
            display_items = list(filtered)

        # Map cursor index (over real sessions only) to display_items index
        real_indices = [i for i, item in enumerate(display_items) if item is not None]
        # Clamp current to valid range
        if not real_indices:
            current = 0
        else:
            current = max(0, min(current, len(real_indices) - 1))

        # Scroll: keep the display item for current in view
        if real_indices:
            display_cursor = real_indices[current]
            if display_cursor < scroll_offset:
                scroll_offset = display_cursor
            elif display_cursor >= scroll_offset + visible_rows:
                scroll_offset = display_cursor - visible_rows + 1

        for i in range(visible_rows):
            di = scroll_offset + i
            if di >= len(display_items):
                break
            item = display_items[di]
            row = i + 4

            if item is None:
                # Divider line
                div = "  " + ("─" * max(0, max_x - 4))
                _safe_addnstr(stdscr, row, 0, div[: max_x - 1], max_x - 1, attrs["dim"])
                continue

            s = item
            # Determine if this display item is the cursor row
            real_idx_in_display = real_indices.index(di) if di in real_indices else -1
            is_sel = real_idx_in_display == current

            when = _truncate(relative_time(s["modified"]), cols["time"])
            topic = s.get("topic") or ""
            topic_is_empty = not topic
            if topic_is_empty:
                topic = "(no prompt)"
            topic = _truncate(topic, cols["topic"])

            size_str = f"{s.get('size_mb', 0):.1f}MB".rjust(cols["size"])
            size_attr = attrs["size_warn"] if s.get("size_mb", 0) > 10 else attrs["time"]

            # Provider label suffix in project column (fits after project name if room)
            prov_tag = f" [{s.get('provider', '')}]"
            proj_with_tag = _truncate(format_project_name(s["project"]) + prov_tag, cols["proj"])

            is_starred_row = s.get("starred", False)
            star_ch = "★" if is_starred_row else " "

            if is_sel:
                gutter = f"▸{star_ch}"
                line = f"{gutter}{proj_with_tag.ljust(cols['proj'])}  {when.ljust(cols['time'])}  {size_str}  {topic}"
                _safe_addnstr(stdscr, row, 0, line.ljust(max_x), max_x - 1, attrs["selected"])
            else:
                _safe_addnstr(stdscr, row, 0, f" {star_ch}", 2)
                _safe_addnstr(stdscr, row, 2, proj_with_tag.ljust(cols["proj"]), cols["proj"], attrs["project"])
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
            elif filtered and 0 <= current < len(filtered):
                s = filtered[current]
                sid = s["id"]
                cwd = s.get("cwd") or decode_project_path(s["project"])
                foot = f" {sid}  ·  {cwd}"
                _safe_addnstr(stdscr, footer_row, 0, _truncate(foot, max_x - 1), max_x - 1, attrs["topic"])
        theme_hint = f" · theme: {THEMES[get_current_theme()]['display_name']} (t)"
        nav = (
            " ↑↓/jk move  ·  / search  ·  G top  ·  p/Tab preview"
            "  ·  f filter  ·  s sort  ·  g group  ·  b bookmark  ·  * starred-only  ·  Enter resume  ·  q quit"
            + theme_hint
        )
        _safe_addnstr(stdscr, footer_row + 1, 0, _truncate(nav, max_x - 1), max_x - 1, attrs["dim"])

        stdscr.refresh()
        key = stdscr.getch()

        # -- Search mode input handling --
        if search_mode:
            if key == 27:  # Esc — cancel search, restore full list
                search_mode = False
                search_query = ""
                filtered = _apply_resume_view(sessions, filter_provider, sort_mode, "", starred_only)
                current = 0
                scroll_offset = 0
            elif key in (curses.KEY_ENTER, 10, 13):  # Enter — accept filter
                search_mode = False
            elif key in (curses.KEY_BACKSPACE, 127, 8):
                search_query = search_query[:-1]
                filtered = _apply_resume_view(sessions, filter_provider, sort_mode, search_query, starred_only)
                current = min(current, max(len(filtered) - 1, 0))
                scroll_offset = 0
            elif 32 <= key <= 126:  # printable character
                search_query += chr(key)
                filtered = _apply_resume_view(sessions, filter_provider, sort_mode, search_query, starred_only)
                current = min(current, max(len(filtered) - 1, 0))
                scroll_offset = 0
            continue

        # -- Normal mode input handling --
        if key in (curses.KEY_UP, ord("k")):
            current = max(0, current - 1)
        elif key in (curses.KEY_DOWN, ord("j")):
            current = min(max(len(filtered) - 1, 0), current + 1)
        elif key == curses.KEY_PPAGE:
            current = max(0, current - visible_rows)
        elif key == curses.KEY_NPAGE:
            current = min(max(len(filtered) - 1, 0), current + visible_rows)
        elif key == ord("G"):
            current = 0  # go to top (vi-like: gg = top; G = bottom, but g taken for group)
        elif key in (curses.KEY_ENTER, 10, 13):
            if filtered and 0 <= current < len(filtered):
                return filtered[current]
        elif key in (ord("p"), ord(" "), 9):  # p, space, Tab → preview
            if filtered and 0 <= current < len(filtered):
                s = filtered[current]
                if s["id"] not in preview_cache:
                    preview_cache[s["id"]] = load_session_preview(s["path"], provider=s.get("provider", "claude"))
                action = _draw_preview(stdscr, attrs, s, preview_cache[s["id"]])
                if action == "resume":
                    return s
                # else: just return to picker
        elif key == ord("/"):
            search_mode = True
            search_query = ""
        elif key == ord("f"):
            # Cycle provider filter: None → claude → gemini → codex → copilot → None
            idx = _RESUME_PROVIDER_CYCLE.index(filter_provider) if filter_provider in _RESUME_PROVIDER_CYCLE else 0
            filter_provider = _RESUME_PROVIDER_CYCLE[(idx + 1) % len(_RESUME_PROVIDER_CYCLE)]
            filtered = _apply_resume_view(sessions, filter_provider, sort_mode, search_query, starred_only)
            current = 0
            scroll_offset = 0
        elif key == ord("s"):
            # Cycle sort mode: time → project → provider → time
            idx = _RESUME_SORT_MODES.index(sort_mode) if sort_mode in _RESUME_SORT_MODES else 0
            sort_mode = _RESUME_SORT_MODES[(idx + 1) % len(_RESUME_SORT_MODES)]
            filtered = _apply_resume_view(sessions, filter_provider, sort_mode, search_query, starred_only)
            current = 0
            scroll_offset = 0
        elif key == ord("g"):
            group_mode = not group_mode
            scroll_offset = 0
        elif key == ord("*"):
            # Toggle starred-only filter; keep search/provider filters intact
            starred_only = not starred_only
            filtered = _apply_resume_view(sessions, filter_provider, sort_mode, search_query, starred_only)
            current = 0
            scroll_offset = 0
        elif key == ord("b"):
            # Bookmark (star) toggle on the highlighted row
            if filtered and 0 <= current < len(filtered):
                s = filtered[current]
                now_starred = toggle_starred_session(
                    s["id"], s.get("provider", "claude"), s["project"], s.get("topic") or ""
                )
                # Update the starred flag in-place on the shared session dict so
                # the gutter indicator updates immediately without a full reload.
                s["starred"] = now_starred
                for sess in sessions:
                    if sess["id"] == s["id"]:
                        sess["starred"] = now_starred
                        break
                # Recompute filtered: if starred_only is on and we just un-starred
                # the current row it will disappear — clamp logic below handles cursor.
                filtered = _apply_resume_view(sessions, filter_provider, sort_mode, search_query, starred_only)
                current = min(current, max(len(filtered) - 1, 0))
        elif key == ord("t"):
            # Cycle to the next theme, re-init the picker attrs so the current
            # draw picks up the new palette, and persist the choice immediately.
            theme_ids = list(THEMES.keys())
            cur = get_current_theme()
            nxt = theme_ids[(theme_ids.index(cur) + 1) % len(theme_ids)] if cur in theme_ids else theme_ids[0]
            set_current_theme(nxt)
            save_persisted_theme(nxt)
            attrs = _picker_attrs("resume")
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
    """Parse a search query, supporting quoted exact phrases and bare terms."""
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
    """Search full conversation text in session JSONL files."""
    results = []
    targets = sessions
    if project_filter:
        pf = project_filter.lower()
        targets = [
            s
            for s in sessions
            if pf in format_project_name(s["project"]).lower() or pf in decode_project_path(s["project"]).lower()
        ]

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
                        matches.append(
                            {
                                "line_no": line_no,
                                "role": role,
                                "snippet": snippet,
                                "terms": terms,
                            }
                        )
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
    attrs = _picker_attrs("search")
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
            _safe_addnstr(
                stdscr, 2, 2, "Filter by project (optional — Enter to skip, search all):", max_x - 3, attrs["accent"]
            )

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
            _safe_addnstr(stdscr, 2, 2, f"Searching in: {proj_label}", max_x - 3, attrs["project"])
            _safe_addnstr(stdscr, 3, 2, 'Case-insensitive. Use "quotes" for exact phrases.', max_x - 3, attrs["dim"])

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
            _safe_addnstr(stdscr, 2, 2, f"Searching in: {proj_label}", max_x - 3, attrs["project"])

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
            match_s = "es" if total_matches != 1 else ""
            session_s = "s" if len(results) != 1 else ""
            summary = f"  {total_matches} match{match_s} in {len(results)} session{session_s}  ·  {proj_label}"
            _safe_addnstr(stdscr, 2, 2, summary, max_x - 3, attrs["accent"])

            query_echo = f'  query: "{query_input}"'
            _safe_addnstr(stdscr, 3, 2, query_echo, max_x - 3, attrs["dim"])

            if not results:
                _safe_addnstr(stdscr, 5, 4, "No matches found.", max_x - 5, attrs["dim"])
                _safe_addnstr(
                    stdscr, 6, 4, "Try different terms or broaden the project filter.", max_x - 5, attrs["dim"]
                )
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
                    is_selected = kind == "result_header" and ri == result_cursor
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
                            scan_total = sum(
                                1
                                for s in sessions
                                if pfl in format_project_name(s["project"]).lower()
                                or pfl in decode_project_path(s["project"]).lower()
                            )
                        scan_done = 0

                        def _progress(done, total):
                            nonlocal scan_done, scan_total
                            scan_done = done
                            scan_total = max(total, 1)

                        results = _search_sessions(sessions, terms, project_filter=pf, on_progress=_progress)
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


# Settings TUI

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
    """Approximate a hex color to the nearest xterm-256 color index."""
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
    attrs = _picker_attrs("settings")

    # Snapshot original theme so we can restore on cancel
    original_theme = get_current_theme()

    # Working state for all three pages

    # Page 0: Appearance
    theme_names = list(THEMES.keys())
    current_theme_idx = theme_names.index(get_current_theme()) if get_current_theme() in theme_names else 0

    # Banner font
    _banner_fonts = _get_valid_banner_fonts()
    _saved_font = load_persisted_banner_font()
    current_font_idx = _banner_fonts.index(_saved_font) if _saved_font in _banner_fonts else 0

    # Animation pack (replaces old launch_anim bool)
    _saved_pack = load_animation_pack()
    _packs_list = list(_VALID_ANIM_PACKS)
    current_pack_idx = (
        _packs_list.index(_saved_pack) if _saved_pack in _VALID_ANIM_PACKS else _packs_list.index(_DEFAULT_ANIM_PACK)
    )

    _rts = load_random_theme_settings()
    random_theme_on = _rts["random_theme_enabled"]
    random_theme_freq = _rts["random_theme_frequency"]  # 1–5

    # Page 1: Behavior
    update_check = load_update_check_enabled()
    show_greeting = _load_bool_setting("show_greeting")
    show_goodbye = _load_bool_setting("show_goodbye")
    tmux_session = _load_bool_setting("tmux_session", default=False)

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

    # Navigation state
    current_page = 0
    n_pages = len(_SETTINGS_PAGES)

    # Per-page cursor positions
    # Page 0: rows = [themes…, fonts…, packs…, random_toggle, freq_slider]
    # Index layout (computed dynamically via helpers below):
    #   0..T-1              → theme rows
    #   T..T+F-1            → font rows
    #   T+F..T+F+P-1        → animation pack rows
    #   T+F+P               → random theme toggle
    #   T+F+P+1             → freq slider
    def _p0_font_offset() -> int:
        return len(theme_names)

    def _p0_pack_offset() -> int:
        return len(theme_names) + len(_banner_fonts)

    def _p0_rand_idx() -> int:
        return len(theme_names) + len(_banner_fonts) + len(_VALID_ANIM_PACKS)

    def _p0_freq_idx() -> int:
        return _p0_rand_idx() + 1

    # Two-column grid for the font section: column-major order.
    # Left col:  fonts[0 .. n_font_rows-1]
    # Right col: fonts[n_font_rows .. F-1]
    _n_font_rows = max(1, (len(_banner_fonts) + 1) // 2)

    page0_cursor = current_theme_idx
    page0_n = len(theme_names) + len(_banner_fonts) + len(_VALID_ANIM_PACKS) + 2
    page0_scroll = 0  # virtual-row scroll offset for the content area

    # Page 1: rows = [update_check, show_greeting, show_goodbye, tmux_session]
    page1_cursor = 0
    page1_n = 4

    # Page 2: credential entries (selectable positions in cred_selectable)
    page2_cursor = 0
    page2_scroll = 0

    # Swatch color pairs — pairs 20+ reserved for swatches
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

    # Scroll helpers for page 0

    def _cursor_to_vrow(c: int) -> int:
        """Map a page-0 cursor index to its virtual row in the content list."""
        T = len(theme_names)
        F = len(_banner_fonts)
        NF = _n_font_rows  # virtual rows the font section occupies
        P = len(_VALID_ANIM_PACKS)
        # Theme rows: header at vrow 0, items at 1..T
        if c < T:
            return 1 + c
        # Font rows: blank at T+1, header at T+2, grid rows at T+3..T+2+NF
        if c < T + F:
            fi = c - T
            row_in_grid = fi % NF  # same vrow for left and right column items
            return T + 3 + row_in_grid
        # Pack rows: blank at T+3+NF, header at T+4+NF, items at T+5+NF..T+4+NF+P
        if c < T + F + P:
            pi = c - T - F
            return T + 5 + NF + pi
        # Random toggle: blank at T+5+NF+P, header at T+6+NF+P, toggle at T+7+NF+P
        if c == T + F + P:
            return T + 7 + NF + P
        # Freq slider
        return T + 8 + NF + P

    def _page0_ensure_visible():
        """Adjust page0_scroll so the focused row is inside the viewport."""
        nonlocal page0_scroll
        max_y_now, _ = stdscr.getmaxyx()
        # Content rows: content_start(3) .. max_y-2 (footer is max_y-2 and max_y-1)
        visible_h = max(1, max_y_now - 3 - 2)
        target = _cursor_to_vrow(page0_cursor)
        if target < page0_scroll:
            page0_scroll = target
        elif target >= page0_scroll + visible_h:
            page0_scroll = target - visible_h + 1
        page0_scroll = max(0, page0_scroll)

    # Helper: draw one tab bar line
    def _draw_tab_bar(max_x):
        x = 0
        for pi, page in enumerate(_SETTINGS_PAGES):
            tab_text = f"  {page['title']}  "
            if pi == current_page:
                _safe_addnstr(
                    stdscr, 0, x, tab_text[: max_x - x], max_x - x, attrs["title"] | curses.A_REVERSE | curses.A_BOLD
                )
            else:
                _safe_addnstr(stdscr, 0, x, tab_text[: max_x - x], max_x - x, attrs["dim"])
            x += len(tab_text)
            if pi < n_pages - 1 and x < max_x - 1:
                _safe_addnstr(stdscr, 0, x, "\u2502", 1, attrs["dim"])  # │
                x += 1

    # Helper: draw page 0 (Appearance)
    def _draw_page0(max_y, max_x, attrs_local):
        content_start = 3
        # Rows content_start .. max_y-3 are the scrollable content area.
        # max_y-2 and max_y-1 are the footer hint + nav bar (always visible).
        _bot = max_y - 2  # first non-content row

        def _sr(vr: int) -> int:
            """Virtual row → screen row."""
            return content_start + vr - page0_scroll

        def _vis(vr: int) -> bool:
            s = _sr(vr)
            return content_start <= s < _bot

        def _draw_vr(vr: int, col: int, text: str, width: int, attr=curses.A_NORMAL):
            s = _sr(vr)
            if content_start <= s < _bot:
                _safe_addnstr(stdscr, s, col, text, width, attr)

        vrow = 0

        # Theme
        _draw_vr(vrow, 2, ("Theme " + "\u2500" * 34)[: max_x - 3], max_x - 3, attrs_local["accent"] | curses.A_BOLD)
        vrow += 1

        for ti, tid in enumerate(theme_names):
            if _vis(vrow):
                s = _sr(vrow)
                tdata = THEMES[tid]
                is_focused = ti == page0_cursor
                is_selected = ti == current_theme_idx
                marker = "\u25c6" if is_selected else "\u00b7"
                marker_attr = attrs_local["accent"] | curses.A_BOLD if is_selected else attrs_local["dim"]
                prefix = "\u25b8 " if is_focused else "  "
                prefix_attr = attrs_local["accent"] | curses.A_BOLD if is_focused else curses.A_NORMAL
                _safe_addnstr(stdscr, s, 0, prefix, 2, prefix_attr)
                _safe_addnstr(stdscr, s, 2, marker, 1, marker_attr)
                _safe_addnstr(stdscr, s, 4, " ", 1, curses.A_NORMAL)
                name_str = tdata["display_name"].ljust(12)
                name_attr = attrs_local["accent"] | curses.A_BOLD if is_selected else curses.A_NORMAL
                _safe_addnstr(stdscr, s, 5, name_str[:12], 12, name_attr)
                sx = 18
                for si in range(min(3, len(tdata["banner"]))):
                    pk = (tid, si)
                    if pk in swatch_pairs and sx < max_x - 2:
                        _safe_addnstr(stdscr, s, sx, _SWATCH_BLOCK * 2, 2, curses.color_pair(swatch_pairs[pk]))
                        sx += 2
                desc = "  " + tdata["description"]
                if sx < max_x - 4:
                    _safe_addnstr(stdscr, s, sx, desc[: max_x - sx - 1], max_x - sx - 1, attrs_local["dim"])
            vrow += 1

        vrow += 1  # blank line

        # Font
        _draw_vr(vrow, 2, ("Font " + "\u2500" * 35)[: max_x - 3], max_x - 3, attrs_local["accent"] | curses.A_BOLD)
        vrow += 1

        font_section_vrow = vrow  # anchor for preview overlay

        # Two-column grid layout.
        # Left col:  fonts[ 0 .. _n_font_rows-1 ]  at col 0
        # Right col: fonts[ _n_font_rows .. F-1 ]   at col _COL2_X
        # Divider at _DIV_X, preview at _PRV_X.
        _COL2_X = 20  # start of right-column entry
        _DIV_X = 40  # vertical divider before preview
        _PRV_X = 42  # preview text start
        _preview_avail = max(0, max_x - _PRV_X - 1)

        # Pre-render the focused font preview (follows cursor, not the committed selection)
        _preview_lines: list[str] = []
        _font_off_local = _p0_font_offset()
        if _banner_fonts and _font_off_local <= page0_cursor < _font_off_local + len(_banner_fonts):
            _preview_font = _banner_fonts[page0_cursor - _font_off_local]
        else:
            _preview_font = _banner_fonts[current_font_idx] if _banner_fonts else _DEFAULT_BANNER_FONT
        if _preview_avail > 10:
            try:
                import pyfiglet as _pf

                _raw = _pf.Figlet(font=_preview_font).renderText("altergo")
                _preview_lines = [ln[:_preview_avail] for ln in _raw.splitlines()]
                while _preview_lines and not _preview_lines[-1].strip():
                    _preview_lines.pop()
            except Exception:
                pass

        _font_off = _p0_font_offset()

        def _draw_font_item(row_vrow: int, col_x: int, fi: int, fname: str):
            """Render one font item at the given virtual row and column offset."""
            if not _vis(row_vrow):
                return
            s = _sr(row_vrow)
            fi_abs = _font_off + fi
            is_focused = fi_abs == page0_cursor
            is_selected = fi == current_font_idx
            marker = "\u25c6" if is_selected else "\u00b7"
            marker_attr = attrs_local["accent"] | curses.A_BOLD if is_selected else attrs_local["dim"]
            prefix = "\u25b8 " if is_focused else "  "
            prefix_attr = attrs_local["accent"] | curses.A_BOLD if is_focused else curses.A_NORMAL
            _safe_addnstr(stdscr, s, col_x, prefix, 2, prefix_attr)
            _safe_addnstr(stdscr, s, col_x + 2, marker, 1, marker_attr)
            name_attr = attrs_local["accent"] | curses.A_BOLD if is_selected else curses.A_NORMAL
            # Name fits in the 15-char slot starting at col_x+4, capped before divider
            _safe_addnstr(stdscr, s, col_x + 4, f" {fname}".ljust(14)[:14], 14, name_attr)

        for row_idx in range(_n_font_rows):
            # Left column: font at row_idx
            _draw_font_item(vrow, 0, row_idx, _banner_fonts[row_idx])
            # Right column: font at n_font_rows + row_idx (may not exist)
            right_fi = _n_font_rows + row_idx
            if right_fi < len(_banner_fonts):
                _draw_font_item(vrow, _COL2_X, right_fi, _banner_fonts[right_fi])
            # Vertical divider
            if _preview_avail > 10 and _DIV_X < max_x - 1 and _vis(vrow):
                _safe_addnstr(stdscr, _sr(vrow), _DIV_X, "\u2502", 1, attrs_local["dim"])
            vrow += 1

        # Preview overlay: anchored to font_section_vrow so it scrolls with the list.
        if _preview_avail > 10:
            _prv_attr = attrs_local["accent"] | curses.A_BOLD
            for li, pline in enumerate(_preview_lines):
                pv = font_section_vrow + li
                if _vis(pv) and pline.strip():
                    _safe_addnstr(stdscr, _sr(pv), _PRV_X, pline, _preview_avail, _prv_attr)

        vrow += 1  # blank line

        # Animation
        _draw_vr(vrow, 2, ("Animation " + "\u2500" * 30)[: max_x - 3], max_x - 3, attrs_local["accent"] | curses.A_BOLD)
        vrow += 1

        # Divider + preview column layout.
        _A_DIV_X, _A_PRV_X = 20, 22
        _anim_avail = max_x - _A_PRV_X - 1

        # Compute ONE live frame per pack using Rich spinner data + wall-clock time.
        # Each pack's frame advances at its spinner's native interval (ms).
        _rich_spinners = _get_rich_spinner_data()
        _now_ms = int(time.time() * 1000)
        _live_frames: dict[str, str] = {}
        for _pn, _pcfg in _ANIM_PACKS.items():
            _sp = _pcfg.get("spinner")
            if _sp and _sp in _rich_spinners:
                _sp_data = _rich_spinners[_sp]
                _sp_frames = _sp_data["frames"]
                _sp_interval = max(1, _sp_data["interval"])
                _fi = (_now_ms // _sp_interval) % len(_sp_frames)
                _live_frames[_pn] = _sp_frames[_fi]
            elif _pn == "minimal":
                # Star blink at ~4 Hz
                _live_frames[_pn] = "\u2736" if (_now_ms // 250) % 2 == 0 else "\u2737"
            else:
                _live_frames[_pn] = "\u2500"  # ─

        _pack_off = _p0_pack_offset()
        for pi, pname in enumerate(_VALID_ANIM_PACKS):
            if _vis(vrow):
                s = _sr(vrow)
                pi_abs = _pack_off + pi
                is_focused = pi_abs == page0_cursor
                is_selected = pi == current_pack_idx
                pcfg = _ANIM_PACKS[pname]
                marker = "\u25c6" if is_selected else "\u00b7"
                marker_attr = attrs_local["accent"] | curses.A_BOLD if is_selected else attrs_local["dim"]
                prefix = "\u25b8 " if is_focused else "  "
                prefix_attr = attrs_local["accent"] | curses.A_BOLD if is_focused else curses.A_NORMAL
                _safe_addnstr(stdscr, s, 0, prefix, 2, prefix_attr)
                _safe_addnstr(stdscr, s, 2, marker, 1, marker_attr)
                label_attr = attrs_local["accent"] | curses.A_BOLD if is_selected else curses.A_NORMAL
                pack_label = f" {pcfg['label']}".ljust(10)
                _safe_addnstr(stdscr, s, 4, pack_label, len(pack_label), label_attr)
                # Vertical divider
                if _A_DIV_X < max_x - 1:
                    _safe_addnstr(stdscr, s, _A_DIV_X, "\u2502", 1, attrs_local["dim"])
                # Live frame right of divider — only for the focused pack
                if is_focused and _anim_avail > 2:
                    lf = _live_frames.get(pname, "\u00b7")
                    _safe_addnstr(
                        stdscr,
                        s,
                        _A_PRV_X,
                        f" {lf}",
                        min(len(lf) + 2, _anim_avail),
                        attrs_local["accent"] | curses.A_BOLD,
                    )
            vrow += 1

        vrow += 1  # blank line

        # Randomize
        _draw_vr(vrow, 2, ("Randomize " + "\u2500" * 30)[: max_x - 3], max_x - 3, attrs_local["accent"] | curses.A_BOLD)
        vrow += 1

        # Random toggle
        if _vis(vrow):
            s = _sr(vrow)
            is_focused = page0_cursor == _p0_rand_idx()
            prefix = "\u25b8 " if is_focused else "  "
            prefix_attr = attrs_local["accent"] | curses.A_BOLD if is_focused else curses.A_NORMAL
            _safe_addnstr(stdscr, s, 0, prefix, 2, prefix_attr)
            dot = "\u25c9" if random_theme_on else "\u25cb"
            dot_attr = attrs_local["accent"] | curses.A_BOLD if random_theme_on else attrs_local["dim"]
            _safe_addnstr(stdscr, s, 2, dot, 1, dot_attr)
            label2 = "  Random theme       "
            _safe_addnstr(stdscr, s, 3, label2[: max_x - 4], max_x - 4, curses.A_NORMAL)
            hint2 = "Pick a new theme automatically every few sessions"
            lx2 = 3 + len(label2)
            if lx2 < max_x - 4:
                _safe_addnstr(stdscr, s, lx2, hint2[: max_x - lx2 - 1], max_x - lx2 - 1, attrs_local["dim"])
        vrow += 1

        # Freq slider
        if _vis(vrow):
            s = _sr(vrow)
            is_focused = page0_cursor == _p0_freq_idx()
            TRACK_LEN = 20
            thumb_pos = int((random_theme_freq - 1) / 4 * (TRACK_LEN - 1))
            if random_theme_on:
                track = "".join(
                    "\u2588" if i < thumb_pos else ("\u25c6" if i == thumb_pos else "\u2591") for i in range(TRACK_LEN)
                )
                slider_attr = (attrs_local["accent"] | curses.A_BOLD) if is_focused else curses.A_NORMAL
                left_label, right_label = "often ", " rarely"
                label_attr = attrs_local["dim"]
                prefix_sl = "\u25b8 " if is_focused else "  "
                prefix_sl_attr = (attrs_local["accent"] | curses.A_BOLD) if is_focused else curses.A_NORMAL
            else:
                track = "\u2592" * (TRACK_LEN - 1) + "\u00b7"
                slider_attr = attrs_local["dim"]
                left_label, right_label = "----- ", " -----"
                label_attr = attrs_local["dim"]
                prefix_sl, prefix_sl_attr = "  ", attrs_local["dim"]
            cx = 0
            _safe_addnstr(stdscr, s, cx, prefix_sl, 2, prefix_sl_attr)
            cx = 2
            _safe_addnstr(stdscr, s, cx, left_label, len(left_label), label_attr)
            cx += len(left_label)
            _safe_addnstr(stdscr, s, cx, "[", 1, attrs_local["dim"])
            cx += 1
            _safe_addnstr(stdscr, s, cx, track, TRACK_LEN, slider_attr)
            cx += TRACK_LEN
            _safe_addnstr(stdscr, s, cx, "]", 1, attrs_local["dim"])
            cx += 1
            _safe_addnstr(stdscr, s, cx, right_label, len(right_label), label_attr)
        vrow += 1

        # Freq description lines
        _freq_descriptions = {
            1: ("Changes nearly every session", "Expect a new look very frequently"),
            2: ("Changes every few sessions", "Plenty of variety"),
            3: ("Changes occasionally", "Balanced \u2014 noticeable but not constant"),
            4: ("Changes infrequently", "Mostly consistent, occasional surprise"),
            5: ("Changes rarely", "Stable look with rare surprises"),
        }
        if random_theme_on:
            line1, line2 = _freq_descriptions.get(random_theme_freq, _freq_descriptions[3])
            if _vis(vrow):
                _safe_addnstr(stdscr, _sr(vrow), 4, ("\u25c6 " + line1)[: max_x - 5], max_x - 5, attrs_local["dim"])
            vrow += 1
            if _vis(vrow):
                _safe_addnstr(stdscr, _sr(vrow), 4, ("\u00b7 " + line2)[: max_x - 5], max_x - 5, attrs_local["dim"])
        else:
            if _vis(vrow):
                _safe_addnstr(
                    stdscr,
                    _sr(vrow),
                    4,
                    "\u00b7 Enable \u201cRandom theme\u201d to configure frequency"[: max_x - 5],
                    max_x - 5,
                    attrs_local["dim"],
                )

    # Helper: draw page 1 (Behavior)
    def _draw_page1(max_y, max_x):
        content_start = 3
        row = content_start

        section = "Launch behavior " + "\u2500" * max(0, 24)
        _safe_addnstr(stdscr, row, 2, section[: max_x - 3], max_x - 3, attrs["accent"] | curses.A_BOLD)
        row += 1

        toggles = [
            ("update_check", update_check, "Update check", "Check PyPI for new altergo versions"),
            ("show_greeting", show_greeting, "Greeting messages", "Time-of-day greeting on launch"),
            ("show_goodbye", show_goodbye, "Goodbye messages", "Witty message after each session"),
            ("tmux_session", tmux_session, "tmux sessions", "Wrap sessions in tmux for SSH persistence"),
        ]

        for ti, (key, val, label, hint) in enumerate(toggles):
            if row >= max_y - 3:
                break
            is_focused = ti == page1_cursor
            prefix = "\u25b8 " if is_focused else "  "
            prefix_attr = attrs["accent"] | curses.A_BOLD if is_focused else curses.A_NORMAL
            _safe_addnstr(stdscr, row, 0, prefix, 2, prefix_attr)

            if val:
                dot = "\u25c9"  # ◉
                dot_attr = attrs["accent"] | curses.A_BOLD
            else:
                dot = "\u25cb"  # ○
                dot_attr = attrs["dim"]
            _safe_addnstr(stdscr, row, 2, dot, 1, dot_attr)

            label_str = "  " + label.ljust(22)
            _safe_addnstr(stdscr, row, 3, label_str[: max_x - 4], max_x - 4, curses.A_NORMAL)
            lx = 3 + len(label_str)
            if lx < max_x - 4:
                _safe_addnstr(stdscr, row, lx, hint[: max_x - lx - 1], max_x - lx - 1, attrs["dim"])
            row += 1

    # Helper: draw page 2 (Credentials)
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
                _safe_addnstr(stdscr, screen_row, 2, section[: max_x - 3], max_x - 3, attrs["accent"] | curses.A_BOLD)
            else:
                entry = crow["entry"]
                enabled = _is_enabled(entry, cred_overrides)
                is_current = row_idx == current_row_idx
                has_warn = "warning" in entry

                warn_tag = " \u26a0" if has_warn else "  "
                path_hint = ", ".join(f"~/{p}" for p in entry["paths"])

                prefix = "\u25b8 " if is_current else "  "
                prefix_attr = attrs["accent"] | curses.A_BOLD if is_current else curses.A_NORMAL
                _safe_addnstr(stdscr, screen_row, 0, prefix, 2, prefix_attr)

                if enabled:
                    dot = "\u25c9"  # ◉
                    dot_attr = attrs["accent"] | curses.A_BOLD
                else:
                    dot = "\u25cb"  # ○
                    dot_attr = attrs["dim"]
                _safe_addnstr(stdscr, screen_row, 2, dot, 1, dot_attr)

                name_str = "  " + entry["name"].ljust(22) + warn_tag
                _safe_addnstr(
                    stdscr,
                    screen_row,
                    3,
                    name_str[: max_x - 4],
                    max_x - 4,
                    curses.A_BOLD if is_current else curses.A_NORMAL,
                )
                nx = 3 + len(name_str)
                if nx < max_x - 4:
                    _safe_addnstr(stdscr, screen_row, nx, path_hint[: max_x - nx - 1], max_x - nx - 1, attrs["dim"])

    # Helper: draw footer
    def _draw_footer(max_y, max_x):
        footer_row = max_y - 2

        if current_page == 0:
            # Show contextual hint for the focused row
            T = len(theme_names)
            F = len(_banner_fonts)
            P = len(_VALID_ANIM_PACKS)
            if page0_cursor < T:
                hint = "  " + THEMES[theme_names[page0_cursor]]["description"]
            elif page0_cursor < T + F:
                fi = page0_cursor - T
                hint = f"  Preview: '{_banner_fonts[fi]}' — select with ↑↓, saved with s"
            elif page0_cursor < T + F + P:
                pi = page0_cursor - T - F
                hint = f"  {_ANIM_PACKS[_VALID_ANIM_PACKS[pi]]['hint']}"
            elif page0_cursor == _p0_rand_idx():
                hint = "  Picks a different theme automatically every few sessions"
            else:
                hint = "  Use \u2190 \u2192 to set how often the theme rotates"
            _safe_addnstr(stdscr, footer_row, 0, hint[: max_x - 1], max_x - 1, attrs["dim"])

        elif current_page == 1:
            hints_behavior = [
                "  Default on. Checks PyPI daily — can be disabled for air-gapped setups",
                "  Friendly time-of-day line shown beneath the banner on launch",
                "  Witty one-liner printed to stderr after every session ends",
                "  Each session runs inside a named tmux window — survive SSH drops, reattach anytime",
            ]
            if 0 <= page1_cursor < len(hints_behavior):
                _safe_addnstr(stdscr, footer_row, 0, hints_behavior[page1_cursor][: max_x - 1], max_x - 1, attrs["dim"])

        elif current_page == 2:
            current_row_idx = cred_selectable[page2_cursor]
            crow = cred_rows[current_row_idx]
            if crow["type"] == "entry" and crow["entry"].get("warning"):
                warn_line = "  \u26a0  " + crow["entry"]["warning"]
                _safe_addnstr(
                    stdscr, footer_row, 0, warn_line[: max_x - 1], max_x - 1, curses.color_pair(7) | curses.A_DIM
                )

        _on_freq_slider = current_page == 0 and page0_cursor == _p0_freq_idx() and random_theme_on
        if _on_freq_slider:
            nav = "  \u2191\u2193/jk navigate  \u2190\u2192/hl adjust  Space toggle  Tab page  s save  q/Esc cancel"
        else:
            nav = "  \u2191\u2193/jk navigate  Space toggle  \u2190\u2192/hl/Tab page  s save  q/Esc cancel"
        _safe_addnstr(stdscr, max_y - 1, 0, nav[: max_x - 1], max_x - 1, attrs["dim"])

    # Main event loop
    while True:
        stdscr.erase()
        max_y, max_x = stdscr.getmaxyx()

        # Reload attrs in case theme changed (live preview)
        attrs = _picker_attrs("settings")

        # Tab bar (row 0)
        _draw_tab_bar(max_x)

        # Page subtitle (row 1)
        subtitle = "  " + _SETTINGS_PAGES[current_page]["subtitle"]
        _safe_addnstr(stdscr, 1, 0, subtitle[: max_x - 1], max_x - 1, attrs["dim"])

        # Separator (row 2) — accent fade: first 8 chars in theme accent, rest dim
        sep_full = "\u2500" * (max_x - 1)
        accent_len = min(8, max_x - 1)
        _safe_addnstr(stdscr, 2, 0, sep_full[:accent_len], accent_len, attrs["accent"])
        if accent_len < max_x - 1:
            _safe_addnstr(stdscr, 2, accent_len, sep_full[accent_len : max_x - 1], max_x - 1 - accent_len, attrs["dim"])

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

        # On page 0, use a short timeout so the animation preview ticks in real
        # time.  KEY_RESIZE and normal input still work; getch returns -1 on timeout.
        stdscr.timeout(80 if current_page == 0 else -1)
        key = stdscr.getch()

        # Timeout with no keypress — just redraw (animation tick)
        if key == -1:
            continue

        # Page navigation
        # Only Tab / Shift-Tab switch pages.  ←/→ are reserved for per-page use.
        if key == ord("\t"):  # Tab → next page
            current_page = (current_page + 1) % n_pages
            continue
        elif key == curses.KEY_BTAB:  # Shift-Tab → prev page
            current_page = (current_page - 1) % n_pages
            continue

        # Global keys
        elif key in (ord("q"), 27):  # Esc / q → cancel
            # Restore original theme on cancel
            set_current_theme(original_theme)
            _picker_attrs("settings")  # reinit color pairs for restored theme
            return None

        elif key == ord("s"):  # Save
            return {
                "theme": theme_names[current_theme_idx],
                "banner_font": _banner_fonts[current_font_idx] if _banner_fonts else _DEFAULT_BANNER_FONT,
                "animation_pack": _VALID_ANIM_PACKS[current_pack_idx],
                "update_check": update_check,
                "show_greeting": show_greeting,
                "show_goodbye": show_goodbye,
                "tmux_session": tmux_session,
                "random_theme_enabled": random_theme_on,
                "random_theme_frequency": random_theme_freq,
                "shared": {k: v for k, v in cred_overrides.items() if cred_defaults.get(k) != v},
            }

        elif key == curses.KEY_RESIZE:
            if current_page == 0:
                _page0_ensure_visible()
            continue

        # ── Per-page navigation & toggling ──────────────────────────────────
        elif current_page == 0:
            _foff = _p0_font_offset()
            _in_font_section = _foff <= page0_cursor < _foff + len(_banner_fonts)

            if key in (curses.KEY_UP, ord("k")):
                if _in_font_section:
                    fi = page0_cursor - _foff
                    col = fi // _n_font_rows
                    row_in_col = fi % _n_font_rows
                    if row_in_col == 0:
                        # Top of column → exit upward to last theme
                        page0_cursor = _foff - 1
                    else:
                        # Move up within the same column
                        page0_cursor = _foff + col * _n_font_rows + (row_in_col - 1)
                else:
                    new_cur = page0_cursor - 1
                    if new_cur == _p0_freq_idx() and not random_theme_on:
                        new_cur -= 1
                    page0_cursor = max(0, new_cur)
                _page0_ensure_visible()
            elif key in (curses.KEY_DOWN, ord("j")):
                if _in_font_section:
                    fi = page0_cursor - _foff
                    col = fi // _n_font_rows
                    row_in_col = fi % _n_font_rows
                    # Last row of left col = n_font_rows-1; right col = F-n_font_rows-1
                    max_row = _n_font_rows - 1 if col == 0 else (len(_banner_fonts) - _n_font_rows - 1)
                    if row_in_col >= max_row:
                        # Bottom of column → exit downward to first pack
                        page0_cursor = _foff + len(_banner_fonts)
                    else:
                        page0_cursor = _foff + col * _n_font_rows + (row_in_col + 1)
                else:
                    new_cur = page0_cursor + 1
                    if new_cur == _p0_freq_idx() and not random_theme_on:
                        new_cur += 1
                    page0_cursor = min(page0_n - 1, new_cur)
                _page0_ensure_visible()
            elif key in (ord(" "), curses.KEY_ENTER, 10, 13):
                _poff_sp = _p0_pack_offset()
                if page0_cursor < len(theme_names):
                    current_theme_idx = page0_cursor
                    set_current_theme(theme_names[current_theme_idx])
                elif _foff <= page0_cursor < _foff + len(_banner_fonts):
                    current_font_idx = page0_cursor - _foff
                elif _poff_sp <= page0_cursor < _poff_sp + len(_VALID_ANIM_PACKS):
                    current_pack_idx = page0_cursor - _poff_sp
                elif page0_cursor == _p0_rand_idx():
                    random_theme_on = not random_theme_on
            elif key in (curses.KEY_LEFT, ord("h")):
                if page0_cursor == _p0_freq_idx() and random_theme_on:
                    random_theme_freq = max(1, random_theme_freq - 1)
                elif _in_font_section:
                    # Move from right column → left column (same row)
                    fi = page0_cursor - _foff
                    col = fi // _n_font_rows
                    if col == 1:
                        page0_cursor = _foff + fi % _n_font_rows
                        _page0_ensure_visible()
            elif key in (curses.KEY_RIGHT, ord("l")):
                if page0_cursor == _p0_freq_idx() and random_theme_on:
                    random_theme_freq = min(5, random_theme_freq + 1)
                elif _in_font_section:
                    # Move from left column → right column (same row)
                    fi = page0_cursor - _foff
                    col = fi // _n_font_rows
                    if col == 0:
                        target_fi = _n_font_rows + fi % _n_font_rows
                        if target_fi < len(_banner_fonts):
                            page0_cursor = _foff + target_fi
                            _page0_ensure_visible()

            # Theme live preview follows cursor, but the committed selection
            # (current_theme_idx / ◆ marker) only moves on Space/Enter above.
            if page0_cursor < len(theme_names):
                hover_theme = theme_names[page0_cursor]
                if hover_theme != get_current_theme():
                    set_current_theme(hover_theme)

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
                elif page1_cursor == 3:
                    tmux_session = not tmux_session

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
                new_val = not _is_enabled(entry, cred_overrides)
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

    # Persist all settings in a single atomic write
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
    data["banner_font"] = result.get("banner_font", _DEFAULT_BANNER_FONT)
    data["animation_pack"] = result.get("animation_pack", _DEFAULT_ANIM_PACK)
    # launch_animation is the old boolean key — keep it in sync as a migration aid
    # so older altergo versions fall back gracefully if the user rolls back.
    data["launch_animation"] = data["animation_pack"] != "off"
    data["update_check"] = result.get("update_check", True)
    data["show_greeting"] = result.get("show_greeting", True)
    data["show_goodbye"] = result.get("show_goodbye", True)
    data["tmux_session"] = result.get("tmux_session", False)
    data["random_theme_enabled"] = result.get("random_theme_enabled", False)
    data["random_theme_frequency"] = result.get("random_theme_frequency", 3)
    # random_theme_counter is managed by maybe_rotate_random_theme — do not touch it here
    data["version"] = 1
    cred_defaults = {e["id"]: e["default_on"] for e in CATALOG}
    data["shared"] = {k: v for k, v in shared_overrides.items() if cred_defaults.get(k) != v}
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


### Keychain isolation (macOS)
#
# [keychain-impl] Empirical verifications performed 2026-04-20 on macOS 25.2.0:
#
# 1. DbName suffix: ~/Library/Preferences/com.apple.security.plist on this Mac
#    uses "~/Library/Keychains/login.keychain" (NO "-db" suffix). Plan B's
#    claim of "-db" was wrong — we use the no-suffix form to match the OS.
#    The on-disk file is "login.keychain-db" but the plist references the
#    legacy name without suffix; macOS resolves both.
#
# 2. set-keychain-settings with no flags: confirmed from `man security` that
#    omitting -l and -u means no lock-on-sleep and no timeout (never locks).
#    No -t flag needed.
#
# 3. -T /usr/bin/security trust: sufficient on this macOS version. The security
#    binary can find-generic-password -w without a GUI prompt because the
#    unlock entry is stored in the already-unlocked login keychain (open since
#    GUI login). Verified by end-to-end test on a throwaway account.

SECURITY_CMD = "/usr/bin/security"
_KC_SERVICE = "com.altergo.account-unlock"
_KC_GUID = "{87191ca3-0fc9-11d4-849a-000502b52122}"  # Apple CSSM DL GUID — constant across all Macs
_KC_SUBSERVICE_TYPE = 6  # CSSM_SERVICE_DL


class KeychainError(Exception):
    """Raised when a /usr/bin/security operation fails in an unexpected way."""


def _sec(argv: list, *, check: bool = True, timeout: int = 10) -> subprocess.CompletedProcess:
    """Thin wrapper around /usr/bin/security."""
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
    """Return the per-account keychain file path. Pure."""
    return account_home / "Library" / "Keychains" / "login.keychain-db"


def _keychain_prefs_path(account_home: Path) -> Path:
    """Return the per-account security preferences plist path. Pure."""
    return account_home / "Library" / "Preferences" / "com.apple.security.plist"


def _write_keychain_prefs(account_home: Path) -> None:
    """Write com.apple.security.plist so processes with HOME=account_home use the per-account keychain."""
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


def _create_account_keychain(account_home: Path, slug: str) -> None:
    """Create (or reconcile) the per-account keychain and its unlock entry.

    Explicit case analysis on (C, D) presence so every partial-state the
    failure matrix enumerates falls through to a consistent fresh build:

    Case 1 — C present, D present, unlock succeeds  → reuse (write B, return).
    Case 2 — C present, D present, unlock fails      → delete C+D, fall through.
    Case 3 — C present, D absent (orphan)            → delete C,   fall through.
    Case 4 — C absent,  D present (stale entry)      → delete D,   fall through.
    Case 5 — C absent,  D absent  (fresh)            → build from scratch.

    After every path B (plist) is written, establishing invariant §5.3.
    """
    kc_path = _keychain_path(account_home)
    kc_path.parent.mkdir(parents=True, exist_ok=True)

    c_present = kc_path.exists()
    d_result = _sec(["find-generic-password", "-s", _KC_SERVICE, "-a", slug, "-w"], check=False)
    d_present = d_result.returncode == 0

    if c_present and d_present:
        # Probe whether D's password actually unlocks C (Case 1 vs Case 2).
        P_probe = d_result.stdout.rstrip("\n")
        probe = _sec(["unlock-keychain", "-p", P_probe, str(kc_path)], check=False)
        if probe.returncode == 0:
            # Case 1: consistent pair, reuse — invariants §5.3, §5.4 satisfied.
            print(_c(2, "  Keychain already exists, reusing"))
            _write_keychain_prefs(account_home)
            return
        # Case 2: password mismatch — delete C and D, rebuild.
        print(_c(2, "  Keychain password mismatch — rebuilding"), file=sys.stderr)
        _sec(["delete-keychain", str(kc_path)], check=False)
        _sec(["delete-generic-password", "-s", _KC_SERVICE, "-a", slug], check=False)

    elif c_present and not d_present:
        # Case 3: orphaned keychain file — delete C, rebuild.
        print(_c(2, "  Orphaned keychain file found — rebuilding"), file=sys.stderr)
        _sec(["delete-keychain", str(kc_path)], check=False)

    elif not c_present and d_present:
        # Case 4: stale unlock entry — delete D, rebuild.
        _sec(["delete-generic-password", "-s", _KC_SERVICE, "-a", slug], check=False)

    # Case 5 (and fall-through from cases 2–4): fresh build.
    # C and D are both absent at this point.
    P = secrets.token_bytes(32).hex()  # 64 hex chars, 256-bit entropy

    _sec(["create-keychain", "-p", P, str(kc_path)])
    # No flags = no auto-lock, no lock-on-sleep, no timeout (confirmed from man security).
    _sec(["set-keychain-settings", str(kc_path)])

    # Store unlock password in the real login keychain. -T /usr/bin/security
    # grants the security binary ACL access so unlock-keychain works in
    # non-GUI contexts (SSH, tmux, cron) without a GUI authorization prompt.
    _sec(["add-generic-password", "-s", _KC_SERVICE, "-a", slug, "-w", P, "-T", SECURITY_CMD])

    # Write B last: B present implies C+D present (invariant §5.3).
    _write_keychain_prefs(account_home)


def _unlock_account_keychain(account_home: Path, slug: str) -> None:
    """Unlock the per-account keychain using the stored password."""
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
    """Remove the per-account keychain, its unlock entry, and the routing plist.

    Removes B+C+D so do_delete_account leaves no keychain artifacts (invariant §5.5).
    """
    _sec(["delete-keychain", str(_keychain_path(account_home))], check=False)
    _sec(["delete-generic-password", "-s", _KC_SERVICE, "-a", slug], check=False)
    # Remove B so Security.framework routing is fully torn down.
    _keychain_prefs_path(account_home).unlink(missing_ok=True)


def _is_keychain_isolated(meta: dict | None) -> bool:
    """Return True if the account metadata requests per-account keychain isolation."""
    return bool(meta) and meta.get("keychain") == "isolated"


def _reconcile_keychain_state(account_home: Path, slug: str, desired: str | None = None) -> None:
    """Reconcile (A, B, C, D) to a consistent state.

    desired="isolated": ensure B+C+D exist and are consistent; write A="isolated".
    desired="system":   remove B; leave C+D alone (user didn't ask to lose tokens);
                        write A="system".
    desired=None:       launch-time drift repair. Read B. If B present and (C missing,
                        D missing, or unlock fails) → rebuild (treat as desired=isolated).
                        If B absent and A says isolated → repair A to system (non-destructive;
                        routing is already system because B is absent).
                        Never delete user data at launch time.

    Call sites:
    - _build_alt_env: desired=None (launch-time silent repair).
    - do_config:      desired=keychain_mode (explicit intent).
    - do_delete_account: not needed — destructive by design; the presence probe handles it.
    """
    meta = load_account_meta(account_home)
    b_present = _keychain_prefs_path(account_home).exists()
    c_present = _keychain_path(account_home).exists()
    d_result = _sec(["find-generic-password", "-s", _KC_SERVICE, "-a", slug, "-w"], check=False)
    d_present = d_result.returncode == 0

    if desired == "isolated":
        # Explicit upgrade: _create_account_keychain reconciles C+D, writes B.
        # do_config calls _create_account_keychain separately; this path is
        # available as a standalone reconcile entry point.
        _create_account_keychain(account_home, slug)
        new_meta = dict(meta) if meta else {}
        new_meta["keychain"] = "isolated"
        save_account_meta(account_home, new_meta)
        return

    if desired == "system":
        # Remove B so routing falls back to real user keychain.  Preserve C+D.
        _keychain_prefs_path(account_home).unlink(missing_ok=True)
        new_meta = dict(meta) if meta else {}
        new_meta["keychain"] = "system"
        save_account_meta(account_home, new_meta)
        return

    # desired=None: launch-time drift detection.  Must be cheap — only shell out
    # if state is actually drifted.
    a_isolated = (meta or {}).get("keychain") == "isolated"

    if not b_present and not a_isolated:
        # Both A and B agree: system mode, no isolation.  No-op.
        return

    if b_present:
        # B says isolated.  Verify C and D are consistent.
        if not c_present or not d_present:
            # C or D missing while B present — drift.  Rebuild silently.
            print(
                _c(2, f"  altergo: repairing keychain state for '{slug}'"),
                file=sys.stderr,
            )
            _create_account_keychain(account_home, slug)
            new_meta = dict(meta) if meta else {}
            new_meta["keychain"] = "isolated"
            save_account_meta(account_home, new_meta)
            return
        # C and D present — probe the unlock to confirm password consistency.
        P_probe = d_result.stdout.rstrip("\n")
        probe = _sec(["unlock-keychain", "-p", P_probe, str(_keychain_path(account_home))], check=False)
        if probe.returncode != 0:
            # Password mismatch drift — rebuild.
            print(
                _c(2, f"  altergo: repairing keychain state for '{slug}'"),
                file=sys.stderr,
            )
            _create_account_keychain(account_home, slug)
            new_meta = dict(meta) if meta else {}
            new_meta["keychain"] = "isolated"
            save_account_meta(account_home, new_meta)
            return
        # B+C+D all consistent.  Ensure A mirrors B (invariant §5.2).
        if not a_isolated:
            new_meta = dict(meta) if meta else {}
            new_meta["keychain"] = "isolated"
            save_account_meta(account_home, new_meta)
        return

    # B absent but A says isolated: non-destructive repair — just update A.
    # Routing is already system (B is absent); don't rebuild C+D at launch time.
    new_meta = dict(meta) if meta else {}
    new_meta["keychain"] = "system"
    save_account_meta(account_home, new_meta)


# Launch


def _build_alt_env(account: str = "default") -> dict:
    """Return a copy of the environment with HOME set to the account home."""
    if account == _NATIVE_ACCOUNT:
        return os.environ.copy()
    account_home, _ = resolve_account(account)
    # Launch-time drift repair: silently reconcile (A,B,C,D) before unlocking.
    # No-op when state is consistent; shells out only when drift is detected.
    # Invariants §5.1–§5.4 are established here for every non-native launch.
    if sys.platform == "darwin":
        try:
            _reconcile_keychain_state(account_home, account, desired=None)
        except KeychainError as e:
            print(f"altergo: keychain reconcile error: {e}", file=sys.stderr)
            # Continue — _unlock_account_keychain below will give a better error
            # if isolation is still expected.
    meta = load_account_meta(account_home)
    if sys.platform == "darwin" and _is_keychain_isolated(meta):
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
    return env


def _find_claude() -> str | None:
    """Find the claude binary, checking PATH and common install locations."""
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
    """Repair any accounts that still have real dirs where symlinks are expected."""
    changed = False
    for acct in list_accounts():
        account_home, account_claude = resolve_account(acct)
        meta = load_account_meta(account_home)

        if meta is not None:
            for pid in meta["providers"]:
                prov = PROVIDERS.get(pid)
                if prov is None:
                    continue
                main_dot = MAIN_HOME / prov["dot_dir"]
                acct_dot = account_home / prov["dot_dir"]
                for name in prov["symlink_dirs"]:
                    src = main_dot / name
                    dst = acct_dot / name
                    if _ensure_symlinked_dir(name, src, dst, acct_dot):
                        changed = True
        else:
            # Legacy account (no account.json at all) — fall back to Claude-only
            for name in SYMLINK_DIRS:
                src = MAIN_CLAUDE / name
                dst = account_claude / name
                if _ensure_symlinked_dir(name, src, dst, account_claude):
                    changed = True
    return changed


def _tmux_available() -> bool:
    """Return True if tmux is installed and reachable on PATH."""
    return shutil.which("tmux") is not None


def _tmux_session_name(account: str, provider: str) -> str:
    """Return a tmux session name for an altergo session."""
    safe = account.replace(".", "-").replace(":", "-")
    return f"{safe}/{provider}"


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
        if account == _NATIVE_ACCOUNT:
            # For native, detect from the real home: pick the first provider whose
            # binary is on PATH and whose dot-dir exists in MAIN_HOME.  This matches
            # the same presence check used in build_launcher_menu so the launcher and
            # CLI are consistent.  Avoids reading ~/account.json which belongs to the
            # user, not to altergo.
            for _pid, _prov in PROVIDERS.items():
                if (MAIN_HOME / _prov["dot_dir"]).exists() and shutil.which(_prov["binary"]):
                    provider = _pid
                    break
            if provider is None:
                sys.exit(
                    "altergo: no provider detected in the real $HOME.\n"
                    "  Specify one explicitly: altergo native <provider>\n"
                    f"  Known providers: {', '.join(PROVIDERS)}"
                )
        else:
            meta = load_account_meta(account_home)
            provider = meta["default_provider"] if meta is not None else "claude"
    elif account != _NATIVE_ACCOUNT:
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
        prov = PROVIDERS.get(provider)
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
    if account != _NATIVE_ACCOUNT:
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
    if provider == "claude" and account != _NATIVE_ACCOUNT:
        _sync_claude_mcps(account_home)

    print(_c(C("dim"), f"  Launching {PROVIDERS[provider]['display_name']}..."))

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
    if account != _NATIVE_ACCOUNT:
        home_change_notice_if_needed()
    # Shell starts effectively instantly, so no twinkle animation — but
    # keep the greeting + update nag for consistency with other launch paths.
    show_banner(
        account,
        latest_version=get_cached_latest_version(),
        show_greeting=_load_bool_setting("show_greeting"),
    )
    if account == _NATIVE_ACCOUNT:
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
    if account != _NATIVE_ACCOUNT:
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


# Account name disambiguation helper

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


# Interactive prompt helpers


def _prompt_new_account_name_tui(existing: list) -> str | None:
    """Full-screen curses name-entry for a brand-new account."""
    if not sys.stdin.isatty() or not sys.stdout.isatty():
        print(
            "altergo: creating an account requires an interactive terminal.\n"
            "  Use: altergo --config <account> --provider <provider>",
            file=sys.stderr,
        )
        sys.exit(1)

    def _draw(stdscr, state):
        curses.curs_set(1)
        attrs = _picker_attrs("onboarding")
        stdscr.timeout(80)
        phase = 0

        while True:
            stdscr.erase()
            max_y, max_x = stdscr.getmaxyx()

            title = " altergo — new account "
            right = " choose a name "
            pad = max(1, max_x - len(right))
            header = title.ljust(pad) + right
            _safe_addnstr(
                stdscr,
                0,
                0,
                header[:max_x],
                max_x - 1,
                attrs["title"] | curses.A_REVERSE | curses.A_BOLD,
            )
            _safe_addnstr(stdscr, 1, 0, ("─" * (max_x - 1))[: max_x - 1], max_x - 1, attrs["dim"])

            row = 3
            if existing:
                chip_line = "  existing: " + "  ".join(existing)
                _safe_addnstr(stdscr, row, 0, chip_line[: max_x - 1], max_x - 1, attrs["dim"])
                row += 2
            else:
                row += 1

            _safe_addnstr(stdscr, row, 2, "Account name", 12, attrs["project"] | curses.A_BOLD)
            row += 2

            box_w = min(max(40, max_x - 6), 64)
            box_x = 2
            box_y = row
            top = "┌" + "─" * (box_w - 2) + "┐"
            bot = "└" + "─" * (box_w - 2) + "┘"
            _safe_addnstr(stdscr, box_y, box_x, top, box_w, attrs["accent"])
            _safe_addnstr(stdscr, box_y + 2, box_x, bot, box_w, attrs["accent"])
            _safe_addnstr(stdscr, box_y + 1, box_x, "│", 1, attrs["accent"])
            _safe_addnstr(stdscr, box_y + 1, box_x + box_w - 1, "│", 1, attrs["accent"])

            buf = state["buffer"]
            inner = box_w - 4
            display = buf[-inner:] if len(buf) > inner else buf
            _safe_addnstr(
                stdscr,
                box_y + 1,
                box_x + 2,
                display,
                inner,
                attrs["project"] | curses.A_BOLD,
            )

            err = state["error"]
            status_row = box_y + 4
            if err:
                _safe_addnstr(stdscr, status_row, 2, err[: max_x - 3], max_x - 3, attrs["size_warn"] | curses.A_BOLD)
            else:
                hint = "Letters, digits, - or _. Must not start with a digit. Max 64 chars."
                _safe_addnstr(stdscr, status_row, 2, hint[: max_x - 3], max_x - 3, attrs["dim"])

            nav = "  Confirm (Enter)  ·  Edit (Backspace)  ·  Cancel (Esc)"
            _draw_animated_nav(stdscr, max_y - 1, nav, max_x - 1, phase, attrs)

            cursor_col = box_x + 2 + min(len(buf), inner)
            try:
                stdscr.move(box_y + 1, cursor_col)
            except curses.error:
                pass

            stdscr.refresh()
            key = stdscr.getch()

            if key == -1:
                phase += 1
                continue
            if key in (curses.KEY_ENTER, 10, 13):
                name = buf.strip()
                if not name:
                    state["error"] = "Name can't be empty."
                    continue
                if not re.match(r"^[a-zA-Z0-9][a-zA-Z0-9_-]*$", name) or len(name) > 64:
                    state["error"] = f"Invalid name '{name}'. Use letters/digits/-/_, must not start with digit."
                    continue
                if name in _RESERVED_NAMES:
                    state["error"] = f"'{name}' is a reserved name. Pick another."
                    continue
                if name in existing:
                    state["error"] = f"'{name}' already exists. Pick a new name or reconfigure from the menu."
                    continue
                state["result"] = name
                return
            elif key == 27:
                state["cancelled"] = True
                return
            elif key in (curses.KEY_BACKSPACE, 127, 8):
                state["buffer"] = buf[:-1]
                state["error"] = ""
            elif key == curses.KEY_RESIZE:
                continue
            elif 32 <= key < 127:
                ch = chr(key)
                if len(buf) < 64:
                    state["buffer"] = buf + ch
                    state["error"] = ""

    state = {"buffer": "", "error": "", "result": None, "cancelled": False}
    try:
        curses.wrapper(_draw, state)
    except Exception as e:
        print(f"altergo: unable to show name-entry TUI ({e}).", file=sys.stderr)
        sys.exit(1)

    if state["cancelled"]:
        return None
    return state["result"]


def _prompt_provider_picker(current_provider: str | None = None) -> str:
    """Curses-based single-select provider picker."""
    # Build ordered list: installed ones first, then others
    installed = [pid for pid, p in PROVIDERS.items() if shutil.which(p["binary"])]
    all_providers = list(PROVIDERS.keys())
    ordered = installed + [p for p in all_providers if p not in installed]

    # Determine initial highlighted provider
    if current_provider and current_provider in ordered:
        initial = current_provider
    elif installed:
        initial = installed[0]
    else:
        initial = "claude"

    # Fall back to plain result when not running in a TTY (e.g. piped input)
    if not sys.stdin.isatty() or not sys.stdout.isatty():
        return initial

    def _draw_picker(stdscr, state):
        """Inner curses draw loop. Mutates state dict in-place."""
        curses.curs_set(0)
        attrs = _picker_attrs("onboarding")
        stdscr.timeout(80)
        phase = 0

        items = state["items"]  # ordered list of provider IDs
        cursor = state["cursor"]  # currently highlighted row index

        while True:
            stdscr.erase()
            max_y, max_x = stdscr.getmaxyx()

            # Header
            header = "  Select provider  (\u2191\u2193 navigate \xb7 Enter confirm \xb7 q quit)"
            _safe_addnstr(stdscr, 0, 0, header[: max_x - 1], max_x - 1, attrs["title"])

            # Separator
            _safe_addnstr(stdscr, 1, 0, ("\u2500" * (max_x - 1))[: max_x - 1], max_x - 1, attrs["dim"])

            # Provider rows starting at line 3
            for idx, pid in enumerate(items):
                row = 3 + idx
                if row >= max_y - 2:
                    break
                p = PROVIDERS[pid]
                is_cursor = idx == cursor

                marker = ">" if is_cursor else " "
                installed_hint = " (installed)" if shutil.which(p["binary"]) else " (not found)"
                label = f"  {marker} {p['display_name']}{installed_hint}"

                row_attr = attrs["selected"] if is_cursor else attrs["dim"]
                _safe_addnstr(stdscr, row, 0, label[: max_x - 1].ljust(min(max_x - 1, 60)), max_x - 1, row_attr)

            # Nav hint at bottom
            nav = "  Confirm (Enter)  \xb7  Navigate (\u2191\u2193/jk)  \xb7  Quit (q/Esc)"
            _draw_animated_nav(stdscr, max_y - 1, nav, max_x - 1, phase, attrs)

            stdscr.refresh()
            key = stdscr.getch()

            if key == -1:
                phase += 1
                continue

            if key in (curses.KEY_UP, ord("k")):
                cursor = max(0, cursor - 1)
            elif key in (curses.KEY_DOWN, ord("j")):
                cursor = min(len(items) - 1, cursor + 1)
            elif key in (curses.KEY_ENTER, 10, 13):
                state["cursor"] = cursor
                return
            elif key in (ord("q"), 27):
                state["cancelled"] = True
                return
            elif key == curses.KEY_RESIZE:
                continue

    initial_cursor = ordered.index(initial) if initial in ordered else 0
    state = {
        "items": ordered,
        "cursor": initial_cursor,
        "cancelled": False,
    }

    try:
        curses.wrapper(_draw_picker, state)
    except Exception:
        return initial

    if state["cancelled"]:
        return current_provider or initial

    return ordered[state["cursor"]]


def _build_config_rows(accounts: list) -> list:
    """Produce the row list rendered by the --config picker."""
    active = get_active_account()
    rows = []
    for acct in accounts:
        meta = load_account_meta(ACCOUNTS_DIR / acct)
        pid = meta["default_provider"] if meta else "claude"
        email = None
        try:
            email = _read_account_email(acct)
        except Exception:
            pass
        kc_mode = meta.get("keychain") if meta else None
        rows.append(("account", acct, pid, acct == active, email, kc_mode))

    # Only offer native when at least one provider binary is actually on PATH —
    # otherwise picking it would immediately fail at launch time.
    if any(shutil.which(p["binary"]) for p in PROVIDERS.values()):
        rows.append(("native", _NATIVE_ACCOUNT, None, active == _NATIVE_ACCOUNT, None, None))

    rows.append(("create", None, None, False, None, None))
    return rows


def _confirm_delete_account_tui(account: str, path) -> bool:
    """Full-screen warning/confirm for irreversible account deletion."""

    def _draw(stdscr, state):
        curses.curs_set(0)
        attrs = _picker_attrs("onboarding")
        stdscr.timeout(80)
        phase = 0

        while True:
            stdscr.erase()
            max_y, max_x = stdscr.getmaxyx()

            title = " altergo — remove account "
            right = " irreversible "
            pad = max(1, max_x - len(right))
            header = title.ljust(pad) + right
            _safe_addnstr(
                stdscr,
                0,
                0,
                header[:max_x],
                max_x - 1,
                attrs["size_warn"] | curses.A_REVERSE | curses.A_BOLD,
            )
            _safe_addnstr(stdscr, 1, 0, ("─" * (max_x - 1))[: max_x - 1], max_x - 1, attrs["dim"])

            lines = [
                ("warn_big", f"  ⚠  Remove account '{account}'?"),
                ("blank", ""),
                ("dim", "  This will:"),
                ("dim", "    · tear down all provider symlinks"),
                ("dim", f"    · remove {path}"),
                ("dim", "    · wipe credentials and sessions stored there"),
                ("blank", ""),
                ("warn", "  This is IRREVERSIBLE."),
                ("dim", "  Provider credentials, MCP config, and local session"),
                ("dim", "  history for this account will be lost."),
            ]
            for i, (kind, ln) in enumerate(lines):
                if 3 + i >= max_y - 2:
                    break
                if kind == "warn_big":
                    attr = attrs["size_warn"] | curses.A_BOLD
                elif kind == "warn":
                    attr = attrs["size_warn"] | curses.A_BOLD
                else:
                    attr = attrs["dim"]
                _safe_addnstr(stdscr, 3 + i, 0, ln[: max_x - 1], max_x - 1, attr)

            nav = "  Confirm remove (y)  ·  Cancel (n/Esc/Enter)"
            _draw_animated_nav(stdscr, max_y - 1, nav, max_x - 1, phase, attrs)

            stdscr.refresh()
            key = stdscr.getch()

            if key == -1:
                phase += 1
                continue
            if key in (ord("y"), ord("Y")):
                state["confirmed"] = True
                return
            if key in (ord("n"), ord("N"), 27, curses.KEY_ENTER, 10, 13, ord("q")):
                state["confirmed"] = False
                return
            if key == curses.KEY_RESIZE:
                continue

    state = {"confirmed": False}
    try:
        curses.wrapper(_draw, state)
    except Exception:
        return False
    return state["confirmed"]


def _run_config_picker(accounts: list, start_cursor: int = 0) -> tuple | None:
    """Render the config picker once and return an action tuple:."""

    def _draw(stdscr, state):
        curses.curs_set(0)
        attrs = _picker_attrs("onboarding")
        stdscr.timeout(80)
        phase = 0
        cursor = state["cursor"]
        rows = _build_config_rows(accounts)

        def _clamp(c):
            return max(0, min(c, len(rows) - 1))

        while True:
            stdscr.erase()
            max_y, max_x = stdscr.getmaxyx()

            n_accts = sum(1 for r in rows if r[0] == "account")
            has_native = any(r[0] == "native" for r in rows)
            n_active = sum(1 for r in rows if r[0] in ("account", "native") and r[3])
            acct_s = "s" if n_accts != 1 else ""
            native_tag = " +native" if has_native else ""
            right = f"{n_accts} account{acct_s}{native_tag} · {n_active} active "
            title = " altergo — configure account "
            pad = max(1, max_x - len(right))
            header = title.ljust(pad) + right
            _safe_addnstr(
                stdscr,
                0,
                0,
                header[:max_x],
                max_x - 1,
                attrs["title"] | curses.A_REVERSE | curses.A_BOLD,
            )
            _safe_addnstr(stdscr, 1, 0, ("─" * (max_x - 1))[: max_x - 1], max_x - 1, attrs["dim"])

            name_w = 14
            prov_w = 14

            base = 3
            y_offset = 0
            for i, r in enumerate(rows):
                y = base + i + y_offset
                # Spacer rows above 'native' and 'create' entries.
                if r[0] in ("native", "create") and i > 0 and rows[i - 1][0] == "account":
                    y_offset += 1
                    y += 1
                elif r[0] == "create" and i > 0 and rows[i - 1][0] == "native":
                    y_offset += 1
                    y += 1
                if y >= max_y - 3:
                    break
                is_cursor = i == cursor

                if r[0] == "account":
                    _kind, name, pid, is_active, email, kc_mode = r
                    prov_label = PROVIDERS.get(pid, {}).get("display_name", pid or "")
                    marker = "●" if is_active else " "
                    email_str = email or ""
                    kc_suffix = "  ·  keychain: isolated" if kc_mode == "isolated" else ""
                    line = (
                        f"  {marker} {name[:name_w].ljust(name_w)}"
                        f"  {prov_label[:prov_w].ljust(prov_w)}  {email_str}{kc_suffix}"
                    )
                    row_attr = attrs["selected"] if is_cursor else attrs["dim"]
                    if is_active and not is_cursor:
                        row_attr = attrs["accent"]
                    _safe_addnstr(stdscr, y, 0, line[: max_x - 1].ljust(max_x - 1), max_x - 1, row_attr)
                elif r[0] == "native":
                    _kind, name, _pid, is_active, _, _kc = r
                    marker = "●" if is_active else " "
                    line = (
                        f"  {marker} {name[:name_w].ljust(name_w)}  "
                        f"{'real $HOME'.ljust(prov_w)}  (passthrough · no isolation)"
                    )
                    if is_cursor:
                        row_attr = attrs["selected"]
                    elif is_active:
                        row_attr = attrs["accent"]
                    else:
                        row_attr = attrs["time"]
                    _safe_addnstr(stdscr, y, 0, line[: max_x - 1].ljust(max_x - 1), max_x - 1, row_attr)
                else:
                    label = "  + Create new account"
                    row_attr = attrs["selected"] if is_cursor else attrs["accent"] | curses.A_BOLD
                    _safe_addnstr(stdscr, y, 0, label[: max_x - 1].ljust(max_x - 1), max_x - 1, row_attr)

            # Context hint — varies with the highlighted row.
            cur_kind = rows[cursor][0] if rows else ""
            if cur_kind == "native":
                hint = "  native passthrough — press d to make it default. Enter also sets default."
            elif cur_kind == "account":
                hint = "  Enter = reconfigure · d = set as default · r/Delete = remove (irreversible)"
            else:
                hint = "  Create a new account."
            _safe_addnstr(stdscr, max_y - 3, 0, hint[: max_x - 1], max_x - 1, attrs["dim"])

            nav = "  Enter · Default (d) · Remove (r) · ↑↓/jk · Quit (q/Esc)"
            _draw_animated_nav(stdscr, max_y - 1, nav, max_x - 1, phase, attrs)

            stdscr.refresh()
            key = stdscr.getch()

            if key == -1:
                phase += 1
                continue
            if key in (curses.KEY_UP, ord("k")):
                cursor = _clamp(cursor - 1)
            elif key in (curses.KEY_DOWN, ord("j")):
                cursor = _clamp(cursor + 1)
            elif key in (curses.KEY_ENTER, 10, 13):
                state["cursor"] = cursor
                picked = rows[cursor]
                if picked[0] == "native":
                    # Native can't be "configured" — Enter here means "make default".
                    set_active_account(picked[1])
                    rows = _build_config_rows(accounts)
                    confirm = f" ✓ '{picked[1]}' set as default account "
                    _safe_addnstr(
                        stdscr,
                        max_y - 1,
                        0,
                        confirm[: max_x - 1].ljust(max_x - 1),
                        max_x - 1,
                        attrs["accent"],
                    )
                    stdscr.refresh()
                    curses.napms(800)
                    continue
                state["action"] = "select"
                return
            elif key in (ord("d"), ord("D")):
                picked = rows[cursor]
                if picked[0] in ("account", "native"):
                    set_active_account(picked[1])
                    rows = _build_config_rows(accounts)
                    confirm = f" ✓ '{picked[1]}' set as default account "
                    _safe_addnstr(
                        stdscr,
                        max_y - 1,
                        0,
                        confirm[: max_x - 1].ljust(max_x - 1),
                        max_x - 1,
                        attrs["accent"],
                    )
                    stdscr.refresh()
                    curses.napms(800)
            elif key in (ord("r"), ord("R"), curses.KEY_DC):
                picked = rows[cursor]
                if picked[0] == "account":
                    state["cursor"] = cursor
                    state["action"] = "remove"
                    return
                elif picked[0] == "native":
                    msg = " native is a reserved passthrough — nothing to remove "
                    _safe_addnstr(
                        stdscr,
                        max_y - 1,
                        0,
                        msg[: max_x - 1].ljust(max_x - 1),
                        max_x - 1,
                        attrs["size_warn"],
                    )
                    stdscr.refresh()
                    curses.napms(900)
            elif key in (ord("q"), 27):
                state["action"] = "quit"
                return
            elif key == curses.KEY_RESIZE:
                continue

    # Clamp relative to the rows we're about to build.
    prelim_rows = _build_config_rows(accounts)
    clamped = max(0, min(start_cursor, len(prelim_rows) - 1))
    state = {"cursor": clamped, "action": None}
    try:
        curses.wrapper(_draw, state)
    except Exception as e:
        print(f"altergo: unable to show config TUI ({e}).", file=sys.stderr)
        sys.exit(1)

    if state["action"] == "quit" or state["action"] is None:
        return None

    # Rebuild once more to decode the final cursor position — rows may have
    # shifted during set-default flashes (cursor index stays stable so this is
    # purely to read the row kind at that index).
    final_rows = _build_config_rows(accounts)
    idx = max(0, min(state["cursor"], len(final_rows) - 1))
    picked = final_rows[idx]
    if state["action"] == "remove" and picked[0] == "account":
        return ("remove", picked[1], idx)
    if picked[0] == "account":
        return ("account", picked[1])
    return ("create",)


def _prompt_config_menu(existing: list) -> str | None:
    """Curses TUI listing existing accounts + a 'Create new' entry."""
    if not sys.stdin.isatty() or not sys.stdout.isatty():
        print(
            "altergo: --config requires an interactive terminal.\n"
            "  Use: altergo --config <account> --provider <provider>",
            file=sys.stderr,
        )
        sys.exit(1)

    cursor = 0
    accounts = list(existing)
    while True:
        if not accounts:
            # All accounts deleted during this session — fall through to the
            # new-account name entry rather than stranding the user.
            return _prompt_new_account_name_tui([])

        action = _run_config_picker(accounts, start_cursor=cursor)
        if action is None:
            return None

        kind = action[0]
        if kind == "account":
            return action[1]
        if kind == "create":
            return _prompt_new_account_name_tui(accounts)
        if kind == "remove":
            target = action[1]
            cursor = action[2]
            if _confirm_delete_account_tui(target, ACCOUNTS_DIR / target):
                do_delete_account(target)
                try:
                    input("  Press Enter to continue… ")
                except (KeyboardInterrupt, EOFError):
                    return None
            accounts = list_accounts()
            cursor = min(cursor, max(0, len(accounts) - 1))


# Goodbye messages
#
# The bank lives in :mod:`altergo_greetings` (``GOODBYES``) alongside the
# greeting bank — both are session-message copy and share the same voice rules.


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


# Interactive provider+account launcher

_LAUNCHER_PROVIDERS = [
    {"id": "claude", "label": "anthropic", "binary": "claude"},
    {"id": "gemini", "label": "gemini", "binary": "gemini"},
    {"id": "codex", "label": "openai", "binary": "codex"},
    {"id": "copilot", "label": "github", "binary": "copilot"},
]


def build_launcher_menu() -> list:
    """Build provider-grouped account menu for the interactive launcher."""
    accounts = list_accounts()
    # Group accounts by their provider(s) from account.json.  Multi-provider
    # accounts appear under every provider they host — the user picks which
    # tool to launch by selecting the chip under the right provider header.
    provider_accounts: dict = {}
    for acct in accounts:
        acct_home = ACCOUNTS_DIR / acct
        meta = load_account_meta(acct_home)
        providers_for_acct = meta["providers"] if meta else ["claude"]
        for pid in providers_for_acct:
            provider_accounts.setdefault(pid, []).append(acct)

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

    # Inject "native" chips for every provider whose binary is available.
    # Native runs with the real $HOME unchanged — no dot-dir isolation needed,
    # so we only require the binary to be on PATH (not a pre-existing dot-dir).
    for lp in _LAUNCHER_PROVIDERS:
        pid = lp["id"]
        prov = PROVIDERS.get(pid)
        if prov is None:
            continue
        if shutil.which(lp["binary"]):
            provider_accounts.setdefault(pid, [])
            if _NATIVE_ACCOUNT not in provider_accounts[pid]:
                provider_accounts[pid].append(_NATIVE_ACCOUNT)

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
            chips.append(
                {
                    "name": acct,
                    "age": acct_ages.get(acct, ""),
                    "available": available,
                }
            )
        menu.append({"provider_id": pid, "label": label, "accounts": chips})
    return menu


def _draw_launcher(stdscr, menu, context_msg: str | None = None):
    """Two-axis curses TUI: ↑↓ providers, ←→ account chips. Returns (account, provider_id, shell_mode)."""
    curses.curs_set(0)
    attrs = _picker_attrs("launcher")
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

        # Header — styled like the settings tab bar (reverse video + bold)
        # so the launcher visually matches the settings/help TUIs.
        title = " altergo — pick account " if context_msg else " altergo — launch"
        prov_s = "s" if n_providers != 1 else ""
        acct_s = "s" if total_accounts != 1 else ""
        right = f"{n_providers} provider{prov_s} · {total_accounts} account{acct_s} "
        header = title.ljust(max_x - len(right)) + right
        _safe_addnstr(stdscr, 0, 0, header[:max_x], max_x - 1, attrs["title"] | curses.A_REVERSE | curses.A_BOLD)

        # Separator
        _safe_addnstr(stdscr, 1, 0, ("─" * (max_x - 1))[: max_x - 1], max_x - 1, attrs["dim"])

        # Optional context banner — rendered when the picker is invoked as a
        # single-shot pass-through (e.g. --yolo-resume with no active account).
        grid_start = 3
        if context_msg:
            _safe_addnstr(stdscr, 2, 2, context_msg[: max_x - 3], max_x - 3, attrs["accent"] | curses.A_BOLD)
            _safe_addnstr(
                stdscr,
                3,
                2,
                "The selected account will be set as default and receive the pending args.",
                max_x - 3,
                attrs["dim"],
            )
            grid_start = 5

        # Provider rows (start below the optional banner, blank row between each)
        row = grid_start
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
                    _safe_addnstr(stdscr, row, x, chip_str[: max_x - x - 1], max_x - x - 1, attrs["dim"])
                elif is_selected:
                    chip_str = f"▓ {chip_text} ▓ "
                    _safe_addnstr(stdscr, row, x, chip_str[: max_x - x - 1], max_x - x - 1, attrs["selected"])
                elif is_focused_row:
                    chip_str = f"░ {chip_text} ░ "
                    _safe_addnstr(stdscr, row, x, chip_str[: max_x - x - 1], max_x - x - 1, attrs["time"])
                else:
                    chip_str = f"  {chip_text}   "
                    _safe_addnstr(stdscr, row, x, chip_str[: max_x - x - 1], max_x - x - 1, attrs["dim"])
                x += len(chip_str)

            row += 2  # blank line between providers

        # Active account indicator (shown in header area if set)
        active_acct = get_active_account()
        if active_acct and max_y > 2:
            active_hint = f" active: {active_acct} "
            hint_col = max(0, max_x - len(active_hint) - 1)
            _safe_addnstr(stdscr, 0, hint_col, active_hint, len(active_hint), attrs["accent"])

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
                    return chip["name"], menu[cursor_row]["provider_id"], False
        elif key == ord("s"):
            if menu and menu[cursor_row]["accounts"]:
                chip = menu[cursor_row]["accounts"][cursor_col]
                if chip["available"]:
                    return chip["name"], menu[cursor_row]["provider_id"], True
        elif key == ord("d"):
            if menu and menu[cursor_row]["accounts"]:
                chip = menu[cursor_row]["accounts"][cursor_col]
                set_active_account(chip["name"])
                # Show brief flash on the footer so user sees confirmation
                confirm = f" ✓ '{chip['name']}' set as active account "
                _safe_addnstr(stdscr, max_y - 1, 0, confirm[: max_x - 1].ljust(max_x - 1), max_x - 1, attrs["accent"])
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
            attrs = _picker_attrs("launcher")
            confirm = f" ✓ theme: {THEMES[nxt]['display_name']} — {THEMES[nxt]['description']} "
            _safe_addnstr(stdscr, max_y - 1, 0, confirm[: max_x - 1].ljust(max_x - 1), max_x - 1, attrs["accent"])
            stdscr.refresh()
            curses.napms(700)
        elif key in (ord("q"), 27):
            return None, None, False
        elif key == curses.KEY_RESIZE:
            continue


def _first_run_onboarding():
    """Full-screen onboarding for brand-new users with zero accounts configured."""
    # Rich is always present (show_banner uses it); import locally so the
    # function is self-contained and mirrors the pattern in show_banner().
    try:
        from rich.console import Console
        from rich.prompt import Prompt
        from rich.text import Text

        console = Console()
    except Exception:
        # Extremely degraded environment — fall back to plain text and bail.
        print("altergo: no accounts found. Run 'altergo --config' first.", file=sys.stderr)
        sys.exit(1)

    # Logo
    # Use pyfiglet's "thin" font (onboarding-only — show_banner stays smslant).
    # Apply the current theme's banner gradient character-by-character across
    # all non-whitespace glyphs so it reads as a gradient sweep.
    theme_id = get_current_theme()
    theme = THEMES.get(theme_id, THEMES[_DEFAULT_THEME])
    grad = theme["banner"]

    logo_lines = []
    try:
        import pyfiglet

        rendered = pyfiglet.Figlet(font="thin").renderText("altergo")
        logo_lines = [ln for ln in rendered.splitlines() if ln.strip()]
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

    # Spinner beat — gives the screen a living feel for ~0.8 s
    # Pick a spinner that matches the active theme (same helper the banner uses).
    try:
        import altergo_greetings as _greet

        _spinner_name = _greet.spinner_for_theme(theme_id)
    except Exception:
        _spinner_name = "dots"

    from rich.live import Live
    from rich.padding import Padding
    from rich.spinner import Spinner
    from rich.table import Table as _Table

    _accent_hex = grad[0]
    _spin_text = Text()
    _spin_text.append("  scanning for providers", style=f"dim {_accent_hex}")

    _spin_row = _Table.grid(padding=(0, 0), expand=False)
    _spin_row.add_column(no_wrap=True)
    _spin_row.add_column(no_wrap=True)
    _spin_row.add_row(Spinner(_spinner_name, style=f"bold {_accent_hex}"), _spin_text)

    with Live(Padding(_spin_row, (0, 0, 0, 2)), console=console, refresh_per_second=12, transient=True):
        time.sleep(0.75)

    # Copy
    # Determine theme accent color for styled hint lines (brand/accent hex stop).
    _mid_hex = grad[len(grad) // 2] if len(grad) > 2 else grad[0]
    console.print()
    console.print(
        Text(
            "  altergo \u2014 multiple AI identities from one terminal.",
            style="dim",
        )
    )
    console.print()
    _no_acct_msg = Text()
    _no_acct_msg.append("  You don't have any accounts yet. ", style="dim")
    _no_acct_msg.append("Let's fix that.", style=f"bold {_accent_hex}")
    console.print(_no_acct_msg)
    console.print()

    # ── Config-options hint ───────────────────────────────────────────────────
    _hint1 = Text()
    _hint1.append("  run ", style="dim")
    _hint1.append("altergo --config", style=f"bold {_mid_hex}")
    _hint1.append(" to configure interactively", style="dim")
    console.print(_hint1)

    _hint2 = Text()
    _hint2.append("  or ", style="dim")
    _hint2.append("altergo --config <account>", style=f"bold {_mid_hex}")
    _hint2.append(" to skip the prompts", style="dim")
    console.print(_hint2)
    console.print()

    # Name prompt loop
    while True:
        try:
            raw = Prompt.ask(
                "  Account name (e.g., personal, pro, sideproject) [or press Enter to run --config]",
                default="",
                show_default=False,
                console=console,
            ).strip()
        except KeyboardInterrupt:
            console.print()
            console.print("  \u2192 run: altergo --config <account> when ready")
            sys.exit(0)

        if not raw:
            console.print()
            console.print("  \u2192 run: altergo --config")
            sys.exit(0)

        # Inline validation — we cannot call validate_account_name() here
        # because it calls sys.exit(1) on failure, which would kill the loop.
        if not re.match(r"^[a-zA-Z0-9][a-zA-Z0-9_-]*$", raw) or len(raw) > 64:
            console.print(
                Text(
                    f"  Invalid name '{raw}'. Use letters, digits, - or _ only; "
                    "must not start with a digit or special char.",
                    style="dim",
                )
            )
            continue

        if raw in _RESERVED_NAMES:
            console.print(
                Text(
                    f"  '{raw}' is a reserved name. Choose a different account name.",
                    style="dim",
                )
            )
            continue

        # Valid name — proceed.
        break

    # Provider selection
    # Use the interactive picker so the user explicitly chooses.
    # If stdin is not a TTY (non-interactive / CI), fall back to "claude".
    if sys.stdin.isatty():
        chosen_provider = _prompt_provider_picker()
    else:
        detected_providers = [pid for pid, p in PROVIDERS.items() if shutil.which(p["binary"])]
        chosen_provider = detected_providers[0] if detected_providers else "claude"

    # Run config then drop into the launcher
    console.print()
    do_config(raw, chosen_provider)
    interactive_launcher()


def interactive_launcher(pending_args: list | None = None, context_msg: str | None = None):
    """Show the provider+account picker and launch the selected account."""
    single_shot = pending_args is not None
    while True:
        menu = build_launcher_menu()
        if not menu:
            print("altergo: no accounts found. Run 'altergo --config' first.", file=sys.stderr)
            sys.exit(1)
        show_banner()
        result = curses.wrapper(_draw_launcher, menu, context_msg)
        account, provider_id, shell_mode = result if result else (None, None, False)
        if not account:
            sys.exit(0)
        if single_shot:
            try:
                set_active_account(account)
            except Exception:
                pass  # don't fail the launch if we can't persist the pick
            if shell_mode:
                sys.exit(launch_shell(account))
            else:
                sys.exit(launch_claude(account, list(pending_args or []), provider=provider_id))
        if shell_mode:
            launch_shell(account)
        else:
            launch_claude(account, provider=provider_id)
        # Session exited — loop back to the menu


# Main


def main():
    # Load the user's persisted theme before anything prints so the banner,
    # help output, and curses screens all share one palette from the first
    # character onward.
    set_current_theme(load_persisted_theme())
    maybe_rotate_random_theme()
    args = sys.argv[1:]

    # ── Altergo-owned commands (not passed to claude) ──────────────────────────

    if args and args[0] in ("-h", "--help"):
        show_help()
        sys.exit(0)

    if args and args[0] == "--version":
        print(f"altergo {__version__}")
        sys.exit(0)

    if args and args[0] == "--config":
        # Supported forms:
        #   altergo --config                                    (interactive)
        #   altergo --config <name>                             (named, interactive provider picker)
        #   altergo --config <name> --provider claude           (fully specified)
        #   altergo --config --provider gemini                  (interactive name, specified provider)
        #   altergo --config <name> --keychain isolated|system  (non-interactive keychain mode)
        remaining = args[1:]
        name = None
        provider_arg = None
        keychain_arg = None  # "isolated", "system", or None (prompt/default)
        i = 0
        while i < len(remaining):
            if remaining[i] == "--provider" and i + 1 < len(remaining):
                provider_arg = remaining[i + 1]
                i += 2
            elif remaining[i] == "--keychain" and i + 1 < len(remaining):
                keychain_arg = remaining[i + 1]
                if keychain_arg == "shared":
                    print(
                        "altergo: --keychain shared is deprecated; use --keychain system "
                        "(alias will be removed in next minor)",
                        file=sys.stderr,
                    )
                    keychain_arg = "system"
                elif keychain_arg not in ("isolated", "system"):
                    print(
                        f"altergo: --keychain must be 'isolated' or 'system', got '{keychain_arg}'",
                        file=sys.stderr,
                    )
                    sys.exit(1)
                i += 2
            elif not remaining[i].startswith("--") and name is None:
                name = remaining[i]
                validate_account_name(name)
                i += 1
            else:
                i += 1

        # Resolve name
        if name is None:
            if sys.stdin.isatty():
                existing_accts = list_accounts()
                if existing_accts:
                    picked = _prompt_config_menu(existing_accts)
                else:
                    picked = _prompt_new_account_name_tui([])
                if picked is None:
                    sys.exit(0)
                name = picked
            else:
                name = "default"
            validate_account_name(name)

        # Resolve provider (exactly one)
        if provider_arg is not None:
            if provider_arg not in PROVIDERS:
                print(f"altergo: unknown provider '{provider_arg}'. Known: {', '.join(PROVIDERS)}", file=sys.stderr)
                sys.exit(1)
            cfg_provider = provider_arg
        else:
            if sys.stdin.isatty():
                account_home, _ = resolve_account(name)
                meta = load_account_meta(account_home)
                current = meta["default_provider"] if meta else None
                cfg_provider = _prompt_provider_picker(current)
            else:
                # Non-interactive: default to claude (backwards compat)
                account_home, _ = resolve_account(name)
                meta = load_account_meta(account_home)
                cfg_provider = meta["default_provider"] if meta else "claude"

        do_config(name, cfg_provider, keychain_arg=keychain_arg)
        sys.exit(0)

    if args and args[0] == "--rename":
        if len(args) < 3:
            print("altergo: usage: altergo --rename <old-name> <new-name>", file=sys.stderr)
            sys.exit(1)
        do_rename(args[1], args[2])
        sys.exit(0)

    if args and args[0] == "--teardown":
        # Support: --teardown --name <name>
        name = "default"
        if len(args) >= 3 and args[1] == "--name":
            name = args[2]
            if name in _RESERVED_NAMES:
                print(f"altergo: '{name}' is a reserved name and cannot be torn down.", file=sys.stderr)
                sys.exit(1)
        do_teardown(name)
        sys.exit(0)

    if args and args[0] == "--settings":
        interactive_settings()
        sys.exit(0)

    if args and args[0] == "--launch":
        interactive_launcher()
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
            print(_c(C("dim"), "  Set with: altergo --theme <theme>   ·   or press 't' in the launcher"))
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

    # --recall → open the interactive session picker across all accounts.
    # Account is resolved from the selected session's provider (not chosen
    # up front), so multi-account setups don't need --use or a positional name.
    if args and args[0] == "--recall":
        if not list_accounts():
            print("altergo: no accounts found. Run 'altergo --config' first.", file=sys.stderr)
            sys.exit(1)
        show_banner()
        sessions = _status_wrap("Scanning sessions…", get_sessions)
        selected = interactive_picker(sessions)
        if not selected:
            print("Cancelled.")
            sys.exit(0)
        provider_id = selected.get("provider", "claude")
        recall_account = _account_for_provider(provider_id)
        if recall_account is None:
            print(
                f"altergo: no account configured for provider '{provider_id}'.\n"
                f"  Create one with: altergo --config <account> --provider {provider_id}",
                file=sys.stderr,
            )
            sys.exit(1)
        recall_cwd = selected.get("cwd") or decode_project_path(selected.get("project", ""))
        launch_claude(recall_account, ["--resume", selected["id"]], cwd=recall_cwd or None)
        sys.exit(0)

    # --yolo-resume [<id>] → resume a session with skip-permissions flags.
    # Intercept before account/provider resolution so the user never has to
    # specify an account name; we derive it from the session metadata.
    _yr_present, _yr_session_id, _yr_rest = _extract_yolo_resume(args)
    if _yr_present:
        if not list_accounts():
            print("altergo: no accounts found. Run 'altergo --config' first.", file=sys.stderr)
            sys.exit(1)

        # Honor a leading explicit account token (e.g. `altergo native --yolo-resume <id>`
        # or `altergo work --yolo-resume <id>`) so it isn't silently dropped.
        _yr_explicit_account: str | None = None
        if _yr_rest and _looks_like_account(_yr_rest[0]):
            _cand = _yr_rest[0]
            if _cand == _NATIVE_ACCOUNT or (ACCOUNTS_DIR / _cand).is_dir():
                _yr_explicit_account = _cand
                _yr_rest = _yr_rest[1:]

        if _yr_session_id is None:
            # Case 1: no ID — open the interactive picker, then launch with yolo.
            show_banner()
            _yr_sessions = _status_wrap("Scanning sessions…", get_sessions)
            _yr_selected = interactive_picker(_yr_sessions)
            if not _yr_selected:
                print("Cancelled.")
                sys.exit(0)
            _yr_provider = _yr_selected.get("provider", "claude")
            _yr_skip = list(PROVIDERS.get(_yr_provider, {}).get("flags", {}).get("skip_perms", []))
            if _yr_explicit_account is not None:
                _yr_account = _yr_explicit_account
            else:
                _yr_account = _account_for_provider(_yr_provider)
            if _yr_account is None:
                print(
                    f"altergo: no account configured for provider '{_yr_provider}'.\n"
                    f"  Create one with: altergo --config <account> --provider {_yr_provider}",
                    file=sys.stderr,
                )
                sys.exit(1)
            _yr_cwd = _yr_selected.get("cwd") or decode_project_path(_yr_selected.get("project", ""))
            launch_claude(_yr_account, ["--resume", _yr_selected["id"]] + _yr_skip + _yr_rest, cwd=_yr_cwd or None)
            sys.exit(0)
        else:
            # Case 2: ID given — find session metadata, pick account, launch.
            _yr_all_sessions = _status_wrap("Scanning sessions…", get_sessions)
            _yr_match = next((s for s in _yr_all_sessions if s["id"] == _yr_session_id), None)
            if _yr_match is None:
                print(
                    _c(
                        C("warn"),
                        f"  altergo: session '{_yr_session_id}' not found in local history "
                        f"— continuing anyway (the provider will validate the ID).",
                    ),
                    file=sys.stderr,
                )
                _yr_provider = "claude"
                _yr_cwd = None
            else:
                _yr_provider = _yr_match.get("provider", "claude")
                _yr_cwd = _yr_match.get("cwd") or decode_project_path(_yr_match.get("project", ""))

            _yr_skip = list(PROVIDERS.get(_yr_provider, {}).get("flags", {}).get("skip_perms", []))

            if _yr_explicit_account is not None:
                # User specified an explicit account — honor it, skip the picker.
                _yr_account = _yr_explicit_account
            else:
                # Determine which accounts support this provider.
                def _yr_has_provider(acct_name: str) -> bool:
                    _m = load_account_meta(ACCOUNTS_DIR / acct_name)
                    if _m is None:
                        return _yr_provider == "claude"
                    return _yr_provider in _m["providers"]

                _yr_eligible = [a for a in list_accounts() if _yr_has_provider(a)]

                if not _yr_eligible:
                    print(
                        f"altergo: no account configured for provider '{_yr_provider}'.\n"
                        f"  Create one with: altergo --config <account> --provider {_yr_provider}",
                        file=sys.stderr,
                    )
                    sys.exit(1)
                elif len(_yr_eligible) == 1:
                    _yr_account = _yr_eligible[0]
                else:
                    # Multiple eligible accounts — prompt the user to pick one.
                    print(f"\n  Multiple accounts support '{_yr_provider}'. Pick one:\n")
                    for _yi, _ya in enumerate(_yr_eligible, 1):
                        print(f"  [{_yi}] {_c(C('command'), _ya)}")
                    print()
                    while True:
                        try:
                            _yr_raw = input(f"  Account [1-{len(_yr_eligible)}]: ").strip()
                        except (KeyboardInterrupt, EOFError):
                            print("\nCancelled.")
                            sys.exit(0)
                        if _yr_raw.isdigit() and 1 <= int(_yr_raw) <= len(_yr_eligible):
                            _yr_account = _yr_eligible[int(_yr_raw) - 1]
                            break
                        print(f"  Please enter a number between 1 and {len(_yr_eligible)}.")

            launch_claude(_yr_account, ["--resume", _yr_session_id] + _yr_skip + _yr_rest, cwd=_yr_cwd or None)
            sys.exit(0)

    if args and args[0] == "--use":
        if len(args) < 2:
            print("altergo: --use requires an account name. Example: altergo --use work", file=sys.stderr)
            sys.exit(1)
        use_name = args[1]
        use_home = ACCOUNTS_DIR / use_name
        if not use_home.is_dir():
            print(
                f"altergo: account '{use_name}' not found. Run 'altergo --config {use_name}' to create it.",
                file=sys.stderr,
            )
            sys.exit(1)
        set_active_account(use_name)
        print(f"altergo: active account set to {_c(C('command'), use_name)}")
        print(_c(C("dim"), f"  Bare 'altergo' will now launch '{use_name}' by default."))
        sys.exit(0)

    # --star [<id>] → star the last or specified session
    if args and args[0] == "--star":
        session_id = args[1] if len(args) > 1 else None
        do_star(session_id)
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
            search_cwd = selected.get("cwd") or decode_project_path(selected.get("project", ""))
            launch_claude(search_account, ["--resume", selected["id"]], cwd=search_cwd or None)
        else:
            print("Cancelled.")
        sys.exit(0)

    # altergo portal [<account>] [<provider>] [flags...]
    if args and args[0] == "portal":
        portal_args = args[1:]
        p_account = None
        p_provider = None
        p_remaining = []
        seen_flag = False
        for tok in portal_args:
            if tok.startswith("-"):
                seen_flag = True
                p_remaining.append(tok)
            elif seen_flag:
                # Value following a flag (e.g. session ID after --resume) — pass through
                p_remaining.append(tok)
            elif p_account is None and tok == _NATIVE_ACCOUNT:
                p_account = tok
            elif p_account is None and (ACCOUNTS_DIR / tok).is_dir():
                p_account = tok
            elif p_provider is None and tok in PROVIDERS:
                p_provider = tok
            else:
                # Unknown positional token before any flags — not an account or provider
                print(
                    f"altergo: portal: unknown account or provider '{tok}'.\n"
                    f"  Run 'altergo' to see accounts, or 'altergo --help' for usage.",
                    file=sys.stderr,
                )
                sys.exit(1)

        if p_account is None:
            _all = list_accounts()
            _active = get_active_account()
            if _active:
                p_account = _active
            elif len(_all) == 1:
                p_account = _all[0]
            elif not _all:
                print("altergo: no accounts found. Run 'altergo --config' first.", file=sys.stderr)
                sys.exit(1)
            else:
                print(
                    f"altergo: multiple accounts ({', '.join(_all)}) — specify one: altergo portal <account>",
                    file=sys.stderr,
                )
                sys.exit(1)

        launch_claude(p_account, p_remaining, provider=p_provider, force_tmux=True)
        sys.exit(0)

    # Account name as first positional arg
    # altergo <name> [sub-command | claude flags...]
    account = None
    if args and _looks_like_account(args[0]):
        candidate = args[0]
        if candidate == _NATIVE_ACCOUNT:
            # Native account: no managed directory — runs with the real $HOME.
            account = candidate
            args = args[1:]
        else:
            acct_home = ACCOUNTS_DIR / candidate
            if not acct_home.is_dir():
                print(
                    f"altergo: account '{candidate}' not found. Run 'altergo --config {candidate}' to create it.",
                    file=sys.stderr,
                )
                sys.exit(1)
            account = candidate
            args = args[1:]

    # Implicit account resolution (no positional name given)
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
            # Pass-through case: the user ran `altergo <flags>` with no active
            # account. We route the original args through the picker so e.g.
            # --yolo-resume <id> isn't silently dropped when the user picks.
            if args:
                _preview = " ".join(args)
                if len(_preview) > 60:
                    _preview = _preview[:57] + "..."
                _ctx = f"No default account set. Pick one — '{_preview}' will run against it."
                interactive_launcher(pending_args=args, context_msg=_ctx)
            else:
                interactive_launcher()
            sys.exit(0)
        elif not _all_accounts:
            if sys.stdout.isatty():
                _first_run_onboarding()
                sys.exit(0)
            else:
                print("altergo: no accounts found. Run 'altergo --config' first.", file=sys.stderr)
                sys.exit(1)
        else:
            # Multiple accounts, non-interactive — cannot pick one silently
            print(
                f"altergo: multiple accounts exist ({', '.join(_all_accounts)}).\n"
                f"  Run 'altergo <account>' to launch a specific account, or\n"
                f"  'altergo --use <account>' to set an active account for bare 'altergo'.",
                file=sys.stderr,
            )
            sys.exit(1)

    # ── Sub-commands (after optional account prefix) ──────────────────────────

    # altergo <name> --add-provider <id>
    # altergo <name> --remove-provider <id> [--yes]
    # altergo <name> --default-provider <id>
    if args and args[0] in ("--add-provider", "--remove-provider", "--default-provider"):
        if account == _NATIVE_ACCOUNT:
            print(
                f"altergo: '{_NATIVE_ACCOUNT}' has no account.json and cannot manage providers.",
                file=sys.stderr,
            )
            sys.exit(1)
        if len(args) < 2 or args[1].startswith("-"):
            print(f"altergo: usage: altergo <account> {args[0]} <provider-id>", file=sys.stderr)
            sys.exit(1)
        sub, pid = args[0], args[1]
        yes = "--yes" in args[2:]
        if pid not in PROVIDERS:
            print(
                f"altergo: unknown provider '{pid}'. Known: {', '.join(PROVIDERS)}",
                file=sys.stderr,
            )
            sys.exit(1)
        if sub == "--add-provider":
            sys.exit(do_add_provider(account, pid))
        if sub == "--remove-provider":
            sys.exit(do_remove_provider(account, pid, assume_yes=yes))
        if sub == "--default-provider":
            sys.exit(do_default_provider(account, pid))

    # altergo [<name>] shell
    if args and args[0] == "shell":
        sys.exit(launch_shell(account))

    # altergo [<name>] portal → same as top-level portal but account already resolved
    if args and args[0] == "portal":
        p_remaining = args[1:]
        p_provider = None
        filtered = []
        for tok in p_remaining:
            if not tok.startswith("-") and tok in PROVIDERS and p_provider is None:
                p_provider = tok
            else:
                filtered.append(tok)
        launch_claude(account, filtered, provider=p_provider, force_tmux=True)
        sys.exit(0)

    # 'use' subcommand removed — each account has exactly one provider
    if args and args[0] == "use":
        print(
            "altergo: 'use' subcommand has been removed.\n"
            "  Each account now has exactly one provider.\n"
            "  Create a separate account instead:\n"
            "    altergo --config <new-name> --provider <provider>",
            file=sys.stderr,
        )
        sys.exit(1)

    # altergo [<name>] -- <cmd> [args...]
    if args and args[0] == "--":
        sys.exit(launch_command(account, args[1:]))

    # Everything else → pass straight through to provider
    # altergo                    → provider (active account)
    # altergo work               → provider (work account, args=[])
    # altergo --resume x         → provider --resume x
    # altergo --dangerously-...  → provider --dangerously-...

    # Extract positional provider name if present (consumed by altergo, not passed to provider CLI)
    # Syntax: altergo <account> <provider> [args...]
    provider = None
    if args and args[0] in PROVIDERS:
        provider = args[0]
        args = args[1:]

    # Final validation: if the first arg is not a provider and doesn't start with '-',
    # it might be a typo for an altergo command (e.g. 'altergo help' instead of '--help').
    if args and not args[0].startswith("-"):
        print(f"altergo: unrecognized command or provider: '{args[0]}'", file=sys.stderr)
        print("  Run 'altergo --help' for usage.", file=sys.stderr)
        sys.exit(1)

    sys.exit(launch_claude(account, args, provider=provider))


if __name__ == "__main__":
    main()
