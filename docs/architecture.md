# Architecture reference

**Applies to:** altergo v0.4.0  
**Audience:** Engineers maintaining altergo, debugging symlink issues, or auditing what altergo touches on disk.

For a prose explanation of why the architecture is designed this way, see [how-it-works.md](how-it-works.md).

---

## Repository layout

```
altergo/
    altergo.py              ← Entire implementation (single file, ~554 lines)
    pyproject.toml          ← Package metadata, entry point, ruff config
    tests/
        test_smoke.py       ← Import, version, --version, --help smoke tests
    docs/
        how-it-works.md     ← Technical deep dive
        architecture.md     ← This file
        migration.md        ← Migration from claude100-resume
        index.html          ← Project website (deployed via GitHub Pages)
        ...
    .github/
        workflows/
            ci.yml          ← Lint (ruff) + test matrix (Python 3.9–3.13, ubuntu + macos)
            release.yml     ← PyPI publish on tag push
            pages.yml       ← GitHub Pages deploy
```

altergo has zero runtime dependencies. Everything it uses — `curses`, `json`, `os`, `pwd`, `shutil`, `sys`, `pathlib`, `datetime` — is Python standard library.

---

## Source file: `altergo.py`

The entire program is one file. Here is a map of its logical sections:

| Line range | Section | Purpose |
|---|---|---|
| 1–34 | Module docstring | Usage reference (also shown in `--help` fallback) |
| 36 | `__version__` | Semver string, source of truth for version |
| 38–45 | Imports | Standard library only |
| 50–54 | `_c()` | ANSI color helper — no-ops when stdout is not a TTY |
| 57–62 | `_link()` | OSC 8 terminal hyperlink — no-ops when stdout is not a TTY |
| 64–109 | `show_help()` | Colored, hyperlinked help output |
| 115–141 | Config constants | `MAIN_HOME`, `ALT_HOME`, `SYMLINK_DIRS`, `SYMLINK_FILES` |
| 146–220 | `do_setup()` | Creates `~/.altergo/`, creates symlinks, checks for credentials |
| 223–243 | `do_teardown()` | Removes symlinks only (leaves credentials and alt home intact) |
| 248–285 | `get_sessions()` | Discovers all session JSONL files, returns sorted list |
| 289–316 | `get_session_preview()` | Reads last 8KB of a session file to extract last user message |
| 319–324 | `format_project_name()` | Decodes Claude's encoded directory names back to readable form |
| 330–337 | `interactive_picker()` | Curses wrapper entry point |
| 340–443 | `_draw_picker()` | Curses rendering loop and keyboard handler |
| 449–468 | `_build_alt_env()` | Builds the modified environment dict (HOME + conditional PATH) |
| 471–478 | `launch_claude()` | Resolves claude binary, calls `_build_alt_env`, execs claude |
| 481–496 | `launch_shell()` | Opens interactive shell with alt HOME and PS1/PROMPT prefix |
| 499–505 | `launch_command()` | Execs arbitrary command with alt HOME |
| 511–573 | `main()` | Argument dispatch — routes to the appropriate function |

---

## Runtime directory layout

The following describes the filesystem state after `altergo --setup` has been run successfully.

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
    plans/
    cache/
    settings.json
    CLAUDE.md
    keybindings.json
```

### Alt account home

```
~/.altergo/
    .claude/
        .credentials.json       ← Real file. Isolated alt credentials. Created on first login.
        projects/               ← Symlink → ~/.claude/projects/
        tasks/                  ← Symlink → ~/.claude/tasks/
        session-env/            ← Symlink → ~/.claude/session-env/
        file-history/           ← Symlink → ~/.claude/file-history/
        shell-snapshots/        ← Symlink → ~/.claude/shell-snapshots/
        agents/                 ← Symlink → ~/.claude/agents/
        plans/                  ← Symlink → ~/.claude/plans/
        cache/                  ← Symlink → ~/.claude/cache/
        settings.json           ← Symlink → ~/.claude/settings.json
        CLAUDE.md               ← Symlink → ~/.claude/CLAUDE.md
        keybindings.json        ← Symlink → ~/.claude/keybindings.json

    # Written by Claude Code during normal usage (not managed by altergo):
    .local/bin/claude           ← Created if 'claude update' is run inside altergo
    .config/gh/                 ← Created if 'altergo shell' + 'gh auth login' is used
    .gitconfig                  ← Created if 'git config --global' is run inside altergo
    .ssh/                       ← Read/written if SSH operations happen inside altergo
    Library/Application Support/claude/   ← macOS only, Electron app support data

    # Unmanaged state written by Claude Code (accumulates over time):
    .claude/paste-cache/        ← Ephemeral paste buffer (isolated per account)
    .claude/plugins/            ← Plugin state (isolated per account, probably unintentional)
