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
</p>

<p align="center">
  Personal, Pro, side project — as many AI accounts as you need.<br>
  <code>altergo pro</code> and you're in. Isolates credentials. Shares everything else.
</p>

> Active development — if something breaks, [open an issue](https://github.com/thepixelabs/altergo/issues).

---

## <img src="docs/icons/why.svg" width="22" align="center"> Why altergo

You hit a rate limit mid-session. `altergo pro` swaps credentials in place. Same project, same history, no ramp-up.

- **Rate-limited, not stopped.** Another account is ready. Drop back into the same session.
- **Thinker, then sprinter.** One account for heavy reasoning, another for fast execution. Flip between them like gear ratios.
- **Work, personal, clients.** Each account isolated at `HOME`. Session history, settings, AWS/gh/kubectl shared by default.

Supports **Claude Code, Gemini CLI, Codex CLI, GitHub Copilot.** macOS and Linux.

---

## <img src="docs/icons/install.svg" width="22" align="center"> Install

```bash
pipx install altergo
```

Requires Python 3.10+ and at least one supported AI CLI on your PATH.

---

## <img src="docs/icons/quickstart.svg" width="22" align="center"> Quick start

```bash
# Name your accounts — run once per login you have
altergo --config hocus
altergo --config pocus

# Pick a default — bare `altergo` now launches it
altergo --use pocus
altergo

# Everything below runs against your default account.
# Prefix with an account name to override (e.g. `altergo hocus --yolo`).

altergo --yolo            # skip provider permission prompts
altergo --yolo-resume     # skip prompts + resume your last session
altergo --recall          # interactive picker across every account
altergo --search "query"  # full-text search across history
```

That's the full workflow. The first launch authenticates that account; subsequent launches drop you straight in.

---

## <img src="docs/icons/commands.svg" width="22" align="center"> Essential commands

| Command | What it does |
|---|---|
| `altergo <account>` | Launch as the named account |
| `altergo --config <account>` | Create or reconfigure an account |
| `altergo --use <account>` | Set the default for bare `altergo` |
| `altergo --recall` | TUI session picker across all accounts |
| `altergo --search <query>` | Full-text search across history |
| `altergo --yolo` / `--yolo-resume` | Skip permission prompts (optionally resume) |
| `altergo portal <account>` | tmux-backed session that survives SSH drops |
| `altergo native` | Launch against your real `$HOME`, no isolation |
| `altergo --settings` | Manage themes, behavior, shared credentials |
| `altergo --help` | Full reference |

---

## <img src="docs/icons/howitworks.svg" width="22" align="center"> How it works (in one paragraph)

altergo overrides `HOME` to `~/.altergo/accounts/<name>/` before exec'ing the provider binary. Each account keeps its own `.credentials.json`; everything else inside the provider's dot-dir (`projects/`, `settings.json`, `CLAUDE.md`, `agents/`, `skills/`, …) is a symlink back to your real `~/.claude/`. Same inode, no sync step. AWS, gcloud, Docker, kubectl, gh stay shared by default — toggle per-tool in `altergo --settings`.

Deep dive: **[docs/architecture.md](docs/architecture.md)**

---

## <img src="docs/icons/howitworks.svg" width="22" align="center"> More

- **[docs/architecture.md](docs/architecture.md)** — directory layout, symlink reference, MCP merge, data flow
- **[docs/settings.md](docs/settings.md)** — every setting and where it lives
- **[docs/keychain-isolation.md](docs/keychain-isolation.md)** — macOS keychain modes
- **[docs/ssh-auth.md](docs/ssh-auth.md)** — using altergo over SSH (OAuth token bridge)
- **[docs/migration.md](docs/migration.md)** — upgrade notes
- **[docs/faq.md](docs/faq.md)** — common messages explained
- **[CHANGELOG.md](CHANGELOG.md)** — release history

---

## License & contributing

Fair-code under [PolyForm Shield 1.0.0](LICENSE) — personal and internal business use is free; commercial use is fine as long as it doesn't directly compete with altergo. See [CONTRIBUTING.md](CONTRIBUTING.md).

---

> altergo is an independent project by [Pixelabs](https://pixelabs.net) — not affiliated with Anthropic, Google, OpenAI, or GitHub. It depends on each provider's internal directory structure; if one changes and altergo breaks, please [open an issue](https://github.com/thepixelabs/altergo/issues). Full terms in [DISCLAIMER.md](DISCLAIMER.md).
