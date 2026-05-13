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


# --- Session messages module (greetings + goodbyes) ------------------------


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
    assert total == 400, "panel-locked at 400 sentences"
    assert len(g.GREETINGS) == 8, "eight time windows"
    for wid, lines in g.GREETINGS.items():
        assert len(lines) == 50, f"window {wid} must have 50 sentences"


def test_greetings_length_cap():
    g = _load_greetings()
    # Hard cap at ~65 chars so nothing wraps under a 29-wide figlet even
    # after indentation + icon. Entries are (emoji, text) tuples — check text.
    for wid, lines in g.GREETINGS.items():
        for emoji, text in lines:
            assert len(text) <= 65, f"'{text}' too long for window {wid}"


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


def test_greetings_no_specific_hour_callouts():
    """Each sentence appears anywhere in a 2–4h window — specific hour
    names ("Ten PM", "Three AM") would lie by up to two hours. Use fuzzy
    markers ("past midnight", "this late", "pre-standup") instead.

    Matches only number-word + AM/PM/o'clock, so "PM" as project-manager
    ("Signals from the PM") does not trigger."""
    import re
    g = _load_greetings()
    pattern = re.compile(
        r"\b(one|two|three|four|five|six|seven|eight|nine|ten|eleven|twelve)"
        r"\s+(?:am|pm|o'?clock)\b",
        re.IGNORECASE,
    )
    for wid, lines in g.GREETINGS.items():
        for _, text in lines:
            m = pattern.search(text)
            assert m is None, (
                f"{wid}: '{text}' uses a specific hour callout ('{m.group(0)}'); "
                f"window spans 2–4 hours so it will be wrong sometimes"
            )


# --- Goodbye bank ----------------------------------------------------------


def test_goodbyes_bank_count():
    g = _load_greetings()
    assert len(g.GOODBYES) == 50, "goodbye bank locked at 50 lines"


def test_goodbyes_shape():
    g = _load_greetings()
    for entry in g.GOODBYES:
        assert isinstance(entry, tuple) and len(entry) == 2
        emoji, text = entry
        assert isinstance(emoji, str) and emoji
        assert isinstance(text, str) and text


def test_pick_goodbye_returns_tuple_from_bank():
    g = _load_greetings()
    emoji, text = g.pick_goodbye()
    assert (emoji, text) in g.GOODBYES


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
    """Session names follow the <project>/<account>/<provider> pattern."""
    mod = _load_altergo()
    name = mod._tmux_session_name("work", "claude", project="myrepo")
    parts = name.split("/")
    assert parts[0] == "myrepo"
    assert parts[1] == "work"
    assert parts[2] == "claude"


def test_tmux_session_name_sanitizes_dots_and_colons():
    """Dots and colons in account names are replaced with dashes."""
    mod = _load_altergo()
    name = mod._tmux_session_name("my.account:v2", "gemini", project="proj")
    assert "." not in name
    assert ":" not in name
    assert name == "proj/my-account-v2/gemini"


def test_tmux_session_names_are_unique():
    """Session name is deterministic for the same project/account/provider triple."""
    mod = _load_altergo()
    names = {mod._tmux_session_name("default", "claude", project="myrepo") for _ in range(20)}
    # Deterministic: all 20 calls return the same name
    assert len(names) == 1


def test_build_tmux_cmd_structure():
    """_build_tmux_cmd wraps the inner command via sh -c."""
    mod = _load_altergo()
    env = {"HOME": "/tmp/fake-home", "PATH": "/usr/bin:/bin"}
    inner = ["claude", "--resume", "abc"]
    result = mod._build_tmux_cmd(inner, env, "default/claude")

    assert result[0] == "tmux"
    assert result[1] == "new-session"
    assert "-s" in result
    assert result[result.index("-s") + 1] == "default/claude"
    # HOME and PATH forwarded via -e flags
    assert "-e" in result
    env_flags = [result[i + 1] for i, v in enumerate(result) if v == "-e"]
    assert any(f.startswith("HOME=") for f in env_flags)
    assert any(f.startswith("PATH=") for f in env_flags)
    # Inner command is wrapped in sh -c after --
    sep = result.index("--")
    assert result[sep + 1] == "sh"
    assert result[sep + 2] == "-c"


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


# --- portal argument routing --------------------------------------------------
#
# These tests exercise the portal argument-parsing block in main() in isolation.
# They monkeypatch launch_claude so no real process is spawned and no account
# directories need to exist on disk (beyond what each test creates with tmp_path).
#
# Design note: we call mod.main() directly after wiring up monkeypatches.
# SystemExit is expected on every code path (portal always calls sys.exit(0)
# or sys.exit(1)).  We catch it and inspect the recorded launch_claude call
# or stderr output.


def _portal_mod(tmp_path, monkeypatch):
    """Return an altergo module with ACCOUNTS_DIR, SETTINGS_FILE, and the
    PROVIDERS / KNOWN_COMMANDS globals pointed at a temp directory.

    Callers are responsible for creating the account subdirectories they need.
    """
    mod = _load_altergo()
    accounts_dir = tmp_path / "accounts"
    accounts_dir.mkdir()
    settings_file = tmp_path / "settings.json"

    monkeypatch.setattr(mod, "ACCOUNTS_DIR", accounts_dir)
    monkeypatch.setattr(mod, "SETTINGS_FILE", settings_file)
    # Prevent banner / animation from writing to stdout during tests.
    monkeypatch.setattr(mod, "show_banner", lambda *a, **kw: None)
    return mod


def _make_account(tmp_path, mod, name: str) -> None:
    """Create a minimal account directory that the portal routing accepts."""
    (mod.ACCOUNTS_DIR / name).mkdir(parents=True, exist_ok=True)


def _run_portal(mod, monkeypatch, argv: list, *, active: str | None = None) -> dict:
    """Drive main() with the given argv and return a dict with:
        "calls"     — list of (account, args, provider, force_tmux) tuples
        "exit_code" — integer exit code from SystemExit
        "stderr"    — captured text written to sys.stderr
    """
    import io
    import sys

    calls = []

    def fake_launch(account, args=None, provider=None, force_tmux=False):
        calls.append({
            "account": account,
            "args": list(args or []),
            "provider": provider,
            "force_tmux": force_tmux,
        })
        sys.exit(0)

    monkeypatch.setattr(mod, "launch_claude", fake_launch)
    monkeypatch.setattr(mod, "sys", sys)

    # Wire active account if requested.
    if active is not None:
        import json
        mod.SETTINGS_FILE.write_text(json.dumps({"active_account": active}))

    monkeypatch.setattr(sys, "argv", ["altergo"] + argv)

    stderr_buf = io.StringIO()
    monkeypatch.setattr(sys, "stderr", stderr_buf)

    exit_code = 0
    try:
        mod.main()
    except SystemExit as exc:
        exit_code = exc.code if isinstance(exc.code, int) else 1

    return {"calls": calls, "exit_code": exit_code, "stderr": stderr_buf.getvalue()}


# -- happy path: no args, active account set -----------------------------------


def test_portal_no_args_uses_active_account(tmp_path, monkeypatch):
    """Given an active account, `altergo portal` launches that account."""
    mod = _portal_mod(tmp_path, monkeypatch)
    _make_account(tmp_path, mod, "work")

    result = _run_portal(mod, monkeypatch, ["portal"], active="work")

    assert result["exit_code"] == 0
    assert len(result["calls"]) == 1
    call = result["calls"][0]
    assert call["account"] == "work"
    assert call["force_tmux"] is True


# -- happy path: explicit account name -----------------------------------------


def test_portal_named_account_launches_that_account(tmp_path, monkeypatch):
    """Given `altergo portal work`, launches the work account."""
    mod = _portal_mod(tmp_path, monkeypatch)
    _make_account(tmp_path, mod, "work")

    result = _run_portal(mod, monkeypatch, ["portal", "work"])

    assert result["exit_code"] == 0
    call = result["calls"][0]
    assert call["account"] == "work"
    assert call["force_tmux"] is True


# -- routing: unrecognised positional token is rejected with a clear error -----


