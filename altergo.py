#!/usr/bin/env python3
"""Altergo — multi-account session manager for Claude Code. Run 'altergo --help' for usage."""

__version__ = "0.10.0"

import curses
import json
import os
import pwd
import re
import shutil
import subprocess
import sys
from datetime import datetime
from pathlib import Path

# --- Terminal helpers ---


def _c(code, text):
    """Wrap text in ANSI color if stdout is a TTY."""
    if not sys.stdout.isatty():
        return text
    return f"\033[{code}m{text}\033[0m"


def _link(url, text):
    """OSC 8 terminal hyperlink — clickable in supported terminals."""
    if not sys.stdout.isatty():
        return text
    return f"\033]8;;{url}\033\\{text}\033]8;;\033\\"


# Color tokens — standardized palette used across help, picker, and launcher
_C_COMMAND = "38;5;39"       # command text (blue)
_C_ARG     = "38;5;87"       # <placeholder> args (electric cyan)
_C_HEADER  = "1;38;5;39"     # section headers (bold blue)
_C_VERSION = "2;38;5;244"    # version / dim text
_C_DIM     = "2"             # secondary descriptions
_C_BRAND   = "38;5;105"      # pixelabs wordmark (indigo)
_C_SUCCESS = "38;5;76"       # checkmarks / success
_C_WARN    = "38;5;220"      # warnings


def show_banner():
    """Print the altergo ASCII banner with gradient. TTY-only."""
    if not sys.stdout.isatty():
        print(f"  altergo {__version__}  —  Switch Claude identities. Keep your context.")
        return
    try:
        from rich_pyfiglet import RichFiglet
        from rich.console import Console
        console = Console()
        figlet = RichFiglet("altergo", font="smslant", colors=["#00d7ff", "#005fd7"], horizontal=True)
        console.print(figlet)
    except Exception:
        print(f"  altergo {__version__}  —  Switch Claude identities. Keep your context.")


def show_help():
    """Print --help output with color and OSC 8 hyperlinks when on a TTY."""

    def h(t):
        return _c(_C_HEADER, t)   # bold blue — section headers

    def kw(t):
        return _c(_C_COMMAND, t)  # blue — commands / keys

    def arg(t):
        return _c(_C_ARG, t)      # electric cyan — <placeholders>

    def dim(t):
        return _c(_C_DIM, t)      # dim — secondary text

    def sep():
        return _c(_C_DIM, "  " + "─" * 58)

    pixelabs = _link("https://pixelabs.net", _c(_C_BRAND, "pixelabs.net"))
    claude_url = _link("https://claude.ai/code", "Claude Code")

    show_banner()
    print(f"  {dim('Because one personality was not causing enough bugs.')}")
    print(f"  A session manager for {claude_url}.  A {pixelabs} project.")

    lines = [
        "",
        sep(),
        h("  Quick Start"),
        f"  {kw('altergo')}                                {dim('Open launcher or launch active account')}",
        f"  {kw('altergo')} {arg('<name>')}                        {dim('Launch a specific account directly')}",
        f"  {kw('altergo --setup')}                       {dim('Create your first account')}",
        f"  {kw('altergo --use')} {arg('<name>')}                  {dim('Set which account bare altergo launches')}",
        "",
        sep(),
        h("  Account Management"),
        f"  {kw('altergo --setup --name')} {arg('<name>')}         {dim('Create or reconfigure an account')}",
        f"  {kw('altergo --setup --provider')} {arg('<p>[,<p>]')}  {dim('Specify providers: claude, gemini, codex, copilot')}",
        f"  {kw('altergo --use')} {arg('<name>')}                  {dim('Set active account for bare altergo')}",
        f"  {kw('altergo --teardown --name')} {arg('<name>')}      {dim('Remove symlinks for an account')}",
        f"  {kw('altergo --settings')}                    {dim('Configure shared credentials (TUI)')}",
        f"  {kw('altergo --launch')}                      {dim('Open provider/account launcher (TUI)')}",
        "",
        sep(),
        h("  Session Management"),
        f"  {kw('altergo --resume')}                      {dim('Pick a session interactively')}",
        f"  {kw('altergo --resume')} {arg('<id>')}                {dim('Resume a specific session by ID')}",
        f"  {kw('altergo --list')}                        {dim('List recent sessions')}",
        "",
        sep(),
        h("  Advanced"),
        f"  {kw('altergo')} {arg('<name>')} {kw('shell')}                {dim('Shell inside account HOME')}",
        f"  {kw('altergo')} {arg('<name>')} {kw('--')} {arg('<cmd> [args]')}    {dim('Run command in account context')}",
        f"  {kw('altergo --teardown')}                    {dim('Remove symlinks (active account)')}",
        f"  {kw('altergo --version')}                     {dim('Show version')}",
        f"  {kw('altergo -h, --help')}                    {dim('Show this help')}",
        "",
        sep(),
        h("  Examples"),
        f"  {kw('altergo')}                                {dim('Open launcher — pick account interactively')}",
        f"  {kw('altergo work')}                          {dim('Direct launch, work account')}",
        f"  {kw('altergo --use work')}                    {dim('Set work as active for bare altergo')}",
        f"  {kw('altergo --setup --name personal')}       {dim('Create personal account')}",
        f"  {kw('altergo --setup --provider claude,codex')}  {dim('Setup with multiple providers')}",
        f"  {kw('altergo work -- gh auth login')}         {dim('Authenticate gh in work context')}",
        f"  {kw('altergo work shell')}                    {dim('Enter work-account shell')}",
        f"  {kw('altergo --resume')}                      {dim('Open session picker')}",
        f"  {kw('altergo --dangerously-skip-permissions')}  {dim('Pass any claude flag through')}",
        "",
        sep(),
        h("  Navigation  (launcher + session picker)"),
        f"  {kw('↑↓/jk')}  {dim('Move')}          {kw('←→/hl')}  {dim('Account (launcher)')}",
        f"  {kw('Enter')}   {dim('Launch')}         {kw('s')}       {dim('Shell mode (launcher)')}",
        f"  {kw('d')}       {dim('Set active (launcher)')}  {kw('p/Tab')}  {dim('Preview (session picker)')}",
        f"  {kw('PgUp/PgDn')}  {dim('Page scroll')}  {kw('g/G')}   {dim('Top/bottom (session picker)')}",
        f"  {kw('q/Esc')}   {dim('Quit')}",
        "",
        dim("  altergo is an independent open-source project by pixelabs · not affiliated with Anthropic PBC"),
        dim("  Claude and Claude Code are trademarks of Anthropic PBC"),
        "",
    ]
    print("\n".join(lines))


# --- Config ---

# Resolve the real home even if HOME is overridden (e.g., running as altergo)
_pw_home = Path(pwd.getpwuid(os.getuid()).pw_dir)
if not _pw_home.exists():
    _pw_home = Path(os.environ["HOME"])

MAIN_HOME = _pw_home
MAIN_CLAUDE = MAIN_HOME / ".claude"
ACCOUNTS_DIR = MAIN_HOME / ".altergo" / "accounts"

# Reserved account names — blocked at --setup --name time
_RESERVED_NAMES = frozenset(
    [
        "main",
        "list",
        "new",
        "rm",
        "shell",
        "setup",
        "teardown",
        "help",
        "version",
        "legacy",
        "backup",
        "migrate",
    ]
)

# Settings file — global (shared across all accounts)
SETTINGS_FILE = MAIN_HOME / ".altergo" / ".altergo.json"


# --- Account helpers ---


def resolve_account(name: str) -> tuple:
    """Return (account_home, account_claude) for the given account name."""
    account_home = ACCOUNTS_DIR / name
    account_claude = account_home / ".claude"
    return account_home, account_claude


def list_accounts() -> list:
    """Return sorted list of account names that exist on disk."""
    if not ACCOUNTS_DIR.exists():
        return []
    return sorted(p.name for p in ACCOUNTS_DIR.iterdir() if p.is_dir() and not p.name.startswith("."))


def validate_account_name(name: str) -> None:
    """Raise SystemExit if name is invalid (bad chars, reserved word, leading dot)."""
    if not re.match(r"^[a-zA-Z0-9][a-zA-Z0-9_-]*$", name) or len(name) > 64:
        print(
            f"altergo: invalid account name '{name}'. "
            "Use letters, digits, - or _ only; must not start with a digit or special char.",
            file=sys.stderr,
        )
        sys.exit(1)
    if name in _RESERVED_NAMES:
        print(f"altergo: '{name}' is a reserved name. Choose a different account name.", file=sys.stderr)
        sys.exit(1)


# --- Migration ---


def detect_legacy() -> bool:
    """Return True if the old ~/.altergo/.claude/ layout exists and new layout does not."""
    old_claude = MAIN_HOME / ".altergo" / ".claude"
    return old_claude.exists() and not ACCOUNTS_DIR.exists()


