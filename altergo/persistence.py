import json
import os
import re
import sys
import threading
import time
from datetime import datetime
from pathlib import Path

import altergo.constants as _const
import altergo.theme as _theme
from altergo._version import __version__


def _dim(text: str) -> str:
    if sys.stdout.isatty():
        return f"\033[2m{text}\033[0m"
    return text


# ---------------------------------------------------------------------------
# Account metadata
# ---------------------------------------------------------------------------


def load_account_meta(account_home: Path) -> dict:
    meta_file = account_home / "account.json"
    slug = account_home.name
    if meta_file.exists():
        try:
            data = json.loads(meta_file.read_text())
        except Exception:
            return _coerce_meta_v3({})
        data["_account_slug"] = slug
        result = _coerce_meta_v3(data)
        result.pop("_account_slug", None)
        return result
    if (account_home / ".claude").exists():
        return _coerce_meta_v3({"provider": "claude"})
    return None


def _coerce_meta_v3(data: dict) -> dict:
    out: dict = {k: v for k, v in data.items() if k not in ("version", "provider", "providers", "default_provider")}
    if data.get("version") == 3 and isinstance(data.get("providers"), list) and data["providers"]:
        seen: set[str] = set()
        providers: list[str] = []
        for p in data["providers"]:
            if isinstance(p, str) and p in _const.PROVIDERS and p not in seen:
                seen.add(p)
                providers.append(p)
        if not providers:
            providers = ["claude"]
        default = data.get("default_provider")
        if not isinstance(default, str) or default not in providers:
            default = providers[0]
    else:
        provider = data.get("provider") if isinstance(data.get("provider"), str) else "claude"
        if provider not in _const.PROVIDERS:
            provider = "claude"
        providers = [provider]
        default = provider
    out["version"] = 3
    out["providers"] = providers
    out["default_provider"] = default
    kc = data.get("keychain")
    _LEGACY_KC_VALUES = {"system", "shared", "dedicated", "isolated"}
    if kc in _LEGACY_KC_VALUES:
        _acct_hint = data.get("_account_slug", "<account>")
        print(
            _dim(
                f"altergo: account '{_acct_hint}' has legacy keychain mode '{kc}' — "
                f"treating as 'keychain'. Run `altergo --config {_acct_hint}` to normalize."
            ),
            file=sys.stderr,
        )
        out["keychain"] = "keychain"
    elif kc in ("none", "keychain"):
        out["keychain"] = kc
    return out


def _read_account_email(account_name: str) -> str | None:
    try:
        account_home = _const.ACCOUNTS_DIR / account_name
        claude_json = account_home / ".claude.json"
        if claude_json.exists():
            data = json.loads(claude_json.read_text())
            email = data.get("oauthAccount", {}).get("emailAddress")
            if email and isinstance(email, str) and "@" in email:
                return email
        codex_auth = account_home / ".codex" / "auth.json"
        if codex_auth.exists():
            import base64

            auth = json.loads(codex_auth.read_text())
            id_token = auth.get("tokens", {}).get("id_token", "")
            if id_token:
                parts = id_token.split(".")
                if len(parts) >= 2:
                    padding = (-len(parts[1])) % 4
                    payload = json.loads(base64.urlsafe_b64decode(parts[1] + "=" * padding))
                    email = payload.get("email")
                    if email and isinstance(email, str) and "@" in email:
                        return email
        gemini_creds = account_home / ".gemini" / "oauth_creds.json"
        if gemini_creds.exists():
            import base64

            creds = json.loads(gemini_creds.read_text())
            id_token = creds.get("id_token", "")
            if id_token:
                parts = id_token.split(".")
                if len(parts) >= 2:
                    padding = (-len(parts[1])) % 4
                    payload = json.loads(base64.urlsafe_b64decode(parts[1] + "=" * padding))
                    email = payload.get("email")
                    if email and isinstance(email, str) and "@" in email:
                        return email
    except Exception:
        pass
    return None


