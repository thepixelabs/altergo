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

import io
import json
import shutil
import sys
from pathlib import Path

import pytest

import altergo.accounts
import altergo.cli
import altergo.constants
import altergo.tui.launcher


# ---------------------------------------------------------------------------
# Shared fixture: isolated accounts dir with a single "pocus" account
# ---------------------------------------------------------------------------


@pytest.fixture()
def routing_env(tmp_path, monkeypatch):
    """Return calls list with a single 'pocus' account wired up."""
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

    monkeypatch.setattr(altergo.constants, "ACCOUNTS_DIR", accounts_dir)
    monkeypatch.setattr(altergo.constants, "MAIN_HOME", main_home)
    monkeypatch.setattr(altergo.constants, "MAIN_CLAUDE", main_home / ".claude")
    monkeypatch.setattr(altergo.constants, "SETTINGS_FILE", tmp_path / "settings.json")
    monkeypatch.setattr(altergo.constants, "STARRED_FILE", tmp_path / "starred.json")
    monkeypatch.setattr(altergo.constants, "LAST_SESSION_FILE", tmp_path / "last_session.json")

    # Silence banner + non-essential startup hooks.
    monkeypatch.setattr(altergo.cli, "show_banner", lambda *a, **kw: None)
    monkeypatch.setattr(altergo.cli, "maybe_rotate_random_theme", lambda: None)
    monkeypatch.setattr(altergo.cli, "load_persisted_theme", lambda: "ocean")

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

    monkeypatch.setattr(altergo.cli, "launch_claude", fake_launch)
    monkeypatch.setattr(sys, "stderr", io.StringIO())

    return calls


# ---------------------------------------------------------------------------
# Happy path: account-only (default provider)
# ---------------------------------------------------------------------------


def test_account_only_uses_default_provider(routing_env, monkeypatch):
    """altergo pocus → launch_claude("pocus", [], provider=None) (default)."""
    calls = routing_env
    monkeypatch.setattr(sys, "argv", ["altergo", "pocus"])

    with pytest.raises(SystemExit) as exc:
        altergo.cli.main()

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
    calls = routing_env
    monkeypatch.setattr(sys, "argv", ["altergo", "pocus", "gemini"])

    with pytest.raises(SystemExit) as exc:
        altergo.cli.main()

    assert exc.value.code == 0
    assert len(calls) == 1
    assert calls[0]["account"] == "pocus"
    assert calls[0]["provider"] == "gemini"
    assert calls[0]["args"] == []


def test_account_plus_claude_provider_recognized(routing_env, monkeypatch):
    """altergo pocus claude → provider='claude' passed to launch_claude."""
    calls = routing_env
    monkeypatch.setattr(sys, "argv", ["altergo", "pocus", "claude"])

    with pytest.raises(SystemExit) as exc:
        altergo.cli.main()

    assert exc.value.code == 0
    assert calls[0]["account"] == "pocus"
    assert calls[0]["provider"] == "claude"
    assert calls[0]["args"] == []


# ---------------------------------------------------------------------------
# Happy path: account + provider + forwarded flags
# ---------------------------------------------------------------------------


def test_account_provider_forwarded_flags(routing_env, monkeypatch):
    """altergo pocus gemini --resume abc → args=['--resume','abc'] forwarded."""
    calls = routing_env
    monkeypatch.setattr(sys, "argv", ["altergo", "pocus", "gemini", "--resume", "abc"])

    with pytest.raises(SystemExit) as exc:
        altergo.cli.main()

    assert exc.value.code == 0
    assert calls[0]["account"] == "pocus"
    assert calls[0]["provider"] == "gemini"
    assert calls[0]["args"] == ["--resume", "abc"]


# ---------------------------------------------------------------------------
# Happy path: account + forwarded flags only (no explicit provider)
# ---------------------------------------------------------------------------


def test_account_forwarded_flags_no_provider(routing_env, monkeypatch):
    """altergo pocus --resume abc → args=['--resume','abc'], provider=None."""
    calls = routing_env
    monkeypatch.setattr(sys, "argv", ["altergo", "pocus", "--resume", "abc"])

    with pytest.raises(SystemExit) as exc:
        altergo.cli.main()

    assert exc.value.code == 0
    assert calls[0]["account"] == "pocus"
    assert calls[0]["provider"] is None
    assert calls[0]["args"] == ["--resume", "abc"]