```

---

## Symlink reference table

Every entry in `SYMLINK_DIRS` and `SYMLINK_FILES` is listed here with its rationale.

### Shared directories (`SYMLINK_DIRS`)

| Directory | Contains | Why shared |
|---|---|---|
| `projects/` | Session JSONL files, one subdirectory per working-directory path | Sessions are indexed by filesystem path, not by account. Both accounts work on the same codebases. Sharing this is the primary purpose of altergo. |
| `tasks/` | Task files from Claude's task system | Tasks are scoped to a project, not to an account. You want the same task context regardless of which account is active. |
| `session-env/` | Shell environment snapshots captured at session start | These are per-session, not per-account. Sharing gives both accounts access to the same environment history. |
| `file-history/` | File access history | Context about which files were recently opened. Account-agnostic. |
| `shell-snapshots/` | Shell state captures | Per-session snapshots. No reason to isolate by account. |
| `agents/` | Agent definition files | Agent configurations are per-project. Sharing means you do not need to recreate agents in each account. |
| `plans/` | Plan files | Plans are project work context, not account state. |
| `cache/` | Response cache | Content-addressed cache. Sharing means neither account re-fetches what the other already fetched, reducing latency and API cost. |

### Shared files (`SYMLINK_FILES`)

| File | Contains | Why shared |
|---|---|---|
| `settings.json` | Editor settings, feature flags, UI preferences | Settings express personal workflow preferences, not account state. You want the same editor behavior from both accounts. |
| `CLAUDE.md` | Global system prompt and instructions for Claude | Instructions are how you configure Claude's behavior. Both accounts should follow the same instructions. |
| `keybindings.json` | Custom key mappings | Muscle memory is account-agnostic. |

### Isolated (real file, not symlinked)

| Path | Why isolated |
|---|---|
| `~/.altergo/.claude/.credentials.json` | This is the entire purpose of altergo. Each account must authenticate separately. Sharing credentials would make the accounts identical. |

### Unmanaged (written by Claude Code, not tracked by altergo)

| Path | Notes |
|---|---|
| `~/.altergo/.claude/paste-cache/` | Ephemeral. Safe to leave isolated. |
| `~/.altergo/.claude/plugins/` | Plugin state is isolated per-account. If you use plugins and want them shared, manually symlink this directory after running setup. |

---

## Environment modifications at launch

`_build_alt_env()` returns a modified copy of `os.environ`. It never mutates the live environment (no `os.environ["HOME"] = ...`). The modified dict is passed to `os.execvpe` and becomes the child process's environment. The calling Python process's environment is unchanged.

| Variable | Modification | Condition |
|---|---|---|
| `HOME` | Set to `~/.altergo` | Always |
| `PATH` | `~/.altergo/.local/bin` prepended | Only if `~/.altergo/.local/bin` exists on disk AND is not already in PATH |
| `PS1` | `(altergo) ` prefix prepended | Only in `launch_shell()`, only for bash/sh |
| `PROMPT` | `(altergo) ` prefix prepended | Only in `launch_shell()`, only for zsh |

All other environment variables are passed through unchanged. altergo does not strip, sanitize, or modify any other variable.

---

## Data flow: invocation to Claude Code running

```
User runs: altergo [args]
│
├─ Python starts altergo.py
│
├─ Module-level: resolve MAIN_HOME
│   pwd.getpwuid(os.getuid()).pw_dir        ← reads /etc/passwd (or Directory Services)
│   Falls back to os.environ["HOME"] only if passwd entry path does not exist
│   MAIN_HOME = resolved real home
│   ALT_HOME  = MAIN_HOME / ".altergo"
│
├─ main(): parse sys.argv[1:]
│   │
│   ├─ -h / --help      → show_help()           → sys.exit(0)
│   ├─ --version        → print version         → sys.exit(0)
│   ├─ --setup          → do_setup()            → sys.exit(0)
│   ├─ --teardown       → do_teardown()         → sys.exit(0)
│   ├─ --list           → get_sessions()        → print table → sys.exit(0)
│   │
│   ├─ --resume (alone)
│   │   └─ get_sessions() → interactive_picker() → user selects
│   │       ├─ selected  → launch_claude(["--resume", id])
│   │       └─ cancelled → sys.exit(0)
│   │
│   ├─ shell            → launch_shell()
│   ├─ -- <cmd> [args]  → launch_command(args[1:])
│   └─ anything else    → launch_claude(args)
│
└─ launch_claude(args) / launch_shell() / launch_command(args)
    │
    ├─ shutil.which("claude")   ← resolves from CURRENT (unmodified) PATH
    │
    ├─ _build_alt_env()
    │   ├─ env = os.environ.copy()
    │   ├─ env["HOME"] = str(ALT_HOME)          ← always
    │   └─ if ALT_HOME/.local/bin exists:
    │       prepend to env["PATH"]              ← conditional
    │
    └─ os.execvpe(binary, [binary] + args, env)
        │
        └─ PROCESS IMAGE REPLACED
           altergo no longer exists.
           Claude Code (or shell, or command) runs as the same PID.
           It reads:
             $HOME/.claude/.credentials.json    ← ~/.altergo/.claude/.credentials.json (real, alt)
             $HOME/.claude/projects/            ← ~/.altergo/.claude/projects/ → ~/.claude/projects/
             $HOME/.claude/settings.json        ← ~/.altergo/.claude/settings.json → ~/.claude/settings.json
             $HOME/.claude/CLAUDE.md            ← ~/.altergo/.claude/CLAUDE.md → ~/.claude/CLAUDE.md
             ... (all other symlinked entries) ...
