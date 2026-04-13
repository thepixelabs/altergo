"""Tests for the version checker, greeting bank, and theme→spinner wiring.

Covers only the pure units — network code is exercised against a monkey-
patched fetch so no real PyPI request is made during tests.
"""

from __future__ import annotations

import datetime
import importlib.util
import json
from pathlib import Path

import pytest

ROOT = Path(__file__).parent.parent
SCRIPT = ROOT / "altergo.py"


def _load_altergo():
    spec = importlib.util.spec_from_file_location("altergo", SCRIPT)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


# --- Version parser & comparator ------------------------------------------


def test_parse_version_basic():
    mod = _load_altergo()
    assert mod._parse_version("0.12.0") == (0, 12, 0)
    assert mod._parse_version("1.2.3") == (1, 2, 3)


def test_parse_version_strips_prerelease():
    mod = _load_altergo()
    # rc1 / beta suffixes should not break comparison
    assert mod._parse_version("0.13.0rc1") == (0, 13, 0)
    assert mod._parse_version("1.0.0-beta") == (1, 0, 0)
    assert mod._parse_version("2.5.1+local") == (2, 5, 1)


def test_parse_version_bad_input():
    mod = _load_altergo()
    assert mod._parse_version("garbage") == ()
    assert mod._parse_version("") == ()


def test_is_newer_true_and_false():
    mod = _load_altergo()
    assert mod._is_newer("0.13.0", "0.12.0")
    assert mod._is_newer("1.0.0", "0.99.99")
    assert not mod._is_newer("0.12.0", "0.12.0")
    assert not mod._is_newer("0.11.0", "0.12.0")
    # Unparseable never reports newer
    assert not mod._is_newer("garbage", "0.12.0")


# --- Version-string sanitizer ---------------------------------------------


def test_sanitize_version_accepts_clean():
    mod = _load_altergo()
    assert mod._sanitize_version("0.12.0") == "0.12.0"
    assert mod._sanitize_version("1.2.3-rc1") == "1.2.3-rc1"
    assert mod._sanitize_version("2.0.0+build.5") == "2.0.0+build.5"


def test_sanitize_version_rejects_ansi_injection():
    mod = _load_altergo()
    # A crafted PyPI response with ANSI escape sequences must be rejected
    assert mod._sanitize_version("0.13.0\x1b[31mboom") is None
    assert mod._sanitize_version("\x1b]8;;http://evil\x07") is None


def test_sanitize_version_rejects_whitespace_and_long():
    mod = _load_altergo()
    assert mod._sanitize_version("0.13 0") is None
    assert mod._sanitize_version("a" * 50) is None
    assert mod._sanitize_version(None) is None
    assert mod._sanitize_version(123) is None


# --- Update cache roundtrip ------------------------------------------------


def test_update_cache_roundtrip(tmp_path, monkeypatch):
    mod = _load_altergo()
    fake_cache = tmp_path / "version_check.json"
    monkeypatch.setattr(mod, "UPDATE_CACHE_FILE", fake_cache)

    # Miss
    assert mod._read_update_cache() == {}

    # Write clean
    mod._write_update_cache("0.13.5")
    data = mod._read_update_cache()
    assert data["schema_version"] == 1
    assert data["latest_version"] == "0.13.5"
    assert "last_check" in data

    # Poisoned cache (tampered string) → sanitize drops the string
    fake_cache.write_text(json.dumps({
        "schema_version": 1,
        "last_check": 0,
        "latest_version": "0.13.5\x1b[31mX",
    }))
    data = mod._read_update_cache()
    assert "latest_version" not in data


def test_update_cache_bad_schema_returns_empty(tmp_path, monkeypatch):
    mod = _load_altergo()
    fake_cache = tmp_path / "version_check.json"
    monkeypatch.setattr(mod, "UPDATE_CACHE_FILE", fake_cache)

    fake_cache.write_text(json.dumps({"schema_version": 99, "latest_version": "0.13.0"}))
    assert mod._read_update_cache() == {}


# --- update_check enable/disable persistence ------------------------------


