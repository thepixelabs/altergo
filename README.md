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

<p align="center">
  <code>pipx install altergo</code>
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

altergo runs each account in its own isolated HOME, so credentials never mix. Session history, settings, provider-specific config files (e.g. `CLAUDE.md` for Claude Code, `rules/` for Codex CLI), and tool configs are shared across all accounts via symlinks — pick up any conversation from any account, instantly.

**Isolated per account:** provider credentials (OAuth tokens, session cookies) and each provider's auth identity. **Shared across all accounts via symlinks:** sessions, projects, skills, commands, agents, settings, keybindings, provider-specific config files, plans, tasks, and file history. Edit a config file under one account — every other account sees the change instantly. Same inode, no sync step, no daemon.

---

## <img src="docs/icons/install.svg" width="22" align="center"> Install

**pipx** (recommended — works out of the box on macOS and Linux, no venv needed)

```bash
pipx install altergo
```

Don't have pipx? `brew install pipx && pipx ensurepath` or `pip install --user pipx`.

**pip** (if you manage your own virtualenv)

```bash
pip install altergo
```

> Modern macOS and Homebrew-managed Python block global `pip install` by default (PEP 668). Use pipx above, or activate a virtualenv first.

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

---

## <img src="docs/icons/features.svg" width="22" align="center"> Features

| Feature | What it means |
|---|---|
| **Named accounts** | `personal`, `pro`, `sideproject`, or any name. One per AI account you use. Each gets its own isolated provider credentials. |
| **One command to switch** | `altergo pro` launches your configured AI assistant with the right credentials. No flags, no config editing. |
| **Credential isolation** | Each account's provider credentials are isolated. AWS, GCP, Docker, kubectl, and GitHub CLI stay shared by default. |
| **Shared skills, commands, agents** | User-authored skills, slash commands, and agent definitions live under your primary home. Every account picks them up through the same symlinks — no duplication across providers. |
| **MCP sync (Claude Code)** | `claude mcp add` registrations propagate across all accounts automatically. OAuth identity stays isolated. |
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
| `altergo --setup-token <account>` | Generate and store an SSH-friendly OAuth token for a Claude Code account (bypasses macOS keychain over SSH) |
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
| `f` | Cycle provider filter: all → Claude Code → gemini → codex → copilot → all |
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

altergo sets `HOME=~/.altergo/accounts/<account>` for the provider process. Each account's credentials live in its isolated provider directory. Everything else is shared via symlinks back to the primary provider directory.

```
~/.claude/                        Your primary Claude Code home (untouched)
    ├── .credentials.json
    ├── projects/
    └── ...

~/.altergo/
    └── accounts/
        ├── default/              Default alt account  (Claude Code provider)
        │   └── .claude/
        │       ├── .credentials.json   ← isolated per account
        │       ├── projects/        ──→ symlink to ~/.claude/projects/
        │       ├── settings.json    ──→ symlink to ~/.claude/settings.json
        │       └── CLAUDE.md        ──→ symlink to ~/.claude/CLAUDE.md
        └── work/                 Named account (altergo --config work)
            └── .gemini/          ← Gemini CLI provider example
                ├── oauth_creds.json    ← isolated per account
                ├── tmp/         ──→ symlink to ~/.gemini/tmp/
                └── commands/    ──→ symlink to ~/.gemini/commands/
```

The isolated credential file for each provider:

| Provider | Isolated file |
|---|---|
| Claude Code | `.claude/.credentials.json` |
| Gemini CLI | `.gemini/oauth_creds.json` |
| Codex CLI | `.codex/auth.json` |
| GitHub Copilot | `.copilot/config.json` |

**Symlinked (shared):** `projects/`, `tasks/`, `session-env/`, `file-history/`, `shell-snapshots/`, `agents/`, `commands/`, `skills/`, `plans/`, `cache/`, `settings.json`, `CLAUDE.md` (Claude Code), `keybindings.json`, and provider-analogous directories for Codex (`sessions/`, `rules/`), Gemini (`tmp/`, `commands/`), and Copilot (`session-state/`, `agents/`, `skills/`, `hooks/`). These belong to *you*, not to a specific OAuth identity — sharing them means one edit is visible from every account, same inode, no sync step.

`altergo --recall` aggregates sessions from all four providers; each session relaunches in its saved working directory. Tools like `gh` and `git` read from `$HOME` — use `altergo <account> shell` or `altergo <account> -- <cmd>` to run them inside a specific account's HOME.

