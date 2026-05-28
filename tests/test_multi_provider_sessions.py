"""Tests for multi-provider session discovery in --recall.

Creates minimal fixture files under tmp_path mimicking the four provider
layouts (one session per provider), then calls get_sessions() with MAIN_HOME
and MAIN_CLAUDE monkeypatched so no real user data is touched.

Verifies:
  - All four providers appear in results
  - provider, topic, cwd, and id are populated correctly
  - Results are sorted by modified descending
  - format_project_name handles non-dash-encoded labels correctly
  - load_session_preview dispatches to the right per-provider loader
"""

from __future__ import annotations

import json
import time
from pathlib import Path

import pytest

import altergo.constants
import altergo.sessions


# ---------------------------------------------------------------------------
# Fixture helpers
# ---------------------------------------------------------------------------


def _make_claude_session(home: Path, session_id: str, project_encoded: str, cwd: str, topic: str) -> Path:
    """Create a minimal Claude Code JSONL session file."""
    proj_dir = home / ".claude" / "projects" / project_encoded
    proj_dir.mkdir(parents=True, exist_ok=True)
    session_file = proj_dir / f"{session_id}.jsonl"
    lines = [
        json.dumps({"cwd": cwd}),
        json.dumps({
            "type": "user",
            "message": {"content": topic},
        }),
    ]
    session_file.write_text("\n".join(lines) + "\n")
    return session_file


def _make_codex_session(home: Path, session_id: str, cwd: str, topic: str) -> Path:
    """Create a minimal Codex JSONL session file under sessions/YYYY/MM/DD/."""
    day_dir = home / ".codex" / "sessions" / "2026" / "04" / "20"
    day_dir.mkdir(parents=True, exist_ok=True)
    session_file = day_dir / f"rollout-20260420-{session_id}.jsonl"
    lines = [
        json.dumps({
            "type": "session_meta",
            "payload": {"id": session_id, "cwd": cwd, "timestamp": "2026-04-20T10:00:00Z"},
        }),
        json.dumps({
            "type": "response_item",
            "payload": {
                "type": "message",
                "role": "user",
                "content": [{"type": "input_text", "text": topic}],
            },
        }),
    ]
    session_file.write_text("\n".join(lines) + "\n")
    return session_file


def _make_codex_session_with_sentinel(home: Path, session_id: str, cwd: str, real_topic: str) -> Path:
    """Create a Codex session where the first user message is a sentinel to be skipped."""
    day_dir = home / ".codex" / "sessions" / "2026" / "04" / "20"
    day_dir.mkdir(parents=True, exist_ok=True)
    session_file = day_dir / f"rollout-20260420-{session_id}.jsonl"
    lines = [
        json.dumps({
            "type": "session_meta",
            "payload": {"id": session_id, "cwd": cwd, "timestamp": "2026-04-20T11:00:00Z"},
        }),
        # Sentinel — must be skipped
        json.dumps({
            "type": "response_item",
            "payload": {
                "type": "message",
                "role": "user",
                "content": [{"type": "input_text", "text": "<permissions instructions>...system stuff</permissions>"}],
            },
        }),
        # Real user message
        json.dumps({
            "type": "response_item",
            "payload": {
                "type": "message",
                "role": "user",
                "content": [{"type": "input_text", "text": real_topic}],
            },
        }),
    ]
    session_file.write_text("\n".join(lines) + "\n")
    return session_file


def _make_gemini_session(home: Path, project_dirname: str, session_id: str, cwd: str, topic: str) -> Path:
    """Create a minimal Gemini JSON session file."""
    chats_dir = home / ".gemini" / "tmp" / project_dirname / "chats"
    chats_dir.mkdir(parents=True, exist_ok=True)
    # Write .project_root
    project_root_file = home / ".gemini" / "tmp" / project_dirname / ".project_root"
    project_root_file.write_text(cwd)
    session_file = chats_dir / f"session-20260420-{session_id[:8]}.json"
    data = {
        "sessionId": session_id,
        "projectHash": "abc123",
        "startTime": "2026-04-20T10:00:00Z",
        "messages": [
            {"type": "user", "content": [{"text": topic}]},
            {"type": "gemini", "content": [{"text": "Sure, I can help with that."}]},
        ],
    }
    session_file.write_text(json.dumps(data))
    return session_file


