import json
import re
from datetime import datetime

import altergo.constants as _const
from altergo.accounts import list_accounts
from altergo.persistence import load_account_meta, load_starred_ids


def _build_provider_map() -> dict:
    """Return a dict mapping session JSONL path → provider id string."""
    path_to_provider: dict = {}
    if not _const.ACCOUNTS_DIR.exists():
        return path_to_provider

    for acct_name in list_accounts():
        acct_home = _const.ACCOUNTS_DIR / acct_name
        meta = load_account_meta(acct_home)
        provider_ids = meta["providers"] if meta is not None else ["claude"]

        for provider_id in provider_ids:
            prov = _const.PROVIDERS.get(provider_id)
            if prov is None:
                continue
            acct_projects = acct_home / prov["dot_dir"] / "projects"
            try:
                resolved_projects = acct_projects.resolve()
            except OSError:
                continue
            if not resolved_projects.is_dir():
                continue

            try:
                for proj_dir in resolved_projects.iterdir():
                    if not proj_dir.is_dir():
                        continue
                    try:
                        for sf in proj_dir.iterdir():
                            if sf.suffix == ".jsonl":
                                try:
                                    path_to_provider[sf.resolve()] = provider_id
                                except OSError:
                                    pass
                    except OSError:
                        continue
            except OSError:
                continue

    return path_to_provider


_CODEX_TOPIC_SENTINELS = ("<permissions ", "<collaboration_mode>", "<skills_instructions>")


def _discover_claude_sessions(starred_ids: set) -> list:
    """Yield session dicts for Claude Code (~/.claude/projects/*/*.jsonl)."""
    sessions = []
    projects_dir = _const.MAIN_CLAUDE / "projects"
    if not projects_dir.exists():
        return sessions

    provider_map = _build_provider_map()

    for project_dir in projects_dir.iterdir():
        if not project_dir.is_dir():
            continue
        project_name = project_dir.name
        for f in project_dir.iterdir():
            if f.suffix != ".jsonl" or f.parent.name == "subagents":
                continue
            try:
                st = f.stat()
            except OSError:
                continue
            session_id = f.stem
            mod_dt = datetime.fromtimestamp(st.st_mtime)
            size_mb = st.st_size / (1024 * 1024)
            topic, cwd = _scan_session_head(f)
            try:
                resolved_path = f.resolve()
            except OSError:
                resolved_path = f
            provider_id = provider_map.get(resolved_path, "claude")
            sessions.append(
                {
                    "id": session_id,
                    "project": project_name,
                    "cwd": cwd,
                    "modified": mod_dt,
                    "size_mb": size_mb,
                    "path": f,
                    "topic": topic,
                    "provider": provider_id,
                    "starred": session_id in starred_ids,
                }
            )
    return sessions


def _discover_codex_sessions(starred_ids: set) -> list:
    """Yield session dicts for Codex CLI (~/.codex/sessions/YYYY/MM/DD/*.jsonl)."""
    sessions = []
    codex_sessions_dir = _const.MAIN_HOME / ".codex" / "sessions"
    if not codex_sessions_dir.exists():
        return sessions

    # Walk YYYY/MM/DD sub-directories
    try:
        year_dirs = sorted(codex_sessions_dir.iterdir())
    except OSError:
        return sessions

    for year_dir in year_dirs:
        if not year_dir.is_dir():
            continue
        try:
            month_dirs = sorted(year_dir.iterdir())
        except OSError:
            continue
        for month_dir in month_dirs:
            if not month_dir.is_dir():
                continue
            try:
                day_dirs = sorted(month_dir.iterdir())
            except OSError:
                continue
            for day_dir in day_dirs:
                if not day_dir.is_dir():
                    continue
                try:
                    files = list(day_dir.iterdir())
                except OSError:
                    continue
                for f in files:
                    if f.suffix != ".jsonl":
                        continue
                    try:
                        st = f.stat()
                    except OSError:
                        continue
                    mod_dt = datetime.fromtimestamp(st.st_mtime)
                    size_mb = st.st_size / (1024 * 1024)
                    session_id, topic, cwd = _scan_codex_session_head(f)
                    if not session_id:
                        # Fall back to filename stem UUID portion
                        session_id = f.stem
                    project = cwd.rstrip("/").rsplit("/", 1)[-1] if cwd else f.stem
                    sessions.append(
                        {
                            "id": session_id,
                            "project": project,
                            "cwd": cwd,
                            "modified": mod_dt,
                            "size_mb": size_mb,
                            "path": f,
                            "topic": topic,
                            "provider": "codex",
                            "starred": session_id in starred_ids,
                        }
                    )
    return sessions