def test_update_check_flag_persistence(tmp_path, monkeypatch):
    mod = _load_altergo()
    fake_settings = tmp_path / "settings.json"
    monkeypatch.setattr(mod, "SETTINGS_FILE", fake_settings)

    # Default (no file) is True
    assert mod.load_update_check_enabled() is True

    # Toggle off, sibling keys preserved
    fake_settings.write_text(json.dumps({"theme": "forest"}))
    mod.save_update_check_enabled(False)
    data = json.loads(fake_settings.read_text())
    assert data["theme"] == "forest"
    assert data["update_check"] is False
    assert mod.load_update_check_enabled() is False

    # Toggle on
    mod.save_update_check_enabled(True)
    assert mod.load_update_check_enabled() is True


# --- Greetings module ------------------------------------------------------


def _load_greetings():
    spec = importlib.util.spec_from_file_location(
        "altergo_greetings", ROOT / "altergo_greetings.py"
    )
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_greetings_bank_counts():
    g = _load_greetings()
    total = sum(len(lines) for lines in g.GREETINGS.values())
    assert total == 80, "panel-locked at 80 sentences"
    assert len(g.GREETINGS) == 8, "eight time windows"
    for wid, lines in g.GREETINGS.items():
        assert len(lines) == 10, f"window {wid} must have 10 sentences"


def test_greetings_length_cap():
    g = _load_greetings()
    # Hard cap at ~65 chars so nothing wraps under a 29-wide figlet even
    # after indentation + icon.
    for wid, lines in g.GREETINGS.items():
        for line in lines:
            assert len(line) <= 65, f"'{line}' too long for window {wid}"


def test_greetings_windows_tile_24_hours():
    g = _load_greetings()
    covered = set()
    for wid, start, end in g.WINDOWS:
        for h in range(start, end + 1):
            assert h not in covered, f"hour {h} covered twice"
            covered.add(h)
    assert covered == set(range(24)), "all 24 hours must be covered"


def test_pick_greeting_stable_within_minute():
    g = _load_greetings()
    t = datetime.datetime(2026, 4, 10, 14, 30)  # afternoon window
    a = g.pick_greeting(t)
    b = g.pick_greeting(t)
    assert a == b, "same minute must return same line"
    # The sentence must come from the afternoon window
    assert a in g.GREETINGS["afternoon"]


def test_pick_icon_weekday_mapping():
    g = _load_greetings()
    # 2026-04-13 is a Monday
    mon = datetime.datetime(2026, 4, 13)
    # 2026-04-12 is a Sunday
    sun = datetime.datetime(2026, 4, 12)
    icon_mon = g.pick_icon(mon)
    icon_sun = g.pick_icon(sun)
    # Must be either the emoji or the ASCII fallback
    assert icon_mon in (g.NATURE_ICONS[0], g.NATURE_ICONS_ASCII[0])
    assert icon_sun in (g.NATURE_ICONS[6], g.NATURE_ICONS_ASCII[6])


def test_theme_spinner_map_covers_all_themes():
    g = _load_greetings()
    mod = _load_altergo()
    for theme_id in mod.THEMES.keys():
        spinner = g.spinner_for_theme(theme_id)
        assert isinstance(spinner, str) and spinner


def test_greeting_copy_guardrails():
    """Spot-check the CEO-mandated rewrites and absent patterns."""
    g = _load_greetings()
    # GREETINGS values are now (emoji, text) tuples — extract just the text.
    all_lines = [text for lines in g.GREETINGS.values() for (_, text) in lines]
    joined = " ".join(all_lines).lower()

    # The two CEO-cut lines must NOT be present
    assert "and so are you" not in joined
    assert "ci servers are tired of you" not in joined

    # The two replacements MUST be present
    assert any("the tests are failing" in l.lower() for l in all_lines)
    assert any("ci is asleep" in l.lower() for l in all_lines)


# --- --update-check CLI flag ----------------------------------------------


def test_known_commands_includes_update_check():
    mod = _load_altergo()
    assert "--update-check" in mod._KNOWN_COMMANDS


