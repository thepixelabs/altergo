import sys


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
        "banner": ["#ff005f", "#ff8700", "#ffff00", "#00ff5f", "#00d7ff", "#af5fff"],
    },
}

_STATIC_ANSI = {
    "dim": "2",
    "version": "2",
}

_DEFAULT_THEME = "ocean"

_CURRENT_THEME = _DEFAULT_THEME


def get_current_theme() -> str:
    return _CURRENT_THEME if _CURRENT_THEME in THEMES else _DEFAULT_THEME


def set_current_theme(name: str) -> None:
    global _CURRENT_THEME
    if name in THEMES:
        _CURRENT_THEME = name


def _gradient_color(stops: list, t: float) -> str:
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
    if role in _STATIC_ANSI:
        return _STATIC_ANSI[role]
    theme = THEMES.get(get_current_theme(), THEMES[_DEFAULT_THEME])
    return theme["ansi"].get(role, "")


def _ansi_to_rich(code: str) -> str:
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
