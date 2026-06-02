# Architecture

**Audience:** anyone debugging altergo, auditing what it touches, or just curious about the design.

altergo isolates AI CLI accounts by overriding `HOME` and symlinking everything inside the provider's dot-dir back to your real home. The result: per-account credentials, shared session history.

---

## The mechanism

Each AI CLI stores credentials and state under a dot-dir in `$HOME`:

| Provider | Dot-dir | Credentials file |
|---|---|---|
| Claude Code | `~/.claude/` | `.credentials.json` |
| Gemini CLI | `~/.gemini/` | `oauth_creds.json` |
| Codex CLI | `~/.codex/` | `auth.json` |
| GitHub Copilot | `~/.copilot/` | `config.json` |

The naive fix — `alias claude-work='HOME=~/work-claude-home claude'` — isolates credentials but also isolates everything else: session history, settings, `CLAUDE.md`, agents, skills. You end up with two parallel universes that have to be maintained in lockstep.

altergo does the selective version. Two mechanisms working together:

1. **Override `HOME`** to `~/.altergo/accounts/<account>/` before `exec`-ing the provider. The provider reads its `.credentials.json` from there — a real, isolated file.
2. **Symlink everything else** inside the account's dot-dir back to `~/.claude/` (or `.gemini/`, `.codex/`, `.copilot/`). Same inode, no sync step. Sessions are keyed by working-directory path, not by account — so they're naturally shared.

---

## Runtime directory layout

```
~/.claude/                        ← Primary account (unchanged)
    .credentials.json
    projects/  tasks/  skills/  agents/  commands/  …
    settings.json  CLAUDE.md  keybindings.json

~/.altergo/
    .altergo.json                 ← Global settings (theme, shared-credential overrides)
    starred.json                  ← Starred sessions
    last_session.json             ← Last-exited session snapshot
    version_check.json            ← Daily PyPI version cache
    accounts/
        default/                  ← HOME for plain `altergo`
            account.json          ← v3 metadata
            .claude/
                .credentials.json ← REAL, isolated
                .claude.json      ← REAL — mcpServers bidirectionally merged
                projects/         → symlink → ~/.claude/projects/
                settings.json     → symlink → ~/.claude/settings.json
                CLAUDE.md         → symlink → ~/.claude/CLAUDE.md
                …                 → all other dirs/files symlinked
            .aws/                 → symlink → ~/.aws/ (if shared)
            .config/gh/           → symlink → ~/.config/gh/ (if shared)
            …
        work/                     ← HOME for `altergo work`
            account.json
            .claude/              ← or .gemini/, .codex/, .copilot/ (one per active provider)
                .credentials.json ← REAL, isolated
                projects/         → symlink → ~/.claude/projects/ (same target as default)
                …
```

CLI-credential symlinks (`.aws/`, `.config/gh/`, `.docker/`, etc.) live at the **account-home level**, not inside the provider dot-dir — so any tool that reads `$HOME` finds them, not just the provider CLI.

---

## Three on-disk treatments

| Treatment | Examples | Rule |
|---|---|---|
| **Real & isolated** | `.credentials.json`, `account.json`, the dot-dir itself, `plugins/`, `paste-cache/` | Per-account data that must differ |
| **Symlinked & shared** | `projects/`, `tasks/`, `agents/`, `skills/`, `commands/`, `settings.json`, `CLAUDE.md`, `keybindings.json`, `cache/`, `session-env/`, … | One inode, every account reads and writes it |
| **Bidirectionally merged** | `.claude.json` → only the `mcpServers` key | Identity stays isolated; MCP server registrations propagate |

---

## Provider matrix

Since v0.40.0 one account can host multiple providers. `account.json` lists the active providers and the default; each active provider gets its own dot-dir.

