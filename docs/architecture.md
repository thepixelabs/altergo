# Architecture reference

**Applies to:** altergo v0.16.0+  
**Audience:** Engineers maintaining altergo, debugging symlink issues, or auditing what altergo touches on disk.

For a prose explanation of why the architecture is designed this way, see [how-it-works.md](how-it-works.md).

---

## Repository layout

```
altergo/
    altergo.py              ← Main implementation (single file, ~3700 lines)
    altergo_greetings.py    ← Greeting messages, time-of-day copy, theme spinners
    pyproject.toml          ← Package metadata, entry point, dependencies
    tests/
        test_smoke.py       ← Core functionality tests
        test_integration.py ← Integration tests for setup, teardown, launch
        test_new_features.py ← Tests for newer features
        conftest.py         ← Shared test fixtures
    docs/
        how-it-works.md     ← Technical deep dive
        architecture.md     ← This file
        settings.md         ← Settings TUI documentation
        migration.md        ← Migration guides
        index.html          ← Project website (deployed via GitHub Pages)
        ...
    .github/
        workflows/
            ci.yml          ← Lint (ruff) + test matrix (Python 3.9–3.13, ubuntu + macos)
            release.yml     ← PyPI publish on tag push
            pages.yml       ← GitHub Pages deploy
            security.yml    ← Dependency security scan
            homebrew-bump.yml ← Homebrew formula bump on release
```

altergo depends on `rich`, `pyfiglet`, and `rich-pyfiglet` for the banner and TUI chrome. Everything else — `curses`, `json`, `os`, `pwd`, `re`, `shutil`, `sys`, `pathlib`, `datetime`, `threading` — is Python standard library.

---

## Source file: `altergo.py`

The entire program is one file. Here is a map of its logical sections:

| Section | Key functions | Purpose |
|---|---|---|
| Themes | `THEMES`, `C()`, `_gradient_color()` | 6-theme color system with gradient support |
| Banner | `show_banner()` | Rich-rendered figlet logo, version, greeting |
| Help | `show_help()` | Colored, hyperlinked help output |
| Config | `MAIN_HOME`, `ACCOUNTS_DIR`, `SETTINGS_FILE` | Path constants |
| Account helpers | `resolve_account()`, `list_accounts()` | Account directory resolution |
| Migration | `detect_legacy()`, `migrate_legacy()` | Auto-migration from v0.4.x layout |
| Providers | `PROVIDERS`, `CATALOG` | Multi-provider support, credential sharing catalog |
| Settings helpers | `load_settings()`, `save_settings()`, `_load_bool_setting()` | Settings persistence |
| Preferences | `_load_bool_setting()` | Boolean settings: greeting, goodbye, animation |
| Update checker | `load_update_check_enabled()`, PyPI cache | Background version check |
| Setup / Teardown | `do_setup()`, `do_teardown()` | Account creation and removal |
| Session discovery | `get_sessions()`, `get_session_preview()` | JSONL session scanning |
| Session picker | `_draw_picker()` | Curses session resume TUI |
| Search | `_draw_search()` | Full-text conversation search |
| Settings TUI | `_draw_settings()`, `interactive_settings()` | Multi-page settings (Appearance, Behavior, Credentials) |
| Launcher | `_draw_launcher()`, `interactive_launcher()` | Provider + account picker |
| Onboarding | `_first_run_onboarding()` | First-run account creation flow |
| Launch | `launch_claude()`, `launch_shell()`, `launch_command()` | Provider binary execution |
| `main()` | `main()` | Argument dispatch |

---

## Runtime directory layout

The following describes the filesystem state after `altergo --setup` has been run successfully.

### Primary account (unchanged)

```
~/.claude/
    .credentials.json           ← Real file. Never touched by altergo.
    projects/
        -Users-alice-code-myapp/
            <session-id>.jsonl
        ...
    tasks/
    session-env/
    file-history/
    shell-snapshots/
    agents/
    plans/
    cache/
    settings.json
    CLAUDE.md
    keybindings.json
```

### Accounts directory

