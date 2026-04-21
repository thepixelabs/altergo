# Architecture reference

**Applies to:** altergo v0.40.0+  
**Audience:** Engineers maintaining altergo, debugging symlink issues, or auditing what altergo touches on disk.

For a prose explanation of why the architecture is designed this way, see [how-it-works.md](how-it-works.md).

---

## Repository layout

```
altergo/
    altergo.py              ← Main implementation (~7959 lines)
    altergo_greetings.py    ← Greeting messages, time-of-day copy, theme spinners
    pyproject.toml          ← Package metadata, entry point, dependencies
    tests/
        test_smoke.py       ← Core functionality tests
        test_integration.py ← Integration tests for config, teardown, launch
        test_new_features.py ← Tests for newer features
        test_keychain.py    ← macOS keychain isolation tests (60 tests)
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
            ci.yml          ← Lint (ruff) + test matrix (Python 3.10–3.13, ubuntu + macos)
            release.yml     ← PyPI publish on tag push
            pages.yml       ← GitHub Pages deploy
            security.yml    ← Dependency security scan
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
| Account helpers | `resolve_account()`, `list_accounts()`, `load_account_meta()`, `save_account_meta()` | Account directory resolution, v3 account.json I/O |
| Providers | `PROVIDERS`, `CATALOG` | Multi-provider support, credential sharing catalog |
| Symlink plumbing | `_ensure_symlinked_dir()`, `_ensure_home_file_symlink()`, `_sync_claude_mcps()` | Per-provider directory symlinks, home-level file symlinks, MCP bidirectional merge |
| Self-heal (dormant) | `_sweep_existing_accounts()` | Repair pass kept for tests; no longer invoked from launch paths (see below) |
| Settings helpers | `load_settings()`, `save_settings()`, `_load_bool_setting()` | Settings persistence |
| Preferences | `_load_bool_setting()` | Boolean settings: greeting, goodbye, animation |
| Update checker | `load_update_check_enabled()`, PyPI cache | Background version check |
| Config / Teardown | `do_config()`, `do_teardown()`, `do_delete_account()` | Account creation, removal, and full delete |
| Multi-provider | `do_add_provider()`, `do_remove_provider()`, `do_default_provider()` | Provider list mutations |
| Session discovery | `get_sessions()`, `_discover_claude_sessions()`, `_discover_codex_sessions()`, `_discover_gemini_sessions()`, `_discover_copilot_sessions()` | Per-provider JSONL session scanning, unified under `get_sessions()` |
| Session picker | `_draw_picker()` | Curses session resume TUI (starred filter, provider filter, sort) |
| Search | `_draw_search()` | Full-text conversation search |
| Settings TUI | `_draw_settings()`, `interactive_settings()` | Multi-page settings (Appearance, Behavior, Credentials) |
| Launcher | `_draw_launcher()`, `interactive_launcher()` | Provider + account picker |
| Onboarding | `_first_run_onboarding()` | First-run account creation flow |
| Keychain | `_create_account_keychain()`, `_write_keychain_prefs()`, `_unlock_account_keychain()` | macOS per-account keychain lifecycle (v0.41.0+) |
| Launch | `launch_claude()`, `launch_shell()`, `launch_command()` | Provider binary execution |
| `main()` | `main()` | Argument dispatch |

---

## Runtime directory layout

The following describes the filesystem state after `altergo --config` has been run successfully.

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
    commands/
    skills/
    plans/
    cache/
    settings.json
    CLAUDE.md
    keybindings.json
```

### Accounts directory

All altergo accounts live under `~/.altergo/accounts/`. The `default` account is used when you run `altergo` with no account name. Named accounts (e.g. `work`, `client-a`) are created with `altergo --config <name>` (positional form since v0.34.0).

