"""Tests for CLI argument routing: account + provider + forwarded flags.

Regression coverage for the four happy-path argv shapes the launcher must
keep supporting:

  - account-only (default provider from account meta)
  - account + explicit provider
  - account + provider + forwarded flags
  - account + forwarded flags only (no explicit provider)

Plus the top-level --yolo-resume entry point (no account prefix), which
should always open the interactive session picker.
"""

from __future__ import annotations

import importlib.util
import io
import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).parent.parent
SCRIPT = ROOT / "altergo.py"


def _load_altergo():
    spec = importlib.util.spec_from_file_location("altergo_routing", SCRIPT)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


# ---------------------------------------------------------------------------
# Shared fixture: isolated accounts dir with a single "pocus" account
# ---------------------------------------------------------------------------


@pytest.fixture()
def routing_env(tmp_path, monkeypatch):
    """Return (mod, accounts_dir) with a single 'pocus' account wired up."""
    mod = _load_altergo()

    accounts_dir = tmp_path / "accounts"
    accounts_dir.mkdir()
    main_home = tmp_path / "main_home"
    main_home.mkdir()
    (main_home / ".claude").mkdir()

    # Create the 'pocus' account with claude as its default provider.
    pocus_home = accounts_dir / "pocus"
    pocus_home.mkdir()
    (pocus_home / ".claude").mkdir()
    (pocus_home / "account.json").write_text(
        json.dumps(
            {
                "version": 3,
                "providers": ["claude", "gemini"],
                "default_provider": "claude",
            }
        )
    )

    monkeypatch.setattr(mod, "ACCOUNTS_DIR", accounts_dir)
    monkeypatch.setattr(mod, "MAIN_HOME", main_home)
    monkeypatch.setattr(mod, "MAIN_CLAUDE", main_home / ".claude")
    monkeypatch.setattr(mod, "SETTINGS_FILE", tmp_path / "settings.json")
    monkeypatch.setattr(mod, "STARRED_FILE", tmp_path / "starred.json")
    monkeypatch.setattr(mod, "LAST_SESSION_FILE", tmp_path / "last_session.json")

    # Silence banner + non-essential startup hooks.
    monkeypatch.setattr(mod, "show_banner", lambda *a, **kw: None)
    monkeypatch.setattr(mod, "maybe_rotate_random_theme", lambda: None)
    monkeypatch.setattr(mod, "load_persisted_theme", lambda: "ocean")

    # Capture launch_claude calls instead of actually running a provider.
    calls = []

    def fake_launch(account, args=None, provider=None, force_tmux=False, cwd=None):
        calls.append(
            {
                "account": account,
                "args": list(args or []),
                "provider": provider,
            }
        )
        raise SystemExit(0)

    monkeypatch.setattr(mod, "launch_claude", fake_launch)
    monkeypatch.setattr(sys, "stderr", io.StringIO())

    return mod, calls


# ---------------------------------------------------------------------------
# Happy path: account-only (default provider)
# ---------------------------------------------------------------------------


def test_account_only_uses_default_provider(routing_env, monkeypatch):
    """altergo pocus → launch_claude("pocus", [], provider=None) (default)."""
    mod, calls = routing_env
    monkeypatch.setattr(sys, "argv", ["altergo", "pocus"])

    with pytest.raises(SystemExit) as exc:
        mod.main()

    assert exc.value.code == 0
    assert len(calls) == 1
    assert calls[0]["account"] == "pocus"
    assert calls[0]["args"] == []
    # provider=None means launch_claude reads default from account meta.
    assert calls[0]["provider"] is None


# ---------------------------------------------------------------------------
# Happy path: account + explicit provider
# ---------------------------------------------------------------------------


def test_account_plus_provider_recognized(routing_env, monkeypatch):
    """altergo pocus gemini → provider='gemini' passed to launch_claude."""
    mod, calls = routing_env
    monkeypatch.setattr(sys, "argv", ["altergo", "pocus", "gemini"])

    with pytest.raises(SystemExit) as exc:
        mod.main()

    assert exc.value.code == 0
    assert len(calls) == 1
    assert calls[0]["account"] == "pocus"
    assert calls[0]["provider"] == "gemini"
    assert calls[0]["args"] == []


def test_account_plus_claude_provider_recognized(routing_env, monkeypatch):
    """altergo pocus claude → provider='claude' passed to launch_claude."""
    mod, calls = routing_env
    monkeypatch.setattr(sys, "argv", ["altergo", "pocus", "claude"])

    with pytest.raises(SystemExit) as exc:
        mod.main()

    assert exc.value.code == 0
    assert calls[0]["account"] == "pocus"
    assert calls[0]["provider"] == "claude"
    assert calls[0]["args"] == []


# ---------------------------------------------------------------------------
# Happy path: account + provider + forwarded flags
# ---------------------------------------------------------------------------