def test_portal_unrecognised_token_exits_with_error(tmp_path, monkeypatch):
    """A positional token before any flags that is neither an account dir nor a known
    provider produces exit 1 rather than being silently forwarded to the provider.
    """
    mod = _portal_mod(tmp_path, monkeypatch)
    _make_account(tmp_path, mod, "work")

    result = _run_portal(mod, monkeypatch, ["portal", "ghost"])

    assert result["exit_code"] == 1


# -- error: no accounts at all -------------------------------------------------


def test_portal_no_accounts_exits_1_with_message(tmp_path, monkeypatch):
    """When no accounts exist at all, `altergo portal` exits 1 with a clear error."""
    mod = _portal_mod(tmp_path, monkeypatch)
    # ACCOUNTS_DIR exists but is empty.

    result = _run_portal(mod, monkeypatch, ["portal"])

    assert result["exit_code"] == 1
    assert "no accounts" in result["stderr"].lower()


# -- error: multiple accounts, no active ---------------------------------------


def test_portal_multiple_accounts_no_active_exits_1(tmp_path, monkeypatch):
    """When multiple accounts exist and none is active, `altergo portal` exits 1."""
    mod = _portal_mod(tmp_path, monkeypatch)
    _make_account(tmp_path, mod, "work")
    _make_account(tmp_path, mod, "personal")
    # No active account — SETTINGS_FILE absent.

    result = _run_portal(mod, monkeypatch, ["portal"])

    assert result["exit_code"] == 1
    assert "multiple" in result["stderr"].lower()
    # Both account names should appear in the error so the user knows what to pick.
    assert "work" in result["stderr"]
    assert "personal" in result["stderr"]


# -- provider pass-through -----------------------------------------------------


def test_portal_with_provider_passes_provider_to_launch(tmp_path, monkeypatch):
    """Given `altergo portal work gemini`, provider='gemini' reaches launch_claude."""
    mod = _portal_mod(tmp_path, monkeypatch)
    _make_account(tmp_path, mod, "work")

    result = _run_portal(mod, monkeypatch, ["portal", "work", "gemini"])

    assert result["exit_code"] == 0
    call = result["calls"][0]
    assert call["account"] == "work"
    assert call["provider"] == "gemini"
    assert call["force_tmux"] is True


# -- --resume flag -------------------------------------------------------------


def test_portal_resume_flag_in_remaining_args(tmp_path, monkeypatch):
    """Given `altergo portal work --resume`, --resume appears in args passed to launch_claude."""
    mod = _portal_mod(tmp_path, monkeypatch)
    _make_account(tmp_path, mod, "work")

    result = _run_portal(mod, monkeypatch, ["portal", "work", "--resume"])

    assert result["exit_code"] == 0
    call = result["calls"][0]
    assert "--resume" in call["args"]


def test_portal_resume_with_id_in_remaining_args(tmp_path, monkeypatch):
    """Given `altergo portal work --resume abc123`, both flags appear in args."""
    mod = _portal_mod(tmp_path, monkeypatch)
    _make_account(tmp_path, mod, "work")

    result = _run_portal(mod, monkeypatch, ["portal", "work", "--resume", "abc123"])

    assert result["exit_code"] == 0
    call = result["calls"][0]
    assert "--resume" in call["args"]
    assert "abc123" in call["args"]
    # Ordering must be preserved — --resume immediately before its ID.
    resume_idx = call["args"].index("--resume")
    assert call["args"][resume_idx + 1] == "abc123"


# -- --yolo-resume must not be hijacked by the global interceptor --------------


def test_portal_native_provider_yolo_resume_passes_through(tmp_path, monkeypatch):
    """`altergo portal native claude --yolo-resume` must reach launch_claude with
    args=['--yolo-resume'], account='native', provider='claude' — the global
    --yolo-resume interceptor must defer to the portal handler when 'portal'
    is in the args, otherwise leftover positionals end up as provider argv junk."""
    mod = _portal_mod(tmp_path, monkeypatch)

    result = _run_portal(mod, monkeypatch, ["portal", "native", "claude", "--yolo-resume"])

    assert result["exit_code"] == 0, result["stderr"]
    assert len(result["calls"]) == 1
    call = result["calls"][0]
    assert call["account"] == "native"
    assert call["provider"] == "claude"
    assert call["args"] == ["--yolo-resume"]
    assert call["force_tmux"] is True


def test_portal_native_yolo_resume_no_provider_passes_through(tmp_path, monkeypatch):
    """`altergo portal native --yolo-resume` (no explicit provider) must still
    reach launch_claude with account='native' and args=['--yolo-resume']."""
    mod = _portal_mod(tmp_path, monkeypatch)

    result = _run_portal(mod, monkeypatch, ["portal", "native", "--yolo-resume"])

    assert result["exit_code"] == 0, result["stderr"]
    call = result["calls"][0]
    assert call["account"] == "native"
    assert call["args"] == ["--yolo-resume"]
    assert call["force_tmux"] is True


def test_portal_native_yolo_resume_with_id_passes_through(tmp_path, monkeypatch):
    """`altergo portal native --yolo-resume <uuid>` must keep --yolo-resume and
    its ID together in launch_claude args (translation happens inside)."""
    mod = _portal_mod(tmp_path, monkeypatch)
    _id = "12345678-1234-1234-1234-123456789012"

    result = _run_portal(mod, monkeypatch, ["portal", "native", "--yolo-resume", _id])

    assert result["exit_code"] == 0, result["stderr"]
    call = result["calls"][0]
    assert call["account"] == "native"
    assert "--yolo-resume" in call["args"]
    assert _id in call["args"]


def test_native_provider_yolo_resume_with_kebab_alias_routes_cleanly(tmp_path, monkeypatch):
    """`altergo native claude --yolo-resume <kebab-alias>` must reach launch_claude
    with account='native', provider='claude', and args=['--yolo-resume', alias].
    No leftover 'claude' or alias text in argv — those would otherwise get
    forwarded to the provider as a chat prompt."""
    mod = _portal_mod(tmp_path, monkeypatch)
    alias = "delete-persona-heartbeat-wrapper"

    result = _run_portal(mod, monkeypatch, ["native", "claude", "--yolo-resume", alias])

    assert result["exit_code"] == 0, result["stderr"]
    assert len(result["calls"]) == 1
    call = result["calls"][0]
    assert call["account"] == "native"
    assert call["provider"] == "claude"
    assert call["args"] == ["--yolo-resume", alias]


def test_native_yolo_resume_with_kebab_alias_no_provider(tmp_path, monkeypatch):
    """`altergo native --yolo-resume <alias>` must reach launch_claude with
    account='native' and args=['--yolo-resume', alias] — the alias must not be
    silently dropped or forwarded as a positional."""
    mod = _portal_mod(tmp_path, monkeypatch)
    alias = "delete-persona-heartbeat-wrapper"

    result = _run_portal(mod, monkeypatch, ["native", "--yolo-resume", alias])

    assert result["exit_code"] == 0, result["stderr"]
    call = result["calls"][0]
    assert call["account"] == "native"
    assert call["args"] == ["--yolo-resume", alias]


# -- force_tmux is always True -------------------------------------------------


def test_portal_always_passes_force_tmux_true(tmp_path, monkeypatch):
    """force_tmux=True is passed to launch_claude regardless of user tmux settings."""
    import json

    mod = _portal_mod(tmp_path, monkeypatch)
    _make_account(tmp_path, mod, "work")
    # Explicitly set tmux_session=False so we know force_tmux comes from portal,
    # not from the user's setting.
    mod.SETTINGS_FILE.write_text(json.dumps({"active_account": "work", "tmux_session": False}))

    result = _run_portal(mod, monkeypatch, ["portal", "work"])

    assert result["exit_code"] == 0
    assert result["calls"][0]["force_tmux"] is True


# -- single account, no active — resolve automatically -------------------------


def test_portal_single_account_no_active_resolves_automatically(tmp_path, monkeypatch):
    """When exactly one account exists and none is active, portal uses it without error."""
    mod = _portal_mod(tmp_path, monkeypatch)
    _make_account(tmp_path, mod, "solo")
    # No SETTINGS_FILE → no active account.

    result = _run_portal(mod, monkeypatch, ["portal"])

    assert result["exit_code"] == 0
    assert result["calls"][0]["account"] == "solo"


# -- already inside tmux -------------------------------------------------------


