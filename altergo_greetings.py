"""Time-of-day greetings, day-of-week icons, and theme→spinner picks.

This is a pure-data module: zero imports from altergo, zero side effects at
import time, stdlib only. It exists as its own file so the copy can be
tweaked without touching altergo.py, and so the hot `--help`/`--version`
paths never pay the cost of loading it.

The 80 greeting lines are assigned to 8 product-defined time windows. The
per-minute random seed in `pick_greeting` means relaunching within the same
minute shows the same line (stable, not slot-machine). Window boundaries
cover all 24 hours with no gaps.

Editorial rules honored when writing the copy:
  - Dry, developer, self-aware — same register as the existing goodbye bank
  - Never cruel to the user; punch at the code or the situation
  - No nationality, generation, politics, religion, profession, or parenting jokes
  - No hustle-culture glorification of overwork
  - Length cap ~60 chars so nothing wraps under the figlet on narrow terminals
  - No emoji in the copy (the day-of-week icon is the only glyph)
"""

from __future__ import annotations

import locale
import random
import sys
import time
from datetime import datetime

# ---------------------------------------------------------------------------
# Time windows
# ---------------------------------------------------------------------------
# Eight inclusive hour ranges tiling the full 24 hours. The ordering here
# is the canonical lookup order used by `pick_greeting`.

WINDOWS: list[tuple[str, int, int]] = [
    # (window_id,        start_hour, end_hour_inclusive)
    ("dead_of_night", 0, 2),   # 00:00–02:59
    ("late_night",    3, 5),   # 03:00–05:59
    ("early_morning", 6, 8),   # 06:00–08:59
    ("morning",       9, 11),  # 09:00–11:59
    ("midday",       12, 13),  # 12:00–13:59
    ("afternoon",    14, 16),  # 14:00–16:59
    ("evening",      17, 19),  # 17:00–19:59
    ("night",        20, 23),  # 20:00–23:59
]


def _window_for_hour(hour: int) -> str:
    """Return the window id containing the given 24-hour `hour`."""
    for wid, start, end in WINDOWS:
        if start <= hour <= end:
            return wid
    # Defensive fallback — should be unreachable while WINDOWS tiles 0..23.
    return "morning"


# ---------------------------------------------------------------------------
# The bank: 80 sentences, 10 per window
# ---------------------------------------------------------------------------

GREETINGS: dict[str, list[str]] = {
    "dead_of_night": [
        "Midnight. Technically a new day, spiritually the same one.",
        "One hour left in the day. The question is which day.",
        "The git log ends here. For now.",
        "Midnight is when senior devs briefly become philosophers.",
        "Almost tomorrow. The bugs will still be waiting.",
        "The compiler has no opinion on your life choices.",
        "Last push of the day, technically speaking.",
        "The deadline is either tomorrow or past.",
        "Two AM is a commitment to a theory.",
        "Still open, still running. That counts for something.",
    ],
    "late_night": [
        "The tests are failing. The night is long.",
        "CI is asleep. You should be too.",
        "Nothing good was ever merged at this hour.",
        "The diff is long. The night is longer.",
        "Your future self will not thank you for this.",
        "Insomnia or deadline — the terminal does not judge.",
        "This is not a phase. Or maybe it is.",
        "The log errors make more sense than the hour.",
        "Three AM: when stubbornness becomes personality.",
        "The cursor blinks patiently. You have not.",
    ],
    "early_morning": [
        "Either very early or very late. Bold either way.",
        "The coffee has not lied to you yet today.",
        "Some birds are up. You have that in common.",
        "Dawn and a blank editor — similarly unforgiving.",
        "Still dark. Your standup will never know.",
        "First commit of the day. The record is clean.",
        "The world boots slowly. Give it a moment.",
        "Up before the sun. The sun does not care.",
        "Seven AM: the last hour the plan still exists.",
        "Eight o'clock and the keyboard is already warm.",
    ],
    "morning": [
        "The workday technically exists now. Noted.",
        "Still two cups of coffee from being functional.",
        "Your calendar has opinions. Ignore some of them.",
        "Morning. The bugs from last night are still there.",
        "Fresh session. The context is already loading.",
        "Reasonable hour. Low bar, but you cleared it.",
        "The day is young. You are not. Go anyway.",
        "Inbox zero is a myth. This session is real.",
        "Ten AM standup: rehearsed, misheard, forgotten.",
        "Eleven. The morning has opinions about itself.",
    ],
    "midday": [
        "Noon. The morning got away from you again.",
        "Pre-lunch clarity: use it before it evaporates.",
        "Lunch is a suggestion. The compiler has a deadline.",
        "The sprint board has not moved itself. Interesting.",
        "Twelve o'clock: peak optimism about the afternoon.",
        "Halfway through the workday, or halfway into it.",
        "The morning was a rehearsal. This is the actual work.",
        "Late enough to have context, early enough to use it.",
        "One PM. The afternoon exists, for better or worse.",
        "Midday: the hour the plan meets reality.",
    ],
    "afternoon": [
        "Post-lunch. Your stack trace is not the only thing foggy.",
        "Two PM: peak meeting time, minimum information exchanged.",
        "The afternoon is long. So is your TODO list.",
        "Halfway through the day. The code has not noticed.",
        "The feature exists in theory. The afternoon will find out.",
        "Statistically the least productive hour. Prove it wrong.",
        "Afternoon: when confident commits become cautious ones.",
        "Somewhere a rubber duck is solving someone's problem.",
        "Three PM. The caffeine wore off. So did the plan.",
        "Four o'clock: the last honest hour of the workday.",
    ],
    "evening": [
        "After hours. The definition of that is flexible for you.",
        "The day had a shape. This is the trailing edge.",
        "Ship it or stash it — the evening asks that question.",
        "Technically off the clock. The terminal missed that memo.",
        "Dinner is a concept. So is done.",
        "Evening: the hour of one-more-thing.",
        "The build passed. You can probably stop now. Probably.",
        "Whatever did not ship today is tomorrow's character arc.",
        "Six PM and the codebase has questions.",
        "Seven: the line between work and a hobby blurs.",
    ],
    "night": [
        "A reasonable time to start a refactor. Said no one.",
        "The diff grows. The rationale shrinks.",
        "Dark outside. The cursor blinks, unbothered.",
        "Late enough that the commit message will be honest.",
        "You and the code, alone again. This is fine.",
        "Nine PM: ambitious scope, poor estimates.",
        "The keyboard has been patient with you all day.",
        "Not the last session of the week. Probably not.",
        "Ten PM. The feature is close. It has always been close.",
        "Eleven: the night shift begins, asked for or not.",
    ],
}