```

---

## Session file format

Claude Code stores sessions as JSONL files at:

```
~/.claude/projects/<encoded-path>/<session-id>.jsonl
```

where `<encoded-path>` is the absolute working directory path with `/` replaced by `-`. Example:

```
~/.claude/projects/-Users-alice-code-myapp/a1b2c3d4-e5f6-7890-abcd-ef1234567890.jsonl
```

Each line in the JSONL file is a JSON object. altergo only reads lines where `"type": "human"` to extract the last user message for the session preview. It reads only the last 8KB of the file to avoid parsing multi-megabyte session histories in full.

The session ID (the filename stem) is a UUID that Claude Code generates. altergo passes it verbatim to `claude --resume <id>` — it does not interpret or modify it.

---

## `--setup` and `--teardown` idempotency

`do_setup()` is safe to run multiple times:

- If a symlink already points to the correct target, it prints a confirmation and moves on.
- If a symlink points to a different target, it warns and skips — it does not silently redirect an existing symlink.
- If the destination exists as a real directory (not a symlink), it warns and skips — it does not delete real data.
- If the source (`~/.claude/<name>`) does not exist yet, it skips the entry — it does not create dangling symlinks.

`do_teardown()` removes only symlinks. It does not touch real files or directories. `~/.altergo/.claude/.credentials.json` is never removed by teardown.

---

## Python version compatibility

altergo targets Python 3.9+ (`requires-python = ">=3.9"` in pyproject.toml). The CI matrix runs against 3.9, 3.10, 3.11, 3.12, and 3.13 on both ubuntu-latest and macos-latest.

The only Python version constraint visible in the code is the use of `pathlib.Path`, f-strings, and walrus operator — none of which require anything beyond 3.8. The 3.9 floor comes from the package metadata rather than any specific language feature used in the code.

No type annotations are used in the source; the code predates the decision to add them and the implementation is short enough that they are not necessary for comprehension.