def save_account_meta(account_home: Path, meta: dict) -> None:
    account_home.mkdir(parents=True, exist_ok=True)
    meta_file = account_home / "account.json"
    tmp = meta_file.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(meta, indent=2))
    os.replace(str(tmp), str(meta_file))


# ---------------------------------------------------------------------------
# Settings (shared catalog overrides)
# ---------------------------------------------------------------------------


def load_settings():
    if not _const.SETTINGS_FILE.exists():
        return {}
    try:
        data = json.loads(_const.SETTINGS_FILE.read_text())
        shared = data.get("shared", {})
        catalog_ids = {e["id"] for e in _const.CATALOG}
        return {k: v for k, v in shared.items() if k in catalog_ids and isinstance(v, bool)}
    except Exception:
        return {}


def save_settings(overrides):
    _const.SETTINGS_FILE.parent.mkdir(parents=True, exist_ok=True)
    data = {}
    if _const.SETTINGS_FILE.exists():
        try:
            data = json.loads(_const.SETTINGS_FILE.read_text())
        except Exception:
            data = {}
    data["version"] = 1
    data["shared"] = overrides
    tmp = _const.SETTINGS_FILE.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(data, indent=2))
    os.replace(str(tmp), str(_const.SETTINGS_FILE))


def _patch_settings(updates: dict) -> None:
    _const.SETTINGS_FILE.parent.mkdir(parents=True, exist_ok=True)
    data: dict = {}
    if _const.SETTINGS_FILE.exists():
        try:
            data = json.loads(_const.SETTINGS_FILE.read_text())
        except Exception:
            data = {}
    data.update(updates)
    tmp = _const.SETTINGS_FILE.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(data, indent=2))
    os.replace(str(tmp), str(_const.SETTINGS_FILE))


# ---------------------------------------------------------------------------
# Starred conversations
# ---------------------------------------------------------------------------


def load_starred_entries() -> list:
    if not _const.STARRED_FILE.exists():
        return []
    try:
        data = json.loads(_const.STARRED_FILE.read_text())
        return [e for e in data.get("starred", []) if isinstance(e.get("id"), str)]
    except Exception:
        return []


def load_starred_ids() -> set:
    return {e["id"] for e in load_starred_entries()}


def _save_starred(entries: list) -> None:
    _const.STARRED_FILE.parent.mkdir(parents=True, exist_ok=True)
    data = {"version": 1, "starred": entries}
    tmp = _const.STARRED_FILE.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(data, indent=2))
    os.replace(str(tmp), str(_const.STARRED_FILE))


def star_session(session_id: str, provider: str, project: str, topic: str) -> None:
    entries = load_starred_entries()
    if any(e["id"] == session_id for e in entries):
        return
    entries.append(
        {
            "id": session_id,
            "provider": provider,
            "project": project,
            "topic": topic or "",
            "starred_at": datetime.now().isoformat(timespec="seconds"),
        }
    )
    _save_starred(entries)


def unstar_session(session_id: str) -> None:
    _save_starred([e for e in load_starred_entries() if e["id"] != session_id])


def toggle_starred_session(session_id: str, provider: str, project: str, topic: str) -> bool:
    entries = load_starred_entries()
    if any(e["id"] == session_id for e in entries):
        _save_starred([e for e in entries if e["id"] != session_id])
        return False
    entries.append(
        {
            "id": session_id,
            "provider": provider,
            "project": project,
            "topic": topic or "",
            "starred_at": datetime.now().isoformat(timespec="seconds"),
        }
    )
    _save_starred(entries)
    return True


# ---------------------------------------------------------------------------
# Last-session tracking
# ---------------------------------------------------------------------------


def save_last_session(session_id: str, provider: str, project: str, topic: str) -> None:
    data = {
        "id": session_id,
        "provider": provider,
        "project": project,
        "topic": topic or "",
        "timestamp": datetime.now().isoformat(timespec="seconds"),
    }
    _const.LAST_SESSION_FILE.parent.mkdir(parents=True, exist_ok=True)
    tmp = _const.LAST_SESSION_FILE.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(data, indent=2))
    os.replace(str(tmp), str(_const.LAST_SESSION_FILE))