def _discover_gemini_sessions(starred_ids: set) -> list:
    """Yield session dicts for Gemini CLI (~/.gemini/tmp/<proj>/chats/*.json)."""
    sessions = []
    gemini_tmp_dir = _const.MAIN_HOME / ".gemini" / "tmp"
    if not gemini_tmp_dir.exists():
        return sessions

    try:
        proj_dirs = list(gemini_tmp_dir.iterdir())
    except OSError:
        return sessions

    for proj_dir in proj_dirs:
        if not proj_dir.is_dir():
            continue
        chats_dir = proj_dir / "chats"
        if not chats_dir.is_dir():
            continue

        # Try to read the canonical project root from .project_root sentinel file
        project_root_file = proj_dir / ".project_root"
        cwd_base = ""
        if project_root_file.is_file():
            try:
                cwd_base = project_root_file.read_text(encoding="utf-8").strip()
            except OSError:
                pass
        if not cwd_base:
            cwd_base = proj_dir.name  # dirname as fallback (relative hint)

        project_label = proj_dir.name

        try:
            chat_files = list(chats_dir.iterdir())
        except OSError:
            continue

        for f in chat_files:
            if f.suffix != ".json":
                continue
            try:
                st = f.stat()
            except OSError:
                continue
            mod_dt = datetime.fromtimestamp(st.st_mtime)
            size_mb = st.st_size / (1024 * 1024)
            session_id, topic, cwd = _scan_gemini_session(f, cwd_base)
            if not session_id:
                session_id = f.stem
            sessions.append(
                {
                    "id": session_id,
                    "project": project_label,
                    "cwd": cwd or cwd_base,
                    "modified": mod_dt,
                    "size_mb": size_mb,
                    "path": f,
                    "topic": topic,
                    "provider": "gemini",
                    "starred": session_id in starred_ids,
                }
            )
    return sessions


def _discover_copilot_sessions(starred_ids: set) -> list:
    """Yield session dicts for GitHub Copilot (~/.copilot/session-state/<uuid>/)."""
    sessions = []
    copilot_state_dir = _const.MAIN_HOME / ".copilot" / "session-state"
    if not copilot_state_dir.exists():
        return sessions

    try:
        session_dirs = list(copilot_state_dir.iterdir())
    except OSError:
        return sessions

    for session_dir in session_dirs:
        if not session_dir.is_dir():
            continue
        session_id = session_dir.name
        workspace_yaml = session_dir / "workspace.yaml"
        events_jsonl = session_dir / "events.jsonl"

        # Prefer workspace.yaml — tiny key:value file, fast to parse
        meta = _parse_copilot_workspace_yaml(workspace_yaml)
        if meta:
            cwd = meta.get("cwd", "")
            topic = meta.get("summary", "")
            # Try to get a more accurate mtime from updated_at
            mod_dt = None
            updated_at = meta.get("updated_at", "")
            if updated_at:
                try:
                    mod_dt = datetime.fromisoformat(updated_at.replace("Z", "+00:00")).replace(tzinfo=None)
                except (ValueError, AttributeError):
                    pass
            sid = meta.get("id", session_id)
        else:
            # Fall back to events.jsonl
            sid, cwd, topic, mod_dt = _scan_copilot_events_head(events_jsonl)
            if not sid:
                sid = session_id

        # Compute size: total bytes under session dir
        size_bytes = 0
        try:
            for entry in session_dir.iterdir():
                try:
                    size_bytes += entry.stat().st_size
                except OSError:
                    pass
        except OSError:
            pass

        if mod_dt is None:
            try:
                st = session_dir.stat()
                mod_dt = datetime.fromtimestamp(st.st_mtime)
            except OSError:
                mod_dt = datetime.fromtimestamp(0)

        project = cwd.rstrip("/").rsplit("/", 1)[-1] if cwd else session_dir.name

        sessions.append(
            {
                "id": sid,
                "project": project,
                "cwd": cwd,
                "modified": mod_dt,
                "size_mb": size_bytes / (1024 * 1024),
                "path": session_dir,
                "topic": topic,
                "provider": "copilot",
                "starred": sid in starred_ids,
            }
        )
    return sessions