```
~/.altergo/
    .altergo.json                   ← Settings file (global, shared across all accounts)
    version_check.json              ← PyPI version cache (daily refresh; see "Network activity")
    accounts/
        default/                    ← Default account home (HOME for plain `altergo`)
            account.json            ← v3 metadata: {"version": 3, "providers": [...], "default_provider": "claude"}
            .claude/                ← Provider dot-dir (only present for Claude accounts)
                .credentials.json   ← Real file. Isolated credentials. Created on first login.
                .claude.json        ← Real file. `mcpServers` bidirectionally merged with main;
                                    ←   `oauthAccount` kept per-account. See "MCP server sync".
                projects/           ← Symlink → ~/.claude/projects/
                tasks/              ← Symlink → ~/.claude/tasks/
                session-env/        ← Symlink → ~/.claude/session-env/
                file-history/       ← Symlink → ~/.claude/file-history/
                shell-snapshots/    ← Symlink → ~/.claude/shell-snapshots/
                agents/             ← Symlink → ~/.claude/agents/
                commands/           ← Symlink → ~/.claude/commands/
                skills/             ← Symlink → ~/.claude/skills/
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
            account.json
            .claude/                ← (or .gemini/, .codex/, .copilot/ — one dot-dir per active provider; v3 accounts can have multiple)
                .credentials.json   ← Real file. Isolated credentials.
                projects/           ← Symlink → ~/.claude/projects/ (same target)
                ...                 ← Same symlink structure as default
            .aws/                   ← Symlink → ~/.aws/ (same shared credentials as default)
            ...

    # Written by the provider CLI during normal usage (not managed by altergo):
    accounts/default/.local/bin/claude     ← Created if 'claude update' runs inside altergo
    accounts/default/Library/Application Support/claude/  ← macOS only
```

### On-disk treatment of an account

Three distinct disciplines are at play inside an account home:

```
~/.claude/  (primary, real — user's real Claude home, never renamed)
├── .credentials.json        ◄── REAL (never linked, never touched by altergo)
├── .claude.json             ◄── REAL (mcpServers bidirectionally synced; oauthAccount kept local)
├── projects/ tasks/ skills/ ◄── REAL (same inode as every account → shared)
├── settings.json CLAUDE.md  ◄── REAL (same inode as every account → shared)
└── plugins/ paste-cache/    ◄── REAL (NOT shared; unmanaged)

~/.altergo/accounts/work/.claude/
├── .credentials.json  ← REAL, isolated per account
├── .claude.json       ← REAL, merged with ~/.claude.json (mcpServers only)
├── projects/ → symlink → ~/.claude/projects/
├── settings.json → symlink → ~/.claude/settings.json
└── plugins/           ← REAL, isolated (not managed)
```

Three treatments:
- **Real & isolated** — per-account data that MUST differ (`.credentials.json`, `account.json`, the dot-dir itself, provider plugin caches).
- **Symlinked & shared** — session history, agent/skill/command definitions, UI settings. One inode, N accounts read and write it.
- **Bidirectionally merged** — only `.claude.json`, and only its `mcpServers` key. See [MCP server sync](#mcp-server-sync).

### Settings file placement

`~/.altergo/.altergo.json` sits at the `~/.altergo/` level, above `accounts/`. It is global — one file shared across all accounts. This is intentional: credential-sharing preferences (AWS, Docker, etc.) apply to the relationship between the main home and the alt account, not to a specific account. See [how-it-works.md](how-it-works.md) for the rationale.

Additional state files at `~/.altergo/` level:

| File | Purpose |
|---|---|
| `~/.altergo/starred.json` | Starred-session catalog. Written by `altergo --star`. |
| `~/.altergo/last_session.json` | Snapshot of the last-exited session. Written at session exit; read by `altergo --star` (no-arg form). |
| `~/.altergo/version_check.json` | PyPI version cache (daily refresh). |

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
- Must not be in `_RESERVED_NAMES`: `default`, `main`, `list`, `new`, `rm`, `shell`, `config`, `setup`, `teardown`, `help`, `version`, `legacy`, `backup`, `migrate`, `use`

`validate_account_name()` is called only during `altergo --config <name>`. It is not called during account lookup in `main()` — if the directory does not exist, the user sees a "not found" error with a hint to run `altergo --config <name>`.



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
    "shell", "use", "portal",
    "--resume", "--recall", "--search", "--config", "--rename",
    "--teardown", "--settings", "--version", "--use", "--launch",
    "--theme", "--star", "-h", "--help", "--"
])