def load_last_session() -> dict | None:
    if not _const.LAST_SESSION_FILE.exists():
        return None
    try:
        return json.loads(_const.LAST_SESSION_FILE.read_text())
    except Exception:
        return None


# ---------------------------------------------------------------------------
# Theme persistence
# ---------------------------------------------------------------------------


def load_persisted_theme() -> str:
    if not _const.SETTINGS_FILE.exists():
        return _theme._DEFAULT_THEME
    try:
        data = json.loads(_const.SETTINGS_FILE.read_text())
        name = data.get("theme")
        if isinstance(name, str) and name in _theme.THEMES:
            return name
    except Exception:
        pass
    return _theme._DEFAULT_THEME


def save_persisted_theme(name: str) -> None:
    if name not in _theme.THEMES:
        return
    _const.SETTINGS_FILE.parent.mkdir(parents=True, exist_ok=True)
    data = {}
    if _const.SETTINGS_FILE.exists():
        try:
            data = json.loads(_const.SETTINGS_FILE.read_text())
        except Exception:
            data = {}
    data["theme"] = name
    tmp = _const.SETTINGS_FILE.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(data, indent=2))
    os.replace(str(tmp), str(_const.SETTINGS_FILE))


# ---------------------------------------------------------------------------
# Native default provider persistence
# ---------------------------------------------------------------------------


def load_native_default_provider() -> "str | None":
    if not _const.SETTINGS_FILE.exists():
        return None
    try:
        data = json.loads(_const.SETTINGS_FILE.read_text())
        pid = data.get("native_default_provider")
        if isinstance(pid, str) and pid in _const.PROVIDERS:
            return pid
    except Exception:
        pass
    return None


def save_native_default_provider(provider_id: str) -> None:
    if provider_id not in _const.PROVIDERS:
        return
    _patch_settings({"native_default_provider": provider_id})


# ---------------------------------------------------------------------------
# Banner font persistence
# ---------------------------------------------------------------------------

_BANNER_FONT_CATALOG: list[str] = [
    "smslant",
    "shadow",
    "small",
    "thin",
    "chunky",
    "avatar",
    "trek",
    "rowancap",
    "elite",
    "smblock",
    "double",
    "bulbhead",
    "tombstone",
    "calvin_s",
    "future",
    "digital",
    "pagga",
]

_DEFAULT_BANNER_FONT = "smslant"
_valid_banner_fonts_cache: list[str] | None = None


def _get_valid_banner_fonts() -> list[str]:
    global _valid_banner_fonts_cache
    if _valid_banner_fonts_cache is not None:
        return _valid_banner_fonts_cache
    try:
        import pyfiglet

        available = set(pyfiglet.FigletFont.getFonts())
        valid = []
        for font_name in _BANNER_FONT_CATALOG:
            if font_name not in available:
                continue
            try:
                rendered = pyfiglet.Figlet(font=font_name).renderText("altergo")
                rows = len([ln for ln in rendered.splitlines() if ln.strip()])
                if rows <= 5:
                    valid.append(font_name)
            except Exception:
                pass
        _valid_banner_fonts_cache = valid if valid else [_DEFAULT_BANNER_FONT]
    except Exception:
        _valid_banner_fonts_cache = [_DEFAULT_BANNER_FONT]
    return _valid_banner_fonts_cache


def load_persisted_banner_font() -> str:
    if not _const.SETTINGS_FILE.exists():
        return _DEFAULT_BANNER_FONT
    try:
        data = json.loads(_const.SETTINGS_FILE.read_text())
        font = data.get("banner_font")
        if isinstance(font, str) and font in _BANNER_FONT_CATALOG:
            return font
    except Exception:
        pass
    return _DEFAULT_BANNER_FONT