def test_account_provider_forwarded_flags(routing_env, monkeypatch):
    """altergo pocus gemini --resume abc → args=['--resume','abc'] forwarded."""
    mod, calls = routing_env
    monkeypatch.setattr(sys, "argv", ["altergo", "pocus", "gemini", "--resume", "abc"])

    with pytest.raises(SystemExit) as exc:
        mod.main()

    assert exc.value.code == 0
    assert calls[0]["account"] == "pocus"
    assert calls[0]["provider"] == "gemini"
    assert calls[0]["args"] == ["--resume", "abc"]


# ---------------------------------------------------------------------------
# Happy path: account + forwarded flags only (no explicit provider)
# ---------------------------------------------------------------------------


def test_account_forwarded_flags_no_provider(routing_env, monkeypatch):
    """altergo pocus --resume abc → args=['--resume','abc'], provider=None."""
    mod, calls = routing_env
    monkeypatch.setattr(sys, "argv", ["altergo", "pocus", "--resume", "abc"])

    with pytest.raises(SystemExit) as exc:
        mod.main()

    assert exc.value.code == 0
    assert calls[0]["account"] == "pocus"
    assert calls[0]["provider"] is None
    assert calls[0]["args"] == ["--resume", "abc"]


# ---------------------------------------------------------------------------
# Top-level --yolo-resume (no account prefix) opens the picker
# ---------------------------------------------------------------------------


def test_top_level_yolo_resume_opens_picker(routing_env, monkeypatch):
    """altergo --yolo-resume (no account) → interactive picker should fire."""
    mod, calls = routing_env

    picker_calls = []

    def fake_picker(sessions):
        picker_calls.append(True)
        return None  # user cancelled

    monkeypatch.setattr(mod, "interactive_picker", fake_picker)
    monkeypatch.setattr(mod, "_status_wrap", lambda msg, fn: fn())
    monkeypatch.setattr(mod, "get_sessions", lambda: [])
    monkeypatch.setattr(sys, "argv", ["altergo", "--yolo-resume"])

    with pytest.raises(SystemExit) as exc:
        mod.main()

    # Picker was opened (user cancelled → exit 0).
    assert exc.value.code == 0
    assert picker_calls, "interactive_picker was NOT called for top-level --yolo-resume"
    # No actual provider launch happened.
    assert calls == []


# ---------------------------------------------------------------------------
# --use sets the active account (real accounts and the reserved 'native')
# ---------------------------------------------------------------------------


def test_use_native_sets_active_account(routing_env, monkeypatch):
    """altergo --use native must persist active_account=native without a dir check."""
    mod, _ = routing_env
    monkeypatch.setattr(sys, "argv", ["altergo", "--use", "native"])

    with pytest.raises(SystemExit) as exc:
        mod.main()

    assert exc.value.code == 0
    assert mod.get_active_account() == "native"


def test_use_unknown_account_rejected(routing_env, monkeypatch):
    """altergo --use ghost (no dir, not 'native') still errors out."""
    mod, _ = routing_env
    monkeypatch.setattr(sys, "argv", ["altergo", "--use", "ghost"])

    with pytest.raises(SystemExit) as exc:
        mod.main()

    assert exc.value.code == 1
    assert mod.get_active_account() is None


# ---------------------------------------------------------------------------
# _account_for_provider honors active=='native' once --use native is set
# ---------------------------------------------------------------------------


def test_account_for_provider_honors_native_when_active(routing_env, monkeypatch):
    """active=='native' + binary on PATH → _account_for_provider returns 'native'."""
    mod, _ = routing_env
    mod.set_active_account("native")
    # Force the provider binary to look "installed" so native is launchable.
    monkeypatch.setattr(mod.shutil, "which", lambda b: "/usr/bin/" + b)
    assert mod._account_for_provider("claude") == "native"


def test_account_for_provider_falls_back_when_native_binary_missing(routing_env, monkeypatch):
    """active=='native' but no binary on PATH → fall through to a regular account."""
    mod, _ = routing_env
    mod.set_active_account("native")
    # Native isn't launchable without the provider binary.
    monkeypatch.setattr(mod.shutil, "which", lambda b: None)
    # `pocus` has `claude` in its providers list (see routing_env fixture).
    assert mod._account_for_provider("claude") == "pocus"


# ---------------------------------------------------------------------------
# --yolo-resume picker: native chip + arrow-key picker
# ---------------------------------------------------------------------------


def test_yolo_picker_includes_native_when_binary_available(routing_env, monkeypatch):
    """_prompt_yolo_account_picker must inject the 'native' chip when binary is on PATH."""
    mod, _ = routing_env
    monkeypatch.setattr(mod.shutil, "which", lambda b: "/usr/bin/" + b)
    # Non-TTY fallback path so we exercise the legacy numbered prompt
    # (the curses path requires a real terminal).
    monkeypatch.setattr(mod.sys.stdin, "isatty", lambda: False, raising=False)
    monkeypatch.setattr(mod.sys.stdout, "isatty", lambda: False, raising=False)
    inputs = iter(["2"])
    monkeypatch.setattr("builtins.input", lambda _prompt="": next(inputs))

    picked = mod._prompt_yolo_account_picker(["pocus"], provider="claude")
    # With native injected after pocus, "2" should pick native.
    assert picked == "native"


