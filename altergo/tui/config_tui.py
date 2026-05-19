import curses
import re
import shutil
import sys

from altergo.accounts import (
    do_delete_account,
    get_active_account,
    list_accounts,
    set_active_account,
)
from altergo.constants import _NATIVE_ACCOUNT, _RESERVED_NAMES, ACCOUNTS_DIR, PROVIDERS
from altergo.persistence import (
    _read_account_email,
    load_account_meta,
    load_native_default_provider,
    save_native_default_provider,
)
from altergo.theme import C, _c
from altergo.tui.common import _draw_animated_nav, _picker_attrs, _safe_addnstr

# Interactive prompt helpers


def _prompt_new_account_name_tui(existing: list) -> "str | None":
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

            nav = "  Confirm (Enter)  \xb7  Edit (Backspace)  \xb7  Cancel (Esc)"
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
                    state["error"] = "Name can’t be empty."
                    continue
                if not re.match(r"^[a-zA-Z0-9][a-zA-Z0-9_-]*$", name) or len(name) > 64:
                    state["error"] = f"Invalid name ‘{name}’. Use letters/digits/-/_, must not start with digit."
                    continue
                if name in _RESERVED_NAMES:
                    state["error"] = f"‘{name}’ is a reserved name. Pick another."
                    continue
                if name in existing:
                    state["error"] = f"‘{name}’ already exists. Pick a new name or reconfigure from the menu."
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


def _prompt_provider_picker(current_provider: "str | None" = None, *, allow_cancel: bool = False) -> "str | None":
    """Curses-based single-select provider picker.

    When ``allow_cancel`` is True, q/Esc returns None instead of falling back
    to the current/initial provider — used by flows where cancel means "do
    nothing", not "keep current".
    """
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
            header = "  Select provider  (↑↓ navigate \xb7 Enter confirm \xb7 q quit)"
            _safe_addnstr(stdscr, 0, 0, header[: max_x - 1], max_x - 1, attrs["title"])

            # Separator
            _safe_addnstr(stdscr, 1, 0, ("─" * (max_x - 1))[: max_x - 1], max_x - 1, attrs["dim"])

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
            nav = "  Confirm (Enter)  \xb7  Navigate (↑↓/jk)  \xb7  Quit (q/Esc)"
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
        if allow_cancel:
            return None
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
                ("warn_big", f"  ⚠  Remove account ‘{account}’?"),
                ("blank", ""),
                ("dim", "  This will:"),
                ("dim", "    \xb7 tear down all provider symlinks"),
                ("dim", f"    \xb7 remove {path}"),
                ("dim", "    \xb7 wipe credentials and sessions stored there"),
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

            nav = "  Confirm remove (y)  \xb7  Cancel (n/Esc/Enter)"
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


def _run_config_picker(accounts: list, start_cursor: int = 0) -> "tuple | None":
    """Render the config picker once and return an action tuple."""

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
            right = f"{n_accts} account{acct_s}{native_tag} \xb7 {n_active} active "
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
                    if kc_mode == "keychain":
                        kc_suffix = "  \xb7  keychain"
                    else:
                        kc_suffix = ""  # none is the opt-out — do not clutter rows
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
                        f"{'real $HOME'.ljust(prov_w)}  (passthrough \xb7 no isolation)"
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
                hint = "  Enter = pick default provider \xb7 d = set as default account"
            elif cur_kind == "account":
                hint = "  Enter = reconfigure \xb7 d = set as default \xb7 r/Delete = remove (irreversible)"
            else:
                hint = "  Create a new account."
            _safe_addnstr(stdscr, max_y - 3, 0, hint[: max_x - 1], max_x - 1, attrs["dim"])

            nav = "  Enter \xb7 Default (d) \xb7 Remove (r) \xb7 ↑↓/jk \xb7 Quit (q/Esc)"
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
                state["action"] = "select"
                return
            elif key in (ord("d"), ord("D")):
                picked = rows[cursor]
                if picked[0] in ("account", "native"):
                    set_active_account(picked[1])
                    rows = _build_config_rows(accounts)
                    confirm = f" ✓ ‘{picked[1]}’ set as default account "
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
    if picked[0] == "native":
        return ("native", idx)
    return ("create",)


def _prompt_config_menu(existing: list) -> "str | None":
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
        if kind == "native":
            cursor = action[1]
            picked_provider = _prompt_provider_picker(load_native_default_provider(), allow_cancel=True)
            if picked_provider in PROVIDERS:
                save_native_default_provider(picked_provider)
                print(_c(C("success"), f"  ✓ native default provider set to ‘{picked_provider}’"))
            # Stay in the menu loop so the user can keep configuring.
            continue
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
