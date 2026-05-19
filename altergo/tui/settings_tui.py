"""Settings TUI — multi-page interactive settings editor."""

import curses
import json
import os
import time

from altergo.accounts import _apply_entry, _is_enabled, list_accounts, resolve_account
from altergo.constants import CATALOG, SETTINGS_FILE
from altergo.persistence import (
    _ANIM_PACKS,
    _DEFAULT_ANIM_PACK,
    _DEFAULT_BANNER_FONT,
    _VALID_ANIM_PACKS,
    _get_rich_spinner_data,
    _get_valid_banner_fonts,
    _load_bool_setting,
    load_animation_pack,
    load_persisted_banner_font,
    load_random_theme_settings,
    load_settings,
    load_update_check_enabled,
)
from altergo.theme import THEMES, C, _c, get_current_theme, set_current_theme
from altergo.tui.common import _hex_to_curses_256, _picker_attrs, _safe_addnstr
from altergo.ui import _status_wrap, show_banner

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
_SWATCH_BLOCK = "█"  # █


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
                _safe_addnstr(stdscr, 0, x, "│", 1, attrs["dim"])  # │
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
        _draw_vr(vrow, 2, ("Theme " + "─" * 34)[: max_x - 3], max_x - 3, attrs_local["accent"] | curses.A_BOLD)
        vrow += 1

        for ti, tid in enumerate(theme_names):
            if _vis(vrow):
                s = _sr(vrow)
                tdata = THEMES[tid]
                is_focused = ti == page0_cursor
                is_selected = ti == current_theme_idx
                marker = "◆" if is_selected else "·"
                marker_attr = attrs_local["accent"] | curses.A_BOLD if is_selected else attrs_local["dim"]
                prefix = "▸ " if is_focused else "  "
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
        _draw_vr(vrow, 2, ("Font " + "─" * 35)[: max_x - 3], max_x - 3, attrs_local["accent"] | curses.A_BOLD)
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
            marker = "◆" if is_selected else "·"
            marker_attr = attrs_local["accent"] | curses.A_BOLD if is_selected else attrs_local["dim"]
            prefix = "▸ " if is_focused else "  "
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
                _safe_addnstr(stdscr, _sr(vrow), _DIV_X, "│", 1, attrs_local["dim"])
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
        _draw_vr(vrow, 2, ("Animation " + "─" * 30)[: max_x - 3], max_x - 3, attrs_local["accent"] | curses.A_BOLD)
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
                _live_frames[_pn] = "✶" if (_now_ms // 250) % 2 == 0 else "✷"
            else:
                _live_frames[_pn] = "─"  # ─

        _pack_off = _p0_pack_offset()
        for pi, pname in enumerate(_VALID_ANIM_PACKS):
            if _vis(vrow):
                s = _sr(vrow)
                pi_abs = _pack_off + pi
                is_focused = pi_abs == page0_cursor
                is_selected = pi == current_pack_idx
                pcfg = _ANIM_PACKS[pname]
                marker = "◆" if is_selected else "·"
                marker_attr = attrs_local["accent"] | curses.A_BOLD if is_selected else attrs_local["dim"]
                prefix = "▸ " if is_focused else "  "
                prefix_attr = attrs_local["accent"] | curses.A_BOLD if is_focused else curses.A_NORMAL
                _safe_addnstr(stdscr, s, 0, prefix, 2, prefix_attr)
                _safe_addnstr(stdscr, s, 2, marker, 1, marker_attr)
                label_attr = attrs_local["accent"] | curses.A_BOLD if is_selected else curses.A_NORMAL
                pack_label = f" {pcfg['label']}".ljust(10)
                _safe_addnstr(stdscr, s, 4, pack_label, len(pack_label), label_attr)
                # Vertical divider
                if _A_DIV_X < max_x - 1:
                    _safe_addnstr(stdscr, s, _A_DIV_X, "│", 1, attrs_local["dim"])
                # Live frame right of divider — only for the focused pack
                if is_focused and _anim_avail > 2:
                    lf = _live_frames.get(pname, "·")
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
        _draw_vr(vrow, 2, ("Randomize " + "─" * 30)[: max_x - 3], max_x - 3, attrs_local["accent"] | curses.A_BOLD)
        vrow += 1

        # Random toggle
        if _vis(vrow):
            s = _sr(vrow)
            is_focused = page0_cursor == _p0_rand_idx()
            prefix = "▸ " if is_focused else "  "
            prefix_attr = attrs_local["accent"] | curses.A_BOLD if is_focused else curses.A_NORMAL
            _safe_addnstr(stdscr, s, 0, prefix, 2, prefix_attr)
            dot = "◉" if random_theme_on else "○"
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
                track = "".join("█" if i < thumb_pos else ("◆" if i == thumb_pos else "░") for i in range(TRACK_LEN))
                slider_attr = (attrs_local["accent"] | curses.A_BOLD) if is_focused else curses.A_NORMAL
                left_label, right_label = "often ", " rarely"
                label_attr = attrs_local["dim"]
                prefix_sl = "▸ " if is_focused else "  "
                prefix_sl_attr = (attrs_local["accent"] | curses.A_BOLD) if is_focused else curses.A_NORMAL
            else:
                track = "▒" * (TRACK_LEN - 1) + "·"
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
            3: ("Changes occasionally", "Balanced — noticeable but not constant"),
            4: ("Changes infrequently", "Mostly consistent, occasional surprise"),
            5: ("Changes rarely", "Stable look with rare surprises"),
        }
        if random_theme_on:
            line1, line2 = _freq_descriptions.get(random_theme_freq, _freq_descriptions[3])
            if _vis(vrow):
                _safe_addnstr(stdscr, _sr(vrow), 4, ("◆ " + line1)[: max_x - 5], max_x - 5, attrs_local["dim"])
            vrow += 1
            if _vis(vrow):
                _safe_addnstr(stdscr, _sr(vrow), 4, ("· " + line2)[: max_x - 5], max_x - 5, attrs_local["dim"])
        else:
            if _vis(vrow):
                _safe_addnstr(
                    stdscr,
                    _sr(vrow),
                    4,
                    "· Enable “Random theme” to configure frequency"[: max_x - 5],
                    max_x - 5,
                    attrs_local["dim"],
                )

    # Helper: draw page 1 (Behavior)
    def _draw_page1(max_y, max_x):
        content_start = 3
        row = content_start

        section = "Launch behavior " + "─" * max(0, 24)
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
            prefix = "▸ " if is_focused else "  "
            prefix_attr = attrs["accent"] | curses.A_BOLD if is_focused else curses.A_NORMAL
            _safe_addnstr(stdscr, row, 0, prefix, 2, prefix_attr)

            if val:
                dot = "◉"  # ◉
                dot_attr = attrs["accent"] | curses.A_BOLD
            else:
                dot = "○"  # ○
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
                section = crow["text"] + "  " + "─" * max(0, 36 - len(crow["text"]))
                _safe_addnstr(stdscr, screen_row, 2, section[: max_x - 3], max_x - 3, attrs["accent"] | curses.A_BOLD)
            else:
                entry = crow["entry"]
                enabled = _is_enabled(entry, cred_overrides)
                is_current = row_idx == current_row_idx
                has_warn = "warning" in entry

                path_hint = ", ".join(f"~/{p}" for p in entry["paths"])

                prefix = "▸ " if is_current else "  "
                prefix_attr = attrs["accent"] | curses.A_BOLD if is_current else curses.A_NORMAL
                _safe_addnstr(stdscr, screen_row, 0, prefix, 2, prefix_attr)

                if enabled:
                    dot = "◉"  # ◉
                    dot_attr = attrs["accent"] | curses.A_BOLD
                else:
                    dot = "○"  # ○
                    dot_attr = attrs["dim"]
                _safe_addnstr(stdscr, screen_row, 2, dot, 1, dot_attr)

                name_str = "  " + entry["name"].ljust(22)
                _safe_addnstr(
                    stdscr,
                    screen_row,
                    3,
                    name_str[: max_x - 4],
                    max_x - 4,
                    curses.A_BOLD if is_current else curses.A_NORMAL,
                )
                nx = 3 + len(name_str)
                if has_warn and nx < max_x - 3:
                    _safe_addnstr(stdscr, screen_row, nx, " ⚠", 2, curses.color_pair(7) | curses.A_BOLD)
                nx += 2  # always advance past warn slot so path_hint column stays stable
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
                hint = "  Use ← → to set how often the theme rotates"
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
                warn_line = "  ⚠  " + crow["entry"]["warning"]
                _safe_addnstr(
                    stdscr, footer_row, 0, warn_line[: max_x - 1], max_x - 1, curses.color_pair(7) | curses.A_BOLD
                )

        _on_freq_slider = current_page == 0 and page0_cursor == _p0_freq_idx() and random_theme_on
        if _on_freq_slider:
            nav = "  ↑↓/jk navigate  ←→/hl adjust  Space toggle  Tab page  s save  q/Esc cancel"
        else:
            nav = "  ↑↓/jk navigate  Space toggle  ←→/hl/Tab page  s save  q/Esc cancel"
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
        sep_full = "─" * (max_x - 1)
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