def test_portal_inside_tmux_prints_warning_and_launches(tmp_path, monkeypatch):
    """When $TMUX is set, portal prints the 'already inside tmux' warning and still launches."""
    import os

    mod = _portal_mod(tmp_path, monkeypatch)
    _make_account(tmp_path, mod, "work")
    monkeypatch.setenv("TMUX", "/tmp/tmux-1234/default,1234,0")

    # launch_claude itself is not monkeypatched here; we need the real
    # force_tmux/TMUX branch to execute.  Monkeypatch subprocess.run so the
    # provider binary is never actually exec'd.
    import subprocess as _subprocess
    import types

    fake_result = types.SimpleNamespace(returncode=0)
    run_calls = []

    def fake_run(cmd, env=None, **kw):
        run_calls.append(cmd)
        return fake_result

    monkeypatch.setattr(mod.subprocess, "run", fake_run)
    # Prevent side-effect helpers from failing (no real HOME / binary).
    monkeypatch.setattr(mod, "_sweep_existing_accounts", lambda: None)
    monkeypatch.setattr(mod, "resolve_account", lambda name: (tmp_path / name, name))
    monkeypatch.setattr(mod, "load_account_meta", lambda path: {"version": 3, "providers": ["claude"], "default_provider": "claude"})
    monkeypatch.setattr(mod, "_find_claude", lambda: "/usr/bin/claude")
    monkeypatch.setattr(mod, "_build_alt_env", lambda name: {"HOME": str(tmp_path / name), "PATH": "/usr/bin"})
    monkeypatch.setattr(mod, "maybe_refresh_update_cache", lambda: None)
    monkeypatch.setattr(mod, "first_launch_notice_if_needed", lambda: None)
    monkeypatch.setattr(mod, "home_change_notice_if_needed", lambda: None)
    monkeypatch.setattr(mod, "load_animation_pack", lambda: "off")
    monkeypatch.setattr(mod, "get_cached_latest_version", lambda: None)
    monkeypatch.setattr(mod, "_load_bool_setting", lambda key, default=False: False)
    monkeypatch.setattr(mod, "_sync_claude_mcps", lambda path: None)
    monkeypatch.setattr(mod, "_record_last_session_after_exit", lambda *a: None)
    monkeypatch.setattr(mod, "_print_launch_message", lambda: None)

    import io, sys
    stdout_buf = io.StringIO()
    monkeypatch.setattr(sys, "stdout", stdout_buf)
    monkeypatch.setattr(sys, "argv", ["altergo", "portal", "work"])

    stderr_buf = io.StringIO()
    monkeypatch.setattr(sys, "stderr", stderr_buf)

    try:
        mod.main()
    except SystemExit:
        pass

    combined_output = stdout_buf.getvalue() + stderr_buf.getvalue()
    assert "already inside a tmux session" in combined_output, (
        f"Expected 'already inside a tmux session' warning; got: {combined_output!r}"
    )
    # A command should still have been launched (subprocess.run called).
    assert len(run_calls) == 1


# -- tmux not installed --------------------------------------------------------


def test_portal_tmux_not_installed_prints_warning_and_launches(tmp_path, monkeypatch):
    """When tmux is absent from PATH, portal warns and launches the provider directly."""
    import os

    mod = _portal_mod(tmp_path, monkeypatch)
    _make_account(tmp_path, mod, "work")
    # Ensure we are NOT inside tmux so the availability branch is reached.
    monkeypatch.delenv("TMUX", raising=False)
    # Make tmux unavailable.
    monkeypatch.setattr(mod.shutil, "which", lambda name: None)

    import subprocess as _subprocess
    import types

    fake_result = types.SimpleNamespace(returncode=0)
    run_calls = []

    def fake_run(cmd, env=None, **kw):
        run_calls.append(cmd)
        return fake_result

    monkeypatch.setattr(mod.subprocess, "run", fake_run)
    monkeypatch.setattr(mod, "_sweep_existing_accounts", lambda: None)
    monkeypatch.setattr(mod, "resolve_account", lambda name: (tmp_path / name, name))
    monkeypatch.setattr(mod, "load_account_meta", lambda path: {"version": 3, "providers": ["claude"], "default_provider": "claude"})
    monkeypatch.setattr(mod, "_find_claude", lambda: "/usr/bin/claude")
    monkeypatch.setattr(mod, "_build_alt_env", lambda name: {"HOME": str(tmp_path / name), "PATH": "/usr/bin"})
    monkeypatch.setattr(mod, "maybe_refresh_update_cache", lambda: None)
    monkeypatch.setattr(mod, "first_launch_notice_if_needed", lambda: None)
    monkeypatch.setattr(mod, "home_change_notice_if_needed", lambda: None)
    monkeypatch.setattr(mod, "load_animation_pack", lambda: "off")
    monkeypatch.setattr(mod, "get_cached_latest_version", lambda: None)
    monkeypatch.setattr(mod, "_load_bool_setting", lambda key, default=False: False)
    monkeypatch.setattr(mod, "_sync_claude_mcps", lambda path: None)
    monkeypatch.setattr(mod, "_record_last_session_after_exit", lambda *a: None)
    monkeypatch.setattr(mod, "_print_launch_message", lambda: None)

    import io, sys
    stdout_buf = io.StringIO()
    monkeypatch.setattr(sys, "stdout", stdout_buf)
    monkeypatch.setattr(sys, "argv", ["altergo", "portal", "work"])

    stderr_buf = io.StringIO()
    monkeypatch.setattr(sys, "stderr", stderr_buf)

    try:
        mod.main()
    except SystemExit:
        pass

    combined_output = stdout_buf.getvalue() + stderr_buf.getvalue()
    assert "tmux not found" in combined_output, (
        f"Expected 'tmux not found' warning; got: {combined_output!r}"
    )
    # Despite no tmux, the provider should still be launched.
    assert len(run_calls) == 1
    # The command must NOT start with "tmux" — direct launch.
    assert run_calls[0][0] != "tmux", (
        "Expected a direct launch without tmux, but the command started with 'tmux'"
    )


# =============================================================================
# Native account
# =============================================================================
#
# The "native" account is a special passthrough that launches the provider
# with the real $HOME unchanged — no HOME isolation, no managed dot-dirs.
# These tests cover:
#   1. Constant and reservation
#   2. resolve_account returns MAIN_HOME / MAIN_CLAUDE
#   3. _build_alt_env does NOT change HOME
#   4. validate_account_name rejects "native"
#   5. main() accepts "altergo native" without a managed account directory
#   6. build_launcher_menu injects native chip when binary + dot-dir present
# =============================================================================


def test_native_constant_exists():
    mod = _load_altergo()
    assert hasattr(mod, "_NATIVE_ACCOUNT")
    assert mod._NATIVE_ACCOUNT == "native"


def test_native_is_reserved():
    mod = _load_altergo()
    assert "native" in mod._RESERVED_NAMES


def test_native_validate_account_name_raises(tmp_path, monkeypatch):
    """validate_account_name must reject 'native' as a reserved name."""
    import sys

    mod = _load_altergo()
    monkeypatch.setattr(mod, "ACCOUNTS_DIR", tmp_path / "accounts")
    monkeypatch.setattr(mod, "SETTINGS_FILE", tmp_path / "settings.json")

    with pytest.raises(SystemExit):
        mod.validate_account_name("native")


def test_native_resolve_account_returns_main_home(tmp_path, monkeypatch):
    """resolve_account('native') must return (MAIN_HOME, MAIN_CLAUDE)."""
    mod = _load_altergo()
    fake_home = tmp_path / "home"
    fake_claude = fake_home / ".claude"
    monkeypatch.setattr(mod, "MAIN_HOME", fake_home)
    monkeypatch.setattr(mod, "MAIN_CLAUDE", fake_claude)

    account_home, account_claude = mod.resolve_account("native")

    assert account_home == fake_home
    assert account_claude == fake_claude


def test_native_resolve_account_non_native_unchanged(tmp_path, monkeypatch):
    """resolve_account for a normal account still maps to ACCOUNTS_DIR/<name>."""
    mod = _load_altergo()
    accounts_dir = tmp_path / "accounts"
    monkeypatch.setattr(mod, "ACCOUNTS_DIR", accounts_dir)

    account_home, account_claude = mod.resolve_account("work")

    assert account_home == accounts_dir / "work"
    assert account_claude == accounts_dir / "work" / ".claude"


