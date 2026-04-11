<p align="center">
  <picture>
    <source media="(prefers-color-scheme: dark)" srcset="docs/logo-dark.svg">
    <source media="(prefers-color-scheme: light)" srcset="docs/logo-light.svg">
    <img alt="altergo" src="docs/logo-dark.svg" width="420">
  </picture>
</p>

<p align="center">
  <strong>Switch AI identities. Keep your context.</strong>
</p>

<p align="center">
  <a href="https://pypi.org/project/altergo/"><img alt="PyPI version" src="https://img.shields.io/pypi/v/altergo"></a>
  <img alt="Python 3.10+" src="https://img.shields.io/badge/python-3.10+-blue.svg">
  <a href="LICENSE"><img alt="License: MIT" src="https://img.shields.io/badge/license-MIT-green.svg"></a>
  <a href="https://github.com/thepixelabs/altergo/actions/workflows/ci.yml"><img alt="CI" src="https://github.com/thepixelabs/altergo/actions/workflows/ci.yml/badge.svg"></a>
  <a href="https://github.com/thepixelabs/altergo/actions/workflows/release.yml"><img alt="CD" src="https://github.com/thepixelabs/altergo/actions/workflows/release.yml/badge.svg"></a>
</p>

<p align="center">
  Personal account, work login, side project — as many as you need.<br>
  <code>altergo personal</code> and you are in. Isolates credentials. Shares everything else.
</p>

---

## <img src="docs/icons/why.svg" width="22" align="center"> Why altergo

You use AI coding assistants — Claude Code, Gemini CLI, Codex, GitHub Copilot — across multiple accounts. A personal login, a work account your employer pays for, maybe a third for open source. Switching between them normally means juggling separate terminals, losing your session history, or manually swapping credential files. That is friction you should not have to think about.

altergo runs each account in its own isolated HOME, so credentials never mix. Session history, settings, and tool configs are shared across all accounts via symlinks — pick up any conversation from any account, instantly.

No daemon. No sync service. No config files to wrangle. One Python file.

### Before and after

<table>
<tr>
<th width="50%">Before altergo</th>
<th width="50%">With altergo</th>
</tr>
<tr>
<td>

- Separate terminals per account, or swap credential files by hand
- Log out, log in, lose your place
- Each account has its own session history — hard to find "where was I?"
- Tool configs (AWS, gcloud, kubectl) randomly break as you jump around
- No idea which account you're currently running as — and no way to tell until you hit a rate limit or get an auth error

</td>
<td>

- One terminal. `altergo work` → right credentials, instantly.
- Credentials swap instantly, no login dance
- Session history shared across **all** accounts — `altergo --resume` picks from everywhere
- AWS, gcloud, Docker, kubectl stay shared by default — nothing breaks
- Each account is isolated at `HOME`, so wires never cross

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

**curl** (single-file, no pip required)

```bash
curl -fsSL \
  https://raw.githubusercontent.com/thepixelabs/altergo/main/altergo.py \
  -o ~/.local/bin/altergo
chmod +x ~/.local/bin/altergo
```

**Homebrew**

```bash
brew install thepixelabs/tap/altergo
```

**Requirements:** Python 3.10+, one or more supported AI CLI tools installed (Claude Code, Gemini CLI, Codex, or GitHub Copilot), macOS or Linux.

---

## <img src="docs/icons/quickstart.svg" width="22" align="center"> Quick start

```bash
# Name your accounts — run once per login you have
altergo --setup --name personal
altergo --setup --name work

# Launch your configured AI assistant as that account
altergo personal

# Open the interactive session picker across all accounts
altergo --resume
```

That is the full workflow. The first time you run `altergo personal`, your configured provider authenticates under that account's isolated credentials. Every session you create is visible from every account — switch accounts, not worlds. Your history follows you everywhere.

---

## <img src="docs/icons/features.svg" width="22" align="center"> Features

| Feature | What it means |
|---|---|
| **Named accounts, unlimited** | `personal`, `work`, `sideproject`, or any name. One per AI account you use. Each gets its own isolated provider credentials. |
| **One command to switch** | `altergo work` launches your configured AI assistant with the right credentials. No flags, no config editing. |
| **Credential isolation** | Each account's provider credentials are isolated. AWS, GCP, Docker, kubectl, and GitHub CLI stay shared by default. |
| **Configurable sharing** | `altergo --settings` opens a multi-page TUI — configure appearance (theme, launch animation), behavior (greeting/goodbye messages, update checks), and which CLI tool credentials are shared. |
| **Interactive session picker** | Full-screen TUI with arrow keys, `j`/`k` vim bindings, page up/down, and a preview of each session's final message. |
| **Session preview** | See project name, last modified time, size, and last message before you resume. |
| **Zero dependencies** | Ships as a single Python file. Standard library only. |
| **Cross-platform** | macOS and Linux wherever Python 3.10+ is available. |
| **Silent auto-migration** | Existing v0.4.x installs upgrade automatically on first run. No manual steps. |