def save_persisted_banner_font(name: str) -> None:
    if name not in _BANNER_FONT_CATALOG:
        return
    _patch_settings({"banner_font": name})


# ---------------------------------------------------------------------------
# Animation packs
# ---------------------------------------------------------------------------

_ANIM_PACKS: dict[str, dict] = {
    "off": {"duration": 0.0, "spinner": None, "label": "Off", "hint": "No animation — instant launch"},
    "minimal": {"duration": 0.4, "spinner": None, "label": "Minimal", "hint": "Brief star pulse, quiet and fast"},
    "smooth": {
        "duration": 0.7,
        "spinner": "boxBounce2",
        "label": "Smooth",
        "hint": "Fat block sweeping around a rectangle",
    },
    "retro": {"duration": 0.5, "spinner": "line", "label": "Retro", "hint": "Classic |/-\\ spinner, quick twinkle"},
    "wave": {
        "duration": 0.6,
        "spinner": "growVertical",
        "label": "Wave",
        "hint": "Growing vertical bars — rise and fall",
    },
    "orbit": {"duration": 0.6, "spinner": "arc", "label": "Orbit", "hint": "Smooth arc rotation — elegant and calm"},
    "pulse": {"duration": 0.8, "spinner": "dots", "label": "Pulse", "hint": "Soft braille dots — gentle and focused"},
    "matrix": {"duration": 0.9, "spinner": "noise", "label": "Matrix", "hint": "Block-fill noise — deep focus mode"},
}
_VALID_ANIM_PACKS: tuple[str, ...] = tuple(_ANIM_PACKS.keys())
_DEFAULT_ANIM_PACK = "minimal"

_RICH_SPINNER_DATA_CACHE: dict | None = None


def _get_rich_spinner_data() -> dict:
    global _RICH_SPINNER_DATA_CACHE
    if _RICH_SPINNER_DATA_CACHE is None:
        try:
            from rich._spinners import SPINNERS as _RS  # type: ignore[import-untyped]

            _RICH_SPINNER_DATA_CACHE = _RS
        except Exception:
            _RICH_SPINNER_DATA_CACHE = {}
    return _RICH_SPINNER_DATA_CACHE


def load_animation_pack() -> str:
    if not _const.SETTINGS_FILE.exists():
        return _DEFAULT_ANIM_PACK
    try:
        data = json.loads(_const.SETTINGS_FILE.read_text())
        pack = data.get("animation_pack")
        if isinstance(pack, str) and pack in _VALID_ANIM_PACKS:
            return pack
        la = data.get("launch_animation")
        if la is False:
            return "off"
    except Exception:
        pass
    return _DEFAULT_ANIM_PACK


# ---------------------------------------------------------------------------
# Random theme rotation
# ---------------------------------------------------------------------------


def load_random_theme_settings() -> dict:
    defaults: dict = {
        "random_theme_enabled": False,
        "random_theme_frequency": 3,
        "random_theme_counter": 0,
    }
    if not _const.SETTINGS_FILE.exists():
        return defaults
    try:
        data = json.loads(_const.SETTINGS_FILE.read_text())
        enabled = data.get("random_theme_enabled")
        freq = data.get("random_theme_frequency")
        ctr = data.get("random_theme_counter")
        return {
            "random_theme_enabled": enabled if isinstance(enabled, bool) else False,
            "random_theme_frequency": freq if isinstance(freq, int) and 1 <= freq <= 5 else 3,
            "random_theme_counter": ctr if isinstance(ctr, int) and ctr >= 0 else 0,
        }
    except Exception:
        return defaults


def _random_theme_counter_range(freq: int) -> tuple:
    if freq <= 2:
        return (1, 5)
    elif freq == 3:
        return (5, 10)
    else:
        return (10, 20)


