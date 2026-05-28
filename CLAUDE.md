# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Commands

```bash
# Dev setup — create .venv and install editable
make dev

# Run local build
make run ARGS='--help'
make run ARGS='--config work'

# Lint (ruff)
ruff check altergo/ altergo.py
ruff format --check altergo/ altergo.py

# All tests
pytest -v

# Single test file
pytest tests/test_smoke.py -v

# Single test by name
pytest tests/test_smoke.py -v -k "test_mcp_sync"

# Direct run (no venv needed if deps are installed)
python altergo.py --help
```

CI (`ci.yml`) runs `ruff check altergo.py` and `pytest -v` across Python 3.10–3.13 on ubuntu-latest and macos-latest. The package lint target (`altergo/`) is not yet wired into CI — only the compat stub is linted there.

## Architecture

### Package layout

The codebase was refactored from a single `altergo.py` monolith into a package. The top-level `altergo.py` is now a **compatibility stub** — it exists so `python altergo.py` and subprocess-level tests still work. All logic lives in the `altergo/` package.

```
altergo/            ← main package
  cli.py            ← entry point (altergo.cli:main); argument dispatch
  accounts.py       ← account lifecycle, provider setup, symlink plumbing, MCP sync
  sessions.py       ← multi-provider session discovery and JSONL/JSON/YAML parsing
  runner.py         ← launch paths (launch_claude/shell/command), env setup, tmux
  persistence.py    ← filesystem I/O: settings, starred sessions, update cache, theme
  keychain.py       ← macOS per-account keychain lifecycle
  constants.py      ← PROVIDERS dict, CATALOG, path constants, SYMLINK_DIRS/FILES
  theme.py          ← 6-theme color system
  ui.py             ← banner, help output, terminal formatting
  __init__.py       ← re-exports for backward compat and test monkeypatching
  tui/
    launcher.py     ← account/provider picker, first-run onboarding
    picker.py       ← --recall session resume TUI
    search.py       ← --search full-text session search TUI
    config_tui.py   ← --config interactive dialogs
    settings_tui.py ← --settings multi-page settings TUI
    common.py       ← shared curses helpers

altergo_greetings.py  ← greeting messages, time-of-day copy, theme spinners (module-level, not in package)
tests/
  conftest.py           ← full_home fixture (monkeypatches globals), fake_claude_bin fixture
  bin/claude            ← fake sentinel binary used by subprocess-level tests
  test_smoke.py         ← core functionality
  test_keychain.py      ← 80 macOS keychain tests
  test_integration.py   ← config/teardown/launch integration
  test_new_features.py  ← recent feature coverage
  test_multi_provider*.py ← multi-provider session and config tests
  test_arg_routing.py   ← CLI argument dispatch
```

### Core mechanism

altergo isolates AI CLI accounts by:
1. **Overriding `HOME`** to `~/.altergo/accounts/<account>/` before execing the provider binary
2. **Symlinking** everything inside the account's provider dot-dir (`.claude/`, `.gemini/`, etc.) back to the real home — so session history, settings, agents, commands, and skills are shared across all accounts
3. **Keeping credentials isolated** — only `.credentials.json` and the provider's auth file are real per-account files

The three treatment categories for every path inside an account's dot-dir:

| Treatment | Examples | Rule |
|---|---|---|
| **Isolated** (real file) | `.credentials.json`, `.claude.json`, `account.json` | Per-account identity and auth |
| **Symlinked/shared** | `projects/`, `tasks/`, `skills/`, `settings.json`, `CLAUDE.md` | Same inode across all accounts |
| **Bidirectionally merged** | `.claude.json` → only `mcpServers` key | Identity stays isolated; MCP servers propagate |

`_sync_claude_mcps()` (`accounts.py`) runs at `--config` time and at every Claude launch: it union-merges `mcpServers` from `~/.claude.json` and the account's `.claude.json` (account wins on collision), writes both atomically, and leaves `oauthAccount` untouched on both sides.

### Key design invariants