def migrate_legacy() -> None:
    """Migrate old single-account layout to N-account layout. Runs at most once."""
    if not detect_legacy():
        return
    old_root = MAIN_HOME / ".altergo"
    # Step 1: take a backup BEFORE any rename so it is never self-referential.
    # The backup lives outside the altergo tree at ~/.altergo-legacy-backup/.
    backup_path = MAIN_HOME / ".altergo-legacy-backup"
    if backup_path.exists():
        print("altergo: backup already exists at ~/.altergo-legacy-backup — skipping backup step")
    else:
        shutil.copytree(str(old_root), str(backup_path), symlinks=True)
    tmp_path = Path(f"/tmp/altergo-migrate-{os.getpid()}")
    # Step 2: rename ~/.altergo → /tmp/altergo-migrate-{pid}
    old_root.rename(tmp_path)
    # Step 3: mkdir -p ~/.altergo/accounts/
    ACCOUNTS_DIR.mkdir(parents=True, exist_ok=True)
    # Step 4: rename /tmp/... → ~/.altergo/accounts/default/
    default_home = ACCOUNTS_DIR / "default"
    tmp_path.rename(default_home)
    # Step 5: write audit trail so users can verify what happened
    migrated_marker = default_home / "MIGRATED.txt"
    migrated_marker.write_text(
        f"Migrated by altergo v{__version__} on {datetime.now().isoformat(timespec='seconds')}\n"
        f"Old layout: ~/.altergo/\n"
        f"New layout: ~/.altergo/accounts/default/\n"
        f"Backup:     ~/.altergo-legacy-backup/\n"
        f"Rollback:   remove ~/.altergo/accounts/ and rename ~/.altergo-legacy-backup back to ~/.altergo\n"
        f"See:        https://altergo.pixelabs.net/docs/migration-0.5\n"
    )
    # Step 6: print a visible block — this is a one-time destructive rename, silence is wrong
    print("altergo: layout migrated for v0.5.0 N-account support")
    print("  ~/.altergo/  →  ~/.altergo/accounts/default/")
    print("  Backup preserved at ~/.altergo-legacy-backup/")
    print("  See https://altergo.pixelabs.net/docs/migration-0.5 for details")


# --- Symlink catalogs ---

# Directories to symlink (shared between main and alt)
SYMLINK_DIRS = [
    "projects",
    "tasks",
    "session-env",
    "file-history",
    "shell-snapshots",
    "agents",
    "plans",
    "cache",
]

# Files to symlink
SYMLINK_FILES = [
    "settings.json",
    "CLAUDE.md",
    "keybindings.json",
]

# Provider definitions — drives per-provider setup/teardown/launch logic.
# SYMLINK_DIRS and SYMLINK_FILES above are kept for backwards compat (teardown
# of legacy accounts that predate account.json).
PROVIDERS = {
    "claude": {
        "display_name": "Claude Code",
        "dot_dir": ".claude",
        "binary": "claude",
        "credentials_file": ".credentials.json",
        "symlink_dirs": [
            "projects", "tasks", "session-env", "file-history",
            "shell-snapshots", "agents", "plans", "cache",
        ],
        "symlink_files": ["settings.json", "CLAUDE.md", "keybindings.json"],
    },
    "gemini": {
        "display_name": "Gemini CLI",
        "dot_dir": ".gemini",
        "binary": "gemini",
        "credentials_file": "oauth_creds.json",
        "symlink_dirs": ["tmp", "commands"],
        "symlink_files": ["settings.json", "GEMINI.md"],
    },
    "codex": {
        "display_name": "Codex CLI",
        "dot_dir": ".codex",
        "binary": "codex",
        "credentials_file": "auth.json",
        "symlink_dirs": ["sessions", "rules"],
        "symlink_files": ["config.toml", "AGENTS.md", "AGENTS.override.md"],
    },
    "copilot": {
        "display_name": "GitHub Copilot",
        "dot_dir": ".copilot",
        "binary": "copilot",
        "credentials_file": "config.json",
        "symlink_dirs": ["session-state", "agents", "skills", "hooks"],
        "symlink_files": ["mcp-config.json", "lsp-config.json"],
    },
}

# Catalog of CLI tools whose credentials can be shared between main and alt.
# Each entry maps to one or more paths relative to $HOME that are symlinked.
# default_on=True  → shared by default (user must explicitly opt out)
# default_on=False → isolated by default (user must explicitly opt in)
# warning          → shown in the settings TUI when this entry is highlighted
CATALOG = [
    # Cloud Providers
    {
        "id": "aws",
        "name": "AWS CLI",
        "category": "Cloud Providers",
        "paths": [".aws"],
        "default_on": True,
    },
    {
        "id": "gcloud",
        "name": "Google Cloud",
        "category": "Cloud Providers",
        "paths": [".config/gcloud"],
        "default_on": True,
    },
    {
        "id": "azure",
        "name": "Azure CLI",
        "category": "Cloud Providers",
        "paths": [".azure", ".config/azure"],
        "default_on": True,
    },
    # Containers & Orchestration
    {
        "id": "docker",
        "name": "Docker",
        "category": "Containers",
        "paths": [".docker"],
        "default_on": True,
    },
    {
        "id": "kube",
        "name": "Kubernetes",
        "category": "Containers",
        "paths": [".kube"],
        "default_on": True,
    },
    # Infrastructure
    {
        "id": "terraform",
        "name": "Terraform",
        "category": "Infrastructure",
        "paths": [".terraform.d"],
        "default_on": True,
    },
    # VCS & Dev Tools
    {
        "id": "gh",
        "name": "GitHub CLI",
        "category": "VCS & Dev Tools",
        "paths": [".config/gh"],
        "default_on": True,
    },
    {
        "id": "glab",
        "name": "GitLab CLI",
        "category": "VCS & Dev Tools",
        "paths": [".config/glab"],
        "default_on": False,
    },
    # Package Managers
    {
        "id": "npm",
        "name": "npm",
        "category": "Package Managers",
        "paths": [".npmrc"],
        "default_on": False,
    },
    # Identity — off by default, high security/identity impact
    {
        "id": "ssh",
        "name": "SSH keys",
        "category": "Identity",
        "paths": [".ssh"],
        "default_on": False,
        "warning": "Shares SSH keys & known_hosts. Keep off if you use per-identity SSH keys.",
    },
    {
        "id": "gitconfig",
        "name": "Git identity",
        "category": "Identity",
        "paths": [".gitconfig"],
        "default_on": False,
        "warning": "Shares git user.name/email. Keep off for separate commit identity per account.",
    },
    {
        "id": "gnupg",
        "name": "GPG keys",
        "category": "Identity",
        "paths": [".gnupg"],
        "default_on": False,
        "warning": "Shares GPG keyring. Keep off if you use per-identity signing keys.",
    },
]

# (SETTINGS_FILE is defined in the Config section above, shared across all accounts)

# --- Settings helpers ---


def load_account_meta(account_home: Path) -> dict:
    """Load account metadata. Returns dict with 'providers' list.

    Backwards compat: if account.json missing but .claude/ exists, returns
    {"version": 1, "providers": ["claude"]} without writing anything.
    If neither exists, returns None.
    """
    meta_file = account_home / "account.json"
    if meta_file.exists():
        try:
            return json.loads(meta_file.read_text())
        except Exception:
            return {"version": 1, "providers": ["claude"]}
    # Legacy account: .claude dir exists but no account.json
    if (account_home / ".claude").exists():
        return {"version": 1, "providers": ["claude"]}
    return None


def save_account_meta(account_home: Path, meta: dict) -> None:
    """Atomically write account.json."""
    account_home.mkdir(parents=True, exist_ok=True)
    meta_file = account_home / "account.json"
    tmp = meta_file.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(meta, indent=2))
    os.replace(str(tmp), str(meta_file))


def load_settings():
    """Load user settings overlay. Returns {id: bool} dict of non-default values."""
    if not SETTINGS_FILE.exists():
        return {}
    try:
        data = json.loads(SETTINGS_FILE.read_text())
        shared = data.get("shared", {})
        catalog_ids = {e["id"] for e in CATALOG}
        return {k: v for k, v in shared.items() if k in catalog_ids and isinstance(v, bool)}
    except Exception:
        return {}


def save_settings(overrides):
    """Atomically write settings overlay to SETTINGS_FILE. Preserves other top-level keys."""
    SETTINGS_FILE.parent.mkdir(parents=True, exist_ok=True)
    data = {}
    if SETTINGS_FILE.exists():
        try:
            data = json.loads(SETTINGS_FILE.read_text())
        except Exception:
            data = {}
    data["version"] = 1
    data["shared"] = overrides
    tmp = SETTINGS_FILE.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(data, indent=2))
    os.replace(str(tmp), str(SETTINGS_FILE))


def get_active_account() -> str | None:
    """Return the persisted active account name, or None if not set / no longer valid."""
    if not SETTINGS_FILE.exists():
        return None
    try:
        data = json.loads(SETTINGS_FILE.read_text())
        name = data.get("active_account")
        if name and isinstance(name, str) and (ACCOUNTS_DIR / name).is_dir():
            return name
        return None
    except Exception:
        return None


def set_active_account(name: str) -> None:
    """Persist active_account to SETTINGS_FILE without clobbering other keys."""
    SETTINGS_FILE.parent.mkdir(parents=True, exist_ok=True)
    data = {}
    if SETTINGS_FILE.exists():
        try:
            data = json.loads(SETTINGS_FILE.read_text())
        except Exception:
            data = {}
    data["active_account"] = name
    tmp = SETTINGS_FILE.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(data, indent=2))
    os.replace(str(tmp), str(SETTINGS_FILE))


def is_enabled(entry, overrides):
    """Return whether a catalog entry is enabled given the user's overrides."""
    return overrides.get(entry["id"], entry["default_on"])


def _ensure_nested_parent(rel, account_home):
    """For paths like .config/gh, ensure account_home/.config is a real directory.

    If it's currently a wholesale symlink to MAIN_HOME/.config (from an older
    setup), migrates it transparently: unlinks the symlink and creates a real
    directory, then individual tool symlinks will be created inside it.
    """
    p = Path(rel)
    if len(p.parts) < 2:
        return
    parent_name = p.parts[0]
    acct_parent = account_home / parent_name
    main_parent = MAIN_HOME / parent_name
    if acct_parent.is_symlink():
        if acct_parent.resolve() == main_parent.resolve():
            acct_parent.unlink()
            acct_parent.mkdir(parents=True, exist_ok=True)
            print(f"  {_c(33, '↻')} Migrated ~/{parent_name}/ from wholesale symlink to managed dir")
    elif not acct_parent.exists():
        acct_parent.mkdir(parents=True, exist_ok=True)