def _make_gemini_session_string_content(home: Path, project_dirname: str, session_id: str, cwd: str, topic: str) -> Path:
    """Create a Gemini session where content is a plain string (not a list)."""
    chats_dir = home / ".gemini" / "tmp" / project_dirname / "chats"
    chats_dir.mkdir(parents=True, exist_ok=True)
    session_file = chats_dir / f"session-20260420-{session_id[:8]}.json"
    data = {
        "sessionId": session_id,
        "messages": [
            {"type": "user", "content": topic},
        ],
    }
    session_file.write_text(json.dumps(data))
    return session_file


def _make_copilot_session(home: Path, session_id: str, cwd: str, topic: str) -> Path:
    """Create a minimal Copilot session directory with workspace.yaml + events.jsonl."""
    session_dir = home / ".copilot" / "session-state" / session_id
    session_dir.mkdir(parents=True, exist_ok=True)

    workspace_yaml = session_dir / "workspace.yaml"
    workspace_yaml.write_text(
        f"id: {session_id}\n"
        f"cwd: {cwd}\n"
        "branch: main\n"
        "created_at: 2026-04-20T09:00:00Z\n"
        "updated_at: 2026-04-20T10:00:00Z\n"
        f"summary: {topic}\n"
    )

    events_jsonl = session_dir / "events.jsonl"
    lines = [
        json.dumps({
            "type": "session.start",
            "data": {
                "sessionId": session_id,
                "context": {"cwd": cwd, "gitRoot": cwd, "branch": "main"},
            },
        }),
        json.dumps({
            "type": "user.message",
            "data": {"content": topic},
        }),
    ]
    events_jsonl.write_text("\n".join(lines) + "\n")
    return session_dir


# ---------------------------------------------------------------------------
# Core discovery test: all four providers
# ---------------------------------------------------------------------------


def test_get_sessions_all_four_providers(tmp_path, monkeypatch):
    """get_sessions() must return at least one session for each of the four providers."""
    home = tmp_path / "home"
    home.mkdir()
    main_claude = home / ".claude"

    monkeypatch.setattr(altergo.constants, "MAIN_HOME", home)
    monkeypatch.setattr(altergo.constants, "MAIN_CLAUDE", main_claude)
    # No accounts dir — _build_provider_map will short-circuit cleanly
    monkeypatch.setattr(altergo.constants, "ACCOUNTS_DIR", home / ".altergo" / "accounts")
    # Avoid touching real starred file
    monkeypatch.setattr(altergo.constants, "STARRED_FILE", home / ".altergo" / "starred.json")

    _make_claude_session(
        home,
        session_id="aaaaaaaa-0000-0000-0000-000000000001",
        project_encoded="-Users-test-myproject",
        cwd="/Users/test/myproject",
        topic="Help me refactor this function",
    )
    _make_codex_session(
        home,
        session_id="bbbbbbbb-0000-0000-0000-000000000002",
        cwd="/Users/test/codexproject",
        topic="Write a bash script to deploy this",
    )
    _make_gemini_session(
        home,
        project_dirname="geminiproject",
        session_id="cccccccc-0000-0000-0000-000000000003",
        cwd="/Users/test/geminiproject",
        topic="Explain this Terraform module",
    )
    _make_copilot_session(
        home,
        session_id="dddddddd-0000-0000-0000-000000000004",
        cwd="/Users/test/copilotproject",
        topic="Review this pull request",
    )

    sessions = altergo.sessions.get_sessions()
    providers_found = {s["provider"] for s in sessions}

    assert "claude" in providers_found, f"claude missing; providers found: {providers_found}"
    assert "codex" in providers_found, f"codex missing; providers found: {providers_found}"
    assert "gemini" in providers_found, f"gemini missing; providers found: {providers_found}"
    assert "copilot" in providers_found, f"copilot missing; providers found: {providers_found}"