All altergo accounts live under `~/.altergo/accounts/`. The `default` account is used when you run `altergo` with no account name. Named accounts (e.g. `work`, `client-a`) are created with `altergo --setup --name <name>`.

```
~/.altergo/
    .altergo.json                   ← Settings file (global, shared across all accounts)
    .legacy-backup/                 ← Backup of pre-v0.5 layout (present after auto-migration only)
    accounts/
        default/                    ← Default account home (HOME for plain `altergo`)
            .claude/
                .credentials.json   ← Real file. Isolated credentials. Created on first login.
                projects/           ← Symlink → ~/.claude/projects/
                tasks/              ← Symlink → ~/.claude/tasks/
                session-env/        ← Symlink → ~/.claude/session-env/
                file-history/       ← Symlink → ~/.claude/file-history/
                shell-snapshots/    ← Symlink → ~/.claude/shell-snapshots/
                agents/             ← Symlink → ~/.claude/agents/
                plans/              ← Symlink → ~/.claude/plans/
                cache/              ← Symlink → ~/.claude/cache/
                settings.json       ← Symlink → ~/.claude/settings.json
                CLAUDE.md           ← Symlink → ~/.claude/CLAUDE.md
                keybindings.json    ← Symlink → ~/.claude/keybindings.json
            .aws/                   ← Symlink → ~/.aws/ (if AWS sharing is enabled)
            .config/
                gh/                 ← Symlink → ~/.config/gh/ (if GitHub CLI sharing is enabled)
                gcloud/             ← Symlink → ~/.config/gcloud/ (if Google Cloud sharing enabled)
                ...
            .docker/                ← Symlink → ~/.docker/ (if Docker sharing is enabled)
            ...

        work/                       ← Named account home (HOME for `altergo work`)
            .claude/
                .credentials.json   ← Real file. Isolated credentials.
                projects/           ← Symlink → ~/.claude/projects/ (same target)
                ...                 ← Same symlink structure as default
            .aws/                   ← Symlink → ~/.aws/ (same shared credentials as default)
            ...

    # Written by Claude Code during normal usage (not managed by altergo):
    accounts/default/.local/bin/claude     ← Created if 'claude update' runs inside altergo
    accounts/default/Library/Application Support/claude/  ← macOS only
```

### Settings file placement

`~/.altergo/.altergo.json` sits at the `~/.altergo/` level, above `accounts/`. It is global — one file shared across all accounts. This is intentional: credential-sharing preferences (AWS, Docker, etc.) apply to the relationship between the main home and the alt account, not to a specific account. See [how-it-works.md](how-it-works.md) for the rationale.

As of v0.16, the settings file stores theme, preference toggles, and credential overrides:

```json
{
  "version": 1,
  "theme": "ocean",
  "update_check": true,
  "show_greeting": true,
  "show_goodbye": true,
  "launch_animation": true,
  "active_account": "work",
  "shared": {
    "ssh": true,
    "gitconfig": false
  }
}
```

All boolean keys default to `true` when absent. The `shared` dict uses a delta pattern — only non-default values are stored. See [settings.md](settings.md) for the full settings TUI documentation.

---

## Account name validation

Account names must pass `validate_account_name()`:

- Match `^[a-zA-Z0-9][a-zA-Z0-9_-]*$` (alphanumeric start, then alphanumeric, `-`, or `_`)
- Maximum 64 characters
- Must not be in `_RESERVED_NAMES`: `default`, `main`, `list`, `new`, `rm`, `shell`, `setup`, `teardown`, `help`, `version`, `legacy`, `backup`, `migrate`

`validate_account_name()` is called only during `--setup --name <name>`. It is not called during account lookup in `main()` — if the directory does not exist, the user sees a "not found" error with a hint to run `--setup --name`.

---

## `ACCOUNTS_DIR` and account helpers

| Function | Signature | Returns |
|---|---|---|
| `resolve_account` | `(name: str) -> tuple` | `(account_home, account_claude)` — both are `Path` objects |
| `list_accounts` | `() -> list` | Sorted list of account name strings that exist on disk; skips entries starting with `.` |
| `validate_account_name` | `(name: str) -> None` | Raises `SystemExit` if the name is invalid or reserved |

