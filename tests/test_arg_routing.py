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