---

## <img src="docs/icons/commands.svg" width="22" align="center"> Command reference

| Command | What it does |
|---|---|
| `altergo <name>` | Launch the configured AI assistant as the named account (e.g. `altergo work`) |
| `altergo` | Launch the default account's AI assistant (backwards compatible) |
| `altergo --resume` | Open the interactive TUI session picker (all accounts) |
| `altergo --resume <id>` | Resume a specific session by ID directly |
| `altergo --list` | Print recent sessions as a plain table |
| `altergo --setup --name <n>` | Create a named account, wire symlinks automatically |
| `altergo --teardown` | Remove symlinks (account directory and credentials untouched) |
| `altergo --teardown --name <n>` | Remove a specific named account's symlinks |
| `altergo --settings` | Multi-page settings TUI: appearance, behavior, and credentials |
| `altergo <name> shell` | Interactive shell inside the named account HOME |
| `altergo <name> -- <cmd>` | Run one command with HOME set to the named account directory |
| `altergo --version` | Show version number |
| `altergo --help` | Show help text |

### Keyboard shortcuts (interactive picker)

| Key | Action |
|---|---|
| `↑` / `k` | Move up |
| `↓` / `j` | Move down |
| `PgUp` / `PgDn` | Page scroll |
| `g` / `G` | Jump to top / bottom |
| `Enter` | Resume session |
| `q` / `Esc` | Quit |

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

altergo sets `HOME=~/.altergo/accounts/<name>` for the provider process. Each account's token lives in its isolated provider directory (e.g. `.claude/.credentials.json` for Claude Code, `.gemini/oauth_creds.json` for Gemini CLI). Everything else is shared via symlinks back to the primary provider directory.

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
        └── work/                 Named account (altergo --setup --name work)
            └── .claude/
                ├── .credentials.json   ← isolated per account
                ├── projects/        ──→ symlink to ~/.claude/projects/
                └── ...
```

**What gets symlinked** (shared across all accounts, Claude Code provider): `projects/`, `tasks/`, `session-env/`, `file-history/`, `shell-snapshots/`, `agents/`, `plans/`, `cache/`, `settings.json`, `CLAUDE.md`, `keybindings.json`

**What stays separate**: provider credentials (`.credentials.json` for Claude Code; `oauth_creds.json` for Gemini CLI; `auth.json` for Codex; `config.json` for Copilot)

**CLI tool credentials** are shared or isolated per tool, configurable via `altergo --settings`. Shared by default: `.aws`, `.config/gcloud`, `.azure`, `.docker`, `.kube`, `.terraform.d`, `.config/gh`. Isolated by default: `.ssh`, `.gitconfig`, `.gnupg`, `.npmrc`, `.config/glab`.

### Running other tools in account context

Some tools (`gh`, `git`, SSH) read credentials from your home directory. Use `altergo <name> shell` or `altergo <name> -- <cmd>` to run them inside a specific account's HOME:

```bash
# Authenticate gh for the work account
altergo work shell
gh auth login
git config --global user.email me@work.com
exit

# Or run a single command directly
altergo work -- gh auth login
altergo work -- gh auth status
```

Credentials set this way persist in `~/.altergo/accounts/work/` and are available every time you run `altergo work`. The same pattern works for the default account with `altergo shell` or `altergo -- <cmd>`.

### macOS Keychain note

When using Claude Code, tokens may be stored in the system Keychain rather than a flat file. When you authenticate inside `altergo work`, the token is stored under a separate Keychain entry keyed to that account's email. The `.credentials.json` file may appear empty — this is expected. Auth still works correctly.

---

## <img src="docs/icons/migrate.svg" width="22" align="center"> Migrating from v0.4.x

If you have an existing `~/.altergo/` directory from v0.4.x, altergo migrates it automatically on first run. Your old setup becomes the default account at `~/.altergo/accounts/default/`. A backup is preserved at `~/.altergo/.legacy-backup/`. No manual steps required.

Full details: [https://altergo.pixelabs.net/docs/migration-0.5](https://altergo.pixelabs.net/docs/migration-0.5)

## Migrating from claude100-resume

If you used the earlier `claude100-resume` tool with `~/claude100-home/`, your credentials and alias are not picked up automatically. See [docs/migration.md](docs/migration.md) for step-by-step instructions.

---

## <img src="docs/icons/legal.svg" width="22" align="center"> Contributing & License

See [CONTRIBUTING.md](CONTRIBUTING.md) · [MIT License](LICENSE)

---

> altergo is an independent open-source project by [Pixelabs](https://pixelabs.net) · not affiliated with Anthropic, Google, OpenAI, or GitHub
>
> altergo depends on the internal directory structure of each supported provider. Any provider may change their structure without notice — if altergo breaks after an update, please [open an issue](https://github.com/thepixelabs/altergo/issues). Back up your provider data directories before first use. Full terms in [DISCLAIMER.md](DISCLAIMER.md).