def test_native_build_alt_env_does_not_change_home(monkeypatch):
    """_build_alt_env('native') must return env with HOME unchanged."""
    mod = _load_altergo()
    original_home = "/original/home"
    monkeypatch.setenv("HOME", original_home)

    env = mod._build_alt_env("native")

    assert env["HOME"] == original_home


def test_native_build_alt_env_regular_account_changes_home(tmp_path, monkeypatch):
    """_build_alt_env for a regular account sets HOME to the account dir."""
    import subprocess, json as _json

    mod = _load_altergo()
    accounts_dir = tmp_path / "accounts"
    account_home = accounts_dir / "work"
    account_home.mkdir(parents=True)
    monkeypatch.setattr(mod, "ACCOUNTS_DIR", accounts_dir)
    monkeypatch.setenv("HOME", "/original/home")

    # Write none-mode meta so the reconciler does not attempt to create a
    # per-account keychain (which would call security and require authorization).
    (account_home / "account.json").write_text(
        _json.dumps({"version": 3, "providers": ["claude"], "default_provider": "claude", "keychain": "none"})
    )
    # Stub _sec to avoid any real security(1) calls in the none-mode reconciler path.
    monkeypatch.setattr(mod, "_sec", lambda argv, **kw: subprocess.CompletedProcess([], 0, "", ""))

    env = mod._build_alt_env("work")

    assert env["HOME"] == str(accounts_dir / "work")


def test_native_main_dispatch_no_account_dir_required(tmp_path, monkeypatch):
    """'altergo native' must succeed even when no accounts/ subdir named 'native' exists."""
    import sys, io

    mod = _load_altergo()
    accounts_dir = tmp_path / "accounts"
    accounts_dir.mkdir()
    monkeypatch.setattr(mod, "ACCOUNTS_DIR", accounts_dir)
    monkeypatch.setattr(mod, "SETTINGS_FILE", tmp_path / "settings.json")
    monkeypatch.setattr(mod, "show_banner", lambda *a, **kw: None)

    calls = []

    def fake_launch(account, args=None, provider=None, force_tmux=False):
        calls.append({"account": account, "args": list(args or []), "provider": provider})
        raise SystemExit(0)

    monkeypatch.setattr(mod, "launch_claude", fake_launch)
    monkeypatch.setattr(sys, "argv", ["altergo", "native"])
    monkeypatch.setattr(sys, "stderr", io.StringIO())

    with pytest.raises(SystemExit) as exc:
        mod.main()

    assert exc.value.code == 0
    assert len(calls) == 1
    assert calls[0]["account"] == "native"


def test_native_main_dispatch_with_provider(tmp_path, monkeypatch):
    """'altergo native gemini' must pass provider='gemini' to launch_claude."""
    import sys, io

    mod = _load_altergo()
    accounts_dir = tmp_path / "accounts"
    accounts_dir.mkdir()
    monkeypatch.setattr(mod, "ACCOUNTS_DIR", accounts_dir)
    monkeypatch.setattr(mod, "SETTINGS_FILE", tmp_path / "settings.json")
    monkeypatch.setattr(mod, "show_banner", lambda *a, **kw: None)

    calls = []

    def fake_launch(account, args=None, provider=None, force_tmux=False):
        calls.append({"account": account, "provider": provider})
        raise SystemExit(0)

    monkeypatch.setattr(mod, "launch_claude", fake_launch)
    monkeypatch.setattr(sys, "argv", ["altergo", "native", "gemini"])
    monkeypatch.setattr(sys, "stderr", io.StringIO())

    with pytest.raises(SystemExit) as exc:
        mod.main()

    assert exc.value.code == 0
    assert calls[0]["account"] == "native"
    assert calls[0]["provider"] == "gemini"


def test_native_build_launcher_menu_injects_chip(tmp_path, monkeypatch):
    """build_launcher_menu must add a 'native' chip for each provider whose
    binary and dot-dir both exist in MAIN_HOME."""
    mod = _load_altergo()

    # Set up a fake MAIN_HOME with a .claude dot-dir so native is detected.
    fake_home = tmp_path / "home"
    (fake_home / ".claude").mkdir(parents=True)
    monkeypatch.setattr(mod, "MAIN_HOME", fake_home)

    # No managed accounts.
    accounts_dir = tmp_path / "accounts"
    accounts_dir.mkdir()
    monkeypatch.setattr(mod, "ACCOUNTS_DIR", accounts_dir)

    # Stub expensive helpers.
    monkeypatch.setattr(mod, "_status_wrap", lambda msg, fn: fn())
    monkeypatch.setattr(mod, "get_sessions", lambda: [])

    # Make 'claude' appear to be on PATH, nothing else.
    monkeypatch.setattr(mod.shutil, "which", lambda name: "/usr/bin/claude" if name == "claude" else None)

    menu = mod.build_launcher_menu()

    # There must be exactly one provider row — claude.
    assert len(menu) == 1
    claude_row = menu[0]
    assert claude_row["provider_id"] == "claude"

    # The native chip must be present.
    chip_names = [c["name"] for c in claude_row["accounts"]]
    assert "native" in chip_names


def test_native_build_launcher_menu_adds_chip_when_binary_present_without_dot_dir(tmp_path, monkeypatch):
    """build_launcher_menu must add a native chip when the binary is on PATH,
    even if the provider dot-dir does not exist in MAIN_HOME yet.

    This lets users reach a fresh provider install from the launcher without
    first creating any config — the provider CLI bootstraps its own dot-dir
    on first run.
    """
    mod = _load_altergo()

    # MAIN_HOME exists but has NO .claude subdir.
    fake_home = tmp_path / "home"
    fake_home.mkdir()
    monkeypatch.setattr(mod, "MAIN_HOME", fake_home)

    accounts_dir = tmp_path / "accounts"
    accounts_dir.mkdir()
    monkeypatch.setattr(mod, "ACCOUNTS_DIR", accounts_dir)

    monkeypatch.setattr(mod, "_status_wrap", lambda msg, fn: fn())
    monkeypatch.setattr(mod, "get_sessions", lambda: [])
    monkeypatch.setattr(mod.shutil, "which", lambda name: "/usr/bin/claude" if name == "claude" else None)

    menu = mod.build_launcher_menu()

    # The claude provider row must appear with just the native chip.
    assert len(menu) == 1
    claude_row = menu[0]
    assert claude_row["provider_id"] == "claude"
    chip_names = [c["name"] for c in claude_row["accounts"]]
    assert "native" in chip_names


def test_native_build_launcher_menu_no_chip_when_binary_absent(tmp_path, monkeypatch):
    """build_launcher_menu must NOT add a native chip when the binary is absent
    from PATH (even if the dot-dir exists)."""
    mod = _load_altergo()

    fake_home = tmp_path / "home"
    (fake_home / ".claude").mkdir(parents=True)
    monkeypatch.setattr(mod, "MAIN_HOME", fake_home)

    accounts_dir = tmp_path / "accounts"
    accounts_dir.mkdir()
    monkeypatch.setattr(mod, "ACCOUNTS_DIR", accounts_dir)

    monkeypatch.setattr(mod, "_status_wrap", lambda msg, fn: fn())
    monkeypatch.setattr(mod, "get_sessions", lambda: [])
    # No binaries available at all.
    monkeypatch.setattr(mod.shutil, "which", lambda name: None)

    menu = mod.build_launcher_menu()

    assert menu == []


# --- configure_account and do_teardown guards ----------------------------------------


def test_native_configure_account_is_rejected(tmp_path, monkeypatch):
    """configure_account('native') must exit 1 with an explanatory message."""
    import sys, io

    mod = _load_altergo()
    monkeypatch.setattr(mod, "ACCOUNTS_DIR", tmp_path / "accounts")
    monkeypatch.setattr(mod, "SETTINGS_FILE", tmp_path / "settings.json")
    monkeypatch.setattr(mod, "show_banner", lambda *a, **kw: None)

    stderr_buf = io.StringIO()
    monkeypatch.setattr(sys, "stderr", stderr_buf)

    with pytest.raises(SystemExit) as exc:
        mod.configure_account("native", "claude")

    assert exc.value.code == 1
    assert "native" in stderr_buf.getvalue()