def _apply_entry(entry, overrides, account_home):
    """Create or remove symlinks for one catalog entry based on current settings."""
    enabled = is_enabled(entry, overrides)
    for rel in entry["paths"]:
        src = MAIN_HOME / Path(rel)
        dst = account_home / Path(rel)
        if enabled:
            if not src.exists():
                print(f"  {_c(2, 'skip')} ~/{rel} (not present in main home)")
                continue
            _ensure_nested_parent(rel, account_home)
            if dst.is_symlink():
                if dst.resolve() == src.resolve():
                    print(f"  {_c(32, '✓')} ~/{rel} already shared")
                else:
                    print(f"  {_c(33, '⚠')} ~/{rel} symlinked elsewhere — skipping")
                continue
            if dst.exists():
                print(f"  {_c(33, '⚠')} ~/{rel} has local data — remove it first to share")
                continue
            dst.symlink_to(src)
            print(f"  {_c(32, '✓')} Sharing ~/{rel}")
        else:
            if dst.is_symlink() and dst.resolve() == src.resolve():
                dst.unlink()
                print(f"  {_c(33, '✓')} Unshared ~/{rel}")


# --- Setup / Teardown ---


def _ensure_symlinked_dir(name: str, src: Path, dst: Path, account_claude: Path) -> bool:
    """Ensure dst is a symlink pointing to src, auto-migrating real dirs if needed.

    Returns True if any change was made (symlink created or content moved).

    Cases:
      (a) dst is already a symlink to src         -> no-op, return False
      (b) dst does not exist                      -> create src + symlink, return True
      (c) dst is a real empty dir                 -> rmdir + symlink, return True
      (d) dst is real non-empty, src empty/absent -> move content to src, symlink, return True
      (e) both have content                       -> merge; conflict items go to quarantine dir
    """
    # (a) Already correct symlink
    if dst.is_symlink():
        if dst.resolve() == src.resolve():
            return False
        # Symlinked elsewhere — leave alone (don't clobber user's intentional link)
        return False

    # (b) dst does not exist
    if not dst.exists():
        src.mkdir(parents=True, exist_ok=True)
        dst.parent.mkdir(parents=True, exist_ok=True)
        dst.symlink_to(src)
        return True

    # dst is a real directory (or file) at this point
    if not dst.is_dir():
        # It's a real file named the same as a dir entry — skip it safely
        return False

    dst_entries = list(dst.iterdir())

    # (c) Real empty dir
    if not dst_entries:
        dst.rmdir()
        src.mkdir(parents=True, exist_ok=True)
        dst.symlink_to(src)
        print(f"  Converted empty {name}/ to symlink")
        return True

    # dst is non-empty
    src_exists_and_nonempty = src.exists() and any(True for _ in src.iterdir())

    if not src_exists_and_nonempty:
        # (d) src absent or empty — move dst content wholesale
        src.parent.mkdir(parents=True, exist_ok=True)
        if not src.exists():
            shutil.move(str(dst), str(src))
        else:
            # src exists but is empty: move each entry in
            for entry in list(dst.iterdir()):
                shutil.move(str(entry), str(src / entry.name))
            dst.rmdir()
        dst.symlink_to(src)
        print(f"  Promoted {name}/ to shared store")
        return True

    # (e) Both src and dst have content — merge with conflict quarantine
    quarantine_base = account_claude / f"{name}.altergo-conflict"
    for entry in list(dst.iterdir()):
        target = src / entry.name
        if not target.exists():
            shutil.move(str(entry), str(target))
        else:
            # Conflict: move to quarantine.
            # Ensure the quarantine base dir exists but do NOT pre-create the
            # entry's subdirectory — shutil.move needs the destination path to
            # not already exist as a directory (otherwise it moves inside it).
            quarantine_base.mkdir(parents=True, exist_ok=True)
            shutil.move(str(entry), str(quarantine_base / entry.name))
            print(f"  warning: conflict: {name}/{entry.name} preserved in {name}.altergo-conflict/")

    # Check if dst is now empty after moves
    remaining = list(dst.iterdir())
    if not remaining:
        dst.rmdir()
        dst.symlink_to(src)
        print(f"  Merged {name}/ into shared store")
        return True
    else:
        print(f"  warning: {name}/ has unresolved conflicts; not symlinked")
        return False


def do_setup(account: str = "default", providers: list[str] | None = None):
    if providers is None:
        providers = ["claude"]
    account_home, account_claude = resolve_account(account)
    header = f"altergo v{__version__} · " + _link("https://pixelabs.net", "pixelabs.net")
    print(_c(2, header))
    print(_c(1, _c(36, f"=== Altergo — Setup ({account}) ===")))
    print()

    # Load existing metadata for created timestamp preservation
    meta = load_account_meta(account_home)

    # 1. Create account home
    if not account_home.exists():
        account_home.mkdir(parents=True)
        print(f"  {_c(32, '✓')} Created account home: {account_home}")
    else:
        print(f"  {_c(32, '✓')} Account home exists: {account_home}")

    # 2. Wire each provider
    for pid in providers:
        prov = PROVIDERS[pid]
        main_dot_dir = MAIN_HOME / prov["dot_dir"]
        acct_dot_dir = account_home / prov["dot_dir"]

        print()
        print(_c(1, _c(36, f"=== Provider: {prov['display_name']} ===")))

        # Ensure provider dot-dir exists
        acct_dot_dir.mkdir(parents=True, exist_ok=True)

        # Symlink directories
        for name in prov["symlink_dirs"]:
            src = main_dot_dir / name
            dst = acct_dot_dir / name

            if dst.is_symlink():
                target = dst.resolve()
                if target == src.resolve():
                    print(f"  {_c(32, '✓')} {name}/ already symlinked")
                else:
                    print(f"  {_c(33, '⚠')} {name}/ symlinked to {target} (expected {src})")
                continue

            # _ensure_symlinked_dir handles all real-dir migration cases (empty
            # real dir, non-empty real dir, merge conflicts).  It prints its own
            # richer messages for promotion/merge/conflict cases.  For the normal
            # fresh-install path (dst absent) it silently creates the symlink and
            # returns True, so we print the standard checkmark here.
            was_absent = not dst.exists()
            _ensure_symlinked_dir(name, src, dst, acct_dot_dir)
            if was_absent and dst.is_symlink():
                print(f"  {_c(32, '✓')} Symlinked {name}/")

        # Symlink files
        for name in prov["symlink_files"]:
            src = main_dot_dir / name
            dst = acct_dot_dir / name

            if not src.exists():
                continue

            if dst.is_symlink():
                print(f"  {_c(32, '✓')} {name} already symlinked")
                continue

            if dst.exists():
                dst.unlink()

            dst.symlink_to(src)
            print(f"  {_c(32, '✓')} Symlinked {name}")

        # Check credentials for this provider
        creds = acct_dot_dir / prov["credentials_file"]
        print()
        if creds.exists():
            print(f"  {_c(32, '✓')} {prov['display_name']} credentials found")
        else:
            print(f"  {_c(33, '⚠')} No {prov['display_name']} credentials found.")
            cmd = f"altergo {account}" if account != "default" else "altergo"
            print(f"     Run '{cmd}' to authenticate.\n")

    # 3. Apply catalog entries (shared CLI tool credentials) at account_home level
    overrides = load_settings()
    for entry in CATALOG:
        _apply_entry(entry, overrides, account_home)

    # 4. Save account metadata
    save_account_meta(account_home, {
        "version": 1,
        "providers": providers,
        "created": (meta.get("created") if meta else None) or datetime.now().isoformat(timespec="seconds"),
    })

    launch_cmd = f"altergo {account}" if account != "default" else "altergo"
    print()
    print(_c(32, "Setup complete!"))
    print(f"  Run {_c(1, launch_cmd)} to start a session  ·  {_c(1, 'altergo --resume')} to pick one")
    print()
    print(_c(2, "  Isolates credentials per provider. Shares AWS, GCP, Docker, and kubectl by default."))
    print(_c(2, f"  Change sharing settings: {_c(0, 'altergo --settings')}"))


def do_teardown(account: str = "default"):
    account_home, account_claude = resolve_account(account)
    header = f"altergo v{__version__} · " + _link("https://pixelabs.net", "pixelabs.net")
    print(_c(2, header))
    print(_c(1, _c(36, f"=== Altergo — Teardown ({account}) ===")))
    print()

    meta = load_account_meta(account_home)

    if meta is not None and "providers" in meta:
        # Modern account with account.json — tear down per-provider symlinks
        for pid in meta["providers"]:
            prov = PROVIDERS.get(pid)
            if prov is None:
                continue
            acct_dot_dir = account_home / prov["dot_dir"]

            for name in prov["symlink_dirs"]:
                dst = acct_dot_dir / name
                if dst.is_symlink():
                    dst.unlink()
                    print(f"  {_c(33, '✓')} Removed symlink: {prov['dot_dir']}/{name}/")

            for name in prov["symlink_files"]:
                dst = acct_dot_dir / name
                if dst.is_symlink():
                    dst.unlink()
                    print(f"  {_c(33, '✓')} Removed symlink: {prov['dot_dir']}/{name}")
    else:
        # Legacy account (no account.json) — fall back to SYMLINK_DIRS + SYMLINK_FILES
        for name in SYMLINK_DIRS:
            dst = account_claude / name
            if dst.is_symlink():
                dst.unlink()
                print(f"  {_c(33, '✓')} Removed symlink: {name}/")

        for name in SYMLINK_FILES:
            dst = account_claude / name
            if dst.is_symlink():
                dst.unlink()
                print(f"  {_c(33, '✓')} Removed symlink: {name}")

    # Catalog entries (shared CLI tool credentials) — always at account_home level
    for entry in CATALOG:
        for rel in entry["paths"]:
            dst = account_home / Path(rel)
            src = MAIN_HOME / Path(rel)
            if dst.is_symlink() and dst.resolve() == src.resolve():
                dst.unlink()
                print(f"  {_c(33, '✓')} Removed symlink: ~/{rel}")

    print()
    print(_c(32, "Teardown complete.") + " Account home and credentials left intact.")


# --- Session Discovery ---