# ---------------------------------------------------------------------------
# Top-level --yolo-resume (no account prefix) opens the picker
# ---------------------------------------------------------------------------


def test_top_level_yolo_resume_opens_picker(routing_env, monkeypatch):
    """altergo --yolo-resume (no account) → interactive picker should fire."""
    calls = routing_env

    picker_calls = []

    def fake_picker(sessions):
        picker_calls.append(True)
        return None  # user cancelled

    monkeypatch.setattr(altergo.cli, "interactive_picker", fake_picker)
    monkeypatch.setattr(altergo.cli, "_status_wrap", lambda msg, fn: fn())
    monkeypatch.setattr(altergo.cli, "get_sessions", lambda: [])
    monkeypatch.setattr(sys, "argv", ["altergo", "--yolo-resume"])

    with pytest.raises(SystemExit) as exc:
        altergo.cli.main()

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
    monkeypatch.setattr(sys, "argv", ["altergo", "--use", "native"])

    with pytest.raises(SystemExit) as exc:
        altergo.cli.main()

    assert exc.value.code == 0
    assert altergo.accounts.get_active_account() == "native"


def test_use_unknown_account_rejected(routing_env, monkeypatch):
    """altergo --use ghost (no dir, not 'native') still errors out."""
    monkeypatch.setattr(sys, "argv", ["altergo", "--use", "ghost"])

    with pytest.raises(SystemExit) as exc:
        altergo.cli.main()

    assert exc.value.code == 1
    assert altergo.accounts.get_active_account() is None


# ---------------------------------------------------------------------------
# _account_for_provider honors active=='native' once --use native is set
# ---------------------------------------------------------------------------


def test_account_for_provider_honors_native_when_active(routing_env, monkeypatch):
    """active=='native' + binary on PATH → _account_for_provider returns 'native'."""
    altergo.accounts.set_active_account("native")
    # Force the provider binary to look "installed" so native is launchable.
    monkeypatch.setattr(shutil, "which", lambda b: "/usr/bin/" + b)
    assert altergo.accounts._account_for_provider("claude") == "native"


def test_account_for_provider_falls_back_when_native_binary_missing(routing_env, monkeypatch):
    """active=='native' but no binary on PATH → fall through to a regular account."""
    altergo.accounts.set_active_account("native")
    # Native isn't launchable without the provider binary.
    monkeypatch.setattr(shutil, "which", lambda b: None)
    # `pocus` has `claude` in its providers list (see routing_env fixture).
    assert altergo.accounts._account_for_provider("claude") == "pocus"


# ---------------------------------------------------------------------------
# --yolo-resume picker: native chip + arrow-key picker
# ---------------------------------------------------------------------------


def test_yolo_picker_includes_native_when_binary_available(routing_env, monkeypatch):
    """_prompt_yolo_account_picker must inject the 'native' chip when binary is on PATH."""
    monkeypatch.setattr(shutil, "which", lambda b: "/usr/bin/" + b)
    # Non-TTY fallback path so we exercise the legacy numbered prompt
    # (the curses path requires a real terminal).
    monkeypatch.setattr(sys.stdin, "isatty", lambda: False, raising=False)
    monkeypatch.setattr(sys.stdout, "isatty", lambda: False, raising=False)
    inputs = iter(["2"])
    monkeypatch.setattr("builtins.input", lambda _prompt="": next(inputs))

    picked = altergo.tui.launcher._prompt_yolo_account_picker(["pocus"], provider="claude")
    # With native injected after pocus, "2" should pick native.
    assert picked == "native"


def test_yolo_picker_skips_native_when_binary_missing(routing_env, monkeypatch):
    """No binary on PATH → native chip is NOT offered."""
    monkeypatch.setattr(shutil, "which", lambda b: None)
    # Only one eligible item → no prompt, returned directly.
    picked = altergo.tui.launcher._prompt_yolo_account_picker(["pocus"], provider="claude")
    assert picked == "pocus"