| Provider | Dot-dir | Credentials file | Symlinked dirs | Symlinked files | Notes |
|---|---|---|---|---|---|
| Claude Code | `.claude/` | `.credentials.json` | `projects/`, `tasks/`, `session-env/`, `file-history/`, `shell-snapshots/`, `agents/`, `commands/`, `skills/`, `plans/`, `cache/` | `settings.json`, `CLAUDE.md`, `keybindings.json` | `.claude.json` is a real file with bidirectional `mcpServers` merge — see [MCP server sync](#mcp-server-sync) |
| Gemini CLI | `.gemini/` | `oauth_creds.json` | `tmp/`, `commands/` | `settings.json`, `GEMINI.md` | — |
| Codex CLI | `.codex/` | `auth.json` | `sessions/`, `rules/` | `config.toml`, `AGENTS.md`, `AGENTS.override.md` | Email extracted from `id_token` JWT for display |
| GitHub Copilot | `.copilot/` | `config.json` | `session-state/`, `agents/`, `skills/`, `hooks/` | `mcp-config.json`, `lsp-config.json` | `mcp-config.json` is symlinked, not merged |

---

## CLI-tool credentials (catalog)

These are shared by default across all accounts — toggle per-tool in `altergo --settings`. They sit at the account-home level (e.g., `~/.altergo/accounts/work/.aws`), so any tool that reads `$HOME` picks them up.

| Entry | Path(s) | Default |
|---|---|---|
| AWS CLI | `.aws` | On |
| Google Cloud | `.config/gcloud` | On |
| Azure CLI | `.azure`, `.config/azure` | On |
| Docker | `.docker` | On |
| Kubernetes | `.kube` | On |
| Terraform | `.terraform.d` | On |
| GitHub CLI | `.config/gh` | On |
| GitLab CLI | `.config/glab` | Off |
| npm | `.npmrc` | Off |
| SSH keys | `.ssh` | Off |
| Git identity | `.gitconfig` | Off |
| GPG keys | `.gnupg` | Off |

Package managers (pip, cargo, gem, yarn, pnpm, composer, go, maven, gradle, bundler) are **off by default** — each account gets a clean install cache. See [settings.md](settings.md) for the full list.

---

## Why `os.execvpe` and not `subprocess`

```python
def launch_claude(account, args=None):
    env = _build_alt_env(account)
    os.execvpe(claude_path, [claude_path, *args], env)
```

`execvpe` replaces the current process image — no fork, no wrapper, no signal forwarding. The shell sees the provider's PID directly. The terminal is owned by the provider without any intermediary.

Using `subprocess` would leave a Python parent alive that would need to forward SIGINT/SIGTERM/SIGWINCH, pipe stdio without corrupting curses output, and propagate the exit code. None of those problems exist with `exec`.

---

## Why `pwd.getpwuid(os.getuid()).pw_dir` and not `os.environ["HOME"]`

```python
MAIN_HOME = Path(pwd.getpwuid(os.getuid()).pw_dir)
```

If you run `altergo` from inside an `altergo shell` session, `$HOME` is already overridden to the account directory. Reading it would make altergo treat the account as the primary home and create nested account directories.

The passwd database is keyed by uid, not env vars, so it returns the real home regardless of what `$HOME` says. This makes altergo re-entrant.

---

## The PATH guard

Claude Code health-checks `$HOME/.local/bin` on startup. With HOME overridden, that resolves to `~/.altergo/accounts/<n>/.local/bin`, which usually doesn't exist. `_build_alt_env` prepends it to PATH — **but only if the directory actually exists on disk**:

```python
if (account_home / ".local" / "bin").exists():
    env["PATH"] = str(account_home / ".local" / "bin") + ":" + env.get("PATH", "")
```

The guard avoids a PATH-injection vector: an unconditional prepend would let anyone with write access to your home create a malicious binary in a directory that previously didn't exist and have it take precedence over system tools. The directory only gets populated by `claude update`, which installs to `$HOME/.local/bin` legitimately.

---

## Argument routing

```python
_KNOWN_COMMANDS = frozenset([
    "shell", "use", "portal",
    "--resume", "--recall", "--search", "--config", "--rename",
    "--teardown", "--settings", "--version", "--use", "--launch",
    "--theme", "--star", "-h", "--help", "--",
])
```

`_looks_like_account(token)` returns True if the token doesn't start with `-`, isn't in `_KNOWN_COMMANDS`, and matches `^[a-zA-Z0-9][a-zA-Z0-9_-]*$`. If True, `main()` then checks whether `ACCOUNTS_DIR / token` exists on disk:

- **Exists** → consume as account name, route the rest of the args under that account.
- **Doesn't exist** → exit with a clear error and a hint (`Run 'altergo --config <token>' to create it`).

So `altergo --dangerously-skip-permissions` passes the flag through to claude (starts with `-`), while `altergo work` routes to the work account, and `altergo wokr` (typo) gets an actionable error instead of silently passing `wokr` to claude as a flag.

---

## MCP server sync

`~/.claude.json` holds two things that pull in opposite directions:

- `mcpServers` — registrations you add with `claude mcp add`. You want these shared across accounts.
- `oauthAccount` — per-account identity. You must **not** share it; that would leak identity across accounts.

altergo's solution: `.claude.json` is a real file in each account, and `_sync_claude_mcps()` runs at every `--config` and every Claude launch. It:

1. Reads `mcpServers` from `~/.claude.json` (main) and the account's `.claude.json`.
2. Union-merges them; on key collision, the account entry wins.
3. Atomically writes the merged map back to both files (tmp file + `os.replace`).
4. Leaves `oauthAccount` and every other key untouched on both sides.

Register an MCP server once, from any account, and every account sees it. OAuth identity stays per-account.

---

## Session discovery and recall

`get_sessions()` scans all four providers and returns a merged list sorted by modification time:

| Provider | Path pattern | Format |
|---|---|---|
| Claude Code | `~/.claude/projects/<dash-encoded>/*.jsonl` | JSONL |
| Codex CLI | `~/.codex/sessions/YYYY/MM/DD/*.jsonl` | JSONL |
| Gemini CLI | `~/.gemini/tmp/<project>/chats/*.json` | Single JSON |
| GitHub Copilot | `~/.copilot/session-state/<UUID>/` | `workspace.yaml` + `events.jsonl` |

Preview extraction reads only the last 8KB of each session file and scans backward for the most recent `"type": "human"` message — fast even on multi-MB sessions.

**cwd-on-recall**: when you pick a session, altergo launches the provider with the session's saved working directory. If that directory no longer exists, altergo prints a dim notice and falls back to your current cwd. Same behavior for `--recall` and `--search`.

---

## Account lifecycle

`configure_account(name, provider)` is idempotent and self-healing. It:

1. Refuses the reserved `native` name.
2. Creates `account_home` and the provider's dot-dir if absent.
3. For each entry in `PROVIDERS[provider]["symlink_dirs"]`, runs `_ensure_symlinked_dir()`. Four cases handled:

   | Case | State | Action |
   |---|---|---|
   | a | Already a symlink to the correct target | No-op |
   | a' | Symlinked elsewhere | Leave alone — don't clobber a user's intentional link |
   | b | Absent | Create source if missing, create symlink |
   | c | Real, empty dir | `rmdir`, create symlink |
   | d | Real, non-empty + main absent/empty | Warn and skip (closes the upgrade-data-loss vector from pre-v0.35.3) |
   | e | Real, non-empty + main also non-empty | Merge into main; on collision, quarantine the account copy under `<name>.altergo-conflict/` |

4. Symlinks each entry in `symlink_files` (unlinking any existing destination first).
5. Runs `_sync_claude_mcps()` for Claude accounts.
6. Applies the CLI-credentials catalog at the account-home level (honors per-tool overrides in `.altergo.json`).
7. **macOS only:** applies the keychain mode (`keychain` or `none`) — see [keychain-isolation.md](keychain-isolation.md).
8. Writes `account.json` (v3).

`do_teardown()` removes only the symlinks it created. `.credentials.json` is never touched.

### account.json (v3)

```json
{
  "version": 3,
  "providers": ["claude", "codex"],
  "default_provider": "claude",
  "created": "2026-04-20T18:32:11",
  "keychain": "keychain"
}
```

| Field | Notes |
|---|---|
| `version` | Always `3` for v3 files on disk |
| `providers` | Ordered list of installed providers (`claude`, `gemini`, `codex`, `copilot`) |
| `default_provider` | What bare `altergo <account>` launches. Must be in `providers`. |
| `created` | ISO 8601, set at creation, never overwritten |
| `keychain` | macOS only. `"keychain"` (default) or `"none"`. Absent = default. |

v2 files (`{"version": 2, "provider": "claude"}`) load forever via `_coerce_meta_v3` and present as single-provider v3 in memory. They're rewritten to v3 only when the user runs `--add-provider`, `--remove-provider`, `--default-provider`, or `--keychain`.

---

## Account name rules

`validate_account_name()` enforces:

- Match `^[a-zA-Z0-9][a-zA-Z0-9_-]*$`
- ≤ 64 characters
- Not reserved: `default`, `main`, `list`, `new`, `rm`, `shell`, `config`, `setup`, `teardown`, `help`, `version`, `legacy`, `backup`, `migrate`, `use`, `native`

Validation only runs at `--config` time; lookups in `main()` just check whether the directory exists.

---

## Environment modifications at launch

`_build_alt_env(account)` returns a modified **copy** of `os.environ` — the live environment is never mutated.

| Variable | Modification | When |
|---|---|---|
| `HOME` | Set to `~/.altergo/accounts/<account>` | Always |
| `PATH` | Prepend `~/.altergo/accounts/<account>/.local/bin` | Only if it exists and isn't already in PATH |
| `PS1` / `PROMPT` | Prepend `(altergo:<account>) ` | Only in `launch_shell()` |
| `CLAUDE_CODE_OAUTH_TOKEN` | Set from the account's `.oauth-token` file, or stripped | Only for claude accounts; see [ssh-auth.md](ssh-auth.md) |

On macOS, the keychain unlock for `keychain`-mode accounts runs here too — silent if the unlock entry is in your real login keychain.

`_find_claude()` runs before any PATH modification: `shutil.which("claude")` against the original PATH, with hardcoded fallbacks (`~/.local/bin/claude`, npm global prefix, Homebrew Apple Silicon, Homebrew Intel). The absolute path is passed to `execvpe` so no PATH search happens at exec time.

---

## Native passthrough

`altergo native` (and `altergo native <provider>`) skips the env override entirely — HOME stays as-is, no symlinks are traversed, no MCP merge runs. Useful for quick sanity checks ("is this bug altergo's fault or the provider's?") and one-off scripts. If you reach for it often, prefer `altergo --config <account>` and a named account.

---

## Shell and command passthrough

```bash
altergo work shell             # interactive shell with HOME=account
altergo work -- gh auth login  # one command with HOME=account
```

Both use `execvpe` — no wrapper, no overhead, exit codes propagate. Use this to authenticate tools (`gh`, `git`, SSH) inside a specific account's environment.

---

## tmux portals

`altergo portal <account>` wraps the launch in a named tmux session (`<project>/<account>/<provider>`). Sessions survive SSH disconnects and detach/reattach cleanly. altergo detects `$TMUX` and skips wrapping inside an existing session. Without tmux installed, it falls back to a plain launch with an install hint.

`altergo --settings` → Behavior → tmux sessions makes every launch behave this way.

---

## Data flow at a glance

```
altergo [account] [args]
│
├─ Resolve MAIN_HOME via passwd (immune to $HOME override)
│
├─ main() parses sys.argv:
│   ├─ -h / --version / --config / --teardown / --settings → handled, exit
│   ├─ --recall → picker → launch_claude(account-of-picked-session, ["--resume", id])
│   ├─ --resume [id] → pass through to provider
│   ├─ _looks_like_account(args[0]) && dir exists → account = args[0]
│   ├─ [account] shell → launch_shell(account)
│   ├─ [account] -- <cmd> → launch_command(account, args)
│   └─ otherwise → launch_claude(account, args)
│
└─ launch_claude(account, args)
    ├─ _find_claude() against unmodified PATH
    ├─ _build_alt_env(account)
    │   ├─ env.copy()
    │   ├─ env["HOME"] = ~/.altergo/accounts/<account>
    │   ├─ prepend .local/bin to PATH if it exists
    │   └─ macOS: unlock per-account keychain (keychain mode, no token)
    └─ os.execvpe(claude, [claude, *args], env)
        │
        └─ Process image replaced. Provider reads:
             $HOME/.claude/.credentials.json   ← REAL, isolated
             $HOME/.claude/projects/            → symlink → ~/.claude/projects/
             $HOME/.claude/settings.json        → symlink → ~/.claude/settings.json
             $HOME/.claude/CLAUDE.md            → symlink → ~/.claude/CLAUDE.md
             $HOME/.aws/                        → symlink → ~/.aws/ (if shared)
             …
```

---

## Source map

The codebase moved from a single `altergo.py` to a package. The top-level `altergo.py` is now a compatibility stub that does `from altergo.cli import main`.

```
altergo/
    cli.py            ← entry point, argument dispatch
    accounts.py       ← account lifecycle, provider setup, symlink plumbing, MCP sync
    sessions.py       ← multi-provider session discovery and parsing
    runner.py         ← launch paths (launch_claude/shell/command), env setup, tmux
    persistence.py    ← settings, starred, update cache, theme on disk
    keychain.py       ← macOS per-account keychain lifecycle
    constants.py      ← PROVIDERS, CATALOG, path constants
    theme.py          ← color system
    ui.py             ← banner, help, formatting
    tui/
        launcher.py     ← account/provider picker, first-run onboarding
        picker.py       ← --recall session resume TUI
        search.py       ← --search full-text TUI
        config_tui.py   ← --config dialogs
        settings_tui.py ← --settings multi-page TUI
        common.py       ← shared curses helpers
altergo.py            ← compatibility stub
altergo_greetings.py  ← greetings, time-of-day copy, spinners (module-level, not in package)
```

---

## Unmanaged state

Two directories accumulate inside the account's provider dot-dir from normal usage and aren't touched by altergo:

- `paste-cache/` — ephemeral clipboard buffer. Per-account is fine.
- `plugins/` — plugin state. Per-account by default. If you want plugins shared, manually symlink `plugins/` after `altergo --config`.

---

## Further reading

- [settings.md](settings.md) — every setting, where it lives, what it toggles
- [keychain-isolation.md](keychain-isolation.md) — macOS keychain modes, lifecycle, threat model
- [ssh-auth.md](ssh-auth.md) — using altergo over SSH (OAuth token bridge)
- [migration.md](migration.md) — upgrade notes
- [faq.md](faq.md) — common messages