def get_sessions():
    """Find all sessions across all projects, return sorted by modification time.

    Cheap pass: stat + first-user-message extraction only. Full preview content
    is loaded on demand by ``load_session_preview`` when the user opens the
    preview pane.
    """
    sessions = []
    projects_dir = MAIN_CLAUDE / "projects"

    if not projects_dir.exists():
        return sessions

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

            sessions.append(
                {
                    "id": session_id,
                    "project": project_name,
                    "cwd": cwd,
                    "modified": mod_dt,
                    "size_mb": size_mb,
                    "path": f,
                    "topic": topic,
                }
            )

    sessions.sort(key=lambda s: s["modified"], reverse=True)
    return sessions


def _extract_text(content):
    """Flatten a Claude Code message ``content`` field into plain text.

    ``content`` may be a string, or a list of blocks (text, tool_use,
    tool_result, image, ...). Only ``text`` blocks contribute. Returns "".
    """
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


def load_session_preview(jsonl_path, max_messages: int = 4, max_lines: int = 400) -> dict:
    """Load opening prompt + first few message turns for the preview pane.

    Reads at most ``max_lines`` lines and returns once ``max_messages`` real
    user/assistant turns have been collected. ``truncated`` is True if the
    session has more content than was returned.
    """
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


def decode_project_path(encoded: str) -> str:
    """Decode Claude Code's project dir name back into a readable path.

    ``-Users-netz-Documents-git-altergo`` -> ``/home/user/Documents/git/altergo``.
    Best-effort: dashes inside path components are indistinguishable from
    separators in this encoding scheme, so we return the most likely form.
    """
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


# --- Interactive Menu ---


def interactive_picker(sessions):
    """Arrow-key driven session picker using curses."""
    if not sessions:
        print("No sessions found.")
        sys.exit(1)

    selected = curses.wrapper(_draw_picker, sessions)
    return selected


def _picker_attrs():
    """Initialize color pairs for the picker. Returns an attrs dict.

    Falls back to monochrome (A_BOLD/A_REVERSE/A_DIM) when colors aren't
    available so the picker degrades gracefully on dumb terminals.
    """
    has_color = False
    try:
        if curses.has_colors():
            curses.start_color()
            curses.use_default_colors()
            has_color = True
    except curses.error:
        has_color = False

    attrs = {}
    if has_color:
        # Brand: cyan + indigo. Prefer 256-color brights when available.
        cyan = 51 if curses.COLORS >= 256 else curses.COLOR_CYAN
        indigo = 105 if curses.COLORS >= 256 else curses.COLOR_BLUE
        gray = 244 if curses.COLORS >= 256 else curses.COLOR_WHITE
        white = 231 if curses.COLORS >= 256 else curses.COLOR_WHITE
        try:
            curses.init_pair(1, curses.COLOR_BLACK, cyan)  # selected row
            curses.init_pair(2, cyan, -1)  # header / accent / shine mid
            curses.init_pair(3, indigo, -1)  # project col / brand
            curses.init_pair(4, gray, -1)  # time col
            curses.init_pair(5, cyan, -1)  # preview pane border
            curses.init_pair(6, white, -1)  # shine peak
            amber = 220 if curses.COLORS >= 256 else curses.COLOR_YELLOW
            curses.init_pair(7, amber, -1)  # size warning (>10MB)
        except curses.error:
            has_color = False

    if has_color:
        attrs["selected"] = curses.color_pair(1) | curses.A_BOLD
        attrs["header"] = curses.color_pair(2) | curses.A_BOLD | curses.A_UNDERLINE
        attrs["title"] = curses.color_pair(2) | curses.A_BOLD
        attrs["project"] = curses.color_pair(3)
        attrs["time"] = curses.color_pair(4) | curses.A_DIM
        attrs["topic"] = curses.A_NORMAL
        attrs["dim"] = curses.A_DIM
        attrs["accent"] = curses.color_pair(2)
        attrs["nav_base"] = curses.A_NORMAL
        attrs["brand"] = curses.color_pair(3) | curses.A_BOLD
        attrs["shine_peak"] = curses.color_pair(6) | curses.A_BOLD
        attrs["shine_mid"] = curses.color_pair(2) | curses.A_BOLD
        attrs["size_warn"] = curses.color_pair(7) | curses.A_DIM
    else:
        attrs["selected"] = curses.A_REVERSE | curses.A_BOLD
        attrs["header"] = curses.A_BOLD | curses.A_UNDERLINE
        attrs["title"] = curses.A_BOLD
        attrs["project"] = curses.A_BOLD
        attrs["time"] = curses.A_DIM
        attrs["topic"] = curses.A_NORMAL
        attrs["dim"] = curses.A_DIM
        attrs["accent"] = curses.A_BOLD
        attrs["nav_base"] = curses.A_NORMAL
        attrs["brand"] = curses.A_BOLD
        attrs["shine_peak"] = curses.A_BOLD | curses.A_REVERSE
        attrs["shine_mid"] = curses.A_BOLD
        attrs["size_warn"] = curses.A_DIM
    return attrs


def _compute_columns(max_x: int) -> dict:
    """Responsive column widths. Topic gets the leftover space."""
    proj_w = 18 if max_x >= 100 else (14 if max_x >= 80 else 10)
    time_w = 11  # "yesterday  " / "12h ago    "
    size_w = 7   # " 1.2MB " right-aligned
    gutter = 2   # leading "▸ "
    spacing = 2  # between cols
    used = gutter + proj_w + spacing + time_w + spacing + size_w + spacing
    topic_w = max(20, max_x - used - 1)
    topic_w = min(topic_w, max(40, max_x - used - 1))
    return {"gutter": gutter, "proj": proj_w, "time": time_w, "size": size_w, "topic": topic_w}


def _truncate(text: str, width: int) -> str:
    if width <= 0:
        return ""
    if len(text) <= width:
        return text
    if width == 1:
        return "…"
    return text[: width - 1] + "…"


def _safe_addnstr(stdscr, y, x, text, n, attr=0):
    """addnstr that swallows curses.error at the bottom-right cell."""
    try:
        stdscr.addnstr(y, x, text, n, attr)
    except curses.error:
        pass


def _safe_addch(stdscr, y, x, ch, attr=0):
    """Single-char writer that swallows curses.error."""
    try:
        stdscr.addstr(y, x, ch, attr)
    except curses.error:
        pass


def _draw_animated_nav(stdscr, row, text, max_width, phase, attrs):
    """Render the footer nav line with a BBS-style shine sweep + twinkling
    separators. The word 'pixelabs' is rendered in brand indigo (bold).

    phase increments every ~80ms; shine sweeps across width then pauses,
    separator dots twinkle on a staggered per-position cycle.
    """
    if max_width <= 0:
        return
    width = min(len(text), max_width)
    if width <= 0:
        return

    # Shine sweep position (extends past width to create a pause between sweeps)
    cycle_len = width + 24
    shine_pos = phase % cycle_len

    # Locate "pixelabs" substring for brand coloring
    lower = text.lower()
    pix_start = lower.find("pixelabs")
    pix_end = pix_start + len("pixelabs") if pix_start >= 0 else -1

    for i in range(width):
        ch = text[i]
        # 1. Base attribute: brand color for "pixelabs", otherwise normal
        if pix_start <= i < pix_end:
            attr = attrs["brand"]
        else:
            attr = attrs["nav_base"]

        # 2. Shine sweep overlay (wave of bright chars sliding right)
        dist = i - shine_pos
        if -1 <= dist <= 1:
            attr = attrs["shine_peak"]
        elif -3 <= dist <= 3:
            attr = attrs["shine_mid"]
        elif -5 <= dist <= 5:
            attr = attrs["shine_mid"] | curses.A_DIM

        # 3. Twinkle effect on separator dots (independent per-position phase)
        if ch == "·":
            twinkle = (phase * 2 + i * 7) % 48
            if twinkle < 2:
                attr = attrs["shine_peak"]
            elif twinkle < 5:
                attr = attrs["shine_mid"]

        _safe_addch(stdscr, row, i, ch, attr)


