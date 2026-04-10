<p align="center">
  <picture>
    <source media="(prefers-color-scheme: dark)" srcset="docs/logo-dark.svg">
    <source media="(prefers-color-scheme: light)" srcset="docs/logo-light.svg">
    <img alt="altergo" src="docs/logo-dark.svg" width="420">
  </picture>
</p>

<p align="center">
  <strong>Switch Claude identities. Keep your context.</strong>
</p>

<p align="center">
  <a href="https://pypi.org/project/altergo/"><img alt="PyPI version" src="https://img.shields.io/pypi/v/altergo"></a>
  <img alt="Python 3.10+" src="https://img.shields.io/badge/python-3.10+-blue.svg">
  <a href="LICENSE"><img alt="License: MIT" src="https://img.shields.io/badge/license-MIT-green.svg"></a>
  <a href="https://github.com/thepixelabs/altergo/actions/workflows/ci.yml"><img alt="CI" src="https://github.com/thepixelabs/altergo/actions/workflows/ci.yml/badge.svg"></a>
  <a href="https://github.com/thepixelabs/altergo/actions/workflows/release.yml"><img alt="CD" src="https://github.com/thepixelabs/altergo/actions/workflows/release.yml/badge.svg"></a>
</p>

<p align="center">
  Named accounts — work, personal, client-A, as many as you need.<br>
  <code>altergo work</code> and you are in. Isolates Claude. Shares everything else.
</p>

---

## <img src="docs/icons/why.svg" width="22" align="center"> Why altergo

You have more than one Claude Code subscription. Switching between them normally means juggling separate terminals, losing your session history, or manually swapping credential files. That is friction you should not have to think about.

altergo runs each Claude account in its own isolated HOME, so credentials never mix. Session history, settings, and tool configs are shared across all accounts via symlinks — pick up any conversation from any account, instantly.

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
- Mixing a work question into a personal session, then panicking

</td>
<td>

- One terminal. `altergo work` → you are in the work account.
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

**Requirements:** Python 3.10+, [Claude Code](https://claude.ai/code) CLI installed, macOS or Linux.

---

## <img src="docs/icons/quickstart.svg" width="22" align="center"> Quick start

```bash
# Create named accounts — repeat for as many as you need
altergo --setup --name work
altergo --setup --name personal

# Launch Claude as that account
altergo work

# Open the interactive session picker across all accounts
altergo --resume
```

That is the full workflow. The first time you run `altergo work`, Claude authenticates under that account's isolated credentials. Every session you create is visible from every account.

---

## <img src="docs/icons/features.svg" width="22" align="center"> Features

| Feature | What it means |
|---|---|
| **Named accounts, unlimited** | `work`, `personal`, `client-a`, or any name. Each gets its own Claude credentials. |
| **One command to switch** | `altergo work` launches Claude with the right credentials. No flags, no config editing. |
| **Credential isolation** | Only Claude's OAuth token is isolated per account. AWS, GCP, Docker, kubectl, and GitHub CLI stay shared by default. |
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
| `altergo <name>` | Launch Claude as the named account (e.g. `altergo work`) |
| `altergo` | Launch Claude as the default account (backwards compatible) |
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

altergo sets `HOME=~/.altergo/accounts/<name>` for the Claude process. Each account's token lives at `~/.altergo/accounts/<name>/.claude/.credentials.json`. Everything else is shared via symlinks back to your primary `~/.claude/`.

```
~/.claude/                        Your primary Claude Code account (untouched)
    ├── .credentials.json
    ├── projects/
    └── ...

~/.altergo/
    └── accounts/
        ├── default/              Default alt account
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

**What gets symlinked** (shared across all accounts): `projects/`, `tasks/`, `session-env/`, `file-history/`, `shell-snapshots/`, `agents/`, `plans/`, `cache/`, `settings.json`, `CLAUDE.md`, `keybindings.json`

**What stays separate**: `.credentials.json`

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

Claude Code may store tokens in the system Keychain rather than a flat file. When you authenticate inside `altergo work`, the token is stored under a separate Keychain entry keyed to that account's email. The `.credentials.json` file may appear empty — this is expected. Auth still works correctly.

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

> altergo is an independent open-source project by [Pixelabs](https://pixelabs.net) · not affiliated with Anthropic PBC
>
> altergo depends on the internal directory structure of Claude Code. Anthropic may change this without notice — if altergo breaks after a Claude Code update, please [open an issue](https://github.com/thepixelabs/altergo/issues). Back up `~/.claude/` before first use. Full terms in [DISCLAIMER.md](DISCLAIMER.md).