def get_sessions():
    """Find all sessions across all projects, return sorted by modification time."""
    starred_ids = load_starred_ids()
    sessions = []
    sessions.extend(_discover_claude_sessions(starred_ids))
    sessions.extend(_discover_codex_sessions(starred_ids))
    sessions.extend(_discover_gemini_sessions(starred_ids))
    sessions.extend(_discover_copilot_sessions(starred_ids))
    sessions.sort(key=lambda s: s["modified"], reverse=True)
    return sessions


def _extract_text(content):
    """Flatten a Claude Code message ``content`` field into plain text."""
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        out = []
        for block in content:
            if not isinstance(block, dict):
                continue
            btype = block.get("type")
            if btype == "text" and isinstance(block.get("text"), str):
                out.append(block["text"])
            elif btype == "tool_result":
                tc = block.get("content")
                if isinstance(tc, str):
                    out.append(tc)
                elif isinstance(tc, list):
                    for sub in tc:
                        if isinstance(sub, dict) and sub.get("type") == "text":
                            out.append(sub.get("text", ""))
        return "\n".join(out)
    return ""


_CODE_FENCE_RE = re.compile(r"```[^\n]*\n.*?```", re.DOTALL)
_INLINE_CODE_RE = re.compile(r"`([^`]*)`")
_MD_LINK_RE = re.compile(r"\[([^\]]+)\]\([^)]*\)")
_WS_RE = re.compile(r"\s+")


def _clean_topic(text: str) -> str:
    """Strip code fences, collapse whitespace, return single-line summary."""
    if not text:
        return ""
    text = _CODE_FENCE_RE.sub(" [code] ", text)
    text = _MD_LINK_RE.sub(r"\1", text)
    text = _INLINE_CODE_RE.sub(r"\1", text)
    text = _WS_RE.sub(" ", text).strip()
    return text


def _is_real_user_message(obj) -> bool:
    """Return True for genuine human user turns (not tool_result-only echoes)."""
    if obj.get("type") != "user":
        return False
    msg = obj.get("message")
    if not isinstance(msg, dict):
        return False
    content = msg.get("content")
    if isinstance(content, str):
        return bool(content.strip())
    if isinstance(content, list):
        # Skip turns that are only tool_result blocks (Claude Code injects these)
        for block in content:
            if isinstance(block, dict) and block.get("type") == "text":
                return bool(block.get("text", "").strip())
        return False
    return False


def _scan_session_head(jsonl_path, max_lines: int = 40) -> tuple:
    """Cheap scan: return (topic, cwd) from the first ``max_lines`` of a session."""
    topic = ""
    cwd = ""
    try:
        with open(jsonl_path, "r", encoding="utf-8", errors="replace") as f:
            for i, line in enumerate(f):
                if i >= max_lines and topic:
                    break
                line = line.strip()
                if not line:
                    continue
                try:
                    obj = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if not cwd and isinstance(obj.get("cwd"), str):
                    cwd = obj["cwd"]
                if not topic and _is_real_user_message(obj):
                    text = _extract_text(obj["message"].get("content"))
                    topic = _clean_topic(text)
    except OSError:
        pass
    return topic, cwd