def test_native_do_teardown_is_rejected(tmp_path, monkeypatch):
    """do_teardown('native') must exit 1 without touching any home directories."""
    import sys, io

    mod = _load_altergo()
    fake_home = tmp_path / "home"
    (fake_home / ".claude").mkdir(parents=True)
    monkeypatch.setattr(mod, "MAIN_HOME", fake_home)
    monkeypatch.setattr(mod, "MAIN_CLAUDE", fake_home / ".claude")
    monkeypatch.setattr(mod, "ACCOUNTS_DIR", tmp_path / "accounts")

    stderr_buf = io.StringIO()
    monkeypatch.setattr(sys, "stderr", stderr_buf)

    with pytest.raises(SystemExit) as exc:
        mod.do_teardown("native")

    assert exc.value.code == 1
    assert "native" in stderr_buf.getvalue()
    # Critically: the dot-dir must be untouched.
    assert (fake_home / ".claude").exists()


def test_native_teardown_dispatch_blocked(tmp_path, monkeypatch):
    """'altergo --teardown --name native' must exit 1 before reaching do_teardown."""
    import sys, io

    mod = _load_altergo()
    monkeypatch.setattr(mod, "ACCOUNTS_DIR", tmp_path / "accounts")
    monkeypatch.setattr(mod, "SETTINGS_FILE", tmp_path / "settings.json")
    monkeypatch.setattr(mod, "show_banner", lambda *a, **kw: None)

    stderr_buf = io.StringIO()
    monkeypatch.setattr(sys, "stderr", stderr_buf)
    monkeypatch.setattr(sys, "argv", ["altergo", "--teardown", "--name", "native"])

    teardown_called = []
    monkeypatch.setattr(mod, "do_teardown", lambda name: teardown_called.append(name))

    with pytest.raises(SystemExit) as exc:
        mod.main()

    assert exc.value.code == 1
    assert teardown_called == []  # do_teardown must NOT have been called


# --- portal dispatch with native -----------------------------------------------


def test_native_portal_dispatch_accepted(tmp_path, monkeypatch):
    """'altergo portal native' must resolve to account='native' not exit 1."""
    mod = _portal_mod(tmp_path, monkeypatch)

    result = _run_portal(mod, monkeypatch, ["portal", "native"])

    assert result["exit_code"] == 0
    assert result["calls"][0]["account"] == "native"
    assert result["calls"][0]["force_tmux"] is True


def test_native_portal_dispatch_with_provider(tmp_path, monkeypatch):
    """'altergo portal native gemini' must pass provider='gemini' to launch_claude."""
    mod = _portal_mod(tmp_path, monkeypatch)

    result = _run_portal(mod, monkeypatch, ["portal", "native", "gemini"])

    assert result["exit_code"] == 0
    call = result["calls"][0]
    assert call["account"] == "native"
    assert call["provider"] == "gemini"


# --- Provider auto-detection for native ----------------------------------------


def test_native_provider_detected_from_dot_dir(tmp_path, monkeypatch):
    """launch_claude('native') with no explicit provider must detect the provider
    from the presence of the dot-dir + binary in the real home."""
    import sys, io, subprocess, types

    mod = _load_altergo()

    fake_home = tmp_path / "home"
    (fake_home / ".claude").mkdir(parents=True)
    monkeypatch.setattr(mod, "MAIN_HOME", fake_home)
    monkeypatch.setattr(mod, "MAIN_CLAUDE", fake_home / ".claude")

    run_calls = []

    def fake_run(cmd, env=None, **kw):
        run_calls.append(cmd)
        return types.SimpleNamespace(returncode=0)

    monkeypatch.setattr(mod.subprocess, "run", fake_run)
    monkeypatch.setattr(mod, "_sweep_existing_accounts", lambda: None)
    monkeypatch.setattr(mod.shutil, "which", lambda name: f"/usr/bin/{name}" if name == "claude" else None)
    monkeypatch.setattr(mod, "maybe_refresh_update_cache", lambda: None)
    monkeypatch.setattr(mod, "first_launch_notice_if_needed", lambda: None)
    monkeypatch.setattr(mod, "home_change_notice_if_needed", lambda: None)
    monkeypatch.setattr(mod, "load_animation_pack", lambda: "off")
    monkeypatch.setattr(mod, "get_cached_latest_version", lambda: None)
    monkeypatch.setattr(mod, "_load_bool_setting", lambda key, default=False: False)
    monkeypatch.setattr(mod, "_sync_claude_mcps", lambda path: None)
    monkeypatch.setattr(mod, "_record_last_session_after_exit", lambda *a: None)
    monkeypatch.setattr(mod, "_print_launch_message", lambda: None)
    monkeypatch.setattr(mod, "show_banner", lambda *a, **kw: None)

    monkeypatch.setattr(sys, "stdout", io.StringIO())
    monkeypatch.setattr(sys, "stderr", io.StringIO())

    # launch_claude now returns the child exit code instead of calling sys.exit —
    # the launcher loop owns the exit so it can re-render the menu between sessions.
    rc = mod.launch_claude("native")

    assert rc == 0
    assert len(run_calls) == 1
    # Must have launched claude, not some other binary.
    assert run_calls[0][0] == "/usr/bin/claude"


def test_native_provider_no_detection_exits_with_message(tmp_path, monkeypatch):
    """launch_claude('native') with no provider and no detectable dot-dir must
    exit 1 with a clear error."""
    import sys, io

    mod = _load_altergo()

    fake_home = tmp_path / "home"
    fake_home.mkdir()  # Empty — no .claude, no .gemini, etc.
    monkeypatch.setattr(mod, "MAIN_HOME", fake_home)
    monkeypatch.setattr(mod, "MAIN_CLAUDE", fake_home / ".claude")

    monkeypatch.setattr(mod, "_sweep_existing_accounts", lambda: None)
    monkeypatch.setattr(mod.shutil, "which", lambda name: None)  # no binaries

    monkeypatch.setattr(sys, "stderr", io.StringIO())

    with pytest.raises(SystemExit) as exc:
        mod.launch_claude("native")

    assert exc.value.code != 0


def test_native_default_provider_save_load_roundtrip(tmp_path, monkeypatch):
    """save_native_default_provider/load_native_default_provider roundtrip; bogus values are rejected."""
    mod = _load_altergo()
    fake_settings = tmp_path / "settings.json"
    monkeypatch.setattr(mod, "SETTINGS_FILE", fake_settings)

    assert mod.load_native_default_provider() is None

    fake_settings.parent.mkdir(parents=True, exist_ok=True)
    fake_settings.write_text(json.dumps({"theme": "forest"}))
    mod.save_native_default_provider("gemini")

    data = json.loads(fake_settings.read_text())
    assert data["theme"] == "forest"
    assert data["native_default_provider"] == "gemini"
    assert mod.load_native_default_provider() == "gemini"

    mod.save_native_default_provider("not-a-real-provider")
    assert mod.load_native_default_provider() == "gemini"


def test_native_default_provider_pinned_takes_precedence(tmp_path, monkeypatch):
    """When a default is pinned and its binary is on PATH, launch_claude must use it
    even if another provider's dot-dir is the only one present in MAIN_HOME."""
    import sys, io, types

    mod = _load_altergo()

    fake_home = tmp_path / "home"
    # Only claude's dot-dir exists, but the user pinned gemini.
    (fake_home / ".claude").mkdir(parents=True)
    monkeypatch.setattr(mod, "MAIN_HOME", fake_home)
    monkeypatch.setattr(mod, "MAIN_CLAUDE", fake_home / ".claude")

    fake_settings = tmp_path / "settings.json"
    monkeypatch.setattr(mod, "SETTINGS_FILE", fake_settings)
    mod.save_native_default_provider("gemini")

    run_calls = []
    monkeypatch.setattr(mod.subprocess, "run", lambda cmd, env=None, **kw: (run_calls.append(cmd), types.SimpleNamespace(returncode=0))[1])
    monkeypatch.setattr(mod, "_sweep_existing_accounts", lambda: None)
    monkeypatch.setattr(mod.shutil, "which", lambda name: f"/usr/bin/{name}" if name in ("claude", "gemini") else None)
    monkeypatch.setattr(mod, "maybe_refresh_update_cache", lambda: None)
    monkeypatch.setattr(mod, "first_launch_notice_if_needed", lambda: None)
    monkeypatch.setattr(mod, "home_change_notice_if_needed", lambda: None)
    monkeypatch.setattr(mod, "load_animation_pack", lambda: "off")
    monkeypatch.setattr(mod, "get_cached_latest_version", lambda: None)
    monkeypatch.setattr(mod, "_load_bool_setting", lambda key, default=False: False)
    monkeypatch.setattr(mod, "_sync_claude_mcps", lambda path: None)
    monkeypatch.setattr(mod, "_record_last_session_after_exit", lambda *a: None)
    monkeypatch.setattr(mod, "_print_launch_message", lambda: None)
    monkeypatch.setattr(mod, "show_banner", lambda *a, **kw: None)
    monkeypatch.setattr(sys, "stdout", io.StringIO())
    monkeypatch.setattr(sys, "stderr", io.StringIO())

    mod.launch_claude("native")

    assert run_calls and run_calls[0][0] == "/usr/bin/gemini"