# ---------------------------------------------------------------------------
# --yolo-resume case 2 (with session ID): active-account bypass
# ---------------------------------------------------------------------------

_FAKE_SESSION = {"id": "sess-abc", "provider": "claude", "cwd": "/tmp"}


def _setup_yr_case2(routing_env, monkeypatch, active_account):
    """Shared wiring for case-2 (session-ID-supplied) --yolo-resume tests.

    Returns (calls, picker_calls).
    """
    calls = routing_env

    monkeypatch.setattr(altergo.cli, "_status_wrap", lambda msg, fn: fn())
    monkeypatch.setattr(altergo.cli, "get_sessions", lambda: [_FAKE_SESSION])
    # native binary present so _native_supports_provider returns True for claude.
    monkeypatch.setattr(shutil, "which", lambda b: "/usr/bin/" + b)

    if active_account is not None:
        altergo.accounts.set_active_account(active_account)

    picker_calls = []

    def fake_yr_picker(eligible, provider=None):
        picker_calls.append({"eligible": eligible, "provider": provider})
        # Return the first eligible account so the launch path completes.
        return eligible[0] if eligible else None

    monkeypatch.setattr(altergo.cli, "_prompt_yolo_account_picker", fake_yr_picker)

    return calls, picker_calls


def test_yolo_resume_with_session_id_active_account_eligible_skips_picker(
    routing_env, monkeypatch
):
    """active account is eligible → picker NOT called, account used directly."""
    calls, picker_calls = _setup_yr_case2(routing_env, monkeypatch, "pocus")
    monkeypatch.setattr(sys, "argv", ["altergo", "--yolo-resume", "sess-abc"])

    with pytest.raises(SystemExit) as exc:
        altergo.cli.main()

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
    calls, picker_calls = _setup_yr_case2(routing_env, monkeypatch, None)
    monkeypatch.setattr(sys, "argv", ["altergo", "--yolo-resume", "sess-abc"])

    with pytest.raises(SystemExit) as exc:
        altergo.cli.main()

    assert exc.value.code == 0
    assert picker_calls, "picker SHOULD have been called when no active account is set"
    assert len(calls) == 1


def test_yolo_resume_with_session_id_active_account_wrong_provider_opens_picker(
    routing_env, monkeypatch
):
    """Active account does not support the session's provider → picker IS called."""
    calls = routing_env

    # Use a session whose provider is 'gemini'.
    gemini_session = {"id": "sess-gem", "provider": "gemini", "cwd": "/tmp"}
    monkeypatch.setattr(altergo.cli, "_status_wrap", lambda msg, fn: fn())
    monkeypatch.setattr(altergo.cli, "get_sessions", lambda: [gemini_session])
    monkeypatch.setattr(shutil, "which", lambda b: None)  # native not available

    # Set active to an account that only has 'claude' (we'll add a second account
    # that only has 'claude' to make the active one truly ineligible for gemini).
    # Actually the 'pocus' account has BOTH claude and gemini, so use a different
    # account with only claude.
    claude_only = altergo.constants.ACCOUNTS_DIR / "claudeonly"
    claude_only.mkdir()
    (claude_only / "account.json").write_text(
        json.dumps({"version": 3, "providers": ["claude"], "default_provider": "claude"})
    )
    altergo.accounts.set_active_account("claudeonly")

    picker_calls = []

    def fake_yr_picker(eligible, provider=None):
        picker_calls.append({"eligible": eligible, "provider": provider})
        return eligible[0] if eligible else None

    monkeypatch.setattr(altergo.cli, "_prompt_yolo_account_picker", fake_yr_picker)
    monkeypatch.setattr(sys, "argv", ["altergo", "--yolo-resume", "sess-gem"])

    with pytest.raises(SystemExit) as exc:
        altergo.cli.main()

    assert exc.value.code == 0
    assert picker_calls, "picker SHOULD have been called when active account lacks the required provider"
    # The account that was launched should be the gemini-eligible one (pocus).
    assert calls[0]["account"] == "pocus"