def _scan_codex_session_head(jsonl_path, max_lines: int = 80) -> tuple:
    """Return (session_id, topic, cwd) from the head of a Codex session JSONL."""
    session_id = ""
    topic = ""
    cwd = ""
    try:
        with open(jsonl_path, "r", encoding="utf-8", errors="replace") as fh:
            for i, line in enumerate(fh):
                if i >= max_lines and session_id and topic:
                    break
                line = line.strip()
                if not line:
                    continue
                try:
                    obj = json.loads(line)
                except json.JSONDecodeError:
                    continue
                t = obj.get("type")
                payload = obj.get("payload") if isinstance(obj.get("payload"), dict) else {}
                if t == "session_meta" and not session_id:
                    session_id = payload.get("id", "")
                    cwd = payload.get("cwd", "")
                if not topic and t == "response_item":
                    if payload.get("type") == "message" and payload.get("role") == "user":
                        content_items = payload.get("content", [])
                        for item in content_items:
                            if not isinstance(item, dict):
                                continue
                            if item.get("type") != "input_text":
                                continue
                            text = item.get("text", "")
                            if any(text.startswith(s) for s in _CODEX_TOPIC_SENTINELS):
                                continue
                            topic = _clean_topic(text)
                            break
    except OSError:
        pass
    return session_id, topic, cwd


def _scan_gemini_session(json_path, cwd_fallback: str = "") -> tuple:
    """Return (session_id, topic, cwd) by parsing a Gemini session JSON file."""
    session_id = ""
    topic = ""
    cwd = cwd_fallback
    try:
        raw = json_path.read_text(encoding="utf-8", errors="replace")
        data = json.loads(raw)
    except (OSError, json.JSONDecodeError):
        return session_id, topic, cwd

    session_id = data.get("sessionId", "")
    # cwd: use .project_root content (already passed as cwd_fallback)
    # Topic: first user message
    messages = data.get("messages", [])
    for msg in messages:
        if not isinstance(msg, dict):
            continue
        if msg.get("type") != "user":
            continue
        content = msg.get("content", "")
        if isinstance(content, str):
            text = content
        elif isinstance(content, list):
            parts = []
            for c in content:
                if isinstance(c, dict) and isinstance(c.get("text"), str):
                    parts.append(c["text"])
                elif isinstance(c, str):
                    parts.append(c)
            text = " ".join(parts)
        else:
            continue
        text = text.strip()
        if text:
            topic = _clean_topic(text)
            break

    return session_id, topic, cwd


def _parse_copilot_workspace_yaml(yaml_path) -> dict:
    """Parse a minimal Copilot workspace.yaml into a plain dict."""
    result = {}
    try:
        text = yaml_path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return result
    for line in text.splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        if ":" not in line:
            continue
        key, _, val = line.partition(":")
        key = key.strip()
        val = val.strip()
        # Strip surrounding quotes if present
        if len(val) >= 2 and val[0] in ('"', "'") and val[-1] == val[0]:
            val = val[1:-1]
        result[key] = val
    return result


def _scan_copilot_events_head(jsonl_path, max_lines: int = 40) -> tuple:
    """Return (session_id, cwd, topic, mod_dt) from events.jsonl head."""
    session_id = ""
    cwd = ""
    topic = ""
    mod_dt = None
    try:
        with open(jsonl_path, "r", encoding="utf-8", errors="replace") as fh:
            for i, line in enumerate(fh):
                if i >= max_lines and session_id and topic:
                    break
                line = line.strip()
                if not line:
                    continue
                try:
                    obj = json.loads(line)
                except json.JSONDecodeError:
                    continue
                t = obj.get("type", "")
                data = obj.get("data") if isinstance(obj.get("data"), dict) else {}
                if t == "session.start" and not session_id:
                    session_id = data.get("sessionId", "")
                    ctx = data.get("context") if isinstance(data.get("context"), dict) else {}
                    cwd = ctx.get("cwd", "") or ctx.get("gitRoot", "")
                    ts = data.get("timestamp", "")
                    if ts:
                        try:
                            mod_dt = datetime.fromisoformat(ts.replace("Z", "+00:00")).replace(tzinfo=None)
                        except (ValueError, AttributeError):
                            pass
                elif t == "user.message" and not topic:
                    content = data.get("content", "")
                    if isinstance(content, str) and content.strip():
                        topic = _clean_topic(content)
    except OSError:
        pass
    return session_id, cwd, topic, mod_dt