# --- tmux_session setting -------------------------------------------------


def test_tmux_session_defaults_to_false(tmp_path, monkeypatch):
    """tmux_session must default to False — we never silently enable tmux."""
    mod = _load_altergo()
    fake_settings = tmp_path / "settings.json"
    monkeypatch.setattr(mod, "SETTINGS_FILE", fake_settings)

    # No file → False
    assert mod._load_bool_setting("tmux_session", default=False) is False

    # File without the key → still False
    fake_settings.write_text(json.dumps({"theme": "ocean"}))
    assert mod._load_bool_setting("tmux_session", default=False) is False


def test_tmux_session_persists(tmp_path, monkeypatch):
    """Enabling tmux_session is preserved across reads and sibling keys survive."""
    mod = _load_altergo()
    fake_settings = tmp_path / "settings.json"
    monkeypatch.setattr(mod, "SETTINGS_FILE", fake_settings)

    # Seed existing settings
    fake_settings.write_text(json.dumps({"theme": "forest", "show_greeting": True}))

    # Write tmux_session=True via a direct settings write (simulate save path)
    data = json.loads(fake_settings.read_text())
    data["tmux_session"] = True
    fake_settings.write_text(json.dumps(data, indent=2))

    assert mod._load_bool_setting("tmux_session", default=False) is True
    # Sibling keys intact
    reloaded = json.loads(fake_settings.read_text())
    assert reloaded["theme"] == "forest"
    assert reloaded["show_greeting"] is True


def test_tmux_session_name_format():
    """Session names follow the altergo-<account>-<provider>-<hex> pattern."""
    mod = _load_altergo()
    name = mod._tmux_session_name("work", "claude")
    parts = name.split("-")
    assert parts[0] == "altergo"
    assert parts[1] == "work"
    assert parts[2] == "claude"
    # Hex suffix: 6 chars, all hex digits
    assert len(parts[3]) == 6
    assert all(c in "0123456789abcdef" for c in parts[3])


def test_tmux_session_name_sanitizes_dots_and_colons():
    """Dots and colons in account names are replaced with dashes."""
    mod = _load_altergo()
    name = mod._tmux_session_name("my.account:v2", "gemini")
    assert "." not in name
    assert ":" not in name
    assert name.startswith("altergo-my-account-v2-gemini-")


def test_tmux_session_names_are_unique():
    """Each call to _tmux_session_name returns a distinct name."""
    mod = _load_altergo()
    names = {mod._tmux_session_name("default", "claude") for _ in range(20)}
    assert len(names) == 20


def test_build_tmux_cmd_structure():
    """_build_tmux_cmd wraps the inner command correctly."""
    mod = _load_altergo()
    env = {"HOME": "/tmp/fake-home", "PATH": "/usr/bin:/bin"}
    inner = ["claude", "--resume", "abc"]
    result = mod._build_tmux_cmd(inner, env, "altergo-default-claude-aabbcc")

    assert result[0] == "tmux"
    assert result[1] == "new-session"
    assert "-s" in result
    assert result[result.index("-s") + 1] == "altergo-default-claude-aabbcc"
    # HOME and PATH forwarded via -e flags
    assert "-e" in result
    env_flags = [result[i + 1] for i, v in enumerate(result) if v == "-e"]
    assert any(f.startswith("HOME=") for f in env_flags)
    assert any(f.startswith("PATH=") for f in env_flags)
    # Inner command follows --
    sep = result.index("--")
    assert result[sep + 1 :] == inner


def test_tmux_available_false_when_not_in_path(monkeypatch):
    """_tmux_available returns False when tmux is not on PATH."""
    mod = _load_altergo()
    monkeypatch.setattr(mod.shutil, "which", lambda name: None)
    assert mod._tmux_available() is False


def test_tmux_available_true_when_in_path(monkeypatch):
    """_tmux_available returns True when tmux is on PATH."""
    mod = _load_altergo()
    monkeypatch.setattr(mod.shutil, "which", lambda name: "/usr/bin/tmux" if name == "tmux" else None)
    assert mod._tmux_available() is True