- **`MAIN_HOME` uses `pwd.getpwuid(os.getuid()).pw_dir`**, not `os.environ["HOME"]`. This makes altergo re-entrant: you can run `altergo` from inside an `altergo shell` session (where `$HOME` is already overridden) and it still finds the correct primary home.
- **`os.execvpe`, not `subprocess`**. The altergo process image is replaced by the provider binary — no wrapper parent, no signal forwarding needed, terminal ownership is clean.
- **`account_home/.local/bin` is prepended to PATH only if it exists on disk** (security guard: avoids a PATH injection vector where an unpopulated directory could later be filled with malicious binaries).
- **`_ensure_symlinked_dir()` is idempotent** — safe to run repeatedly; handles the four cases of missing, already-linked, empty real dir, and non-empty real dir with potential merge/quarantine.

### Account metadata schema (v3)

`~/.altergo/accounts/<name>/account.json`:
```json
{
  "version": 3,
  "providers": ["claude", "codex"],
  "default_provider": "claude",
  "created": "2026-04-20T18:32:11",
  "keychain": "isolated"
}
```

v2 files (`{"version": 2, "provider": "claude"}`) load forever via `_coerce_meta_v3` in `persistence.py`; the file only flips to v3 on disk when the user runs `--add-provider`, `--remove-provider`, `--default-provider`, or `--keychain`.

### Testing conventions

- `conftest.py:full_home` temporarily monkeypatches `altergo.MAIN_HOME`, `altergo.ACCOUNTS_DIR`, etc. to a `tmp_path` tree, runs `configure_account()` to build a realistic fixture, then restores the originals before yielding. Tests that mutate globals must restore them; `full_home` already handles this.
- `conftest.py:fake_claude_bin` prepends `tests/bin/` to PATH so `shutil.which("claude")` resolves to the sentinel script that prints `ALTERGO_TEST_*` lines.
- Keychain tests pass `keychain_arg="none"` to `configure_account()` to avoid touching the real macOS keychain. Only tests in `test_keychain.py` that explicitly exercise keychain paths use `keychain_arg="isolated"` or `"dedicated"`.
- The `full_home` fixture sets up `default`, `work`, and `personal` accounts. Most smoke/integration tests use this fixture rather than building their own directory trees.

### Runtime directories

```
~/.altergo/
  .altergo.json           ← global settings (theme, shared-credential overrides, etc.)
  starred.json            ← starred sessions catalog
  last_session.json       ← last-exited session snapshot (for --star with no arg)
  version_check.json      ← PyPI version cache (daily)
  accounts/
    <name>/               ← account HOME (set as $HOME at launch)
      account.json        ← v3 metadata
      .claude/            ← provider dot-dir (one per active provider)
        .credentials.json ← REAL, isolated
        .claude.json      ← REAL, mcpServers merged; oauthAccount isolated
        projects/         ← symlink → ~/.claude/projects/
        settings.json     ← symlink → ~/.claude/settings.json
        CLAUDE.md         ← symlink → ~/.claude/CLAUDE.md
        ...               ← all other dirs/files symlinked to ~/.claude/
      .aws/               ← symlink → ~/.aws/ (if enabled in settings)
      .config/gh/         ← symlink → ~/.config/gh/ (if enabled)
      ...
```

CLI-credential catalog symlinks (`.aws/`, `.docker/`, `.kube/`, etc.) live at `account_home/` level — not inside the provider dot-dir — because they must be discoverable by `$HOME` resolution from any tool, not just the provider CLI.

### Session discovery

`get_sessions()` in `sessions.py` scans all four providers and returns sessions sorted by modification time:

| Provider | Path | Format |
|---|---|---|
| Claude Code | `~/.claude/projects/<dash-encoded>/*.jsonl` | JSONL |
| Codex CLI | `~/.codex/sessions/YYYY/MM/DD/*.jsonl` | JSONL |
| Gemini CLI | `~/.gemini/tmp/<project>/chats/*.json` | Single JSON |
| GitHub Copilot | `~/.copilot/session-state/<UUID>/` | `workspace.yaml` + `events.jsonl` |

Session preview extraction reads only the last 8KB of JSONL files, scanning backward for the most recent `"type": "human"` line.

### Argument routing in `cli.py:main()`

`_looks_like_account(token)` returns `True` for tokens that: don't start with `-`, aren't in `_KNOWN_COMMANDS`, and match `^[a-zA-Z0-9][a-zA-Z0-9_-]*$`. If `True`, `main()` checks disk for `ACCOUNTS_DIR / token` — found → consume as account name; not found → exit with a hint. This is how `altergo work` routes to the `work` account while `altergo --dangerously-skip-permissions` passes the flag straight to claude.