# ---------------------------------------------------------------------------
# Day-of-week nature icon rotation
# ---------------------------------------------------------------------------
# CEO-approved nature palette (Thursday 🌧️ was swapped for 🌳 — no weather
# downers mid-week). Index matches datetime.weekday(): Monday=0..Sunday=6.

NATURE_ICONS: list[str] = [
    "🌊",   # Mon — tide coming in
    "🌿",   # Tue — quietly growing
    "⛰️",   # Wed — mid-peak
    "🌳",   # Thu — forest / growth (swap from 🌧️)
    "🔥",   # Fri — controlled burn, ship it
    "🌄",   # Sat — a horizon you chose
    "🌑",   # Sun — the moon minds its business
]

# ASCII fallback for non-UTF-8 terminals (CI, old SSH, busybox).
NATURE_ICONS_ASCII: list[str] = [
    "~",   # Mon
    '"',   # Tue
    "^",   # Wed
    ":",   # Thu
    "*",   # Fri
    "/",   # Sat
    "o",   # Sun
]


def _supports_unicode() -> bool:
    """Best-effort detection of whether the current stdout handles emoji.

    Looks at the actual encoding of ``sys.stdout`` first, then falls back to
    the locale preferred encoding. Anything not UTF-{8,16,32} is treated as
    ASCII-only so we don't spray mojibake into CI logs or old terminals.
    """
    enc = (getattr(sys.stdout, "encoding", None) or "").lower()
    if enc.startswith(("utf", "cp65001")):
        return True
    try:
        loc = (locale.getpreferredencoding(False) or "").lower()
    except Exception:
        loc = ""
    return loc.startswith("utf")


def pick_icon(now: datetime | None = None) -> str:
    """Return the nature icon for the given day-of-week (or today).

    Falls back to a plain ASCII character when the terminal cannot render
    emoji — see :func:`_supports_unicode`.
    """
    when = now or datetime.now()
    idx = when.weekday()  # Monday=0..Sunday=6
    if _supports_unicode():
        return NATURE_ICONS[idx]
    return NATURE_ICONS_ASCII[idx]


# ---------------------------------------------------------------------------
# Greeting picker
# ---------------------------------------------------------------------------

def pick_greeting(now: datetime | None = None) -> str:
    """Return one witty line appropriate for the current time of day.

    The selection is seeded by the current minute-of-epoch, so re-launching
    altergo within the same minute shows the same line (stable, deliberate)
    while subsequent minutes rotate through the bank freely.

    Uses a private ``random.Random`` instance so we never perturb any other
    code that relies on the global ``random`` state.
    """
    when = now or datetime.now()
    window = _window_for_hour(when.hour)
    bank = GREETINGS.get(window) or GREETINGS["morning"]
    seed = int(time.time() // 60)
    rng = random.Random(seed ^ hash(window))
    return rng.choice(bank)


# ---------------------------------------------------------------------------
# Theme → Rich spinner mapping
# ---------------------------------------------------------------------------
# Keyed by theme id; values are Rich built-in spinner names. Used by both the
# launch-handoff animation and any other Rich `Status` surface that wants a
# spinner that matches the current palette. Kept here so altergo.py's THEMES
# dict doesn't have to carry runtime concerns.

THEME_SPINNERS: dict[str, str] = {
    "ocean":    "dots",        # Gemini-style snake — the flagship
    "forest":   "arc",         # calm organic curve
    "lavender": "circle",      # soft dot-to-dot
    "sunset":   "star",        # ✶✸✹✺✹✷ — warm twinkle
    "mono":     "line2",       # minimalist dash sweep
    "rainbow":  "aesthetic",   # ▰▱▱▱ growing bar — maximalist
}


def spinner_for_theme(theme_id: str) -> str:
    """Return the Rich spinner name paired with the given theme."""
    return THEME_SPINNERS.get(theme_id, "dots")