def _draw_picker(stdscr, sessions):
    curses.curs_set(0)
    attrs = _picker_attrs()
    stdscr.timeout(80)  # ~12fps animation tick — getch() returns -1 on timeout

    current = 0
    scroll_offset = 0
    preview_cache = {}  # session_id -> loaded preview dict
    phase = 0

    while True:
        stdscr.erase()
        max_y, max_x = stdscr.getmaxyx()
        cols = _compute_columns(max_x)

        # Title bar
        title = f" altergo — pick a session  ·  {len(sessions)} total"
        _safe_addnstr(stdscr, 0, 0, title.ljust(max_x), max_x - 1, attrs["title"])

        # Column header row
        proj_h = "Project".ljust(cols["proj"])
        time_h = "When".ljust(cols["time"])
        size_h = "Size".rjust(cols["size"])
        topic_h = "Topic"
        col_header = f"  {proj_h}  {time_h}  {size_h}  {topic_h}"
        _safe_addnstr(stdscr, 2, 0, col_header.ljust(max_x), max_x - 1, attrs["header"])

        # Visible area: title(1) + blank(1) + col_header(2) + footer(2)
        visible_rows = max(1, max_y - 6)

        if current < scroll_offset:
            scroll_offset = current
        elif current >= scroll_offset + visible_rows:
            scroll_offset = current - visible_rows + 1

        for i in range(visible_rows):
            idx = scroll_offset + i
            if idx >= len(sessions):
                break
            s = sessions[idx]
            row = i + 3
            is_sel = idx == current

            project = _truncate(format_project_name(s["project"]), cols["proj"])
            when = _truncate(relative_time(s["modified"]), cols["time"])
            topic = s.get("topic") or ""
            topic_is_empty = not topic
            if topic_is_empty:
                topic = "(no prompt)"
            topic = _truncate(topic, cols["topic"])

            size_str = f"{s.get('size_mb', 0):.1f}MB".rjust(cols["size"])
            size_attr = attrs["size_warn"] if s.get("size_mb", 0) > 10 else attrs["time"]

            if is_sel:
                line = f"▸ {project.ljust(cols['proj'])}  {when.ljust(cols['time'])}  {size_str}  {topic}"
                _safe_addnstr(stdscr, row, 0, line.ljust(max_x), max_x - 1, attrs["selected"])
            else:
                # Render columns separately so each gets its own color
                _safe_addnstr(stdscr, row, 0, "  ", 2)
                _safe_addnstr(stdscr, row, 2, project.ljust(cols["proj"]), cols["proj"], attrs["project"])
                x = 2 + cols["proj"] + 2
                _safe_addnstr(stdscr, row, x, when.ljust(cols["time"]), cols["time"], attrs["time"])
                x += cols["time"] + 2
                _safe_addnstr(stdscr, row, x, size_str, cols["size"], size_attr)
                x += cols["size"] + 2
                topic_attr = attrs["dim"] if topic_is_empty else attrs["topic"]
                _safe_addnstr(stdscr, row, x, topic, max_x - x - 1, topic_attr)

        # Footer: session id + cwd (normal brightness, not dim)
        footer_row = max_y - 2
        if 0 <= current < len(sessions):
            s = sessions[current]
            sid = s["id"]
            cwd = s.get("cwd") or decode_project_path(s["project"])
            foot = f" {sid}  ·  {cwd}"
            _safe_addnstr(stdscr, footer_row, 0, _truncate(foot, max_x - 1), max_x - 1, attrs["topic"])
        nav = " ↑↓/jk move  ·  g/G top/bot  ·  PgUp/PgDn page  ·  p/Tab preview  ·  Enter resume  ·  q quit  ·  pixelabs"
        _draw_animated_nav(stdscr, footer_row + 1, nav, max_x - 1, phase, attrs)

        stdscr.refresh()
        key = stdscr.getch()

        # Animation tick: getch timed out (no key pressed) — advance phase and redraw
        if key == -1:
            phase += 1
            continue

        if key in (curses.KEY_UP, ord("k")):
            current = max(0, current - 1)
        elif key in (curses.KEY_DOWN, ord("j")):
            current = min(len(sessions) - 1, current + 1)
        elif key == curses.KEY_PPAGE:
            current = max(0, current - visible_rows)
        elif key == curses.KEY_NPAGE:
            current = min(len(sessions) - 1, current + visible_rows)
        elif key == ord("g"):
            current = 0
        elif key == ord("G"):
            current = len(sessions) - 1
        elif key in (curses.KEY_ENTER, 10, 13):
            return sessions[current]
        elif key in (ord("p"), ord(" "), 9):  # p, space, Tab → preview
            if 0 <= current < len(sessions):
                s = sessions[current]
                if s["id"] not in preview_cache:
                    preview_cache[s["id"]] = load_session_preview(s["path"])
                action = _draw_preview(stdscr, attrs, s, preview_cache[s["id"]])
                if action == "resume":
                    return s
                # else: just return to picker
        elif key in (ord("q"), 27):
            return None
        elif key == curses.KEY_RESIZE:
            continue


def _wrap_text(text: str, width: int):
    """Simple word-wrap that also breaks on existing newlines."""
    if width <= 0:
        return [text]
    out = []
    for raw_line in text.splitlines() or [""]:
        if not raw_line:
            out.append("")
            continue
        line = ""
        for word in raw_line.split(" "):
            if not line:
                candidate = word
            else:
                candidate = line + " " + word
            if len(candidate) <= width:
                line = candidate
            else:
                if line:
                    out.append(line)
                # Hard-break very long tokens
                while len(word) > width:
                    out.append(word[:width])
                    word = word[width:]
                line = word
        out.append(line)
    return out


def _draw_preview(stdscr, attrs, session, preview):
    """Modal preview pane. Returns 'resume' if user hit Enter, else 'back'."""
    scroll = 0
    while True:
        stdscr.erase()
        max_y, max_x = stdscr.getmaxyx()

        title = f" Preview — {format_project_name(session['project'])} "
        _safe_addnstr(stdscr, 0, 0, title.ljust(max_x), max_x - 1, attrs["title"])

        # Metadata block
        meta_lines = [
            f"Session : {session['id']}",
            f"Project : {session.get('cwd') or decode_project_path(session['project'])}",
            f"Modified: {session['modified'].strftime('%Y-%m-%d %H:%M:%S')}  ({relative_time(session['modified'])})",
            f"Size    : {session['size_mb']:.2f} MB",
        ]
        if preview.get("error"):
            meta_lines.append(f"Error   : {preview['error']}")

        # Build the body lines (metadata + messages)
        body = []
        for ml in meta_lines:
            body.append(("meta", ml))
        body.append(("blank", ""))
        body.append(("sep", "─" * max(10, max_x - 4)))
        body.append(("blank", ""))

        msgs = preview.get("messages") or []
        if not msgs:
            body.append(("dim", "(no readable messages found in this session)"))
        else:
            wrap_w = max(20, max_x - 4)
            for role, text in msgs:
                label = "You" if role == "user" else "Claude"
                role_attr = "accent" if role == "user" else "project"
                body.append((role_attr, f"▸ {label}"))
                # Cap each message preview to ~12 wrapped lines so the pane stays scrollable
                wrapped = _wrap_text(text, wrap_w)
                for line in wrapped[:12]:
                    body.append(("text", "  " + line))
                if len(wrapped) > 12:
                    body.append(("dim", f"  … ({len(wrapped) - 12} more lines)"))
                body.append(("blank", ""))
            if preview.get("truncated"):
                body.append(("dim", "… session continues beyond preview"))

        # Scrollable region: rows 2..max_y-3
        view_h = max(1, max_y - 4)
        max_scroll = max(0, len(body) - view_h)
        scroll = max(0, min(scroll, max_scroll))

        for i in range(view_h):
            bi = scroll + i
            if bi >= len(body):
                break
            kind, text = body[bi]
            row = 2 + i
            if kind == "meta":
                _safe_addnstr(stdscr, row, 2, _truncate(text, max_x - 3), max_x - 3, attrs["dim"])
            elif kind == "sep":
                _safe_addnstr(stdscr, row, 2, _truncate(text, max_x - 3), max_x - 3, attrs["dim"])
            elif kind == "blank":
                pass
            elif kind == "dim":
                _safe_addnstr(stdscr, row, 2, _truncate(text, max_x - 3), max_x - 3, attrs["dim"])
            elif kind in ("accent", "project"):
                _safe_addnstr(stdscr, row, 2, _truncate(text, max_x - 3), max_x - 3, attrs[kind])
            else:
                _safe_addnstr(stdscr, row, 2, _truncate(text, max_x - 3), max_x - 3, attrs["topic"])

        nav = " ↑↓/jk scroll · PgUp/PgDn page · Enter resume · q/Esc back"
        _safe_addnstr(stdscr, max_y - 1, 0, _truncate(nav, max_x - 1), max_x - 1, attrs["dim"])

        stdscr.refresh()
        key = stdscr.getch()
        if key in (curses.KEY_UP, ord("k")):
            scroll -= 1
        elif key in (curses.KEY_DOWN, ord("j")):
            scroll += 1
        elif key == curses.KEY_PPAGE:
            scroll -= view_h
        elif key == curses.KEY_NPAGE:
            scroll += view_h
        elif key in (curses.KEY_ENTER, 10, 13):
            return "resume"
        elif key in (ord("q"), 27, ord("p"), 9, ord(" ")):
            return "back"
        elif key == curses.KEY_RESIZE:
            continue


# --- Settings TUI ---


def interactive_settings():
    """Open the settings TUI, save on confirm, and apply changes immediately."""
    overrides = curses.wrapper(_draw_settings, CATALOG, load_settings())
    if overrides is None:
        print("Cancelled.")
        return
    save_settings(overrides)
    print()
    print(_c(1, _c(36, "=== Applying settings ===")))
    print()
    for acct_name in list_accounts() or ["default"]:
        acct_home, _ = resolve_account(acct_name)
        if acct_home.exists():
            for entry in CATALOG:
                _apply_entry(entry, overrides, acct_home)
    print()
    print(_c(32, "Settings saved and applied."))


