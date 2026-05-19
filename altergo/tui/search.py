import curses
import json

from altergo.sessions import (
    _extract_text,
    decode_project_path,
    format_project_name,
    relative_time,
)
from altergo.tui.common import (
    _draw_animated_nav,
    _picker_attrs,
    _safe_addnstr,
    _truncate,
)

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