def load_session_preview(
    session_or_path, max_messages: int = 4, max_lines: int = 400, provider: str = "claude"
) -> dict:
    """Load opening prompt + first few message turns for the preview pane."""
    if provider == "gemini":
        return _load_gemini_preview(session_or_path, max_messages=max_messages)
    if provider == "codex":
        return _load_codex_preview(session_or_path, max_messages=max_messages, max_lines=max_lines)
    if provider == "copilot":
        return _load_copilot_preview(session_or_path, max_messages=max_messages)
    # Default: Claude JSONL
    return _load_claude_preview(session_or_path, max_messages=max_messages, max_lines=max_lines)


def _load_claude_preview(jsonl_path, max_messages: int = 4, max_lines: int = 400) -> dict:
    """Load preview for a Claude Code JSONL session."""
    messages = []
    cwd = ""
    total_lines = 0
    truncated = False
    try:
        with open(jsonl_path, "r", encoding="utf-8", errors="replace") as f:
            for line in f:
                total_lines += 1
                if total_lines > max_lines:
                    truncated = True
                    break
                line = line.strip()
                if not line:
                    continue
                try:
                    obj = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if not cwd and isinstance(obj.get("cwd"), str):
                    cwd = obj["cwd"]
                t = obj.get("type")
                msg = obj.get("message") if isinstance(obj.get("message"), dict) else None
                if t == "user" and _is_real_user_message(obj):
                    text = _extract_text(msg.get("content"))
                    if text.strip():
                        messages.append(("user", text.strip()))
                elif t == "assistant" and msg:
                    text = _extract_text(msg.get("content"))
                    if text.strip():
                        messages.append(("assistant", text.strip()))
                if len(messages) >= max_messages:
                    # Peek one more line to know if there's more content
                    if f.readline():
                        truncated = True
                    break
    except OSError as e:
        return {"messages": [], "cwd": "", "truncated": False, "error": str(e)}
    return {"messages": messages, "cwd": cwd, "truncated": truncated, "error": None}


def _load_codex_preview(jsonl_path, max_messages: int = 4, max_lines: int = 400) -> dict:
    """Load preview for a Codex CLI JSONL session."""
    messages = []
    cwd = ""
    total_lines = 0
    truncated = False
    try:
        with open(jsonl_path, "r", encoding="utf-8", errors="replace") as fh:
            for line in fh:
                total_lines += 1
                if total_lines > max_lines:
                    truncated = True
                    break
                line = line.strip()
                if not line:
                    continue
                try:
                    obj = json.loads(line)
                except json.JSONDecodeError:
                    continue
                t = obj.get("type")
                payload = obj.get("payload") if isinstance(obj.get("payload"), dict) else {}
                if t == "session_meta" and not cwd:
                    cwd = payload.get("cwd", "")
                if t == "response_item" and payload.get("type") == "message":
                    role = payload.get("role", "")
                    content_items = payload.get("content", [])
                    text_parts = []
                    for item in content_items:
                        if isinstance(item, dict) and item.get("type") in ("input_text", "output_text"):
                            text_parts.append(item.get("text", ""))
                        elif isinstance(item, str):
                            text_parts.append(item)
                    text = " ".join(text_parts).strip()
                    if role == "user" and text:
                        if not any(text.startswith(s) for s in _CODEX_TOPIC_SENTINELS):
                            messages.append(("user", text))
                    elif role == "assistant" and text:
                        messages.append(("assistant", text))
                if len(messages) >= max_messages:
                    truncated = bool(fh.readline())
                    break
    except OSError as e:
        return {"messages": [], "cwd": "", "truncated": False, "error": str(e)}
    return {"messages": messages, "cwd": cwd, "truncated": truncated, "error": None}


