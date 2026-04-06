# altergo

> Your other Claude — switch Claude Code identities without losing a thought.

[![PyPI version](https://img.shields.io/pypi/v/altergo)](https://pypi.org/project/altergo/)
[![Python 3.9+](https://img.shields.io/badge/python-3.9+-blue.svg)](https://python.org)
[![License: MIT](https://img.shields.io/badge/license-MIT-green.svg)](LICENSE)
[![CI](https://github.com/thepixelabs/altergo/actions/workflows/ci.yml/badge.svg)](https://github.com/thepixelabs/altergo/actions/workflows/ci.yml)

<!-- TODO: Add demo GIF here -->

## What is this?

If you have multiple Claude Code subscriptions (personal + work, two orgs, etc.), switching between them means losing access to your session history. **Altergo** fixes that — it shares session data via symlinks while keeping credentials separate, so you can pick up any conversation from either account.

## Quick start

```bash
pip install altergo
altergo --setup
altergo
```

## Features

- **Interactive session picker** — curses TUI with arrow keys, j/k, page up/down
- **Session preview** — see project name, last modified, size, and last message
- **Zero dependencies** — Python standard library only
- **Cross-platform** — macOS and Linux
- **Automatic setup/teardown** — one command to configure, one to undo

## How it works

```
~/.claude/                  ← Your primary Claude Code account
    ├── .credentials.json   ← Primary credentials (untouched)
    ├── projects/           ← Session files
    ├── settings.json
    └── ...

~/.altergo/                 ← Your alt account
    ├── .claude/
    │   ├── .credentials.json  ← Alt credentials (separate)
    │   ├── projects/ → symlink to ~/.claude/projects/
    │   ├── settings.json → symlink
    │   └── ...            ← All session dirs are symlinked
    └── ...
```

Both accounts see the same sessions. Only credentials stay separate.

## Usage

```
altergo                       Interactive session picker
altergo new                   Start a new session with alt credentials
altergo --resume <id>         Resume a specific session
altergo --list                List all sessions
altergo --setup               First-time setup (alt home + symlinks)
altergo --teardown            Undo setup
altergo --version             Show version
altergo --help                Show help
```

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

## Contributing

See [CONTRIBUTING.md](CONTRIBUTING.md).

## Migrating from claude100-resume

If you used the previous `claude100-resume` tool with `~/claude100-home/`, your credentials and alias will not be picked up automatically. See [docs/migration.md](docs/migration.md) for step-by-step instructions.

## License

[MIT](LICENSE)