`ACCOUNTS_DIR` is `MAIN_HOME / ".altergo" / "accounts"`. `resolve_account("work")` returns `(ACCOUNTS_DIR / "work", ACCOUNTS_DIR / "work" / ".claude")`.

---

## Account disambiguation in `main()`

When the first argument is not a known flag or subcommand, `main()` checks whether it could be an account name using `_looks_like_account()`:

```
_KNOWN_COMMANDS = frozenset([
    "shell", "--resume", "--list", "--setup", "--teardown",
    "--settings", "--version", "-h", "--help", "--"
])

_looks_like_account(token):
    → False if token starts with "-"
    → False if token is in _KNOWN_COMMANDS
    → True  if token matches ^[a-zA-Z0-9][a-zA-Z0-9_-]*$
```

If `_looks_like_account` returns `True`, `main()` checks whether `ACCOUNTS_DIR / token` exists on disk. If it does not exist, altergo exits with a clear error and a hint. If it does exist, the token is consumed as the account name and the remaining arguments are processed as the sub-command or claude flags.

This means `altergo --dangerously-skip-permissions` passes `--dangerously-skip-permissions` straight through to claude (starts with `-`, so not an account name), while `altergo work` routes to the `work` account.

---

## Auto-migration: `detect_legacy()` and `migrate_legacy()`

`detect_legacy()` returns `True` when both of these conditions hold:
1. `~/.altergo/.claude/` exists (the old v0.4.x single-account layout)
2. `~/.altergo/accounts/` does not yet exist

`migrate_legacy()` runs at the top of `main()` on every invocation. When `detect_legacy()` returns `True`, it performs the migration in five steps:

1. Rename `~/.altergo/` to `/tmp/altergo-migrate-<pid>/`
2. Create `~/.altergo/accounts/`
3. Rename `/tmp/altergo-migrate-<pid>/` to `~/.altergo/accounts/default/`
4. Copy `accounts/default/` to `~/.altergo/.legacy-backup/` (preserving symlinks)
5. Write `~/.altergo/accounts/default/MIGRATED.txt` as an audit trail
6. Print a 4-line visible block to stdout describing the migration

The use of `/tmp/` as an intermediate staging area means the rename in step 1 is atomic on the local filesystem (same device). If the process is interrupted between steps 1 and 3, the data sits safely in `/tmp/` under a PID-qualified name. The migration is idempotent: once `accounts/` exists, `detect_legacy()` returns `False` and `migrate_legacy()` returns immediately without printing anything.

---

## Symlink reference table

Every entry in `SYMLINK_DIRS`, `SYMLINK_FILES`, and `CATALOG` is described here.

### Inside `account_home/.claude/` — shared session data (`SYMLINK_DIRS`)

| Directory | Contains | Why shared |
|---|---|---|
| `projects/` | Session JSONL files, one subdirectory per working-directory path | Sessions are indexed by filesystem path, not by account. All accounts work on the same codebases. Sharing this is the primary purpose of altergo. |
| `tasks/` | Task files from Claude's task system | Tasks are scoped to a project, not to an account. You want the same task context regardless of which account is active. |
| `session-env/` | Shell environment snapshots captured at session start | These are per-session, not per-account. Sharing gives all accounts access to the same environment history. |
| `file-history/` | File access history | Context about which files were recently opened. Account-agnostic. |
| `shell-snapshots/` | Shell state captures | Per-session snapshots. No reason to isolate by account. |
| `agents/` | Agent definition files | Agent configurations are per-project. Sharing means you do not need to recreate agents in each account. |
| `plans/` | Plan files | Plans are project work context, not account state. |
| `cache/` | Response cache | Content-addressed cache. Sharing means no account re-fetches what another already fetched, reducing latency and API cost. |

### Inside `account_home/.claude/` — shared config (`SYMLINK_FILES`)

