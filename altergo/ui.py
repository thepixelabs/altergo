import os
import re
import sys
import time

from altergo._version import __version__
from altergo.persistence import (
    _is_newer,
    _read_account_email,
    _sanitize_version,
    load_persisted_banner_font,
)
from altergo.theme import (
    _DEFAULT_THEME,
    THEMES,
    C,
    _ansi_to_rich,
    _c,
    _gradient_ansi,
    _gradient_color,
    _link,
    get_current_theme,
)


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
        (
            "altergo --config --keychain",
            f"{kw('altergo --config --keychain')} {arg('<m>')}",
            "keychain | none (macOS only)",
        ),
        ("altergo --use <account>", f"{kw('altergo --use')} {arg('<account>')}", "Set as default account"),
        ("altergo --teardown", f"{kw('altergo --teardown')} {arg('[--name <n>]')}", "Remove account + symlinks"),
        ("altergo --settings", kw("altergo --settings"), "Manage shared credentials"),
        (
            "altergo --setup-token <account>",
            f"{kw('altergo --setup-token')} {arg('<account>')}",
            "Generate SSH-friendly OAuth token (claude only)",
        ),
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