def _draw_settings(stdscr, catalog, overrides):
    """Settings TUI. Returns overlay {id: bool} on save, None on cancel."""
    curses.curs_set(0)
    curses.use_default_colors()
    curses.init_pair(1, curses.COLOR_BLACK, curses.COLOR_CYAN)  # selected row
    curses.init_pair(2, curses.COLOR_CYAN, -1)  # title bar
    curses.init_pair(6, curses.COLOR_GREEN, -1)  # enabled item
    curses.init_pair(7, curses.COLOR_YELLOW, -1)  # warning text

    local = dict(overrides)  # mutable working copy

    # Build flat row list: headers + entries in catalog order
    rows = []
    seen_cats = []
    for entry in catalog:
        cat = entry["category"]
        if cat not in seen_cats:
            seen_cats.append(cat)
            rows.append({"type": "header", "text": cat})
        rows.append({"type": "entry", "entry": entry})

    selectable = [i for i, r in enumerate(rows) if r["type"] == "entry"]
    defaults = {e["id"]: e["default_on"] for e in catalog}
    sel_pos = 0
    scroll_offset = 0

    while True:
        stdscr.clear()
        max_y, max_x = stdscr.getmaxyx()

        # Title bar
        title = " Altergo — Shared Credentials  ·  Space toggle  ·  s save  ·  Esc cancel"
        stdscr.attron(curses.color_pair(2) | curses.A_BOLD)
        stdscr.addnstr(0, 0, title.ljust(max_x), max_x - 1)
        stdscr.attroff(curses.color_pair(2) | curses.A_BOLD)

        subtitle = "  Share CLI credentials between accounts. Only Claude login stays separate."
        stdscr.attron(curses.A_DIM)
        stdscr.addnstr(1, 0, subtitle[: max_x - 1], max_x - 1)
        stdscr.attroff(curses.A_DIM)

        visible_rows = max(1, max_y - 5)
        current_row_idx = selectable[sel_pos]

        # Scroll to keep selection visible
        if current_row_idx < scroll_offset:
            scroll_offset = current_row_idx
        elif current_row_idx >= scroll_offset + visible_rows:
            scroll_offset = current_row_idx - visible_rows + 1

        for i in range(visible_rows):
            row_idx = scroll_offset + i
            if row_idx >= len(rows):
                break
            screen_row = i + 3
            row = rows[row_idx]

            if row["type"] == "header":
                stdscr.attron(curses.A_BOLD)
                stdscr.addnstr(screen_row, 2, row["text"][: max_x - 3], max_x - 3)
                stdscr.attroff(curses.A_BOLD)
            else:
                entry = row["entry"]
                enabled = is_enabled(entry, local)
                is_current = row_idx == current_row_idx
                has_warn = "warning" in entry

                check = "[x]" if enabled else "[ ]"
                warn_tag = " !" if has_warn else "  "
                name_part = f"  {check} {entry['name']:<22}{warn_tag}"
                path_hint = "  " + ", ".join(f"~/{p}" for p in entry["paths"])

                if is_current:
                    full = f"▸ {check} {entry['name']:<22}{warn_tag}{path_hint.strip()}"
                    stdscr.attron(curses.color_pair(1) | curses.A_BOLD)
                    stdscr.addnstr(screen_row, 0, full[: max_x - 1].ljust(max_x - 1), max_x - 1)
                    stdscr.attroff(curses.color_pair(1) | curses.A_BOLD)
                else:
                    if enabled:
                        stdscr.attron(curses.color_pair(6))
                    stdscr.addnstr(screen_row, 0, name_part[: max_x - 1], max_x - 1)
                    if enabled:
                        stdscr.attroff(curses.color_pair(6))
                    nc = len(name_part)
                    if nc < max_x - 1:
                        stdscr.attron(curses.A_DIM)
                        stdscr.addnstr(screen_row, nc, path_hint[: max_x - nc - 1], max_x - nc - 1)
                        stdscr.attroff(curses.A_DIM)

        # Footer
        footer_row = max_y - 2
        current_entry = rows[current_row_idx].get("entry", {})
        if current_entry.get("warning"):
            stdscr.attron(curses.color_pair(7))
            stdscr.addnstr(footer_row, 0, f"  ! {current_entry['warning']}"[: max_x - 1], max_x - 1)
            stdscr.attroff(curses.color_pair(7))

        nav = "  Space toggle  ·  ↑↓ / j k navigate  ·  s save & apply  ·  Esc cancel"
        stdscr.attron(curses.A_DIM)
        stdscr.addnstr(footer_row + 1, 0, nav[: max_x - 1], max_x - 1)
        stdscr.attroff(curses.A_DIM)

        stdscr.refresh()

        key = stdscr.getch()
        if key in (curses.KEY_UP, ord("k")):
            sel_pos = max(0, sel_pos - 1)
        elif key in (curses.KEY_DOWN, ord("j")):
            sel_pos = min(len(selectable) - 1, sel_pos + 1)
        elif key == curses.KEY_PPAGE:
            sel_pos = max(0, sel_pos - visible_rows)
        elif key == curses.KEY_NPAGE:
            sel_pos = min(len(selectable) - 1, sel_pos + visible_rows)
        elif key == ord(" "):
            entry = rows[selectable[sel_pos]]["entry"]
            local[entry["id"]] = not is_enabled(entry, local)
        elif key == ord("s"):
            # Only write non-default values to keep the file minimal
            overlay = {k: v for k, v in local.items() if defaults.get(k) != v}
            return overlay
        elif key in (ord("q"), 27):
            return None


# --- Launch ---


def _build_alt_env(account: str = "default") -> dict:
    """Return a copy of the environment with HOME set to the account home.

    If account_home/.local/bin exists, it is prepended to PATH so that Claude
    Code's startup PATH check (which resolves relative to $HOME) doesn't warn
    about a missing native-installation directory.  The guard on existence is
    intentional: we only inject the directory when something has actually been
    installed there (e.g. via `claude update` inside an altergo session).
    Without the guard we would prepend a ghost path on every launch and give
    an uncontrolled write target higher precedence than all system binaries.
    """
    account_home, _ = resolve_account(account)
    env = os.environ.copy()
    env["HOME"] = str(account_home)
    acct_local_bin = account_home / ".local" / "bin"
    if acct_local_bin.exists():
        acct_local_bin_str = str(acct_local_bin)
        path_dirs = env.get("PATH", "").split(":")
        if acct_local_bin_str not in path_dirs:
            env["PATH"] = acct_local_bin_str + ":" + env.get("PATH", "")
    return env


def _find_claude() -> str | None:
    """Find the claude binary, checking PATH and common install locations.

    PATH may be incomplete if the user invokes altergo before their shell rc
    has finished loading (e.g., typing very quickly in a new terminal window).
    The fallbacks cover the most common Claude Code install locations.
    """
    path = shutil.which("claude")
    if path:
        return path
    fallbacks = [
        _pw_home / ".local" / "bin" / "claude",  # claude install default
        _pw_home / ".npm-global" / "bin" / "claude",  # npm --global-prefix
        Path("/opt/homebrew/bin/claude"),  # Homebrew on Apple Silicon
        Path("/usr/local/bin/claude"),  # Homebrew on Intel / manual
    ]
    for p in fallbacks:
        if p.exists() and os.access(p, os.X_OK):
            return str(p)
    return None


def _sweep_existing_accounts() -> bool:
    """Repair any accounts that still have real dirs where symlinks are expected.

    Runs automatically after migrate_legacy() and at the start of launch_claude()
    so that existing 0.6.0 users are repaired on next launch without needing
    to run --setup manually.  Silent unless something actually changes.
    """
    changed = False
    for acct in list_accounts():
        _, account_claude = resolve_account(acct)
        for name in SYMLINK_DIRS:
            src = MAIN_CLAUDE / name
            dst = account_claude / name
            if _ensure_symlinked_dir(name, src, dst, account_claude):
                changed = True
    return changed


def launch_claude(account: str = "default", args=None, provider: str | None = None):
    """Launch a provider CLI with account HOME, passing args through unchanged.

    If provider is None, reads account.json to determine which provider to use.
    Single-provider accounts auto-select; multi-provider accounts require an
    explicit --provider flag (handled by SE2 in main()).
    """
    _sweep_existing_accounts()

    account_home, _ = resolve_account(account)

    # Resolve provider
    if provider is None:
        meta = load_account_meta(account_home)
        if meta is not None and "providers" in meta:
            prov_list = meta["providers"]
        else:
            prov_list = ["claude"]

        if len(prov_list) == 1:
            provider = prov_list[0]
        else:
            names = ", ".join(prov_list)
            print(
                f"altergo: account '{account}' has multiple providers ({names}).\n"
                f"  Pass --provider <name> to select one.",
                file=sys.stderr,
            )
            sys.exit(1)

    # Find the binary
    if provider == "claude":
        binary_path = _find_claude()
        if not binary_path:
            sys.exit(
                "altergo: 'claude' not found in PATH or common install locations.\n"
                "  If you just opened this terminal, your shell may still be initializing.\n"
                "  Wait a moment and try again, or open a new tab."
            )
    else:
        prov = PROVIDERS.get(provider)
        if prov is None:
            print(f"altergo: unknown provider '{provider}'.", file=sys.stderr)
            sys.exit(1)
        binary_path = shutil.which(prov["binary"])
        if not binary_path:
            sys.exit(
                f"altergo: '{prov['binary']}' not found in PATH.\n"
                f"  Install {prov['display_name']} and try again."
            )

    env = _build_alt_env(account)
    cmd = [binary_path] + (args or [])
    result = subprocess.run(cmd, env=env)
    _print_launch_message()
    sys.exit(result.returncode)


def launch_shell(account: str = "default"):
    """Open an interactive shell with HOME set to account directory."""
    account_home, _ = resolve_account(account)
    env = _build_alt_env(account)
    # Prompt hint so users know they are in the alt context
    shell = env.get("SHELL", "/bin/sh")
    shell_name = Path(shell).name
    # Prepend a marker to PS1 / PROMPT so the user sees they are in altergo context.
    # We set it in env; the shell will use it if no .bashrc/.zshrc overrides it.
    label = f"altergo:{account}"
    if shell_name in ("bash", "sh"):
        env["PS1"] = env.get("PS1", r"\u@\h:\w\$ ").lstrip()
        env["PS1"] = f"({label}) {env['PS1']}"
    elif shell_name == "zsh":
        env["PROMPT"] = f"({label}) {env.get('PROMPT', '%n@%m %~ %# ')}"
    print(_c(36, f"Entering altergo shell [{account}] (HOME={account_home})"))
    print(_c(2, "Run 'exit' or Ctrl-D to return to your primary account.\n"))
    result = subprocess.run([shell], env=env)
    _print_launch_message()
    sys.exit(result.returncode)


def launch_command(account: str = "default", cmd_args=None):
    """Run an arbitrary command with HOME set to account directory."""
    if not cmd_args:
        print(_c(31, "altergo -- requires a command. Example: altergo -- gh auth login"), file=sys.stderr)
        sys.exit(1)
    cmd_path = shutil.which(cmd_args[0])
    if not cmd_path:
        print(_c(31, f"altergo: '{cmd_args[0]}' not found in PATH"), file=sys.stderr)
        sys.exit(1)
    env = _build_alt_env(account)
    result = subprocess.run([cmd_path] + cmd_args[1:], env=env)
    _print_launch_message()
    sys.exit(result.returncode)


# --- Account name disambiguation helper ---


_KNOWN_COMMANDS = frozenset(
    ["shell", "--resume", "--list", "--setup", "--teardown", "--settings", "--version", "--use", "--launch", "-h", "--help", "--"]
)