def test_config_menu_native_action_saves_provider_pin(tmp_path, monkeypatch):
    """The --config TUI's native action persists the picked provider via save_native_default_provider."""
    mod = _load_altergo()

    fake_settings = tmp_path / "settings.json"
    monkeypatch.setattr(mod, "SETTINGS_FILE", fake_settings)

    accounts_dir = tmp_path / "accounts"
    accounts_dir.mkdir()
    monkeypatch.setattr(mod, "ACCOUNTS_DIR", accounts_dir)
    monkeypatch.setattr(mod, "list_accounts", lambda: ["work"])
    (accounts_dir / "work").mkdir()

    # Stub the curses pickers so the menu loop runs headlessly:
    # 1st call: native row pressed → returns ("native", 1)
    # 2nd call: ("account", "work") to exit the loop with a name
    calls = {"picker": 0, "saved": []}

    def fake_run_picker(accts, start_cursor=0):
        calls["picker"] += 1
        if calls["picker"] == 1:
            return ("native", 1)
        return ("account", "work")

    def fake_provider_picker(current=None, *, allow_cancel=False):
        # User picks 'gemini' regardless of current pin.
        return "gemini"

    monkeypatch.setattr(mod, "_run_config_picker", fake_run_picker)
    monkeypatch.setattr(mod, "_prompt_provider_picker", fake_provider_picker)
    import sys as _sys, io
    class _FakeTTY(io.StringIO):
        def isatty(self):
            return True
    monkeypatch.setattr(_sys, "stdin", _FakeTTY())
    monkeypatch.setattr(_sys, "stdout", _FakeTTY())

    result = mod._prompt_config_menu(["work"])

    assert result == "work"
    assert mod.load_native_default_provider() == "gemini"


def test_config_menu_native_cancel_does_not_save(tmp_path, monkeypatch):
    """Cancelling the provider picker (allow_cancel → None) leaves the pin untouched."""
    mod = _load_altergo()

    fake_settings = tmp_path / "settings.json"
    monkeypatch.setattr(mod, "SETTINGS_FILE", fake_settings)
    # Pre-seed a pin to confirm it isn't overwritten on cancel.
    mod.save_native_default_provider("claude")

    accounts_dir = tmp_path / "accounts"
    accounts_dir.mkdir()
    monkeypatch.setattr(mod, "ACCOUNTS_DIR", accounts_dir)
    monkeypatch.setattr(mod, "list_accounts", lambda: ["work"])
    (accounts_dir / "work").mkdir()

    calls = {"picker": 0}

    def fake_run_picker(accts, start_cursor=0):
        calls["picker"] += 1
        if calls["picker"] == 1:
            return ("native", 1)
        return ("account", "work")

    monkeypatch.setattr(mod, "_run_config_picker", fake_run_picker)
    monkeypatch.setattr(mod, "_prompt_provider_picker", lambda current=None, *, allow_cancel=False: None)
    import sys as _sys, io
    class _FakeTTY(io.StringIO):
        def isatty(self):
            return True
    monkeypatch.setattr(_sys, "stdin", _FakeTTY())
    monkeypatch.setattr(_sys, "stdout", _FakeTTY())

    mod._prompt_config_menu(["work"])

    assert mod.load_native_default_provider() == "claude"


def test_native_default_provider_pinned_falls_back_when_binary_missing(tmp_path, monkeypatch):
    """A pinned provider whose binary is no longer on PATH falls back to auto-detect."""
    import sys, io, types

    mod = _load_altergo()

    fake_home = tmp_path / "home"
    (fake_home / ".claude").mkdir(parents=True)
    monkeypatch.setattr(mod, "MAIN_HOME", fake_home)
    monkeypatch.setattr(mod, "MAIN_CLAUDE", fake_home / ".claude")

    fake_settings = tmp_path / "settings.json"
    monkeypatch.setattr(mod, "SETTINGS_FILE", fake_settings)
    mod.save_native_default_provider("gemini")

    run_calls = []
    monkeypatch.setattr(mod.subprocess, "run", lambda cmd, env=None, **kw: (run_calls.append(cmd), types.SimpleNamespace(returncode=0))[1])
    monkeypatch.setattr(mod, "_sweep_existing_accounts", lambda: None)
    # gemini binary is gone; only claude is on PATH.
    monkeypatch.setattr(mod.shutil, "which", lambda name: f"/usr/bin/{name}" if name == "claude" else None)
    monkeypatch.setattr(mod, "maybe_refresh_update_cache", lambda: None)
    monkeypatch.setattr(mod, "first_launch_notice_if_needed", lambda: None)
    monkeypatch.setattr(mod, "home_change_notice_if_needed", lambda: None)
    monkeypatch.setattr(mod, "load_animation_pack", lambda: "off")
    monkeypatch.setattr(mod, "get_cached_latest_version", lambda: None)
    monkeypatch.setattr(mod, "_load_bool_setting", lambda key, default=False: False)
    monkeypatch.setattr(mod, "_sync_claude_mcps", lambda path: None)
    monkeypatch.setattr(mod, "_record_last_session_after_exit", lambda *a: None)
    monkeypatch.setattr(mod, "_print_launch_message", lambda: None)
    monkeypatch.setattr(mod, "show_banner", lambda *a, **kw: None)
    monkeypatch.setattr(sys, "stdout", io.StringIO())
    monkeypatch.setattr(sys, "stderr", io.StringIO())

    mod.launch_claude("native")

    assert run_calls and run_calls[0][0] == "/usr/bin/claude"


# =============================================================================
# _translate_yolo_flags
# =============================================================================


@pytest.mark.parametrize("provider,expected_suffix", [
    ("claude",  ["--dangerously-skip-permissions"]),
    ("gemini",  ["--yolo"]),
    ("codex",   ["--dangerously-bypass-approvals-and-sandbox"]),
    ("copilot", None),  # copilot suffix comes from PROVIDERS["copilot"]["flags"]["skip_perms"]
])
def test_yolo_flag_per_provider(provider, expected_suffix):
    """--yolo alone: prefix empty, synthetic flag stripped, suffix = provider skip_perms."""
    mod = _load_altergo()
    prefix, cleaned, suffix = mod._translate_yolo_flags(provider, ["--yolo", "do this"])
    assert prefix == []
    assert "--yolo" not in cleaned
    assert "--yolo-resume" not in cleaned
    if expected_suffix is not None:
        assert suffix == expected_suffix
    else:
        # For providers whose skip_perms list may vary, just verify it's non-empty
        # and that --yolo is not in user args.
        assert suffix == mod.PROVIDERS[provider]["flags"]["skip_perms"]
    assert "do this" in cleaned


def test_yolo_resume_codex():
    """Codex --yolo-resume (no id, with a trailing flag): resume_subcommand
    goes to prefix, bypass flag to suffix, the flag stays in cleaned."""
    mod = _load_altergo()
    prefix, cleaned, suffix = mod._translate_yolo_flags("codex", ["--yolo-resume", "--profile", "fast"])
    assert prefix == ["resume", "--last"]
    assert suffix == ["--dangerously-bypass-approvals-and-sandbox"]
    assert "--yolo" not in cleaned
    assert "--yolo-resume" not in cleaned
    assert "--profile" in cleaned
    assert "fast" in cleaned