_looks_like_account(token):
    → False if token starts with "-"
    → False if token is in _KNOWN_COMMANDS
    → True  if token matches ^[a-zA-Z0-9][a-zA-Z0-9_-]*$
```

If `_looks_like_account` returns `True`, `main()` checks whether `ACCOUNTS_DIR / token` exists on disk. If it does not exist, altergo exits with a clear error and a hint. If it does exist, the token is consumed as the account name and the remaining arguments are processed as the sub-command or claude flags.

This means `altergo --dangerously-skip-permissions` passes `--dangerously-skip-permissions` straight through to claude (starts with `-`, so not an account name), while `altergo work` routes to the `work` account.

---

## Historical: legacy auto-migration (removed)

Pre-v0.35.3, altergo ran a `detect_legacy()` / `migrate_legacy()` pair at the top of `main()` to upgrade v0.4.x single-account layouts in place. It was removed in v0.35.3 because all users were already on the N-account layout and the code was dead weight. No code path in the current tree calls it.

Two adjacent pieces of history are worth knowing when diagnosing an upgrade:

- **v0.22.0 silent un-symlink of `.claude.json`** — accounts created between v0.21.2 and v0.22.0 had `.claude.json` as a symlink via `symlink_home_files`. `_sync_claude_mcps` detects that case, reads the content through the link, removes the symlink, and writes a real file with the merged `mcpServers`. Content is preserved; the rewrite is atomic.
- **v0.35.3 dead-code removal** — the unconditional `_sweep_existing_accounts()` call from `main()` and from `launch_claude()` was removed. The function itself is kept (tests exercise it as a repair-path oracle), but no production code path calls it. If an operator ever needs to force a sweep across every account, they can drive it from a Python shell; there is no CLI flag for it.

---

## Symlink reference table

Every entry in the per-provider `symlink_dirs`/`symlink_files` lists and in `CATALOG` is described here. The module-level `SYMLINK_DIRS` / `SYMLINK_FILES` constants (altergo.py:844-863) now exist only as the fallback used by `_sweep_existing_accounts` for legacy accounts without `account.json`; the authoritative lists live in the `PROVIDERS` dict (altergo.py:868-915).

### Provider matrix

Since v0.40.0 one account can declare multiple providers. The v3 `account.json` stores a `providers` list and a `default_provider` — see [v3 account.json schema](#v3-accountjson-schema-v0400) below. Each active provider gets its own dot-dir in the account home.

| Provider | dot_dir | Credentials file | Symlinked dirs | Symlinked files | Per-provider behaviours |
|---|---|---|---|---|---|
| Claude Code | `.claude/` | `.credentials.json` | `projects/`, `tasks/`, `session-env/`, `file-history/`, `shell-snapshots/`, `agents/`, `commands/`, `skills/`, `plans/`, `cache/` | `settings.json`, `CLAUDE.md`, `keybindings.json` | `.claude.json` is a **real file** with bidirectional `mcpServers` merge — see [MCP server sync](#mcp-server-sync). |
| Gemini CLI | `.gemini/` | `oauth_creds.json` | `tmp/`, `commands/` | `settings.json`, `GEMINI.md` | None. |
| Codex CLI | `.codex/` | `auth.json` | `sessions/`, `rules/` | `config.toml`, `AGENTS.md`, `AGENTS.override.md` | Email address extracted from `id_token` JWT for display. |
| GitHub Copilot | `.copilot/` | `config.json` | `session-state/`, `agents/`, `skills/`, `hooks/` | `mcp-config.json`, `lsp-config.json` | `mcp-config.json` is **symlinked**, not merged. If Copilot ever embeds per-account identity into this file, that would leak identity across accounts (cross-check before shipping the next Copilot release). |

### Inside `account_home/.claude/` — shared session data (Claude `symlink_dirs`)

| Directory | Contains | Why shared |
|---|---|---|
| `projects/` | Session JSONL files, one subdirectory per working-directory path | Sessions are indexed by filesystem path, not by account. All accounts work on the same codebases. Sharing this is the primary purpose of altergo. |
| `tasks/` | Task files from Claude's task system | Tasks are scoped to a project, not to an account. You want the same task context regardless of which account is active. |
| `session-env/` | Shell environment snapshots captured at session start | These are per-session, not per-account. Sharing gives all accounts access to the same environment history. |
| `file-history/` | File access history | Context about which files were recently opened. Account-agnostic. |
| `shell-snapshots/` | Shell state captures | Per-session snapshots. No reason to isolate by account. |
| `agents/` | Agent definition files | Agent configurations are per-project. Sharing means you do not need to recreate agents in each account. |
| `commands/` | Custom slash-command markdown files | User-authored prompt templates with no credential or session state. |
| `skills/` | User skill definitions | User-authored content (markdown + scripts) with no credential or session state. |
| `plans/` | Plan files | Plans are project work context, not account state. |
| `cache/` | Response cache | Content-addressed cache. Sharing means no account re-fetches what another already fetched, reducing latency and API cost. |

### Inside `account_home/.claude/` — shared config (Claude `symlink_files`)

| File | Contains | Why shared |
|---|---|---|
| `settings.json` | Editor settings, feature flags, UI preferences, **hooks** | Settings express personal workflow preferences, not account state. Note that `settings.json` can declare hook scripts — see [SECURITY.md](../SECURITY.md) for the threat model implications. |
| `CLAUDE.md` | Global system prompt and instructions for Claude | Instructions are how you configure Claude's behavior. All accounts should follow the same instructions. Shared `CLAUDE.md` is a cross-account prompt-injection channel — treat its contents as trusted. |
| `keybindings.json` | Custom key mappings | Muscle memory is account-agnostic. |

### `account_home/.claude/.claude.json` — real file, bidirectionally merged

| File | Contains | Treatment |
|---|---|---|
| `.claude.json` | `mcpServers` (MCP server registrations) AND `oauthAccount` (per-account identity metadata) | **Not symlinked.** `mcpServers` is bidirectionally merged with `~/.claude.json` at `--config` and at every Claude launch; `oauthAccount` is left untouched on both sides so each account keeps its own identity. See [MCP server sync](#mcp-server-sync). |

### At `account_home/` level — shared CLI tool credentials (`CATALOG`)

Claude credentials stay isolated per account. AWS, GCP, Azure, Docker, Kubernetes, Terraform, and GitHub CLI credentials are shared across accounts by default — configurable per-entry via `altergo --settings`.

These symlinks live directly in the account home (e.g., `~/.altergo/accounts/work/.aws`), not inside `.claude/`. This placement means they are available to any tool that reads `$HOME` — not just the active provider CLI.

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
| `~/.altergo/accounts/<name>/.claude/.claude.json` | Holds `oauthAccount` (per-account identity). Symlinking would leak identity across accounts. `mcpServers` inside it is bidirectionally synced separately. |
| `~/.altergo/accounts/<name>/account.json` | v3 metadata: providers list, default_provider, optional keychain flag. Written by `save_account_meta`. v2 files (`{"version": 2, "provider": "..."}`) load forever but are only rewritten to v3 on mutation. |

### Unmanaged (written by the provider CLI, not tracked by altergo)

| Path | Notes |
|---|---|
| `~/.altergo/accounts/<name>/.claude/paste-cache/` | Ephemeral. Safe to leave isolated. |
| `~/.altergo/accounts/<name>/.claude/plugins/` | Plugin state is isolated per-account. If you use plugins and want them shared, manually symlink this directory after running `altergo --config`. |

---

## Environment modifications at launch

`_build_alt_env(account)` returns a modified copy of `os.environ`. It never mutates the live environment. The modified dict is passed to `os.execvpe` and becomes the child process's environment.

| Variable | Modification | Condition |
|---|---|---|
| `HOME` | Set to `~/.altergo/accounts/<name>` | Always |
| `PATH` | `~/.altergo/accounts/<name>/.local/bin` prepended | Only if that directory exists on disk AND is not already in PATH |
| `PS1` | `(altergo:<name>) ` prefix prepended | Only in `launch_shell()`, only for bash/sh |
| `PROMPT` | `(altergo:<name>) ` prefix prepended | Only in `launch_shell()`, only for zsh |

Additionally, before the environment dict is returned on macOS when keychain isolation is enabled, `_unlock_account_keychain(account_home, account)` is called. It reads the unlock password from the real login keychain (silent) and unlocks the per-account `login.keychain-db`. The keychain remains unlocked for the session. On `KeychainError`, `_build_alt_env` exits 1.

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
│   ├─ parse sys.argv[1:]
│   │   ├─ -h / --help      → show_help()           → sys.exit(0)
│   │   ├─ --version        → print version         → sys.exit(0)
│   │   ├─ --config [--name <n>]  → do_config(n)      → sys.exit(0)
│   │   ├─ --teardown [--name <n>] → do_teardown(n) → sys.exit(0)
│   │   ├─ --settings       → interactive_settings() → sys.exit(0)
│   │   │
│   │   ├─ --recall
│   │   │   └─ get_sessions() → interactive_picker() → user selects
│   │   │       ├─ selected  → _account_for_provider(s.provider) → launch_claude(acct, ["--resume", id])
│   │   │       └─ cancelled → sys.exit(0)
│   │   │
│   │   ├─ --resume [id]    → (falls through to launch_claude(account, args) — provider sees --resume)
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

## Session file formats

Since v0.40.0, `get_sessions()` scans all four providers. Each provider stores sessions differently:

| Provider | Path pattern | Format |
|---|---|---|
| Claude Code | `~/.claude/projects/<dash-encoded>/*.jsonl` | JSONL — one JSON object per line |
| Codex CLI | `~/.codex/sessions/YYYY/MM/DD/*.jsonl` | JSONL |
| Gemini CLI | `~/.gemini/tmp/<project>/chats/*.json` | Single-JSON document |
| GitHub Copilot | `~/.copilot/session-state/<UUID>/` (directory) | `workspace.yaml` + `events.jsonl` |

**Claude Code** encodes the working directory path with `/` replaced by `-`:

```
~/.claude/projects/-Users-alice-code-myapp/a1b2c3d4-e5f6-7890-abcd-ef1234567890.jsonl
```

Each line is a JSON object. altergo reads only lines where `"type": "human"` to extract the last user message for the preview. It reads only the last 8KB to avoid parsing multi-megabyte files in full. The session ID (filename stem) is a UUID passed verbatim to `claude --resume <id>`.

Because `projects/` is symlinked to the same target for every account, Claude Code sessions are globally visible across all altergo accounts regardless of which account created them.

**Resumed sessions launch in their saved cwd.** `launch_claude` accepts a `cwd` argument: if the path exists, the provider process starts with that working directory. If it no longer exists, altergo prints a dim notice and falls back to the caller's cwd. This applies to both `--recall` and `--search`.

---

## `--config` and `--teardown` idempotency

`do_config()` (altergo.py:2610-2730) is safe to run multiple times. Each symlinked directory passes through `_ensure_symlinked_dir()` (altergo.py:2394-2473), which handles four distinct cases:

| Case | State of `account_home/<dot>/name/` | Action |
|---|---|---|
| (a) | Already a symlink to the correct `~/.claude/name/` target | No-op. Print "already symlinked". |
| (a') | Symlinked elsewhere (different target) | Leave alone — do not clobber a user's intentional link. |
| (b) | Absent | Create `~/.claude/name/` if missing, create the symlink. |
| (c) | Real, empty directory | `rmdir` it, create the symlink. |
| (d) | Real, non-empty directory **and** shared store `~/.claude/name/` is absent/empty | Warn and skip. Prior versions moved content into the shared store silently; that was the upgrade-data-loss vector closed in v0.35.3. |
| (e) | Real, non-empty directory **and** shared store is also non-empty | Merge: move each entry to the shared store if absent there; on collision, move the account copy to `<name>.altergo-conflict/` quarantine. If the account dir ends up empty, promote to symlink. |

For home-level files (e.g. `.claude.json` in older code paths), `_ensure_home_file_symlink()` (altergo.py:2476-2506) is the file-level analogue with similar cases. `.claude.json` itself is now outside this path — it has its own bidirectional merge (next section).

`do_teardown()` removes only symlinks and (optionally) the account home itself; `.credentials.json` is never touched by teardown. See `do_teardown` in altergo.py:2733+ for the exact sequence.

The dormant `_sweep_existing_accounts()` (altergo.py:5077-5117) is the self-heal helper that used to run on every `--config` and launch pre-v0.35.3; it walks every account, reads `account.json`, and reruns `_ensure_symlinked_dir` per provider. It is still in the source (covered by tests) but no production code path calls it. If the repair behaviour is needed in a future release, re-wire it from `do_config` — do not re-introduce the unconditional call from `main()`.

---

## MCP server sync

`~/.claude.json` carries two logically distinct blobs in a single file:

1. `mcpServers` — MCP server registrations. Account-agnostic: if you add a new MCP server in one account, you probably want it everywhere.
2. `oauthAccount` — OAuth identity metadata (email, UUID, session). Per-account by definition. Symlinking the whole file would leak identity across accounts on the first write.

`_sync_claude_mcps(account_home)` (altergo.py:2509-2576, originally commit `eef91f6`) resolves this by doing a bidirectional merge restricted to `mcpServers`:

1. If `account_home/.claude.json` is a symlink (legacy shape from the short-lived v0.21.2 → v0.22.0 window), read the content through the link, unlink it, and rewrite as a real file. Content-preserving, atomic.
2. Load `mcpServers` from both `~/.claude.json` (main) and `account_home/.claude.json`. Either may be missing.
3. Merge: `{**main, **account}` — account wins on key collision, matching the usual "local overrides shared" ergonomics.
4. If the merged map differs from either side, rewrite that side via tmp-file + `os.replace`. Atomic per-side; no partial writes.
5. `oauthAccount` and every other top-level key are left exactly as they were on both sides.

The sync runs:
- Once at `--config` time for Claude accounts (altergo.py:2701-2703).
- Once at every Claude launch for non-native accounts (altergo.py:5275-5276).

No polling, no background thread. The merge is a few lines of JSON and runs inline on the launch path. For the `native` passthrough account, `account_home == MAIN_HOME`, so the sync is skipped — merging a file with itself is a no-op but would needlessly rewrite `~/.claude.json`.

---

## Account lifecycle

`do_config(account, provider)` is the creation and reconfiguration path. It executes roughly the following steps (altergo.py:2610-2730):

1. **Reject `native`.** The reserved `native` account is the zero-isolation passthrough; it cannot be configured.
2. **Resolve paths.** `resolve_account(name)` returns `(account_home, account_claude)`.
3. **Load prior metadata.** `load_account_meta(account_home)` — used only to preserve the `created` timestamp across re-runs.
4. **Create `account_home`** if absent.
5. **Create the provider dot-dir** (`~/.altergo/accounts/<n>/<dot_dir>/`).
6. **Symlink provider dirs** — for each entry in `PROVIDERS[provider]["symlink_dirs"]`, run through `_ensure_symlinked_dir()`.
7. **Symlink provider files** — for each entry in `PROVIDERS[provider]["symlink_files"]`, unlink any existing file at the destination (safe because these are config files the provider will re-fetch/re-render) and create the symlink. Skipped silently if the source doesn't exist yet.
8. **Symlink home-level files** — `PROVIDERS[provider].get("symlink_home_files", [])`. Currently empty for all providers; kept as an extension point.
9. **Report credentials state.** If the provider's credentials file is absent, print a hint to authenticate by running `altergo <name>`.
10. **MCP sync (Claude only).** `_sync_claude_mcps(account_home)`.
11. **Apply the CLI-credentials catalog.** For each `CATALOG` entry, honour the user's override in `.altergo.json` or fall back to `default_on`. Link or unlink accordingly at the account-home level (not inside the dot-dir).
12. **Keychain setup (macOS, opt-in).** If `--keychain isolated` was passed, or if the account already has `keychain: isolated` in its metadata, call `_create_account_keychain(account_home, account)`. This creates the per-account `login.keychain-db`, writes `com.apple.security.plist`, and stores the unlock password in the real login keychain. The function is idempotent — if the keychain file already exists it is reused. On `KeychainError`, `do_config` downgrades the setting to `shared` and continues. See [Keychain isolation reference](#keychain-isolation-reference) below.
13. **Write v3 metadata.** `account.json = {"version": 3, "providers": [...], "default_provider": "<id>", "created": <iso8601>}` via `save_account_meta`. The `keychain` key is included only when isolation is enabled.

There is no separate "repair" step in the current flow — `_ensure_symlinked_dir()` is itself idempotent and self-healing for the four cases enumerated above.

### v3 account.json schema (v0.40.0+)

Introduced in v0.40.0. v3 supports multiple providers per account:

```json
{
  "version": 3,
  "providers": ["claude", "codex"],
  "default_provider": "claude",
  "created": "2026-04-20T18:32:11",
  "keychain": "isolated"
}
```

| Field | Type | Notes |
|---|---|---|
| `version` | int | Always `3` for v3 files on disk |
| `providers` | list[str] | Ordered list of installed provider ids (`claude`, `gemini`, `codex`, `copilot`) |
| `default_provider` | str | Provider used by bare `altergo <name>`. Must be in `providers`. |
| `created` | str | ISO 8601 timestamp, set at account creation, never overwritten |
| `keychain` | str (optional) | `"isolated"` when macOS per-account keychain is enabled. Absent when `shared` (default). |

The `keychain` key is present only when keychain isolation is enabled (macOS, opt-in). When absent, the account uses the shared (default) keychain behavior.

**v2 read compatibility:** v2 files (`{"version": 2, "provider": "claude"}`) load forever. `load_account_meta()` reads a v2 file via `_coerce_meta_v3` and presents it in memory as a single-provider v3 record. The file on disk is only rewritten to v3 when the user mutates the account via `--add-provider`, `--remove-provider`, `--default-provider`, or `--keychain`. Read-only sessions leave v2 files untouched.

**Disk write triggers:** the disk file flips from v2 to v3 only when the user runs one of:

- `altergo <name> --add-provider <id>` — installs symlinks for a new provider; reconciles any account-local orphan data via `_reconcile_orphan_dot_dir` (MAIN wins on collision; losers archived under `<dot>.orphaned/<timestamp>/`); appends to `providers`.
- `altergo <name> --remove-provider <id> [--yes]` — removes provider symlinks; refuses to remove the last remaining provider; rebinds `default_provider` if needed.
- `altergo <name> --default-provider <id>` — updates `default_provider`; zero filesystem effect on dot-dirs.

`load_account_meta()` treats any of the following as a legacy Claude account:
- No `account.json` file but a `.claude/` directory exists
- `account.json` exists but cannot be parsed
- `account.json` has an unrecognized `version` or is missing required keys

All these cases fall through to a synthetic single-provider record in memory.

---

## Python version compatibility

altergo targets Python 3.10+ (`requires-python = ">=3.10"` in pyproject.toml). The CI matrix runs against 3.10, 3.11, 3.12, and 3.13 on both ubuntu-latest and macos-latest.

Type annotations are used selectively in the source — newer functions carry return type hints (e.g. `-> str | None`), while older functions predate the decision to add them.

---

## Keychain isolation reference

**macOS only. v0.41.0+.** The keychain subsystem lives at `altergo.py:~5843–5996`. It uses two Python stdlib imports added in v0.41.0: `plistlib` and `secrets`.

### Constants

| Constant | Value | Purpose |
|---|---|---|
| `_KC_SERVICE` | `"com.altergo.account-unlock"` | Service name for the unlock-password generic-password entry in the real login keychain |
| `_KC_GUID` | `"{87191ca3-0fc9-11d4-849a-000502b52122}"` | Apple CSSM DL GUID (constant across all Macs) used in `DLDBSearchList` plist |
| `_KC_SUBSERVICE_TYPE` | `6` (int) | CSSM_SERVICE_DL — identifies the keychain DL service type in the plist |

### File paths

| Path | Description |
|---|---|
| `<account_home>/Library/Keychains/login.keychain-db` | Per-account keychain file |
| `<account_home>/Library/Preferences/com.apple.security.plist` | DLDBSearchList plist; uses `~/Library/Keychains/login.keychain` tilde-form for `DbName` (no `-db` suffix, matches Apple convention) |

### Call sites

| Location | Function | What happens |
|---|---|---|
| `altergo.py:~2725` (`do_config`) | `_create_account_keychain` | Called when `--keychain isolated` is set. Creates keychain, writes plist, stores unlock entry. On `KeychainError`, downgrades to `shared` and continues. |
| `altergo.py:~2778` (`do_config`) | Downgrade path | When `--keychain shared` is passed and the account was previously isolated, deletes keychain and unlock entry. |
| `altergo.py:~2955` (`do_delete_account`) | `_delete_account_keychain` | Deletes the per-account keychain and unlock entry before removing the account home. On `KeychainError`, warns and continues — rmtree proceeds regardless. |
| `altergo.py:~5423` (`_build_alt_env`) | `_unlock_account_keychain` | Called before returning the env dict. Reads unlock password from login keychain (silent), unlocks per-account keychain. On `KeychainError`, exits 1. |

### Error paths

`KeychainError` is raised when `/usr/bin/security` exits non-zero or is not found. Each call site handles it differently:

| Call site | On `KeychainError` |
|---|---|
| `do_config` (create) | Downgrades account to `shared`, prints warning, continues |
| `do_config` (downgrade cleanup) | Prints warning, continues — account is already set to `shared` |
| `do_delete_account` | Prints warning, continues — rmtree removes remaining files |
| `_build_alt_env` | Exits 1 — cannot activate isolated account without unlocking its keychain |

### Idempotency

`_create_account_keychain` checks whether the keychain file already exists before creating it. If it does, creation is skipped and the existing keychain is reused. If the keychain file exists but the unlock entry in the login keychain is missing (orphan state), altergo warns and aborts — it cannot reconstruct a lost unlock password. Recovery: delete `<account_home>/Library/Keychains/login.keychain-db` and re-run `altergo --config <name> --keychain isolated`.

### Tests

`tests/test_keychain.py` — 60 tests covering create/delete/unlock/downgrade paths, orphan detection, plist structure, idempotency, and `KeychainError` error paths.