| File | Contains | Why shared |
|---|---|---|
| `settings.json` | Editor settings, feature flags, UI preferences | Settings express personal workflow preferences, not account state. |
| `CLAUDE.md` | Global system prompt and instructions for Claude | Instructions are how you configure Claude's behavior. All accounts should follow the same instructions. |
| `keybindings.json` | Custom key mappings | Muscle memory is account-agnostic. |

### At `account_home/` level — shared CLI tool credentials (`CATALOG`)

Isolates Claude credentials. Shares AWS, GCP, Docker, and kubectl by default.

AWS, GCP, Docker, and kubectl credentials are shared across accounts by default — configurable via `altergo --settings`.

These symlinks live directly in the account home (e.g., `~/.altergo/accounts/work/.aws`), not inside `.claude/`. This placement means they are available to any tool that reads `$HOME` — not just Claude Code.

| Entry | Paths | Default | Notes |
|---|---|---|---|
| AWS CLI | `.aws` | On | |
| Google Cloud | `.config/gcloud` | On | |
| Azure CLI | `.azure`, `.config/azure` | On | Two paths, both symlinked |
| Docker | `.docker` | On | |
| Kubernetes | `.kube` | On | |
| Terraform | `.terraform.d` | On | |
| GitHub CLI | `.config/gh` | On | |
| GitLab CLI | `.config/glab` | Off | |
| npm | `.npmrc` | Off | |
| SSH keys | `.ssh` | Off | Shares keys and known_hosts |
| Git identity | `.gitconfig` | Off | Shares user.name/email |
| GPG keys | `.gnupg` | Off | Shares keyring |

### Isolated (real file, not symlinked)

| Path | Why isolated |
|---|---|
| `~/.altergo/accounts/<name>/.claude/.credentials.json` | This is the entire purpose of altergo. Each account must authenticate separately. |

### Unmanaged (written by Claude Code, not tracked by altergo)

| Path | Notes |
|---|---|
| `~/.altergo/accounts/<name>/.claude/paste-cache/` | Ephemeral. Safe to leave isolated. |
| `~/.altergo/accounts/<name>/.claude/plugins/` | Plugin state is isolated per-account. If you use plugins and want them shared, manually symlink this directory after running setup. |

---

## Environment modifications at launch

`_build_alt_env(account)` returns a modified copy of `os.environ`. It never mutates the live environment. The modified dict is passed to `os.execvpe` and becomes the child process's environment.

| Variable | Modification | Condition |
|---|---|---|
| `HOME` | Set to `~/.altergo/accounts/<name>` | Always |
| `PATH` | `~/.altergo/accounts/<name>/.local/bin` prepended | Only if that directory exists on disk AND is not already in PATH |
| `PS1` | `(altergo:<name>) ` prefix prepended | Only in `launch_shell()`, only for bash/sh |
| `PROMPT` | `(altergo:<name>) ` prefix prepended | Only in `launch_shell()`, only for zsh |

All other environment variables pass through unchanged.

### Claude binary resolution

`_find_claude()` is called before `_build_alt_env()`. It first calls `shutil.which("claude")` against the unmodified `PATH`. If that fails, it tries four hardcoded fallback paths (native install default, npm global prefix, Homebrew on Apple Silicon, Homebrew on Intel). The absolute path returned is passed to `os.execvpe` so no PATH search occurs at exec time.

---

## Data flow: invocation to Claude Code running

