from __future__ import annotations

import locale
import random
import sys
import time
from datetime import datetime

WINDOWS: list[tuple[str, int, int]] = [
    ("dead_of_night", 0, 2),
    ("late_night",    3, 5),
    ("early_morning", 6, 8),
    ("morning",       9, 11),
    ("midday",       12, 13),
    ("afternoon",    14, 16),
    ("evening",      17, 19),
    ("night",        20, 23),
]


def _window_for_hour(hour: int) -> str:
    for wid, start, end in WINDOWS:
        if start <= hour <= end:
            return wid
    return "morning"


GREETINGS: dict[str, list[tuple[str, str]]] = {
    "dead_of_night": [
        ("🌑", "Midnight. Technically a new day, spiritually the same one."),
        ("⏰", "One hour left in the day. The question is which day."),
        ("📜", "The git log ends here. For now."),
        ("🤔", "Midnight is when senior devs briefly become philosophers."),
        ("🐛", "Almost tomorrow. The bugs will still be waiting."),
        ("🤖", "The compiler has no opinion on your life choices."),
        ("🚀", "Last push of the day, technically speaking."),
        ("📅", "The deadline is either tomorrow or past."),
        ("🧪", "Two AM is a commitment to a theory."),
        ("💻", "Still open, still running. That counts for something."),
    ],
    "late_night": [
        ("❌", "The tests are failing. The night is long."),
        ("😴", "CI is asleep. You should be too."),
        ("⚠️",  "Nothing good was ever merged at this hour."),
        ("📝", "The diff is long. The night is longer."),
        ("😬", "Your future self will not thank you for this."),
        ("👁️",  "Insomnia or deadline — the terminal does not judge."),
        ("🌀", "This is not a phase. Or maybe it is."),
        ("🔴", "The log errors make more sense than the hour."),
        ("💪", "Three AM: when stubbornness becomes personality."),
        ("⌛", "The cursor blinks patiently. You have not."),
    ],
    "early_morning": [
        ("⚡", "Either very early or very late. Bold either way."),
        ("☕", "The coffee has not lied to you yet today."),
        ("🐦", "Some birds are up. You have that in common."),
        ("📄", "Dawn and a blank editor — similarly unforgiving."),
        ("🤫", "Still dark. Your standup will never know."),
        ("✅", "First commit of the day. The record is clean."),
        ("🌍", "The world boots slowly. Give it a moment."),
        ("🌅", "Up before the sun. The sun does not care."),
        ("📋", "Seven AM: the last hour the plan still exists."),
        ("⌨️",  "Eight o'clock and the keyboard is already warm."),
    ],
    "morning": [
        ("📌", "The workday technically exists now. Noted."),
        ("☕", "Still two cups of coffee from being functional."),
        ("📆", "Your calendar has opinions. Ignore some of them."),
        ("🐛", "Morning. The bugs from last night are still there."),
        ("🔄", "Fresh session. The context is already loading."),
        ("✅", "Reasonable hour. Low bar, but you cleared it."),
        ("🏃", "The day is young. You are not. Go anyway."),
        ("📬", "Inbox zero is a myth. This session is real."),
        ("🎤", "Ten AM standup: rehearsed, misheard, forgotten."),
        ("🕚", "Eleven. The morning has opinions about itself."),
    ],
    "midday": [
        ("😅", "Noon. The morning got away from you again."),
        ("💡", "Pre-lunch clarity: use it before it evaporates."),
        ("🤖", "Lunch is a suggestion. The compiler has a deadline."),
        ("📊", "The sprint board has not moved itself. Interesting."),
        ("😊", "Twelve o'clock: peak optimism about the afternoon."),
        ("⚖️",  "Halfway through the workday, or halfway into it."),
        ("🎬", "The morning was a rehearsal. This is the actual work."),
        ("🧠", "Late enough to have context, early enough to use it."),
        ("⏱️",  "One PM. The afternoon exists, for better or worse."),
        ("💥", "Midday: the hour the plan meets reality."),
    ],
    "afternoon": [
        ("🌫️", "Post-lunch. Your stack trace is not the only thing foggy."),
        ("📡", "Two PM: peak meeting time, minimum information exchanged."),
        ("📝", "The afternoon is long. So is your TODO list."),
        ("🔭", "Halfway through the day. The code has not noticed."),
        ("🔬", "The feature exists in theory. The afternoon will find out."),
        ("📈", "Statistically the least productive hour. Prove it wrong."),
        ("😬", "Afternoon: when confident commits become cautious ones."),
        ("🦆", "Somewhere a rubber duck is solving someone's problem."),
        ("☕", "Three PM. The caffeine wore off. So did the plan."),
        ("⏰", "Four o'clock: the last honest hour of the workday."),
    ],
    "evening": [
        ("🌙", "After hours. The definition of that is flexible for you."),
        ("📉", "The day had a shape. This is the trailing edge."),
        ("🚢", "Ship it or stash it — the evening asks that question."),
        ("⌚", "Technically off the clock. The terminal missed that memo."),
        ("🍽️",  "Dinner is a concept. So is done."),
        ("🔁", "Evening: the hour of one-more-thing."),
        ("✅", "The build passed. You can probably stop now. Probably."),
        ("📖", "Whatever did not ship today is tomorrow's character arc."),
        ("❓", "Six PM and the codebase has questions."),
        ("🎯", "Seven: the line between work and a hobby blurs."),
    ],
    "night": [
        ("🤡", "A reasonable time to start a refactor. Said no one."),
        ("📉", "The diff grows. The rationale shrinks."),
        ("🖱️",  "Dark outside. The cursor blinks, unbothered."),
        ("💬", "Late enough that the commit message will be honest."),
        ("🔥", "You and the code, alone again. This is fine."),
        ("🎯", "Nine PM: ambitious scope, poor estimates."),
        ("⌨️",  "The keyboard has been patient with you all day."),
        ("🤷", "Not the last session of the week. Probably not."),
        ("🔮", "Ten PM. The feature is close. It has always been close."),
        ("🌃", "Eleven: the night shift begins, asked for or not."),
    ],
}

NATURE_ICONS: list[str] = ["🌊", "🌿", "⛰️", "🌳", "🔥", "🌄", "🌑"]
NATURE_ICONS_ASCII: list[str] = ["~", '"', "^", ":", "*", "/", "o"]


def _supports_unicode() -> bool:
    enc = (getattr(sys.stdout, "encoding", None) or "").lower()
    if enc.startswith(("utf", "cp65001")):
        return True
    try:
        loc = (locale.getpreferredencoding(False) or "").lower()
    except Exception:
        loc = ""
    return loc.startswith("utf")


def pick_icon(now: datetime | None = None) -> str:
    when = now or datetime.now()
    idx = when.weekday()
    if _supports_unicode():
        return NATURE_ICONS[idx]
    return NATURE_ICONS_ASCII[idx]


def pick_greeting(now: datetime | None = None) -> tuple[str, str]:
    """Return ``(emoji, text)`` for the current time window."""
    when = now or datetime.now()
    window = _window_for_hour(when.hour)
    bank = GREETINGS.get(window) or GREETINGS["morning"]
    seed = int(time.time() // 60)
    rng = random.Random(seed ^ hash(window))
    return rng.choice(bank)


THEME_SPINNERS: dict[str, str] = {
    "ocean":    "star",
    "forest":   "star",
    "lavender": "star",
    "sunset":   "star",
    "mono":     "star2",
    "rainbow":  "star",
}


def spinner_for_theme(theme_id: str) -> str:
    return THEME_SPINNERS.get(theme_id, "dots")