### MCP servers: sync, not symlink (Claude Code)

Claude Code stores both `mcpServers` and `oauthAccount` inside `~/.claude.json`. Symlinking that file would leak your OAuth identity across accounts; *not* sharing it would strand every `claude mcp add` in whichever account happened to run it. altergo splits the difference: on every `altergo --config` and every Claude launch it **bidirectionally merges** the `mcpServers` section between your primary `~/.claude.json` and the account's `.claude.json`, then atomically writes both files back. `oauthAccount` is never touched. Register an MCP server once; every account sees it.

**CLI tool credentials** are shared or isolated per tool, configurable via `altergo --settings`. Shared by default: `.aws`, `.config/gcloud`, `.azure`, `.docker`, `.kube`, `.terraform.d`, `.config/gh`. Isolated by default: `.ssh`, `.gitconfig`, `.gnupg`, `.npmrc`, `.config/glab`.

### Keychain modes (macOS)

By default, altergo gives each account its own per-account keychain, unlocked silently at session start (`keychain` mode). Opt out with `none` for flat-file credentials only. To set the mode explicitly:

```bash
altergo --config <account> --keychain keychain   # or: --keychain none
```

**`none` mode warning:** macOS may show a keychain password dialog. Always click **Cancel** — never "Reset To Defaults" (that destroys your real login keychain, unrelated to altergo).

See [docs/keychain-isolation.md](docs/keychain-isolation.md) for the full lifecycle, mode switching instructions, and troubleshooting guide.

### SSH access (Claude Code, keychain accounts)

SSH has no GUI session, so macOS cannot service keychain reads — `keychain` mode accounts fail to authenticate over SSH. altergo works around this with a per-account OAuth token file: run `altergo --setup-token <account>` (or accept the offer during `altergo --config`), open the printed URL in any browser, approve, and paste the token back. After that the account works over SSH without a keychain prompt. Each account stores its own token — no cross-account leakage.

See [docs/ssh-auth.md](docs/ssh-auth.md) for per-account isolation, token rotation, security notes, and troubleshooting.

---

## <img src="docs/icons/migrate.svg" width="22" align="center"> Migrating older installs

- **v0.40.0 — multi-provider accounts, `--recall` across all providers, cwd-on-recall, `b`/`*` rebind:** `account.json` upgrades to v3 automatically on the next account mutation (e.g. `--add-provider`). v2 files load forever without being rewritten — no user action required.
- **v0.46.0 — keychain alias removal + Cancel warning:** All legacy `--keychain` aliases removed — only `keychain` and `none` are accepted. Accounts with legacy values in `account.json` fall through to the default (`keychain` mode); re-run `altergo --config <account>` to persist the new value. See [docs/migration.md](docs/migration.md).

See [docs/migration.md](docs/migration.md) for all earlier upgrade notes, syntax changes, and archived migrations.

---

## <img src="docs/icons/howitworks.svg" width="22" align="center"> Next steps

- [docs/how-it-works.md](docs/how-it-works.md) — the mechanics and design tradeoffs, in depth
- [docs/settings.md](docs/settings.md) — every setting, what it toggles, and where it is stored
- [docs/migration.md](docs/migration.md) — upgrade notes, syntax changes, and archived migrations

Power-user features new users miss: `altergo --search "<query>"` for full-text search across every session; **tmux session persistence** (toggle in `altergo --settings` → Behavior) so SSH drops never kill a session; `altergo work --add-provider codex` for one account that runs multiple providers; `altergo native` to bypass isolation for quick one-offs.

---

## <img src="docs/icons/legal.svg" width="22" align="center"> Contributing

See [CONTRIBUTING.md](CONTRIBUTING.md).

## License

This project is fair-code distributed under the **PolyForm Shield 1.0.0 License**.

You may use, modify, and distribute this software for personal and internal business operations. Commercial use is permitted, provided it does not directly compete with the primary product or services offered by the repository owner.

Please refer to the [`LICENSE`](LICENSE) file for the complete terms and conditions.

---

```bash
pipx install altergo
```

> altergo is an independent fair-code project by [Pixelabs](https://pixelabs.net) · not affiliated with Anthropic, Google, OpenAI, or GitHub
>
> altergo depends on the internal directory structure of each supported provider. Any provider may change their structure without notice — if altergo breaks after an update, please [open an issue](https://github.com/thepixelabs/altergo/issues). Back up your provider data directories before first use. Full terms in [DISCLAIMER.md](DISCLAIMER.md).