def maybe_rotate_random_theme() -> None:
    import random as _random

    rts = load_random_theme_settings()
    if not rts["random_theme_enabled"]:
        return

    freq = rts["random_theme_frequency"]
    counter = rts["random_theme_counter"]

    if counter <= 0:
        lo, hi = _random_theme_counter_range(freq)
        _patch_settings({"random_theme_counter": _random.randint(lo, hi)})
        return

    counter -= 1
    if counter > 0:
        _patch_settings({"random_theme_counter": counter})
        return

    current = _theme.get_current_theme()
    choices = [t for t in _theme.THEMES if t != current]
    new_theme = _random.choice(choices) if choices else current
    lo, hi = _random_theme_counter_range(freq)
    _theme.set_current_theme(new_theme)
    _patch_settings({"theme": new_theme, "random_theme_counter": _random.randint(lo, hi)})


# ---------------------------------------------------------------------------
# Launch-handoff animation duration
# ---------------------------------------------------------------------------

_HANDOFF_ANIM_SECONDS: dict[str, float] = {
    "claude": 0.7,
    "gemini": 0.7,
    "copilot": 0.7,
    "codex": 0.0,
}


def _handoff_duration(provider: str | None) -> float:
    if provider is None:
        return 0.0
    return _HANDOFF_ANIM_SECONDS.get(provider, 0.0)


# ---------------------------------------------------------------------------
# Update checker
# ---------------------------------------------------------------------------

UPDATE_CACHE_FILE = _const.MAIN_HOME / ".altergo" / "version_check.json"
UPDATE_CACHE_TTL_SECONDS = 24 * 60 * 60
UPDATE_FETCH_TIMEOUT = 3.0
UPDATE_FETCH_MAX_BYTES = 32 * 1024
UPDATE_PYPI_URL = "https://pypi.org/pypi/altergo/json"

_VERSION_RE = re.compile(r"^[0-9a-zA-Z.\-+]{1,32}$")


def _sanitize_version(v) -> str | None:
    if not isinstance(v, str):
        return None
    if _VERSION_RE.match(v):
        return v
    return None


def load_update_check_enabled() -> bool:
    if not _const.SETTINGS_FILE.exists():
        return True
    try:
        data = json.loads(_const.SETTINGS_FILE.read_text())
        v = data.get("update_check")
        if isinstance(v, bool):
            return v
    except Exception:
        pass
    return True


def save_update_check_enabled(enabled: bool) -> None:
    _const.SETTINGS_FILE.parent.mkdir(parents=True, exist_ok=True)
    data = {}
    if _const.SETTINGS_FILE.exists():
        try:
            data = json.loads(_const.SETTINGS_FILE.read_text())
        except Exception:
            data = {}
    data["update_check"] = bool(enabled)
    tmp = _const.SETTINGS_FILE.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(data, indent=2))
    os.replace(str(tmp), str(_const.SETTINGS_FILE))


def _load_bool_setting(key: str, default: bool = True) -> bool:
    if not _const.SETTINGS_FILE.exists():
        return default
    try:
        data = json.loads(_const.SETTINGS_FILE.read_text())
        v = data.get(key)
        return v if isinstance(v, bool) else default
    except Exception:
        return default


def _get_intro_shown() -> bool:
    if not _const.SETTINGS_FILE.exists():
        return False
    try:
        data = json.loads(_const.SETTINGS_FILE.read_text())
        return bool(data.get("update_check_intro_shown"))
    except Exception:
        return False


def _mark_intro_shown() -> None:
    _const.SETTINGS_FILE.parent.mkdir(parents=True, exist_ok=True)
    data = {}
    if _const.SETTINGS_FILE.exists():
        try:
            data = json.loads(_const.SETTINGS_FILE.read_text())
        except Exception:
            data = {}
    data["update_check_intro_shown"] = True
    tmp = _const.SETTINGS_FILE.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(data, indent=2))
    os.replace(str(tmp), str(_const.SETTINGS_FILE))


def _read_update_cache() -> dict:
    if not UPDATE_CACHE_FILE.exists():
        return {}
    try:
        data = json.loads(UPDATE_CACHE_FILE.read_text())
    except Exception:
        return {}
    if not isinstance(data, dict):
        return {}
    if data.get("schema_version") != 1:
        return {}
    v = _sanitize_version(data.get("latest_version"))
    if v is None:
        data.pop("latest_version", None)
    else:
        data["latest_version"] = v
    return data