def _looks_like_account(token: str) -> bool:
    """Return True if token could be an account name (not a flag, not a known command)."""
    if token.startswith("-"):
        return False
    if token in _KNOWN_COMMANDS:
        return False
    # Must look like a valid account name (alphanumeric start, no spaces)
    return bool(re.match(r"^[a-zA-Z0-9][a-zA-Z0-9_-]*$", token))


# --- Interactive prompt helpers ---


def _prompt_account_name() -> str:
    """Interactively prompt for account name. Shows existing accounts."""
    existing = list_accounts()
    if existing:
        print(f"  Existing accounts: {', '.join(_c(36, a) for a in existing)}")
    while True:
        raw = input("  Account name: ").strip()
        if not raw:
            print("  Please enter an account name.")
            continue
        try:
            validate_account_name(raw)
            return raw
        except SystemExit:
            print(f"  Invalid name '{raw}'. Use letters, digits, - or _ only.")


def _prompt_provider_selection(current_providers: list[str] | None = None) -> list[str]:
    """Prompt user to select which AI providers this account uses.

    Detects installed provider binaries and pre-checks them.
    current_providers: if set, pre-check these instead of detecting.
    Returns list of provider IDs (at least one).
    """
    # Build ordered list: installed ones first, then others
    installed = [pid for pid, p in PROVIDERS.items() if shutil.which(p["binary"])]
    all_providers = list(PROVIDERS.keys())
    ordered = installed + [p for p in all_providers if p not in installed]

    pre_checked = current_providers if current_providers is not None else installed
    # Always ensure claude is pre-checked if nothing is installed
    if not pre_checked:
        pre_checked = ["claude"]

    print()
    print("  Select AI providers for this account (space to toggle, enter to confirm):")
    print()

    selected = set(pre_checked)
    items = ordered

    # Simple interactive: show numbered list, ask for comma-separated selection
    for i, pid in enumerate(items):
        p = PROVIDERS[pid]
        check_mark = _c(32, "\u2713")
        checked = check_mark if pid in selected else " "
        installed_hint = _c(2, " (installed)") if shutil.which(p["binary"]) else _c(31, " (not found)")
        print(f"  [{checked}] {i+1}. {p['display_name']}{installed_hint}")

    print()
    pre_nums = [str(items.index(p) + 1) for p in pre_checked if p in items]
    default_str = ",".join(pre_nums) or "1"
    raw = input(f"  Enter numbers separated by commas [{_c(36, default_str)}]: ").strip()

    if not raw:
        chosen_indices = [int(n) - 1 for n in default_str.split(",")]
    else:
        try:
            chosen_indices = [int(n.strip()) - 1 for n in raw.split(",")]
        except ValueError:
            chosen_indices = [int(n) - 1 for n in default_str.split(",")]

    result = []
    for i in chosen_indices:
        if 0 <= i < len(items):
            result.append(items[i])

    # Deduplicate while preserving order
    seen = set()
    deduped = []
    for pid in result:
        if pid not in seen:
            seen.add(pid)
            deduped.append(pid)

    if not deduped:
        warn = _c(33, "\u26a0")
        print(f"  {warn} No provider selected \u2014 defaulting to Claude Code.")
        deduped = ["claude"]

    return deduped


# --- Goodbye messages ---

_GOODBYE = [
    "Back to reality. Good luck with the next bug.",
    "Session closed. The context window has left the building.",
    "That was productive, ah?",
    "Claude has left the chat. Your git blame remains.",
    "All that intelligence, and it still couldn't push to main for you.",
    "See you in 5 minutes when the next edge case appears.",
    "The model has spoken. Whether it was right is your problem.",
    "Tokens spent. Wisdom optional.",
    "Another session closed. Another PR description that writes itself.",
    "Done. The AI did the thinking. You take the blame.",
    "Clean exit. The work continues.",
    "Until next time. May your tests be green.",
    "Context preserved. You know where to find it.",
    "Ship it.",
    "Commit early, commit often. You know the drill.",
]


def _print_launch_message():
    """Print a witty handoff line to stderr before handing off to an AI session."""
    if not sys.stderr.isatty():
        return
    import random
    msg = random.choice(_GOODBYE)
    print(f"\n  {_c(_C_COMMAND, 'altergo')}  {_c(_C_DIM, msg)}\n", file=sys.stderr)


# --- Interactive provider+account launcher ---

_LAUNCHER_PROVIDERS = [
    {"id": "claude",  "label": "anthropic", "binary": "claude"},
    {"id": "gemini",  "label": "gemini",    "binary": "gemini"},
    {"id": "codex",   "label": "openai",    "binary": "codex"},
    {"id": "copilot", "label": "github",    "binary": "copilot"},
]


def build_launcher_menu() -> list:
    """Build provider-grouped account menu for the interactive launcher.

    Returns a list of provider dicts:
        [{"provider_id": str, "label": str, "accounts": [{"name": str, "age": str, "available": bool}]}]
    """
    accounts = list_accounts()
    # Group accounts by their primary provider from account.json
    provider_accounts: dict = {}
    for acct in accounts:
        acct_home = ACCOUNTS_DIR / acct
        meta = load_account_meta(acct_home)
        providers_for_acct = meta["providers"] if meta else ["claude"]
        primary = providers_for_acct[0] if providers_for_acct else "claude"
        provider_accounts.setdefault(primary, []).append(acct)

    # Resolve most-recent session age per account (best-effort)
    all_sessions = get_sessions()
    acct_ages: dict = {}
    for s in all_sessions:
        # Sessions live under MAIN_CLAUDE/projects — not per-account, so use
        # the first session encountered as a proxy for "recently active"
        for acct in accounts:
            if acct not in acct_ages:
                acct_ages[acct] = relative_time(s["modified"])
        if len(acct_ages) == len(accounts):
            break

    # Build ordered menu following _LAUNCHER_PROVIDERS order, then any extras
    seen_providers = set()
    menu = []
    ordered_ids = [p["id"] for p in _LAUNCHER_PROVIDERS] + list(provider_accounts.keys())
    for pid in ordered_ids:
        if pid in seen_providers or pid not in provider_accounts:
            continue
        seen_providers.add(pid)
        label = next((p["label"] for p in _LAUNCHER_PROVIDERS if p["id"] == pid), pid)
        binary = next((p["binary"] for p in _LAUNCHER_PROVIDERS if p["id"] == pid), pid)
        available = bool(shutil.which(binary))
        chips = []
        for acct in provider_accounts[pid]:
            chips.append({
                "name": acct,
                "age": acct_ages.get(acct, ""),
                "available": available,
            })
        menu.append({"provider_id": pid, "label": label, "accounts": chips})
    return menu


def _draw_launcher(stdscr, menu):
    """Two-axis curses TUI: ↑↓ providers, ←→ account chips. Returns (account, shell_mode)."""
    curses.curs_set(0)
    attrs = _picker_attrs()
    stdscr.timeout(80)

    cursor_row = 0
    cursor_col = 0
    phase = 0

    # Sanitize initial cursor position
    def clamp_col(row, col):
        if not menu:
            return 0
        return min(col, max(0, len(menu[row]["accounts"]) - 1))

    while True:
        stdscr.erase()
        max_y, max_x = stdscr.getmaxyx()

        total_accounts = sum(len(p["accounts"]) for p in menu)
        n_providers = len(menu)

        # Header
        title = " altergo — launch"
        right = f"{n_providers} provider{'s' if n_providers != 1 else ''} · {total_accounts} account{'s' if total_accounts != 1 else ''} "
        header = title.ljust(max_x - len(right)) + right
        _safe_addnstr(stdscr, 0, 0, header[:max_x], max_x - 1, attrs["title"])

        # Separator
        _safe_addnstr(stdscr, 1, 0, ("─" * (max_x - 1))[:max_x - 1], max_x - 1, attrs["dim"])

        # Provider rows (start at row 3, blank row between each)
        row = 3
        for pi, prov in enumerate(menu):
            if row >= max_y - 3:
                break
            label = prov["label"][:12].ljust(12)
            is_focused_row = pi == cursor_row
            label_attr = attrs["project"] | curses.A_BOLD if is_focused_row else attrs["project"]
            _safe_addnstr(stdscr, row, 2, label, 12, label_attr)

            x = 16
            for ci, chip in enumerate(prov["accounts"]):
                if x >= max_x - 5:
                    _safe_addnstr(stdscr, row, x, "…", 1, attrs["dim"])
                    break
                name = chip["name"][:10]
                age = chip["age"][:5] if chip["age"] else ""
                chip_text = f"{name} · {age}" if age else name
                is_selected = is_focused_row and ci == cursor_col

                if not chip["available"]:
                    chip_str = f"✗ {chip_text}  "
                    _safe_addnstr(stdscr, row, x, chip_str[:max_x - x - 1], max_x - x - 1, attrs["dim"])
                elif is_selected:
                    chip_str = f"▓ {chip_text} ▓ "
                    _safe_addnstr(stdscr, row, x, chip_str[:max_x - x - 1], max_x - x - 1, attrs["selected"])
                elif is_focused_row:
                    chip_str = f"░ {chip_text} ░ "
                    _safe_addnstr(stdscr, row, x, chip_str[:max_x - x - 1], max_x - x - 1, attrs["time"])
                else:
                    chip_str = f"  {chip_text}   "
                    _safe_addnstr(stdscr, row, x, chip_str[:max_x - x - 1], max_x - x - 1, attrs["dim"])
                x += len(chip_str)

            row += 2  # blank line between providers

        # Active account indicator (shown in header area if set)
        active_acct = get_active_account()
        if active_acct and max_y > 2:
            active_hint = f" active: {active_acct} "
            _safe_addnstr(stdscr, 0, max(0, max_x - len(active_hint) - 1), active_hint, len(active_hint), attrs["accent"])

        # Nav footer
        nav = " ↑↓/jk provider  ·  ←→/hl account  ·  Enter launch  ·  s shell  ·  d set active  ·  q quit"
        _draw_animated_nav(stdscr, max_y - 1, nav, max_x - 1, phase, attrs)

        stdscr.refresh()
        key = stdscr.getch()

        if key == -1:
            phase += 1
            continue

        if key in (curses.KEY_UP, ord("k")):
            cursor_row = max(0, cursor_row - 1)
            cursor_col = clamp_col(cursor_row, 0)
        elif key in (curses.KEY_DOWN, ord("j")):
            cursor_row = min(len(menu) - 1, cursor_row + 1)
            cursor_col = clamp_col(cursor_row, 0)
        elif key in (curses.KEY_LEFT, ord("h")):
            cursor_col = max(0, cursor_col - 1)
        elif key in (curses.KEY_RIGHT, ord("l")):
            cursor_col = clamp_col(cursor_row, cursor_col + 1)
        elif key in (curses.KEY_ENTER, 10, 13):
            if menu and menu[cursor_row]["accounts"]:
                chip = menu[cursor_row]["accounts"][cursor_col]
                if chip["available"]:
                    return chip["name"], False
        elif key == ord("s"):
            if menu and menu[cursor_row]["accounts"]:
                chip = menu[cursor_row]["accounts"][cursor_col]
                if chip["available"]:
                    return chip["name"], True
        elif key == ord("d"):
            if menu and menu[cursor_row]["accounts"]:
                chip = menu[cursor_row]["accounts"][cursor_col]
                set_active_account(chip["name"])
                # Show brief flash on the footer so user sees confirmation
                confirm = f" ✓ '{chip['name']}' set as active account "
                _safe_addnstr(stdscr, max_y - 1, 0, confirm[:max_x - 1].ljust(max_x - 1), max_x - 1, attrs["accent"])
                stdscr.refresh()
                curses.napms(800)
        elif key in (ord("q"), 27):
            return None, False
        elif key == curses.KEY_RESIZE:
            continue


