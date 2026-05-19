import curses
import re
import shutil
import sys
import time

from altergo._version import __version__
from altergo.accounts import (
    _native_supports_provider,
    configure_account,
    get_active_account,
    list_accounts,
    set_active_account,
)
from altergo.constants import _NATIVE_ACCOUNT, _RESERVED_NAMES, ACCOUNTS_DIR, PROVIDERS
from altergo.persistence import load_account_meta, save_persisted_theme
from altergo.runner import launch_claude, launch_shell
from altergo.sessions import get_sessions, relative_time
from altergo.theme import (
    _DEFAULT_THEME,
    THEMES,
    C,
    _c,
    _gradient_color,
    get_current_theme,
    set_current_theme,
)
from altergo.tui.common import _draw_animated_nav, _picker_attrs, _safe_addnstr
from altergo.tui.config_tui import _prompt_provider_picker
from altergo.ui import _status_wrap, show_banner

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
            "  altergo — multiple AI identities from one terminal.",
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
            console.print("  → run: altergo --config <account> when ready")
            sys.exit(0)

        if not raw:
            console.print()
            console.print("  → run: altergo --config")
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
    configure_account(raw, chosen_provider)
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


def _prompt_yolo_account_picker(
    eligible: list,
    *,
    provider: str,
) -> "str | None":
    """Curses-driven account picker for the --yolo-resume multi-account fork.

    Renders the eligible regular accounts plus a 'native' chip when the
    provider binary is on $PATH. The currently persisted active account is
    marked with ● and pre-selected by the cursor.

    Keys: ↑↓/jk navigate, Enter confirm, d set highlighted as default account
    (persisted to active_account via [[set_active_account]]), q/Esc cancel.

    Falls back to a numbered input prompt when stdin/stdout isn't a TTY so the
    flow still works under pipes and SSH sessions without a controlling tty.
    """
    items = list(eligible)
    if _native_supports_provider(provider) and _NATIVE_ACCOUNT not in items:
        items.append(_NATIVE_ACCOUNT)
    if not items:
        return None
    if len(items) == 1:
        return items[0]

    # Non-TTY fallback — preserve the legacy numbered prompt, now including
    # native so scripted callers can pick it too.
    if not sys.stdin.isatty() or not sys.stdout.isatty():
        print(f"\n  Multiple accounts support '{provider}'. Pick one:\n")
        for i, name in enumerate(items, 1):
            tag = "  (real $HOME passthrough)" if name == _NATIVE_ACCOUNT else ""
            print(f"  [{i}] {_c(C('command'), name)}{tag}")
        print()
        while True:
            try:
                raw = input(f"  Account [1-{len(items)}]: ").strip()
            except (KeyboardInterrupt, EOFError):
                print("\nCancelled.")
                return None
            if raw.isdigit() and 1 <= int(raw) <= len(items):
                return items[int(raw) - 1]
            print(f"  Please enter a number between 1 and {len(items)}.")

    def _draw(stdscr, state):
        curses.curs_set(0)
        attrs = _picker_attrs("resume")
        stdscr.timeout(80)
        phase = 0
        while True:
            stdscr.erase()
            max_y, max_x = stdscr.getmaxyx()

            header = f"  Pick account for '{provider}'  (↑↓ navigate · Enter confirm · d set default · q quit)"
            _safe_addnstr(stdscr, 0, 0, header[: max_x - 1], max_x - 1, attrs["title"])
            _safe_addnstr(stdscr, 1, 0, ("─" * (max_x - 1))[: max_x - 1], max_x - 1, attrs["dim"])

            active = get_active_account()
            cursor = state["cursor"]
            for idx, name in enumerate(state["items"]):
                row = 3 + idx
                if row >= max_y - 2:
                    break
                is_cursor = idx == cursor
                is_default = name == active
                marker = "●" if is_default else " "
                suffix = "  (real $HOME · passthrough)" if name == _NATIVE_ACCOUNT else ""
                label = f"  {marker} {name}{suffix}"
                if is_cursor:
                    row_attr = attrs["selected"]
                elif is_default:
                    row_attr = attrs["accent"]
                else:
                    row_attr = attrs["dim"]
                _safe_addnstr(stdscr, row, 0, label[: max_x - 1].ljust(max_x - 1), max_x - 1, row_attr)

            flash = state.get("flash")
            if flash and phase < state.get("flash_until", 0):
                _safe_addnstr(stdscr, max_y - 1, 0, flash[: max_x - 1].ljust(max_x - 1), max_x - 1, attrs["accent"])
            else:
                nav = "  Enter · Default (d) · ↑↓/jk · Quit (q/Esc)"
                _draw_animated_nav(stdscr, max_y - 1, nav, max_x - 1, phase, attrs)

            stdscr.refresh()
            key = stdscr.getch()
            if key == -1:
                phase += 1
                continue
            if key in (curses.KEY_UP, ord("k")):
                state["cursor"] = max(0, cursor - 1)
            elif key in (curses.KEY_DOWN, ord("j")):
                state["cursor"] = min(len(state["items"]) - 1, cursor + 1)
            elif key in (curses.KEY_ENTER, 10, 13):
                state["action"] = "select"
                return
            elif key in (ord("d"), ord("D")):
                picked_name = state["items"][cursor]
                set_active_account(picked_name)
                state["flash"] = f" ✓ '{picked_name}' set as default account "
                state["flash_until"] = phase + 10  # ~0.8s at the 80ms tick
            elif key in (ord("q"), 27):
                state["action"] = "quit"
                return
            elif key == curses.KEY_RESIZE:
                continue

    # Pre-select the cursor on the currently persisted active account so the
    # default round-trip (Enter) keeps the user's existing pick.
    active0 = get_active_account()
    cursor0 = items.index(active0) if active0 in items else 0
    state = {"cursor": cursor0, "items": items, "action": None, "flash": None}
    try:
        curses.wrapper(_draw, state)
    except Exception:
        return None
    if state["action"] != "select":
        return None
    return state["items"][state["cursor"]]