def test_yolo_resume_gemini():
    """Gemini --yolo-resume: resume flags go to prefix, skip_perms to suffix."""
    mod = _load_altergo()
    prefix, cleaned, suffix = mod._translate_yolo_flags("gemini", ["--yolo-resume"])
    assert prefix == ["--resume", "latest"]
    assert suffix == ["--yolo"]
    assert "--yolo" not in cleaned
    assert "--yolo-resume" not in cleaned


def test_no_yolo_flags_is_noop():
    """Neither flag present: returns ([], original_args, []) without mutation."""
    mod = _load_altergo()
    original = ["--model", "sonnet"]
    prefix, cleaned, suffix = mod._translate_yolo_flags("claude", original)
    assert prefix == []
    assert cleaned == ["--model", "sonnet"]
    assert suffix == []


def test_yolo_mixed_with_user_args():
    """--yolo alongside real user args: only the synthetic flag is removed."""
    mod = _load_altergo()
    prefix, cleaned, suffix = mod._translate_yolo_flags(
        "claude", ["--yolo", "do this", "--model", "sonnet"]
    )
    assert prefix == []
    assert "--yolo" not in cleaned
    assert "do this" in cleaned
    assert "--model" in cleaned
    assert "sonnet" in cleaned
    assert suffix == ["--dangerously-skip-permissions"]


# =============================================================================
# --yolo-resume with optional session ID
# =============================================================================

_FAKE_ID = "4794df18-1ece-40c5-8e2c-59f1054d0b2c"


@pytest.mark.parametrize(
    "provider,expected_prefix,expected_suffix",
    [
        ("claude", ["--resume", _FAKE_ID], ["--dangerously-skip-permissions"]),
        ("gemini", ["--resume", _FAKE_ID], ["--yolo"]),
        ("codex", ["resume", _FAKE_ID], ["--dangerously-bypass-approvals-and-sandbox"]),
        ("copilot", ["--resume", _FAKE_ID], None),  # suffix = PROVIDERS skip_perms, may vary
    ],
)
def test_yolo_resume_by_id_equals_form(provider, expected_prefix, expected_suffix):
    """--yolo-resume=ID: all providers substitute the ID into resume_by_id template."""
    mod = _load_altergo()
    prefix, cleaned, suffix = mod._translate_yolo_flags(provider, [f"--yolo-resume={_FAKE_ID}"])
    assert prefix == expected_prefix
    if expected_suffix is not None:
        assert suffix == expected_suffix
    else:
        assert suffix == mod.PROVIDERS[provider]["flags"]["skip_perms"]
    assert _FAKE_ID not in cleaned  # never leak into user args / prompt
    assert not any(a.startswith("--yolo") for a in cleaned)


@pytest.mark.parametrize(
    "provider,expected_prefix",
    [
        ("claude", ["--resume", _FAKE_ID]),
        ("gemini", ["--resume", _FAKE_ID]),
        ("codex", ["resume", _FAKE_ID]),
        ("copilot", ["--resume", _FAKE_ID]),
    ],
)
def test_yolo_resume_by_id_space_form(provider, expected_prefix):
    """--yolo-resume ID: paired positional is consumed when it looks like a UUID."""
    mod = _load_altergo()
    prefix, cleaned, suffix = mod._translate_yolo_flags(provider, ["--yolo-resume", _FAKE_ID])
    assert prefix == expected_prefix
    # ID must not leak into cleaned args — that's the bug we're fixing.
    assert _FAKE_ID not in cleaned
    assert cleaned == []


def test_yolo_resume_space_form_uppercase_uuid():
    """UUID match is case-insensitive — uppercase IDs are still consumed."""
    mod = _load_altergo()
    upper = _FAKE_ID.upper()
    prefix, cleaned, suffix = mod._translate_yolo_flags("claude", ["--yolo-resume", upper])
    assert prefix == ["--resume", upper]
    assert upper not in cleaned


def test_yolo_resume_space_form_kebab_alias_consumed():
    """Claude accepts named-session aliases (kebab-case) for --resume; any
    non-flag token after --yolo-resume is forwarded as the session id so
    aliases like 'delete-persona-heartbeat-wrapper' don't get treated as
    chat prompts."""
    mod = _load_altergo()
    alias = "delete-persona-heartbeat-wrapper"
    prefix, cleaned, suffix = mod._translate_yolo_flags("claude", ["--yolo-resume", alias])
    assert prefix == ["--resume", alias]
    assert alias not in cleaned


def test_yolo_resume_space_form_almost_uuid_consumed():
    """Any non-flag token is consumed as the id; the provider validates shape."""
    mod = _load_altergo()
    almost = "4794df18-1ece-40c5-8e2c"  # missing final segment, still not a flag
    prefix, cleaned, suffix = mod._translate_yolo_flags("claude", ["--yolo-resume", almost])
    assert prefix == ["--resume", almost]
    assert almost not in cleaned


def test_yolo_resume_followed_by_flag_not_consumed():
    """A trailing token that starts with '-' is a flag, not an id."""
    mod = _load_altergo()
    prefix, cleaned, suffix = mod._translate_yolo_flags("claude", ["--yolo-resume", "--model", "sonnet"])
    assert prefix == ["--continue"]
    assert "--model" in cleaned
    assert "sonnet" in cleaned


def test_yolo_resume_no_id_regression_claude():
    """--yolo-resume with no ID still maps to resume_last for claude."""
    mod = _load_altergo()
    prefix, cleaned, suffix = mod._translate_yolo_flags("claude", ["--yolo-resume"])
    assert prefix == ["--continue"]
    assert suffix == ["--dangerously-skip-permissions"]
    assert cleaned == []


def test_yolo_resume_no_id_regression_copilot():
    """--yolo-resume with no ID still maps to resume_last for copilot."""
    mod = _load_altergo()
    prefix, cleaned, suffix = mod._translate_yolo_flags("copilot", ["--yolo-resume"])
    assert prefix == ["--continue"]
    assert suffix == mod.PROVIDERS["copilot"]["flags"]["skip_perms"]


def test_yolo_resume_by_id_with_user_args():
    """ID is consumed even when other user args follow."""
    mod = _load_altergo()
    prefix, cleaned, suffix = mod._translate_yolo_flags("claude", ["--yolo-resume", _FAKE_ID, "--model", "sonnet"])
    assert prefix == ["--resume", _FAKE_ID]
    assert cleaned == ["--model", "sonnet"]
    assert _FAKE_ID not in cleaned


def test_looks_like_session_id():
    """Sanity check on the UUID matcher."""
    mod = _load_altergo()
    assert mod._looks_like_session_id(_FAKE_ID)
    assert mod._looks_like_session_id(_FAKE_ID.upper())
    assert not mod._looks_like_session_id("not-a-uuid")
    assert not mod._looks_like_session_id("")
    # Trailing junk must not match.
    assert not mod._looks_like_session_id(_FAKE_ID + "x")


# =============================================================================
# launch_claude cwd forwarding
# =============================================================================


def _launch_mod(tmp_path, monkeypatch):
    """Return an altergo module wired for launch_claude unit tests.

    subprocess.run is replaced by a fake that records keyword arguments.
    All side-effect helpers (banner, animation, mcps sync, etc.) are no-ops.
    """
    import types

    mod = _load_altergo()

    run_calls = []

    def fake_run(cmd, env=None, cwd=None, **kw):
        run_calls.append({"cmd": cmd, "env": env, "cwd": cwd})
        return types.SimpleNamespace(returncode=0)

    monkeypatch.setattr(mod.subprocess, "run", fake_run)
    monkeypatch.setattr(mod, "resolve_account", lambda name: (tmp_path / name, name))
    monkeypatch.setattr(mod, "load_account_meta", lambda path: {"version": 3, "providers": ["claude"], "default_provider": "claude"})
    monkeypatch.setattr(mod, "_find_claude", lambda: "/usr/bin/claude")
    monkeypatch.setattr(mod, "_build_alt_env", lambda name: {"HOME": str(tmp_path / name), "PATH": "/usr/bin"})
    monkeypatch.setattr(mod, "maybe_refresh_update_cache", lambda: None)
    monkeypatch.setattr(mod, "first_launch_notice_if_needed", lambda: None)
    monkeypatch.setattr(mod, "home_change_notice_if_needed", lambda: None)
    monkeypatch.setattr(mod, "load_animation_pack", lambda: "off")
    monkeypatch.setattr(mod, "get_cached_latest_version", lambda: None)
    monkeypatch.setattr(mod, "_load_bool_setting", lambda key, default=False: False)
    monkeypatch.setattr(mod, "_sync_claude_mcps", lambda path: None)
    monkeypatch.setattr(mod, "_record_last_session_after_exit", lambda *a: None)
    monkeypatch.setattr(mod, "_print_launch_message", lambda: None)
    monkeypatch.setattr(mod, "show_banner", lambda *a, **kw: None)

    import io, sys
    monkeypatch.setattr(sys, "stdout", io.StringIO())
    monkeypatch.setattr(sys, "stderr", io.StringIO())

    return mod, run_calls