def test_get_sessions_sorted_by_modified_descending(tmp_path, monkeypatch):
    """Results must be sorted newest-first by the modified timestamp."""
    home = tmp_path / "home"
    home.mkdir()
    main_claude = home / ".claude"

    monkeypatch.setattr(altergo.constants, "MAIN_HOME", home)
    monkeypatch.setattr(altergo.constants, "MAIN_CLAUDE", main_claude)
    monkeypatch.setattr(altergo.constants, "ACCOUNTS_DIR", home / ".altergo" / "accounts")
    monkeypatch.setattr(altergo.constants, "STARRED_FILE", home / ".altergo" / "starred.json")

    # Create sessions with distinct mtimes using utime
    claude_file = _make_claude_session(
        home,
        session_id="aaaaaaaa-0000-0000-0000-000000000001",
        project_encoded="-Users-test-p",
        cwd="/Users/test/p",
        topic="old claude session",
    )
    gemini_file = _make_gemini_session(
        home,
        project_dirname="newproj",
        session_id="cccccccc-0000-0000-0000-000000000003",
        cwd="/Users/test/newproj",
        topic="new gemini session",
    )

    # Force a predictable time ordering
    old_ts = 1_700_000_000
    new_ts = 1_800_000_000
    import os
    os.utime(str(claude_file), (old_ts, old_ts))
    os.utime(str(gemini_file), (new_ts, new_ts))

    sessions = altergo.sessions.get_sessions()
    modified_times = [s["modified"].timestamp() for s in sessions]
    assert modified_times == sorted(modified_times, reverse=True), (
        "Sessions are not sorted newest-first"
    )


# ---------------------------------------------------------------------------
# Claude-specific field assertions
# ---------------------------------------------------------------------------


def test_claude_session_fields(tmp_path, monkeypatch):
    """Claude session must have correct id, cwd, topic, and provider."""
    home = tmp_path / "home"
    home.mkdir()
    main_claude = home / ".claude"

    monkeypatch.setattr(altergo.constants, "MAIN_HOME", home)
    monkeypatch.setattr(altergo.constants, "MAIN_CLAUDE", main_claude)
    monkeypatch.setattr(altergo.constants, "ACCOUNTS_DIR", home / ".altergo" / "accounts")
    monkeypatch.setattr(altergo.constants, "STARRED_FILE", home / ".altergo" / "starred.json")

    _make_claude_session(
        home,
        session_id="aaaaaaaa-1111-1111-1111-111111111111",
        project_encoded="-Users-test-myproject",
        cwd="/Users/test/myproject",
        topic="Refactor the authentication module",
    )

    sessions = altergo.sessions.get_sessions()
    claude = next((s for s in sessions if s["provider"] == "claude"), None)
    assert claude is not None
    assert claude["id"] == "aaaaaaaa-1111-1111-1111-111111111111"
    assert claude["cwd"] == "/Users/test/myproject"
    assert "Refactor" in claude["topic"]


# ---------------------------------------------------------------------------
# Codex-specific field assertions
# ---------------------------------------------------------------------------


def test_codex_session_fields(tmp_path, monkeypatch):
    """Codex session must have correct id, cwd, topic, and provider."""
    home = tmp_path / "home"
    home.mkdir()

    monkeypatch.setattr(altergo.constants, "MAIN_HOME", home)
    monkeypatch.setattr(altergo.constants, "MAIN_CLAUDE", home / ".claude")
    monkeypatch.setattr(altergo.constants, "ACCOUNTS_DIR", home / ".altergo" / "accounts")
    monkeypatch.setattr(altergo.constants, "STARRED_FILE", home / ".altergo" / "starred.json")

    _make_codex_session(
        home,
        session_id="bbbbbbbb-2222-2222-2222-222222222222",
        cwd="/Users/test/codexproject",
        topic="Deploy the application",
    )

    sessions = altergo.sessions.get_sessions()
    codex = next((s for s in sessions if s["provider"] == "codex"), None)
    assert codex is not None
    assert codex["id"] == "bbbbbbbb-2222-2222-2222-222222222222"
    assert codex["cwd"] == "/Users/test/codexproject"
    assert "Deploy" in codex["topic"]