def interactive_launcher():
    """Show the provider+account picker and launch the selected account."""
    menu = build_launcher_menu()
    if not menu:
        print("altergo: no accounts found. Run 'altergo --setup' first.", file=sys.stderr)
        sys.exit(1)
    result = curses.wrapper(_draw_launcher, menu)
    account, shell_mode = result if result else (None, False)
    if not account:
        sys.exit(0)
    if shell_mode:
        launch_shell(account)
    else:
        launch_claude(account)


# --- Main ---


def main():
    # Auto-migrate legacy layout before any other processing
    migrate_legacy()
    # Repair any accounts that still have real dirs instead of symlinks
    # (covers the default account after legacy migration, and any 0.6.0 users
    # whose accounts/default/.claude/projects/ was left as a real dir).
    _sweep_existing_accounts()

    args = sys.argv[1:]

    # ── Altergo-owned commands (not passed to claude) ──────────────────────────

    if args and args[0] in ("-h", "--help"):
        show_help()
        sys.exit(0)

    if args and args[0] == "--version":
        print(f"altergo {__version__}")
        sys.exit(0)

    if args and args[0] == "--setup":
        # Parse --name and --provider flags
        # Supported forms:
        #   altergo --setup                              (interactive)
        #   altergo --setup --name work                  (named, interactive provider)
        #   altergo --setup --name work --provider claude,gemini  (fully specified)
        #   altergo --setup --provider gemini            (interactive name, specified provider)
        remaining = args[1:]
        name = None
        provider_arg = None
        i = 0
        while i < len(remaining):
            if remaining[i] == "--name" and i + 1 < len(remaining):
                name = remaining[i + 1]
                validate_account_name(name)
                i += 2
            elif remaining[i] == "--provider" and i + 1 < len(remaining):
                provider_arg = remaining[i + 1]
                i += 2
            else:
                i += 1

        # Resolve name
        if name is None:
            if sys.stdin.isatty():
                name = _prompt_account_name()
            else:
                name = "default"

        # Resolve providers
        if provider_arg is not None:
            providers = [p.strip() for p in provider_arg.split(",")]
            unknown = [p for p in providers if p not in PROVIDERS]
            if unknown:
                print(f"altergo: unknown provider(s): {', '.join(unknown)}. Known: {', '.join(PROVIDERS)}", file=sys.stderr)
                sys.exit(1)
        else:
            if sys.stdin.isatty():
                account_home, _ = resolve_account(name)
                meta = load_account_meta(account_home)
                current = meta["providers"] if meta else None
                providers = _prompt_provider_selection(current)
            else:
                # Non-interactive: default to claude (backwards compat)
                account_home, _ = resolve_account(name)
                meta = load_account_meta(account_home)
                providers = meta["providers"] if meta else ["claude"]

        do_setup(name, providers)
        sys.exit(0)

    if args and args[0] == "--teardown":
        # Support: --teardown --name <name>
        name = "default"
        if len(args) >= 3 and args[1] == "--name":
            name = args[2]
        do_teardown(name)
        sys.exit(0)

    if args and args[0] == "--settings":
        interactive_settings()
        sys.exit(0)

    if args and args[0] == "--launch":
        interactive_launcher()
        sys.exit(0)

    if args and args[0] == "--list":
        sessions = get_sessions()
        if not sessions:
            print("No sessions found.")
            sys.exit(0)
        header_row = f"{'Project':<20} {'Modified':<18} {'Size':>6}  Session ID"
        print(_c(2, header_row))
        print(_c(2, "-" * 80))
        for s in sessions[:30]:
            project = format_project_name(s["project"])
            modified = s["modified"].strftime("%Y-%m-%d %H:%M")
            size = f"{s['size_mb']:.1f}MB"
            print(f"{_c(36, f'{project:<20}')} {_c(2, f'{modified:<18}')} {_c(33, f'{size:>6}')}  {s['id']}")
        sys.exit(0)

    if args and args[0] == "--use":
        if len(args) < 2:
            print("altergo: --use requires an account name. Example: altergo --use work", file=sys.stderr)
            sys.exit(1)
        use_name = args[1]
        use_home = ACCOUNTS_DIR / use_name
        if not use_home.is_dir():
            print(
                f"altergo: account '{use_name}' not found. Run 'altergo --setup --name {use_name}' to create it.",
                file=sys.stderr,
            )
            sys.exit(1)
        set_active_account(use_name)
        print(f"altergo: active account set to {_c(_C_COMMAND, use_name)}")
        print(_c(_C_DIM, f"  Bare 'altergo' will now launch '{use_name}' by default."))
        sys.exit(0)

    # --resume with no ID → open interactive picker
    if args and args[0] == "--resume" and len(args) == 1:
        accounts = list_accounts()
        if not accounts:
            print("altergo: no accounts found. Run 'altergo --setup' first.", file=sys.stderr)
            sys.exit(1)
        if len(accounts) == 1:
            resume_account = accounts[0]
        else:
            active = get_active_account()
            if active:
                resume_account = active
            else:
                print(
                    f"altergo: multiple accounts exist ({', '.join(accounts)}).\n"
                    f"  Use 'altergo <name> --resume' to pick an account, or\n"
                    f"  'altergo --use <name>' to set an active account.",
                    file=sys.stderr,
                )
                sys.exit(1)
        sessions = get_sessions()
        selected = interactive_picker(sessions)
        if selected:
            launch_claude(resume_account, ["--resume", selected["id"]])
        else:
            print("Cancelled.")
        sys.exit(0)

    # ── Account name as first positional arg ──────────────────────────────────
    # altergo <name> [sub-command | claude flags...]
    account = None
    if args and _looks_like_account(args[0]):
        candidate = args[0]
        acct_home = ACCOUNTS_DIR / candidate
        if not acct_home.is_dir():
            print(
                f"altergo: account '{candidate}' not found. Run 'altergo --setup --name {candidate}' to create it.",
                file=sys.stderr,
            )
            sys.exit(1)
        account = candidate
        args = args[1:]

    # ── Implicit account resolution (no positional name given) ───────────────
    if account is None:
        _all_accounts = list_accounts()
        _active = get_active_account()
        if _active:
            account = _active
            if sys.stderr.isatty():
                print(f"  {_c(_C_DIM, 'account:')} {_c(_C_COMMAND, account)}", file=sys.stderr)
        elif len(_all_accounts) == 1:
            account = _all_accounts[0]
        elif len(_all_accounts) > 1 and sys.stdout.isatty():
            interactive_launcher()
            sys.exit(0)
        elif not _all_accounts:
            print("altergo: no accounts found. Run 'altergo --setup' first.", file=sys.stderr)
            sys.exit(1)
        else:
            # Multiple accounts, non-interactive — cannot pick one silently
            print(
                f"altergo: multiple accounts exist ({', '.join(_all_accounts)}).\n"
                f"  Run 'altergo <name>' to launch a specific account, or\n"
                f"  'altergo --use <name>' to set an active account for bare 'altergo'.",
                file=sys.stderr,
            )
            sys.exit(1)

    # ── Sub-commands (after optional account prefix) ──────────────────────────

    # altergo [<name>] shell
    if args and args[0] == "shell":
        launch_shell(account)

    # altergo [<name>] -- <cmd> [args...]
    if args and args[0] == "--":
        launch_command(account, args[1:])

    # ── Everything else → pass straight through to claude ────────────────────
    # altergo                    → claude (active account)
    # altergo work               → claude (work account, args=[])
    # altergo --resume x         → claude --resume x
    # altergo --dangerously-...  → claude --dangerously-...

    # Extract --provider flag if present (consumed by altergo, not passed to claude)
    provider = None
    filtered_args = []
    i = 0
    while i < len(args):
        if args[i] == "--provider" and i + 1 < len(args):
            provider = args[i + 1]
            i += 2
        else:
            filtered_args.append(args[i])
            i += 1
    launch_claude(account, filtered_args, provider=provider)


if __name__ == "__main__":
    main()
