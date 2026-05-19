"""altergo package — re-exports for backward compat and test monkeypatching."""

import sys
import types

from altergo._version import __version__  # noqa: F401

# Accounts
from altergo.accounts import (  # noqa: F401
    _account_for_provider,
    _ensure_symlinked_dir,
    _native_supports_provider,
    configure_account,
    do_add_provider,
    do_default_provider,
    do_delete_account,
    do_remove_provider,
    do_rename,
    do_star,
    do_teardown,
    get_active_account,
    list_accounts,
    resolve_account,
    set_active_account,
    validate_account_name,
)

# CLI entry point
from altergo.cli import main  # noqa: F401

# Constants
from altergo.constants import (  # noqa: F401
    _NATIVE_ACCOUNT,
    _RESERVED_NAMES,
    ACCOUNTS_DIR,
    CATALOG,
    LAST_SESSION_FILE,
    MAIN_CLAUDE,
    MAIN_HOME,
    PROVIDERS,
    SETTINGS_FILE,
    STARRED_FILE,
    SYMLINK_DIRS,
    SYMLINK_FILES,
)

# Persistence
from altergo.persistence import (  # noqa: F401
    UPDATE_CACHE_FILE,
    _is_newer,
    _load_bool_setting,
    _parse_version,
    _read_update_cache,
    _sanitize_version,
    _write_update_cache,
    load_account_meta,
    load_animation_pack,
    load_native_default_provider,
    load_persisted_banner_font,
    load_persisted_theme,
    load_random_theme_settings,
    load_settings,
    load_update_check_enabled,
    maybe_rotate_random_theme,
    save_account_meta,
    save_native_default_provider,
    save_persisted_theme,
    save_update_check_enabled,
)

# Runner
from altergo.runner import (  # noqa: F401
    _KNOWN_COMMANDS,
    _build_alt_env,
    _build_tmux_cmd,
    _extract_yolo_resume,
    _find_claude,
    _looks_like_account,
    _looks_like_session_id,
    _sweep_existing_accounts,
    _tmux_available,
    _tmux_session_name,
    _translate_yolo_flags,
    launch_claude,
    launch_command,
    launch_shell,
)

# Sessions
from altergo.sessions import (  # noqa: F401
    decode_project_path,
    format_project_name,
    get_sessions,
    relative_time,
)

# Theme
from altergo.theme import (  # noqa: F401
    _DEFAULT_THEME,
    THEMES,
    C,
    _c,
    get_current_theme,
    set_current_theme,
)

# TUI
from altergo.tui.common import _apply_resume_view, _session_matches  # noqa: F401
from altergo.tui.config_tui import (  # noqa: F401
    _prompt_config_menu,
    _prompt_new_account_name_tui,
    _prompt_provider_picker,
    _run_config_picker,
)
from altergo.tui.launcher import (  # noqa: F401
    _first_run_onboarding,
    _prompt_yolo_account_picker,
    build_launcher_menu,
    interactive_launcher,
)
from altergo.tui.picker import interactive_picker  # noqa: F401
from altergo.tui.search import interactive_search  # noqa: F401
from altergo.tui.settings_tui import interactive_settings  # noqa: F401

# UI
from altergo.ui import (  # noqa: F401
    _status_wrap,
    show_banner,
    show_help,
)

# ---------------------------------------------------------------------------
# Module __setattr__ hook — propagates constant patches to submodules so that
# monkeypatch.setattr(altergo, "ACCOUNTS_DIR", x) works in tests.
# ---------------------------------------------------------------------------

_PROPAGATE_TO_CONST = frozenset(
    {
        "ACCOUNTS_DIR",
        "MAIN_HOME",
        "MAIN_CLAUDE",
        "SETTINGS_FILE",
        "STARRED_FILE",
        "LAST_SESSION_FILE",
    }
)


class _AltergoModule(types.ModuleType):
    def __setattr__(self, name: str, value) -> None:
        super().__setattr__(name, value)
        if name in _PROPAGATE_TO_CONST:
            import altergo.constants as _c

            object.__setattr__(_c, name, value)
            # Also propagate to any submodule that bound the constant at import
            # time via a plain `from altergo.constants import X` statement.
            import altergo.cli as _cli
            import altergo.persistence as _pers

            for _mod in (_cli, _pers):
                if hasattr(_mod, name):
                    object.__setattr__(_mod, name, value)


sys.modules[__name__].__class__ = _AltergoModule