```
User runs: altergo [account] [args]
│
├─ Python starts altergo.py
│
├─ Module-level: resolve MAIN_HOME
│   pwd.getpwuid(os.getuid()).pw_dir        ← reads /etc/passwd (or Directory Services)
│   Falls back to os.environ["HOME"] only if passwd entry path does not exist
│   MAIN_HOME    = resolved real home
│   MAIN_CLAUDE  = MAIN_HOME / ".claude"
│   ACCOUNTS_DIR = MAIN_HOME / ".altergo" / "accounts"
│
├─ main()
│   ├─ migrate_legacy()                     ← runs on every invocation; no-op if new layout
│   │
│   ├─ parse sys.argv[1:]
│   │   ├─ -h / --help      → show_help()           → sys.exit(0)
│   │   ├─ --version        → print version         → sys.exit(0)
│   │   ├─ --setup [--name <n>]  → do_setup(n)      → sys.exit(0)
│   │   ├─ --teardown [--name <n>] → do_teardown(n) → sys.exit(0)
│   │   ├─ --settings       → interactive_settings() → sys.exit(0)
│   │   ├─ --list           → get_sessions() → print table → sys.exit(0)
│   │   │
│   │   ├─ --resume (alone)
│   │   │   └─ get_sessions() → interactive_picker() → user selects
│   │   │       ├─ selected  → launch_claude("default", ["--resume", id])
│   │   │       └─ cancelled → sys.exit(0)
│   │   │
│   │   ├─ _looks_like_account(args[0]) ?
│   │   │   ├─ yes, dir exists → account = args[0]; args = args[1:]
│   │   │   └─ yes, dir missing → print error + hint → sys.exit(1)
│   │   │
│   │   ├─ [account] shell → launch_shell(account)
│   │   ├─ [account] -- <cmd> [args] → launch_command(account, args[1:])
│   │   └─ anything else   → launch_claude(account, args)
│   │
└─ launch_claude(account, args) / launch_shell(account) / launch_command(account, args)
    │
    ├─ _find_claude()         ← resolves from CURRENT (unmodified) PATH + fallbacks
    │
    ├─ _build_alt_env(account)
    │   ├─ env = os.environ.copy()
    │   ├─ env["HOME"] = str(ACCOUNTS_DIR / account)    ← always
    │   └─ if account_home/.local/bin exists:
    │       prepend to env["PATH"]                      ← conditional
    │
    └─ os.execvpe(binary, [binary] + args, env)
        │
        └─ PROCESS IMAGE REPLACED
           Claude Code (or shell, or command) runs as the same PID.
           It reads:
             $HOME/.claude/.credentials.json    ← account-specific real file
             $HOME/.claude/projects/            ← symlink → ~/.claude/projects/
             $HOME/.claude/settings.json        ← symlink → ~/.claude/settings.json
             $HOME/.claude/CLAUDE.md            ← symlink → ~/.claude/CLAUDE.md
             $HOME/.aws/                        ← symlink → ~/.aws/ (if enabled)
             ... (all other catalog symlinks) ...
```

---

## Session file format

Claude Code stores sessions as JSONL files at:

```
~/.claude/projects/<encoded-path>/<session-id>.jsonl
```

where `<encoded-path>` is the absolute working directory path with `/` replaced by `-`. Example:

```
~/.claude/projects/-Users-alice-code-myapp/a1b2c3d4-e5f6-7890-abcd-ef1234567890.jsonl
```

Each line in the JSONL file is a JSON object. altergo only reads lines where `"type": "human"` to extract the last user message for the session preview. It reads only the last 8KB of the file to avoid parsing multi-megabyte session histories in full.

The session ID (the filename stem) is a UUID that Claude Code generates. altergo passes it verbatim to `claude --resume <id>`.

Because `projects/` is symlinked to the same target for every account, sessions are globally visible across all altergo accounts regardless of which account created them.

---

## `--setup` and `--teardown` idempotency

`do_setup()` is safe to run multiple times:

- If a symlink already points to the correct target, it prints a confirmation and moves on.
- If a symlink points to a different target, it warns and skips — it does not silently redirect an existing symlink.
- If the destination exists as a real directory (not a symlink), it warns and skips — it does not delete real data.
- If the source (`~/.claude/<name>`) does not exist yet, it skips the entry — it does not create dangling symlinks.

`do_teardown()` removes only symlinks. It does not touch real files or directories. `.credentials.json` is never removed by teardown.

---

## Python version compatibility

altergo targets Python 3.9+ (`requires-python = ">=3.9"` in pyproject.toml). The CI matrix runs against 3.9, 3.10, 3.11, 3.12, and 3.13 on both ubuntu-latest and macos-latest.

No type annotations are used in the source; the code predates the decision to add them and the implementation is short enough that they are not necessary for comprehension.
