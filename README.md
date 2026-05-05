<p align="center">
  <picture>
    <source media="(prefers-color-scheme: dark)" srcset="docs/logo-dark.svg">
    <source media="(prefers-color-scheme: light)" srcset="docs/logo-light.svg">
    <img alt="altergo" src="docs/logo-dark.svg" width="420">
  </picture>
</p>

<p align="center">
  <strong>Don't break flow. Switch accounts.</strong>
</p>

<p align="center">
  <a href="https://pypi.org/project/altergo/"><img alt="PyPI version" src="https://img.shields.io/pypi/v/altergo"></a>
  <img alt="Python 3.10+" src="https://img.shields.io/badge/python-3.10+-blue.svg">
  <a href="LICENSE"><img alt="License: PolyForm Shield 1.0.0" src="https://img.shields.io/badge/license-PolyForm%20Shield%201.0.0-blue.svg"></a>
  <a href="https://github.com/thepixelabs/altergo/actions/workflows/ci.yml"><img alt="CI" src="https://github.com/thepixelabs/altergo/actions/workflows/ci.yml/badge.svg"></a>
  <a href="https://github.com/thepixelabs/altergo/actions/workflows/release.yml"><img alt="CD" src="https://github.com/thepixelabs/altergo/actions/workflows/release.yml/badge.svg"></a>
  <img alt="Status: work in progress" src="https://img.shields.io/badge/work%20in%20progress-issues%20welcome-orange.svg">
</p>

<p align="center">
  Personal account, Pro subscription, side project — as many as you need.<br>
  <code>altergo personal</code> and you are in. Isolates credentials. Shares everything else.
</p>

