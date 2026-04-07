# altergo

> Switch Claude identities. Keep your context.

[![PyPI version](https://img.shields.io/pypi/v/altergo)](https://pypi.org/project/altergo/)
[![Python 3.9+](https://img.shields.io/badge/python-3.9+-blue.svg)](https://python.org)
[![License: PolyForm Shield 1.0.0](https://img.shields.io/badge/license-PolyForm%20Shield%201.0.0-blue.svg)](LICENSE)
[![CI](https://github.com/thepixelabs/altergo/actions/workflows/ci.yml/badge.svg)](https://github.com/thepixelabs/altergo/actions/workflows/ci.yml)

<!-- TODO: Add demo GIF here -->

altergo is an independent open-source project by pixelabs · not affiliated with Anthropic PBC

## What is this?

If you have multiple Claude Code subscriptions (personal, work, multiple orgs), switching between them normally means losing your session history. **Altergo** fixes that — it keeps each account's Claude credentials separate while sharing session data, AWS, GCP, Docker, and kubectl config by default via symlinks. Pick up any conversation from any account.

Each account is a named directory under `~/.altergo/accounts/`. You can create as many as you need.

## Quick start

```bash
pip install altergo

# Set up your default account
altergo --setup

# Optionally create a named account
altergo --setup --name work

# Launch Claude with your default account
altergo

# Launch Claude with your work account
altergo work
```

## Features

- **Named accounts, unlimited** — create accounts for personal, work, each org, or any context
- **One-command switching** — `altergo work` launches Claude under the work account instantly
- **Credential isolation** — each account has its own Claude credentials; AWS, GCP, Docker, and kubectl are shared by default
- **Interactive session picker** — curses TUI with arrow keys, j/k, page up/down
- **Session preview** — see project name, last modified, size, and last message
- **Zero dependencies** — Python standard library only
- **Cross-platform** — macOS and Linux
- **Automatic setup/teardown** — one command to configure, one to undo
- **Auto-migration from v0.4.x** — existing `~/.altergo/` layout is migrated automatically on first run

## How it works

```
~/.claude/                        Your primary Claude Code account (untouched)
    ├── .credentials.json
    ├── projects/
    └── ...

~/.altergo/
    └── accounts/
        ├── default/              Default alt account
        │   ├── .claude/
        │   │   ├── .credentials.json   Alt credentials (separate)
        │   │   ├── projects/ -------> symlink to ~/.claude/projects/
        │   │   └── settings.json ---> symlink
        │   └── ...
        └── work/                 Named account (altergo --setup --name work)
            ├── .claude/
            │   ├── .credentials.json   Work credentials (separate)
            │   ├── projects/ -------> symlink to ~/.claude/projects/
            │   └── ...
            └── ...
```

All accounts see the same sessions. Only Claude credentials stay separate.

## Usage

```
altergo                            Start a new session (default account)
altergo --resume                   Open interactive session picker
altergo --resume <id>              Resume a specific session
altergo --list                     List recent sessions
altergo --setup                    First-time setup (default account)
altergo --setup --name <name>      Create a named account
altergo --teardown                 Remove default account symlinks
altergo --teardown --name <name>   Remove a named account
altergo --settings                 Configure shared credentials (interactive TUI)
altergo shell                      Open a shell inside default account HOME
altergo <name>                     Start a new session with a named account
altergo <name> shell               Open a shell inside a named account HOME
altergo <name> -- <cmd> [args...]  Run any command in a named account context
altergo -- <cmd> [args...]         Run any command in default account context
altergo --version                  Show version
altergo --help                     Show help
```

### Running other tools in account context

Some tools (`gh`, `git`, SSH) read credentials from your home directory. To authenticate them for a specific account:

```bash
# Enter an interactive shell inside the work account HOME
altergo work shell
gh auth login          # authenticates gh for work account
git config --global user.email me@work.com
exit

# Or run a single command directly
altergo work -- gh auth login
altergo work -- gh auth status
```

Credentials set inside `altergo work shell` persist in `~/.altergo/accounts/work/` and are available every time you run `altergo work`.

The same pattern works for the default account using `altergo shell` or `altergo -- <cmd>`.

### Keyboard shortcuts (interactive picker)

| Key | Action |
|-----|--------|
| `↑` / `k` | Move up |
| `↓` / `j` | Move down |
| `PgUp` / `PgDn` | Page scroll |
| `g` / `G` | Jump to top / bottom |
| `Enter` | Resume session |
| `q` / `Esc` | Quit |

## Install

### pip (recommended)

```bash
pip install altergo
```

### Homebrew

```bash
brew install thepixelabs/tap/altergo
```

### Manual

```bash
curl -o ~/.local/bin/altergo https://raw.githubusercontent.com/thepixelabs/altergo/main/altergo.py
chmod +x ~/.local/bin/altergo
```

## Requirements

- Python 3.9+
- [Claude Code](https://claude.ai/code) CLI installed
- macOS or Linux

## Migrating from v0.4.x

If you have an existing `~/.altergo/` directory, altergo migrates it automatically on first run to `~/.altergo/accounts/default/`. A backup is preserved at `~/.altergo/.legacy-backup/`. See [https://altergo.pixelabs.net/docs/migration-0.5](https://altergo.pixelabs.net/docs/migration-0.5) for details.

## Migrating from claude100-resume

If you used the previous `claude100-resume` tool with `~/claude100-home/`, your credentials and alias will not be picked up automatically. See [docs/migration.md](docs/migration.md) for step-by-step instructions.

## Contributing

See [CONTRIBUTING.md](CONTRIBUTING.md).

## License

[PolyForm Shield 1.0.0](LICENSE)