def test_yolo_picker_skips_native_when_binary_missing(routing_env, monkeypatch):
    """No binary on PATH → native chip is NOT offered."""
    mod, _ = routing_env
    monkeypatch.setattr(mod.shutil, "which", lambda b: None)
    # Only one eligible item → no prompt, returned directly.
    picked = mod._prompt_yolo_account_picker(["pocus"], provider="claude")
    assert picked == "pocus"


# ---------------------------------------------------------------------------
# --yolo-resume case 2 (with session ID): active-account bypass
# ---------------------------------------------------------------------------

_FAKE_SESSION = {"id": "sess-abc", "provider": "claude", "cwd": "/tmp"}


def _setup_yr_case2(routing_env, monkeypatch, active_account):
    """Shared wiring for case-2 (session-ID-supplied) --yolo-resume tests.

    Returns (mod, calls, picker_calls).
    """
    mod, calls = routing_env

    monkeypatch.setattr(mod, "_status_wrap", lambda msg, fn: fn())
    monkeypatch.setattr(mod, "get_sessions", lambda: [_FAKE_SESSION])
    # native binary present so _native_supports_provider returns True for claude.
    monkeypatch.setattr(mod.shutil, "which", lambda b: "/usr/bin/" + b)

    if active_account is not None:
        mod.set_active_account(active_account)

    picker_calls = []

    def fake_yr_picker(eligible, provider=None):
        picker_calls.append({"eligible": eligible, "provider": provider})
        # Return the first eligible account so the launch path completes.
        return eligible[0] if eligible else None

    monkeypatch.setattr(mod, "_prompt_yolo_account_picker", fake_yr_picker)

    return mod, calls, picker_calls


def test_yolo_resume_with_session_id_active_account_eligible_skips_picker(
    routing_env, monkeypatch
):
    """active account is eligible → picker NOT called, account used directly."""
    mod, calls, picker_calls = _setup_yr_case2(routing_env, monkeypatch, "pocus")
    monkeypatch.setattr(sys, "argv", ["altergo", "--yolo-resume", "sess-abc"])

    with pytest.raises(SystemExit) as exc:
        mod.main()

    assert exc.value.code == 0
    assert picker_calls == [], "picker should NOT have been called when active account is eligible"
    assert len(calls) == 1
    assert calls[0]["account"] == "pocus"
    assert "--resume" in calls[0]["args"]
    assert "sess-abc" in calls[0]["args"]


def test_yolo_resume_with_session_id_no_active_account_opens_picker(
    routing_env, monkeypatch
):
    """No active account persisted → picker IS called."""
    mod, calls, picker_calls = _setup_yr_case2(routing_env, monkeypatch, None)
    monkeypatch.setattr(sys, "argv", ["altergo", "--yolo-resume", "sess-abc"])

    with pytest.raises(SystemExit) as exc:
        mod.main()

    assert exc.value.code == 0
    assert picker_calls, "picker SHOULD have been called when no active account is set"
    assert len(calls) == 1


def test_yolo_resume_with_session_id_active_account_wrong_provider_opens_picker(
    routing_env, monkeypatch
):
    """Active account does not support the session's provider → picker IS called."""
    mod, calls = routing_env

    # Use a session whose provider is 'gemini'.
    gemini_session = {"id": "sess-gem", "provider": "gemini", "cwd": "/tmp"}
    monkeypatch.setattr(mod, "_status_wrap", lambda msg, fn: fn())
    monkeypatch.setattr(mod, "get_sessions", lambda: [gemini_session])
    monkeypatch.setattr(mod.shutil, "which", lambda b: None)  # native not available

    # Set active to an account that only has 'claude' (we'll add a second account
    # that only has 'claude' to make the active one truly ineligible for gemini).
    # Actually the 'pocus' account has BOTH claude and gemini, so use a different
    # account with only claude.
    claude_only = mod.ACCOUNTS_DIR / "claudeonly"
    claude_only.mkdir()
    (claude_only / "account.json").write_text(
        json.dumps({"version": 3, "providers": ["claude"], "default_provider": "claude"})
    )
    mod.set_active_account("claudeonly")

    picker_calls = []

    def fake_yr_picker(eligible, provider=None):
        picker_calls.append({"eligible": eligible, "provider": provider})
        return eligible[0] if eligible else None

    monkeypatch.setattr(mod, "_prompt_yolo_account_picker", fake_yr_picker)
    monkeypatch.setattr(sys, "argv", ["altergo", "--yolo-resume", "sess-gem"])

    with pytest.raises(SystemExit) as exc:
        mod.main()

    assert exc.value.code == 0
    assert picker_calls, "picker SHOULD have been called when active account lacks the required provider"
    # The account that was launched should be the gemini-eligible one (pocus).
    assert calls[0]["account"] == "pocus"
