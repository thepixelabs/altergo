import curses

from altergo.sessions import format_project_name
from altergo.theme import _DEFAULT_THEME, THEMES, _gradient_color, get_current_theme

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
    """Render the footer nav line."""
    if max_width <= 0:
        return
    width = min(len(text), max_width)
    if width <= 0:
        return
    lower = text.lower()
    pix_start = lower.find("pixelabs")
    pix_end = pix_start + len("pixelabs") if pix_start >= 0 else -1
    for i in range(width):
        ch = text[i]
        if pix_start <= i < pix_end:
            attr = attrs["brand"]
        else:
            attr = attrs["nav_base"]
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