def test_codex_sentinel_skip(tmp_path, monkeypatch):
    """Codex scanner must skip <permissions ...> sentinel messages for topic."""
    home = tmp_path / "home"
    home.mkdir()

    monkeypatch.setattr(altergo.constants, "MAIN_HOME", home)
    monkeypatch.setattr(altergo.constants, "MAIN_CLAUDE", home / ".claude")
    monkeypatch.setattr(altergo.constants, "ACCOUNTS_DIR", home / ".altergo" / "accounts")
    monkeypatch.setattr(altergo.constants, "STARRED_FILE", home / ".altergo" / "starred.json")

    _make_codex_session_with_sentinel(
        home,
        session_id="bbbbbbbb-3333-3333-3333-333333333333",
        cwd="/Users/test/project",
        real_topic="Fix the memory leak",
    )

    sessions = altergo.sessions.get_sessions()
    codex = next((s for s in sessions if s["provider"] == "codex"), None)
    assert codex is not None
    assert "Fix the memory leak" in codex["topic"]
    assert "<permissions" not in codex["topic"]


# ---------------------------------------------------------------------------
# Gemini-specific field assertions
# ---------------------------------------------------------------------------


def test_gemini_session_fields(tmp_path, monkeypatch):
    """Gemini session must have correct id, cwd (from .project_root), topic, and provider."""
    home = tmp_path / "home"
    home.mkdir()

    monkeypatch.setattr(altergo.constants, "MAIN_HOME", home)
    monkeypatch.setattr(altergo.constants, "MAIN_CLAUDE", home / ".claude")
    monkeypatch.setattr(altergo.constants, "ACCOUNTS_DIR", home / ".altergo" / "accounts")
    monkeypatch.setattr(altergo.constants, "STARRED_FILE", home / ".altergo" / "starred.json")

    _make_gemini_session(
        home,
        project_dirname="gemproject",
        session_id="cccccccc-4444-4444-4444-444444444444",
        cwd="/Users/test/gemproject",
        topic="Explain the CI pipeline",
    )

    sessions = altergo.sessions.get_sessions()
    gemini = next((s for s in sessions if s["provider"] == "gemini"), None)
    assert gemini is not None
    assert gemini["id"] == "cccccccc-4444-4444-4444-444444444444"
    assert gemini["cwd"] == "/Users/test/gemproject"
    assert "CI pipeline" in gemini["topic"]


def test_gemini_session_no_project_root_falls_back_to_dirname(tmp_path, monkeypatch):
    """Gemini cwd must fall back to the dirname when .project_root is absent."""
    home = tmp_path / "home"
    home.mkdir()

    monkeypatch.setattr(altergo.constants, "MAIN_HOME", home)
    monkeypatch.setattr(altergo.constants, "MAIN_CLAUDE", home / ".claude")
    monkeypatch.setattr(altergo.constants, "ACCOUNTS_DIR", home / ".altergo" / "accounts")
    monkeypatch.setattr(altergo.constants, "STARRED_FILE", home / ".altergo" / "starred.json")

    # Create session WITHOUT .project_root
    project_dirname = "noprojectroot"
    chats_dir = home / ".gemini" / "tmp" / project_dirname / "chats"
    chats_dir.mkdir(parents=True, exist_ok=True)
    session_file = chats_dir / "session-20260420-aabbccdd.json"
    session_file.write_text(json.dumps({
        "sessionId": "cccccccc-5555-5555-5555-555555555555",
        "messages": [{"type": "user", "content": "hello there"}],
    }))

    sessions = altergo.sessions.get_sessions()
    gemini = next((s for s in sessions if s["provider"] == "gemini"), None)
    assert gemini is not None
    # cwd should be the dirname since .project_root absent
    assert gemini["cwd"] == project_dirname


def test_gemini_session_string_content(tmp_path, monkeypatch):
    """Gemini topic extraction handles string content (not list-of-dicts)."""
    home = tmp_path / "home"
    home.mkdir()

    monkeypatch.setattr(altergo.constants, "MAIN_HOME", home)
    monkeypatch.setattr(altergo.constants, "MAIN_CLAUDE", home / ".claude")
    monkeypatch.setattr(altergo.constants, "ACCOUNTS_DIR", home / ".altergo" / "accounts")
    monkeypatch.setattr(altergo.constants, "STARRED_FILE", home / ".altergo" / "starred.json")

    _make_gemini_session_string_content(
        home,
        project_dirname="strproj",
        session_id="cccccccc-6666-6666-6666-666666666666",
        cwd="/Users/test/strproj",
        topic="Debug the OOM crash",
    )

    sessions = altergo.sessions.get_sessions()
    gemini = next((s for s in sessions if s["provider"] == "gemini"), None)
    assert gemini is not None
    assert "OOM" in gemini["topic"]