def _write_update_cache(latest_version: str | None) -> None:
    UPDATE_CACHE_FILE.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "schema_version": 1,
        "last_check": int(time.time()),
    }
    v = _sanitize_version(latest_version)
    if v is not None:
        payload["latest_version"] = v
    tmp = UPDATE_CACHE_FILE.with_suffix(".json.tmp")
    try:
        tmp.write_text(json.dumps(payload))
        os.replace(str(tmp), str(UPDATE_CACHE_FILE))
        try:
            os.chmod(str(UPDATE_CACHE_FILE), 0o600)
        except OSError:
            pass
    except Exception:
        pass


def _parse_version(v: str) -> tuple:
    try:
        core = v.split("+", 1)[0].split("-", 1)[0]
        parts: list[int] = []
        for p in core.split("."):
            digits = ""
            for ch in p:
                if ch.isdigit():
                    digits += ch
                else:
                    break
            if digits:
                parts.append(int(digits))
        return tuple(parts)
    except Exception:
        return ()


def _is_newer(latest: str, current: str) -> bool:
    a = _parse_version(latest)
    b = _parse_version(current)
    if not a or not b:
        return False
    return a > b


def _fetch_latest_version() -> None:
    try:
        import urllib.error
        import urllib.request

        class _CappedRedirect(urllib.request.HTTPRedirectHandler):
            max_redirections = 3

        ua = f"altergo/{__version__} Python/{sys.version_info.major}.{sys.version_info.minor}"
        req = urllib.request.Request(UPDATE_PYPI_URL, headers={"User-Agent": ua})
        opener = urllib.request.build_opener(_CappedRedirect())
        with opener.open(req, timeout=UPDATE_FETCH_TIMEOUT) as resp:
            raw = resp.read(UPDATE_FETCH_MAX_BYTES + 1)
            if len(raw) > UPDATE_FETCH_MAX_BYTES:
                _write_update_cache(None)
                return
            data = json.loads(raw.decode("utf-8", errors="replace"))
        info = data.get("info") if isinstance(data, dict) else None
        raw_v = info.get("version") if isinstance(info, dict) else None
        sanitized = _sanitize_version(raw_v)
        _write_update_cache(sanitized)
    except Exception:
        try:
            _write_update_cache(None)
        except Exception:
            pass


def maybe_refresh_update_cache() -> None:
    if not load_update_check_enabled():
        return
    cache = _read_update_cache()
    if not cache:
        _write_update_cache(None)
        return
    last = cache.get("last_check", 0)
    now = int(time.time())
    if now < last - 60:
        pass
    elif now - last < UPDATE_CACHE_TTL_SECONDS:
        return
    t = threading.Thread(target=_fetch_latest_version, daemon=True)
    t.start()


def get_cached_latest_version() -> str | None:
    cache = _read_update_cache()
    return _sanitize_version(cache.get("latest_version"))


def first_launch_notice_if_needed() -> None:
    if _get_intro_shown():
        return
    _mark_intro_shown()


def _get_home_notice_shown() -> bool:
    if not _const.SETTINGS_FILE.exists():
        return False
    try:
        data = json.loads(_const.SETTINGS_FILE.read_text())
        return bool(data.get("home_notice_shown"))
    except Exception:
        return False


def _mark_home_notice_shown() -> None:
    _const.SETTINGS_FILE.parent.mkdir(parents=True, exist_ok=True)
    data = {}
    if _const.SETTINGS_FILE.exists():
        try:
            data = json.loads(_const.SETTINGS_FILE.read_text())
        except Exception:
            data = {}
    data["home_notice_shown"] = True
    tmp = _const.SETTINGS_FILE.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(data, indent=2))
    os.replace(str(tmp), str(_const.SETTINGS_FILE))