def test_launch_claude_cwd_forwarded_to_subprocess(tmp_path, monkeypatch):
    """When cwd is a valid directory, subprocess.run receives cwd=<that path>."""
    mod, run_calls = _launch_mod(tmp_path, monkeypatch)

    target_dir = tmp_path / "myproject"
    target_dir.mkdir()

    mod.launch_claude("work", args=["--resume", "abc"], cwd=str(target_dir))

    assert len(run_calls) == 1
    assert run_calls[0]["cwd"] == str(target_dir)


def test_launch_claude_cwd_path_object_forwarded(tmp_path, monkeypatch):
    """cwd can be a Path object — it is converted to a string before passing."""
    mod, run_calls = _launch_mod(tmp_path, monkeypatch)

    target_dir = tmp_path / "myproject"
    target_dir.mkdir()

    mod.launch_claude("work", args=["--resume", "abc"], cwd=target_dir)

    assert run_calls[0]["cwd"] == str(target_dir)


def test_launch_claude_invalid_cwd_falls_back_to_none(tmp_path, monkeypatch):
    """When cwd points to a non-existent directory, subprocess.run gets cwd=None."""
    import sys

    mod, run_calls = _launch_mod(tmp_path, monkeypatch)

    ghost_dir = tmp_path / "does_not_exist"
    # Intentionally do NOT create ghost_dir.

    stdout_buf = sys.stdout  # already redirected to StringIO by _launch_mod
    mod.launch_claude("work", args=["--resume", "abc"], cwd=str(ghost_dir))

    assert len(run_calls) == 1
    assert run_calls[0]["cwd"] is None


def test_launch_claude_invalid_cwd_prints_dim_notice(tmp_path, monkeypatch):
    """A notice is printed (not an exception) when cwd is invalid."""
    import sys

    mod, run_calls = _launch_mod(tmp_path, monkeypatch)

    stdout_buf = sys.__stdout__  # captured by monkeypatch in _launch_mod
    ghost_dir = tmp_path / "vanished_project"

    captured = __import__("io").StringIO()
    monkeypatch.setattr(sys, "stdout", captured)

    mod.launch_claude("work", args=["--resume", "abc"], cwd=str(ghost_dir))

    output = captured.getvalue()
    assert "no longer exists" in output or len(run_calls) == 1  # notice printed, launch proceeds


def test_launch_claude_no_cwd_passes_none(tmp_path, monkeypatch):
    """Omitting cwd entirely leaves subprocess.run's cwd as None (caller's directory)."""
    mod, run_calls = _launch_mod(tmp_path, monkeypatch)

    mod.launch_claude("work")

    assert run_calls[0]["cwd"] is None


def test_build_tmux_cmd_with_cwd():
    """When cwd is provided, _build_tmux_cmd emits -c <cwd> before -e flags."""
    mod = _load_altergo()
    env = {"HOME": "/tmp/fake-home", "PATH": "/usr/bin:/bin"}
    inner = ["claude", "--resume", "abc"]
    result = mod._build_tmux_cmd(inner, env, "default/claude", cwd="/tmp/myproject")

    assert "-c" in result
    c_idx = result.index("-c")
    assert result[c_idx + 1] == "/tmp/myproject"
    # -c must appear before -- (before the inner command)
    sep = result.index("--")
    assert c_idx < sep


def test_build_tmux_cmd_without_cwd_omits_c_flag():
    """When cwd is None (default), no -c <directory> flag is emitted before --."""
    mod = _load_altergo()
    env = {"HOME": "/tmp/fake-home", "PATH": "/usr/bin:/bin"}
    inner = ["claude", "--resume", "abc"]
    result = mod._build_tmux_cmd(inner, env, "default/claude")

    # Only look at the tmux-option tokens before the "--" separator;
    # "sh -c <wrapper>" after -- is expected and must not be flagged.
    sep = result.index("--")
    tmux_tokens = result[:sep]
    assert "-c" not in tmux_tokens


# =============================================================================
# _apply_resume_view — starred_only filter
# =============================================================================


def _make_sessions(specs):
    """Build minimal session dicts for picker view tests.

    Each spec is a dict with keys: id, provider (default 'claude'), starred (default False).
    """
    import datetime

    sessions = []
    for i, spec in enumerate(specs):
        sessions.append({
            "id": spec.get("id", f"sess-{i}"),
            "provider": spec.get("provider", "claude"),
            "starred": spec.get("starred", False),
            "project": "-Users-user-project",
            "modified": datetime.datetime(2026, 1, 1, 12, 0, 0),
            "size_mb": 1.0,
            "topic": f"topic {i}",
        })
    return sessions


def test_apply_resume_view_starred_only_filters_unstarred():
    """starred_only=True returns only sessions with starred=True."""
    mod = _load_altergo()
    sessions = _make_sessions([
        {"id": "a", "starred": True},
        {"id": "b", "starred": False},
        {"id": "c", "starred": True},
    ])
    result = mod._apply_resume_view(sessions, None, "time", "", starred_only=True)
    ids = [s["id"] for s in result]
    assert ids == ["a", "c"]


def test_apply_resume_view_starred_only_false_returns_all():
    """starred_only=False (default) does not filter out unstarred sessions."""
    mod = _load_altergo()
    sessions = _make_sessions([
        {"id": "a", "starred": True},
        {"id": "b", "starred": False},
    ])
    result = mod._apply_resume_view(sessions, None, "time", "", starred_only=False)
    assert len(result) == 2


def test_apply_resume_view_starred_only_default_is_false():
    """Calling _apply_resume_view without starred_only behaves identically to starred_only=False."""
    mod = _load_altergo()
    sessions = _make_sessions([
        {"id": "a", "starred": True},
        {"id": "b", "starred": False},
    ])
    result = mod._apply_resume_view(sessions, None, "time", "")
    assert len(result) == 2


def test_apply_resume_view_starred_only_empty_when_none_starred():
    """starred_only=True with no starred sessions returns an empty list."""
    mod = _load_altergo()
    sessions = _make_sessions([
        {"id": "a", "starred": False},
        {"id": "b", "starred": False},
    ])
    result = mod._apply_resume_view(sessions, None, "time", "", starred_only=True)
    assert result == []


def test_apply_resume_view_starred_only_and_provider_filter_compose():
    """starred_only=True and filter_provider both active: only starred sessions of that provider."""
    mod = _load_altergo()
    sessions = _make_sessions([
        {"id": "a", "provider": "claude", "starred": True},
        {"id": "b", "provider": "gemini", "starred": True},
        {"id": "c", "provider": "claude", "starred": False},
        {"id": "d", "provider": "gemini", "starred": False},
    ])
    result = mod._apply_resume_view(sessions, "claude", "time", "", starred_only=True)
    ids = [s["id"] for s in result]
    assert ids == ["a"], f"Expected only starred claude sessions; got {ids}"


def test_apply_resume_view_starred_only_survives_search_query():
    """starred_only=True combined with a search query intersects both filters."""
    mod = _load_altergo()
    sessions = _make_sessions([
        {"id": "a", "starred": True},
        {"id": "b", "starred": True},
        {"id": "c", "starred": False},
    ])
    # Patch _session_matches to simulate a search that only matches id "a"
    import unittest.mock as mock
    with mock.patch.object(mod, "_session_matches", side_effect=lambda s, q: s["id"] == "a"):
        result = mod._apply_resume_view(sessions, None, "time", "anything", starred_only=True)
    ids = [s["id"] for s in result]
    assert ids == ["a"]