# ---------------------------------------------------------------------------
# Copilot-specific field assertions
# ---------------------------------------------------------------------------


def test_copilot_session_fields(tmp_path, monkeypatch):
    """Copilot session must have correct id, cwd, topic, and provider."""
    home = tmp_path / "home"
    home.mkdir()

    monkeypatch.setattr(altergo.constants, "MAIN_HOME", home)
    monkeypatch.setattr(altergo.constants, "MAIN_CLAUDE", home / ".claude")
    monkeypatch.setattr(altergo.constants, "ACCOUNTS_DIR", home / ".altergo" / "accounts")
    monkeypatch.setattr(altergo.constants, "STARRED_FILE", home / ".altergo" / "starred.json")

    _make_copilot_session(
        home,
        session_id="dddddddd-7777-7777-7777-777777777777",
        cwd="/Users/test/copilotproject",
        topic="Review the PR changes",
    )

    sessions = altergo.sessions.get_sessions()
    copilot = next((s for s in sessions if s["provider"] == "copilot"), None)
    assert copilot is not None
    assert copilot["id"] == "dddddddd-7777-7777-7777-777777777777"
    assert copilot["cwd"] == "/Users/test/copilotproject"
    assert "PR changes" in copilot["topic"]


def test_copilot_session_without_workspace_yaml(tmp_path, monkeypatch):
    """Copilot session falls back to events.jsonl when workspace.yaml is absent."""
    home = tmp_path / "home"
    home.mkdir()

    monkeypatch.setattr(altergo.constants, "MAIN_HOME", home)
    monkeypatch.setattr(altergo.constants, "MAIN_CLAUDE", home / ".claude")
    monkeypatch.setattr(altergo.constants, "ACCOUNTS_DIR", home / ".altergo" / "accounts")
    monkeypatch.setattr(altergo.constants, "STARRED_FILE", home / ".altergo" / "starred.json")

    session_id = "dddddddd-8888-8888-8888-888888888888"
    session_dir = home / ".copilot" / "session-state" / session_id
    session_dir.mkdir(parents=True, exist_ok=True)
    # No workspace.yaml — only events.jsonl
    events_jsonl = session_dir / "events.jsonl"
    lines = [
        json.dumps({
            "type": "session.start",
            "data": {
                "sessionId": session_id,
                "context": {"cwd": "/Users/test/fallbackproject", "gitRoot": "/Users/test/fallbackproject"},
            },
        }),
        json.dumps({
            "type": "user.message",
            "data": {"content": "Write integration tests"},
        }),
    ]
    events_jsonl.write_text("\n".join(lines) + "\n")

    sessions = altergo.sessions.get_sessions()
    copilot = next((s for s in sessions if s["provider"] == "copilot"), None)
    assert copilot is not None
    assert copilot["id"] == session_id
    assert copilot["cwd"] == "/Users/test/fallbackproject"
    assert "integration tests" in copilot["topic"]


# ---------------------------------------------------------------------------
# format_project_name: non-Claude labels pass through unchanged
# ---------------------------------------------------------------------------


def test_format_project_name_plain_label():
    """A plain project label (no leading dash) is returned as-is."""
    assert altergo.sessions.format_project_name("altergo") == "altergo"
    assert altergo.sessions.format_project_name("myproject") == "myproject"


def test_format_project_name_dash_encoded_claude():
    """A Claude dash-encoded path is decoded to its last component."""
    assert altergo.sessions.format_project_name("-Users-someuser-Documents-git-altergo") == "altergo"


def test_format_project_name_absolute_path():
    """An absolute path stored in project is shortened to its basename."""
    assert altergo.sessions.format_project_name("/Users/test/myproject") == "myproject"


# ---------------------------------------------------------------------------
# load_session_preview dispatches to the right per-provider loader
# ---------------------------------------------------------------------------