def _load_gemini_preview(json_path, max_messages: int = 4) -> dict:
    """Load preview for a Gemini CLI JSON session file."""
    messages = []
    cwd = ""
    truncated = False
    try:
        raw = json_path.read_text(encoding="utf-8", errors="replace")
        data = json.loads(raw)
    except (OSError, json.JSONDecodeError) as e:
        return {"messages": [], "cwd": "", "truncated": False, "error": str(e)}

    msg_list = data.get("messages", [])
    for msg in msg_list:
        if not isinstance(msg, dict):
            continue
        msg_type = msg.get("type", "")
        content = msg.get("content", "")
        if isinstance(content, str):
            text = content.strip()
        elif isinstance(content, list):
            parts = []
            for c in content:
                if isinstance(c, dict) and isinstance(c.get("text"), str):
                    parts.append(c["text"])
                elif isinstance(c, str):
                    parts.append(c)
            text = " ".join(parts).strip()
        else:
            text = ""
        if not text:
            continue
        if msg_type == "user":
            messages.append(("user", text))
        elif msg_type in ("assistant", "gemini", "model"):
            messages.append(("assistant", text))
        if len(messages) >= max_messages:
            truncated = True
            break

    return {"messages": messages, "cwd": cwd, "truncated": truncated, "error": None}


def _load_copilot_preview(session_dir, max_messages: int = 4) -> dict:
    """Load preview for a GitHub Copilot session directory."""
    messages = []
    cwd = ""
    truncated = False

    # Try workspace.yaml for cwd
    workspace_yaml = session_dir / "workspace.yaml"
    meta = _parse_copilot_workspace_yaml(workspace_yaml)
    if meta:
        cwd = meta.get("cwd", "")

    # Read events.jsonl for messages
    events_jsonl = session_dir / "events.jsonl"
    try:
        with open(events_jsonl, "r", encoding="utf-8", errors="replace") as fh:
            for line in fh:
                line = line.strip()
                if not line:
                    continue
                try:
                    obj = json.loads(line)
                except json.JSONDecodeError:
                    continue
                t = obj.get("type", "")
                data = obj.get("data") if isinstance(obj.get("data"), dict) else {}
                if t == "session.start" and not cwd:
                    ctx = data.get("context") if isinstance(data.get("context"), dict) else {}
                    cwd = ctx.get("cwd", "") or ctx.get("gitRoot", "")
                elif t == "user.message":
                    content = data.get("content", "")
                    if isinstance(content, str) and content.strip():
                        messages.append(("user", content.strip()))
                elif t in ("assistant.message", "copilot.message"):
                    content = data.get("content", "")
                    if isinstance(content, str) and content.strip():
                        messages.append(("assistant", content.strip()))
                if len(messages) >= max_messages:
                    truncated = True
                    break
    except OSError:
        # events.jsonl may not exist; fall back to summary from workspace.yaml
        summary = meta.get("summary", "") if meta else ""
        if summary:
            messages = [("user", summary)]

    return {"messages": messages, "cwd": cwd, "truncated": truncated, "error": None}


def decode_project_path(encoded: str) -> str:
    """Decode Claude Code's project dir name back into a readable path."""
    if not encoded:
        return ""
    s = encoded
    if s.startswith("-"):
        s = "/" + s[1:].replace("-", "/")
    else:
        s = s.replace("-", "/")
    return s


def format_project_name(encoded):
    """Short, readable project name (last path component)."""
    if not encoded:
        return ""
    # Non-Claude providers store a plain label or basename — return it directly.
    if "/" in encoded or not encoded.startswith("-"):
        return encoded.rstrip("/").rsplit("/", 1)[-1] or encoded
    # Claude dash-encoded path
    decoded = decode_project_path(encoded)
    name = decoded.rstrip("/").rsplit("/", 1)[-1]
    return name or encoded


def relative_time(dt: datetime, now: datetime = None) -> str:
    """Return a compact relative-time string ('2h ago', 'yesterday', '3d ago')."""
    if now is None:
        now = datetime.now()
    delta = now - dt
    secs = int(delta.total_seconds())
    if secs < 0:
        return "just now"
    if secs < 60:
        return f"{secs}s ago"
    mins = secs // 60
    if mins < 60:
        return f"{mins}m ago"
    hrs = mins // 60
    if hrs < 24:
        return f"{hrs}h ago"
    days = hrs // 24
    if days == 1:
        return "yesterday"
    if days < 7:
        return f"{days}d ago"
    if days < 30:
        return f"{days // 7}w ago"
    if days < 365:
        return f"{days // 30}mo ago"
    return f"{days // 365}y ago"
