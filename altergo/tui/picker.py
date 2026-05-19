import curses

from altergo.persistence import save_persisted_theme, toggle_starred_session
from altergo.sessions import (
    decode_project_path,
    format_project_name,
    load_session_preview,
    relative_time,
)
from altergo.theme import THEMES, get_current_theme, set_current_theme
from altergo.tui.common import (
    _RESUME_PROVIDER_CYCLE,
    _RESUME_SORT_MODES,
    _apply_resume_view,
    _compute_columns,
    _picker_attrs,
    _safe_addnstr,
    _truncate,
    _wrap_text,
)


def interactive_picker(sessions):
    """Arrow-key driven session picker using curses."""
    if not sessions:
        print("No sessions found.")
        import sys

        sys.exit(1)

    selected = curses.wrapper(_draw_picker, sessions)
    return selected


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