def test_load_session_preview_claude(tmp_path):
    """Claude preview reads messages from JSONL."""
    session_file = tmp_path / "session.jsonl"
    lines = [
        json.dumps({"cwd": "/Users/test/p"}),
        json.dumps({"type": "user", "message": {"content": "Hello Claude"}}),
        json.dumps({"type": "assistant", "message": {"content": [{"type": "text", "text": "Hi there!"}]}}),
    ]
    session_file.write_text("\n".join(lines) + "\n")

    result = altergo.sessions.load_session_preview(session_file, provider="claude")
    assert result["error"] is None
    roles = [r for r, _ in result["messages"]]
    assert "user" in roles


def test_load_session_preview_codex(tmp_path):
    """Codex preview reads response_item messages from JSONL."""
    session_file = tmp_path / "rollout.jsonl"
    lines = [
        json.dumps({
            "type": "session_meta",
            "payload": {"id": "abc", "cwd": "/Users/test/p"},
        }),
        json.dumps({
            "type": "response_item",
            "payload": {
                "type": "message",
                "role": "user",
                "content": [{"type": "input_text", "text": "Build the Docker image"}],
            },
        }),
        json.dumps({
            "type": "response_item",
            "payload": {
                "type": "message",
                "role": "assistant",
                "content": [{"type": "output_text", "text": "Running docker build..."}],
            },
        }),
    ]
    session_file.write_text("\n".join(lines) + "\n")

    result = altergo.sessions.load_session_preview(session_file, provider="codex")
    assert result["error"] is None
    assert any(role == "user" and "Docker" in text for role, text in result["messages"])


def test_load_session_preview_gemini(tmp_path):
    """Gemini preview reads messages from JSON file."""
    session_file = tmp_path / "session-abc.json"
    data = {
        "sessionId": "gemini-uuid",
        "messages": [
            {"type": "user", "content": [{"text": "Describe this architecture"}]},
            {"type": "gemini", "content": [{"text": "The architecture consists of..."}]},
        ],
    }
    session_file.write_text(json.dumps(data))

    result = altergo.sessions.load_session_preview(session_file, provider="gemini")
    assert result["error"] is None
    assert any(role == "user" and "architecture" in text for role, text in result["messages"])
    assert any(role == "assistant" for role, _ in result["messages"])


def test_load_session_preview_copilot(tmp_path):
    """Copilot preview reads messages from events.jsonl."""
    session_dir = tmp_path / "copilot-session"
    session_dir.mkdir()

    events_jsonl = session_dir / "events.jsonl"
    lines = [
        json.dumps({
            "type": "session.start",
            "data": {"sessionId": "cop-uuid", "context": {"cwd": "/Users/test/p"}},
        }),
        json.dumps({
            "type": "user.message",
            "data": {"content": "What does this code do?"},
        }),
        json.dumps({
            "type": "assistant.message",
            "data": {"content": "This code implements a binary search."},
        }),
    ]
    events_jsonl.write_text("\n".join(lines) + "\n")

    result = altergo.sessions.load_session_preview(session_dir, provider="copilot")
    assert result["error"] is None
    assert any(role == "user" and "code" in text for role, text in result["messages"])


def test_load_session_preview_missing_file(tmp_path):
    """A missing session file returns an error dict without raising."""
    ghost = tmp_path / "nonexistent.jsonl"
    result = altergo.sessions.load_session_preview(ghost, provider="claude")
    assert result["error"] is not None
    assert result["messages"] == []


# ---------------------------------------------------------------------------
# _parse_copilot_workspace_yaml
# ---------------------------------------------------------------------------


def test_parse_copilot_workspace_yaml(tmp_path):
    """Parses key:value pairs including quoted values correctly."""
    yaml_file = tmp_path / "workspace.yaml"
    yaml_file.write_text(
        "id: abc-123\n"
        "cwd: /Users/test/project\n"
        "branch: main\n"
        'summary: "Fix the login bug"\n'
        "created_at: 2026-04-20T09:00:00Z\n"
    )

    result = altergo.sessions._parse_copilot_workspace_yaml(yaml_file)
    assert result["id"] == "abc-123"
    assert result["cwd"] == "/Users/test/project"
    assert result["summary"] == "Fix the login bug"
    assert result["branch"] == "main"


def test_parse_copilot_workspace_yaml_missing(tmp_path):
    """Returns empty dict when file is absent."""
    result = altergo.sessions._parse_copilot_workspace_yaml(tmp_path / "no-such-file.yaml")
    assert result == {}