> **Active development** — rough edges exist. If something breaks, [open an issue](https://github.com/thepixelabs/altergo/issues).

---

## <img src="docs/icons/why.svg" width="22" align="center"> Why altergo

You're mid-session and your AI hits a limit — or you need a different model for the next task. `altergo pro` swaps credentials in place. Same project, same history, no ramp-up. You just keep working.

**When altergo matters:**

- **Rate-limited. Not stopped.** You hit the wall mid-thought. Another account is ready. Switch credentials and drop back into the same session — no lost context, no starting over.
- **Thinker, then sprinter.** One account for deep architecture (extended reasoning, heavy models). Another for rapid execution (fast models, high throughput). Flip between them like gear ratios — same codebase, different operating mode.
- **Clients, credentials, firewalls.** Consultant with three engagements? OSS contributor with a personal account and a project account? Each gets isolated credentials. Shared history stays local. Nothing leaks sideways.
- **Work vs. personal.** Your employer provisions a managed AI account. You also have a personal one for side projects. Keep them cleanly separated on one machine without touching either.

altergo runs each account in its own isolated HOME, so credentials never mix. Session history, settings, and tool configs are shared across all accounts via symlinks — pick up any conversation from any account, instantly.

### Isolated by account. Shared where it matters.

**Each account keeps its own:**

- `~/.claude/.credentials.json` — OAuth tokens and session cookies live per account. Nothing leaks sideways.
- `~/.claude.json` — per account (holds your `oauthAccount` identity), but `mcpServers` is bidirectionally synced so `claude mcp add` registrations propagate automatically.

**Every account shares:**

- your sessions and projects
- your skills, commands, and agents
- your CLAUDE.md and keybindings
- your plans, tasks, file history, and shell snapshots
- your settings.json

Shared entries are real symlinks to the same underlying file or directory — when you edit your CLAUDE.md under one account, every other account sees the change instantly. Same inode, no sync step.

No daemon. No sync service. No config files to wrangle.

### Before and after

<table>
<tr>
<th width="50%">Before altergo</th>
<th width="50%">With altergo</th>
</tr>
<tr>
<td>

- Hit a limit mid-session → terminal dead end, context lost, start over
- Separate terminals per account, or swap credential files by hand
- Each account has its own session history — "where was I?" requires hunting
- Tool configs (AWS, gcloud, kubectl) randomly break as you jump around
- No visual indicator of which account is active until something breaks

</td>
<td>

- Hit a limit → `altergo pro` → same session, different credentials, keep going
- One terminal. One command. Right credentials, instantly.
- Session history shared across **all** accounts — `altergo --recall` picks from everywhere
- AWS, gcloud, Docker, kubectl stay shared by default — nothing breaks
- Each account isolated at `HOME`, wires never cross

</td>
</tr>
</table>

---

## <img src="docs/icons/install.svg" width="22" align="center"> Install

**pip** (recommended — always up to date from PyPI)

```bash
pip install altergo
```

**pipx** (isolated environment)

```bash
pipx install altergo
```

**curl** (drop the script into your PATH directly — note: this skips `altergo_greetings.py`, so a few cosmetic banners will fall back to text-only)

```bash
curl -fsSL \
  https://raw.githubusercontent.com/thepixelabs/altergo/main/altergo.py \
  -o ~/.local/bin/altergo
chmod +x ~/.local/bin/altergo
```

**Requirements:** Python 3.10+, one or more supported AI CLI tools installed (Claude Code, Gemini CLI, Codex, or GitHub Copilot), macOS or Linux.

---

## <img src="docs/icons/quickstart.svg" width="22" align="center"> Quick start

```bash
# Name your accounts — run once per login you have
altergo --config personal
altergo --config pro

# Launch your configured AI assistant as that account
altergo personal

# Open the interactive session picker across all accounts
altergo --recall
```

That is the full workflow. The first time you run `altergo personal`, your configured provider authenticates under that account's isolated credentials. Every session you create is visible from every account — switch accounts, not worlds. Your history follows you everywhere.

### What to try next

- `altergo --search "docker build"` — full-text search across every session from every account
- `altergo --recall` — interactive picker across Claude Code, Gemini CLI, Codex CLI, and GitHub Copilot sessions; press `/` to search, `f` to filter by provider, `b` to bookmark, `*` for starred-only, `s` to sort
- `altergo work --add-provider codex` — one identity, many tools: your `work` account can run claude AND codex AND gemini, switched by `altergo work codex` etc.
- `altergo --settings` — enable **tmux sessions** so your AI keeps running when SSH drops
- `altergo native` — launch your provider against your real `$HOME` (bypass isolation when you need it)
- `altergo --rename old new` — rename an account without losing credentials or history

---

## <img src="docs/icons/features.svg" width="22" align="center"> Features

| Feature | What it means |
|---|---|
| **Named accounts** | `personal`, `pro`, `sideproject`, or any name. One per AI account you use. Each gets its own isolated provider credentials. |
| **One command to switch** | `altergo pro` launches your configured AI assistant with the right credentials. No flags, no config editing. |
| **Credential isolation** | Each account's provider credentials are isolated. AWS, GCP, Docker, kubectl, and GitHub CLI stay shared by default. |
| **Shared skills, commands, agents** | User-authored Claude Code skills, slash commands, and agent definitions live under your primary home. Every account picks them up through the same symlinks. |
| **MCP sync** | `claude mcp add` registrations propagate across all accounts automatically. OAuth identity stays isolated. |
| **Configurable sharing** | `altergo --settings` opens a multi-page TUI — configure appearance (theme, launch animation), behavior (greeting/goodbye messages, tmux persistence, update checks), and which CLI tool credentials are shared. |
| **Interactive session picker** | Full-screen TUI with arrow keys, `j`/`k` vim bindings, full-text search (`/`), provider filter (`f`), sort (`s`), grouping (`g`), bookmark (`b`), starred-only filter (`*`), and a preview of each session's final message. Resumed sessions launch in the session's saved working directory. |
| **Full-text conversation search** | `altergo --search "query"` searches across every session from every account. |
| **tmux session persistence** | Opt in via settings — wraps every session in a tmux window so it survives SSH disconnects and can be reattached. |
| **Native passthrough** | `altergo native` launches your provider against your real `$HOME` — handy for quick one-offs without isolation. |
| **Minimal dependencies** | Standard library for the core. `rich`, `pyfiglet`, and `rich-pyfiglet` are loaded at runtime for TUI chrome; altergo degrades gracefully if they are absent. |
| **Keychain modes (macOS)** | Default (`keychain`) gives each account its own per-account keychain, unlocked silently at launch. Opt out with `none` for flat-file credentials only. See [docs/keychain-isolation.md](docs/keychain-isolation.md) · [FAQ](docs/faq.md). |
| **Cross-platform** | macOS and Linux wherever Python 3.10+ is available. |

---

## <img src="docs/icons/commands.svg" width="22" align="center"> Command reference

| Command | What it does |
|---|---|
| `altergo <account>` | Launch the configured AI assistant as the named account (e.g. `altergo personal`) |
| `altergo <account> <provider>` | Launch a specific provider under the named account, overriding that account's default (e.g. `altergo personal gemini`) |
| `altergo` | Launch the default account's AI assistant (backwards compatible) |
| `altergo native` | Launch your configured provider against your real `$HOME` — no isolation, no symlinks |
| `altergo native <provider>` | Same as above, but force a specific provider (e.g. `altergo native gemini`) |
| `altergo --recall` | Open the interactive TUI session picker (all accounts, all providers); account is resolved from the selected session |
| `altergo --resume` | Pass `--resume` through to the provider's own native resume UI |
| `altergo --resume <id>` | Resume a specific session by ID directly |
| `altergo --star [<id>]` | Star the last-exited session, or star a specific session by ID |
| `altergo --launch` | Open the interactive launcher directly |
| `altergo portal [<account>] [<provider>]` | Force a tmux-backed launch — keeps the session alive over SSH reconnects |
| `altergo <account> portal` | Same as above, scoped to a named account |
| `altergo --search <query>` | Full-text search across every session from every account |
| `altergo --config <account>` | Create or reconfigure a named account, wire symlinks automatically |
| `altergo --config <account> --keychain keychain\|none` | Set keychain mode: `keychain` (default, per-account keychain) or `none` (flat files only) — macOS only |
| `altergo --setup-token <account>` | Generate and store an SSH-friendly OAuth token for a claude account (bypasses macOS keychain over SSH) |
| `altergo <account> --add-provider <id>` | Add another provider to an existing account (reconciles any orphan data) |
| `altergo <account> --remove-provider <id>` | Remove a provider from an account (session data in MAIN_HOME untouched) |
| `altergo <account> --default-provider <id>` | Set which provider plain `altergo <account>` launches |
| `altergo --yolo` | Skip provider permission prompts (translates to the provider-native flag) |
| `altergo --yolo-resume [<id>]` | Skip permission prompts and resume the last session (or a specific session by ID) |
| `altergo --rename <old> <new>` | Rename an existing account (credentials and history preserved) |
| `altergo --teardown` | Remove symlinks (account directory and credentials untouched) |
| `altergo --teardown --name <n>` | Remove a specific named account's symlinks |
| `altergo --settings` | Multi-page settings TUI: appearance, behavior, and credentials |
| `altergo <account> shell` | Interactive shell inside the named account HOME |
| `altergo <account> -- <cmd>` | Run one command with HOME set to the named account directory |
| `altergo --version` | Show version number |
| `altergo --help` | Show help text |

### Keyboard shortcuts (interactive picker)

| Key | Action |
|---|---|
| `↑` / `k` | Move selection up |
| `↓` / `j` | Move selection down |
| `PgUp` | Jump up one viewport |
| `PgDn` | Jump down one viewport |
| `G` | Go to top of list |
| `Enter` | Resume the highlighted session (launches in its saved cwd) |
| `p` / `Space` / `Tab` | Open preview pane |
| `/` | Incremental search (project / topic / cwd / id) |
| `f` | Cycle provider filter: all → claude → gemini → codex → copilot → all |
| `s` | Cycle sort: time → project → provider → time |
| `g` | Toggle project-grouping dividers |
| `b` | Bookmark the highlighted row (toggle star) |
| `*` | Toggle starred-only filter |
| `t` | Cycle theme (persists immediately) |
| `q` / `Esc` | Cancel |

### Keyboard shortcuts (settings TUI)

| Key | Action |
|---|---|
| `←` / `→` / `h` / `l` / `Tab` | Switch pages |
| `↑` / `↓` / `j` / `k` | Navigate within page |
| `Space` | Toggle setting |
| `s` | Save and exit |
| `q` / `Esc` | Cancel |

---

## <img src="docs/icons/howitworks.svg" width="22" align="center"> How it works

altergo sets `HOME=~/.altergo/accounts/<account>` for the provider process. Each account's token lives in its isolated provider directory (e.g. `.claude/.credentials.json` for Claude Code, `.gemini/oauth_creds.json` for Gemini CLI, `.codex/auth.json` for Codex CLI, `.copilot/config.json` for GitHub Copilot). Everything else is shared via symlinks back to the primary provider directory.

```
~/.claude/                        Your primary Claude Code account (untouched)
    ├── .credentials.json
    ├── projects/
    └── ...

~/.altergo/
    └── accounts/
        ├── default/              Default alt account  (Claude Code provider shown)
        │   └── .claude/
        │       ├── .credentials.json   ← isolated per account
        │       ├── projects/        ──→ symlink to ~/.claude/projects/
        │       ├── settings.json    ──→ symlink to ~/.claude/settings.json
        │       └── CLAUDE.md        ──→ symlink to ~/.claude/CLAUDE.md
        └── pro/                  Named account (altergo --config pro)
            └── .claude/
                ├── .credentials.json   ← isolated per account
                ├── projects/        ──→ symlink to ~/.claude/projects/
                └── ...
```

**What gets symlinked — shared across all accounts (Claude Code provider):** `projects/`, `tasks/`, `session-env/`, `file-history/`, `shell-snapshots/`, `agents/`, `commands/`, `skills/`, `plans/`, `cache/`, `settings.json`, `CLAUDE.md`, `keybindings.json`. Other providers share analogous directories (e.g. Codex shares `sessions/` and `rules/`; Gemini shares `tmp/` and `commands/`; GitHub Copilot shares `session-state/`, `agents/`, `skills/`, and `hooks/`).

The "why": user-authored content (skills, commands, agents, CLAUDE.md), persistent preferences (settings.json, keybindings.json), and project state (projects, tasks, plans, session history) all belong to *you*, not to a specific OAuth identity. Sharing them means one edit is visible from every account — same inode, no sync step.

**What stays separate per account:** provider credentials (`.credentials.json` for Claude Code; `oauth_creds.json` for Gemini CLI; `auth.json` for Codex CLI; `config.json` for GitHub Copilot) and the isolated machinery behind them (`.claude.json`, `plugins/`, `paste-cache/`).

### Session recall across all providers

`altergo --recall` aggregates sessions from all four providers. Each session remembers the working directory where it ran — selecting a session from the picker relaunches it inside that original directory. If the directory no longer exists, altergo prints a dim notice and falls back to your current directory. The same behavior applies to `altergo --search`.

### MCP servers: sync, not symlink

Claude Code stores both `mcpServers` and `oauthAccount` inside `~/.claude.json`. Symlinking that file would leak your OAuth identity across accounts; *not* sharing it would strand every `claude mcp add` in whichever account happened to run it. altergo splits the difference: on every `altergo --config` and every Claude launch it **bidirectionally merges** the `mcpServers` section between your primary `~/.claude.json` and the account's `.claude.json`, then atomically writes both files back. `oauthAccount` is never touched. Register an MCP server once; every account sees it.

**CLI tool credentials** are shared or isolated per tool, configurable via `altergo --settings`. Shared by default: `.aws`, `.config/gcloud`, `.azure`, `.docker`, `.kube`, `.terraform.d`, `.config/gh`. Isolated by default: `.ssh`, `.gitconfig`, `.gnupg`, `.npmrc`, `.config/glab`.

### Running other tools in account context

Some tools (`gh`, `git`, SSH) read credentials from your home directory. Use `altergo <account> shell` or `altergo <account> -- <cmd>` to run them inside a specific account's HOME:

```bash
# Authenticate gh inside a specific account's environment
altergo pro shell
gh auth login
exit

# Or run a single command directly
altergo pro -- gh auth login
altergo pro -- gh auth status
```

Credentials set this way persist in `~/.altergo/accounts/pro/` and are available every time you run `altergo pro`. The same pattern works for the default account with `altergo shell` or `altergo -- <cmd>`.

### Keychain modes (macOS)

By default, altergo gives each account its own `login.keychain-db`, unlocked silently at session start (`keychain` mode — the default since v0.45.0). Provider credentials are isolated per account.

When you run `altergo --config <account>` interactively, altergo prompts you to pick `keychain` or `none` and explains both inline — including how each mode behaves over SSH. The "Allow access" dialog you may see is actually in `none` mode: the per-account keychain is intentionally locked, so when a provider tries to write to it macOS prompts for a password you don't have — click Cancel and the provider falls back to flat-file credentials. In `keychain` mode altergo handles unlock silently with a stored password, so you don't see popups. Re-running `--config` always re-prompts so you can switch modes any time, with the current mode as the default answer. To skip the prompt and set explicitly:

```bash
altergo --config <account> --keychain keychain   # or: --keychain none
```

If you pick `keychain`, altergo immediately offers to set up an OAuth token bridge so the account works over SSH without the keychain. See [SSH access](#ssh-access) below for the full flow.

| Mode | On-disk | Keychain writes | Unlock at launch |
|---|---|---|---|
| `keychain` (default) | plist + per-account keychain + unlock entry | succeed | yes |
| `none` | plist + empty locked keychain | blocked → providers fall back to flat files | no |

**Switching modes:** `--keychain none` removes the unlock entry from your real login keychain and preserves the per-account keychain file on disk (so a later re-upgrade to `keychain` can reuse it, but providers will need to re-authenticate). `--keychain keychain` rebuilds the keychain and unlock entry. Full cleanup happens on `altergo --delete-account <account>`.

**`none` mode warning:** In `none` mode, macOS may show a keychain password dialog. Always click **Cancel** — never "Reset To Defaults" (that destroys your real login keychain, unrelated to altergo). See [FAQ](docs/faq.md#what-is-the-keychain-password-prompt-i-keep-seeing-none-mode) for details.

**v0.46.0:** The `--keychain` option only accepts `keychain` and `none`. All legacy aliases (`dedicated`, `isolated`, `system`, `shared`, `private`) were removed. Accounts with legacy values in `account.json` fall through to the default (`keychain` mode); re-run `altergo --config <account>` to persist the new value.

**This is workflow isolation, not cryptographic separation.** Any process running under your macOS user can potentially read keychain entries. If you need hard isolation — e.g., client work under NDA — use separate macOS user accounts.

**UI indicators:** `altergo --config` (interactive picker) shows `  ·  keychain` next to keychain-mode accounts. None-mode accounts show no suffix (opt-out is implicit).

**Dev tool credentials are shared by design.** `gh`, `aws`, `gcloud`, and other dev tools are symlinked to your real `$HOME` by default so your existing logins work across all altergo accounts — no re-auth needed. Keychain mode applies to AI provider credentials only and does not affect these symlinks. Toggle per-tool in `altergo --settings` → Credentials if you need per-account separation.

See [docs/keychain-isolation.md](docs/keychain-isolation.md) for the full lifecycle and troubleshooting guide.

---

## <img src="docs/icons/howitworks.svg" width="22" align="center"> SSH access (keychain accounts)

If you SSH into your Mac and your accounts use `keychain`, the macOS Security framework requires a GUI session to service keychain reads — SSH has none, so auth fails. altergo works around this with a per-account OAuth token file. During `altergo --config`, you are offered the chance to set one up. You can also run it at any time:

```bash
altergo --setup-token work
```

When you run that command, altergo launches `claude setup-token`, which prints an authorization URL. Open the URL in a browser (your phone works fine over SSH), approve, and paste the token back:

```
  Generating an SSH-friendly OAuth token

  You're over SSH — claude setup-token will print a URL.
  Open it in your phone or another browser, approve, and paste
  the token back here when it prints to the terminal.

  Paste the token below (starts with sk-ant-oat01-…):
  token: sk-ant-oat01-…

  ✓ token saved   /Users/you/.altergo/accounts/work/.claude/.oauth-token
```

After that, `altergo work --yolo` (or any launch of that account) works over SSH without a keychain prompt. Each account stores its own token — `work` and `personal` can be separate identities with no shell-level exports or cross-account leakage.

See [docs/ssh-auth.md](docs/ssh-auth.md) for the full explanation: why this happens, per-account isolation, token rotation, security notes, and troubleshooting.

---

## <img src="docs/icons/migrate.svg" width="22" align="center"> Migrating older installs

- **v0.40.0 — multi-provider accounts, `--recall` across all providers, cwd-on-recall, `b`/`*` rebind:** `account.json` upgrades to v3 automatically on the next account mutation (e.g. `--add-provider`). v2 files load forever without being rewritten — no user action required. The picker's `b` key now bookmarks; `*` toggles a starred-only filter. Resumed sessions launch in their saved cwd. See [docs/migration.md](docs/migration.md#v0400--accountjson-v2--v3-schema) for details.
- **v0.46.0 — keychain alias removal + Cancel warning:** All legacy `--keychain` aliases (`dedicated`, `isolated`, `system`, `shared`) removed — only `private` and `none` accepted. Accounts with legacy values in `account.json` are treated as `private` with a one-time warning. New warning when choosing `none` mode explains the Cancel-vs-Reset-To-Defaults risk. See [docs/migration.md](docs/migration.md#v0460--keychain-alias-removal--cancel-warning).
- **v0.45.0 — keychain mode rename + default flip:** `dedicated` → per-account keychain (later renamed `private`, now `keychain`); `isolated` → `none`. Default flipped from `none` to per-account keychain (now called `keychain`). See [docs/migration.md](docs/migration.md#v0450--keychain-mode-rename-private--none).
- **v0.44.0 — keychain safety-default flip:** Default keychain mode was `isolated` (blocking, now called `none`). Existing accounts using `system` were silently migrated to `isolated` (same behavior, now called `none`). The old `isolated` mode (per-account keychain, now called `keychain`) was renamed `dedicated`. See [docs/migration.md](docs/migration.md#v0440--keychain-safety-default-flip).
- **v0.43.0 — keychain preserve-and-reuse:** Downgrading from `isolated` (now `keychain`) to `system` (now `none`) preserves the per-account keychain file on disk. Re-upgrading reuses the preserved file.
- **v0.41.0 — opt-in keychain isolation (macOS):** Introduced per-account keychains. Default was `system`; opt in per account with `--keychain isolated`. That mode is now called `keychain`. See [docs/keychain-isolation.md](docs/keychain-isolation.md).
- **From v0.4.x:** auto-migration existed through v0.35.2 and was removed in v0.35.3. If you are still on a pre-v0.5.0 layout today, see [docs/migration.md](docs/migration.md#archived-migration-notes-v04x--v050) for the archived steps — or open an issue for manual guidance.
- **Syntax change in v0.34.0:** `altergo --config --name <n>` is now `altergo --config <account>`. The old form was removed; update any aliases.
- **From claude100-resume:** credentials and aliases are not picked up automatically. See [docs/migration.md](docs/migration.md) for step-by-step instructions.

---

## <img src="docs/icons/howitworks.svg" width="22" align="center"> Next steps

- [docs/how-it-works.md](docs/how-it-works.md) — the mechanics and design tradeoffs, in depth
- [docs/settings.md](docs/settings.md) — every setting, what it toggles, and where it is stored
- [docs/migration.md](docs/migration.md) — upgrade notes, syntax changes, and archived migrations

Three power-user features new users miss:

- `altergo --search "<query>"` — full-text search across every session, every account
- **tmux session persistence** — toggle it in `altergo --settings` → Behavior so SSH drops never kill a session again
- `altergo native` — launch your provider against your real `$HOME` when you want isolation out of the way

---

## <img src="docs/icons/legal.svg" width="22" align="center"> Contributing

See [CONTRIBUTING.md](CONTRIBUTING.md).

## License

This project is fair-code distributed under the **PolyForm Shield 1.0.0 License**.

You may use, modify, and distribute this software for personal and internal business operations. Commercial use is permitted, provided it does not directly compete with the primary product or services offered by the repository owner.

Please refer to the [`LICENSE`](LICENSE) file for the complete terms and conditions.

---

> altergo is an independent fair-code project by [Pixelabs](https://pixelabs.net) · not affiliated with Anthropic, Google, OpenAI, or GitHub
>
> altergo depends on the internal directory structure of each supported provider. Any provider may change their structure without notice — if altergo breaks after an update, please [open an issue](https://github.com/thepixelabs/altergo/issues). Back up your provider data directories before first use. Full terms in [DISCLAIMER.md](DISCLAIMER.md).
