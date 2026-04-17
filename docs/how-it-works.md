# How altergo works

**Applies to:** altergo v0.37.0+  
**Audience:** Engineers who want to understand the design in depth — not just what altergo does, but why it does it that way.

The [README](../README.md) covers installation and basic usage. This document covers the mechanics, the tradeoffs, and the reasoning behind every design decision.

---

## The problem

Claude Code stores everything under `~/.claude/`:

```
~/.claude/
    .credentials.json       ← OAuth tokens / session cookies for your account
    projects/               ← Session history, one subdirectory per working directory
    tasks/                  ← Task context from Claude's built-in task system
    agents/                 ← Agent definitions
    commands/               ← Custom slash commands
    skills/                 ← User skills
    plans/                  ← Plan files
    session-env/            ← Shell environment snapshots
    file-history/           ← File access history
    shell-snapshots/        ← Shell state captures
    cache/                  ← Response cache
    settings.json           ← Editor settings, feature flags, preferences
    CLAUDE.md               ← Your global system prompt / instructions
    keybindings.json        ← Custom keybindings
```

There is no built-in support for multiple accounts. Common scenarios where this matters:

- **Session continuity**: You hit a rate limit mid-session and need to continue on a second account without losing your place.
- **Thinker + executor**: You run one account on high-capability models for architecture decisions and a second on faster models for execution — same project, two operating modes.
- **Multiple clients**: You work with client-A and client-B, each providing their own organization seat, and need their contexts fully isolated.
- **Work vs. personal**: Your employer provisions a managed AI account; you also have a personal account for OSS and side projects on the same machine.
- **Testing / isolation**: You want to run a second account to test different CLAUDE.md instructions without touching your primary configuration.

In all of these cases, `~/.claude/.credentials.json` holds the active session for exactly one account at a time. Switching accounts naively means losing everything else in `~/.claude/`.

---

## The naive solution and why it fails

The simplest approach is a shell alias:

```bash
alias claude-work='HOME=~/work-claude-home claude'
```

This does achieve credential isolation: when Claude Code starts, it reads `$HOME/.claude/.credentials.json`, so pointing `HOME` at a different directory means it authenticates as a different account.

But it also means the work account sees an entirely different `~/.claude/`. Its `projects/` is empty. Its `settings.json` has defaults. Your CLAUDE.md instructions are not there. The keybindings you spent time configuring are gone. Every session you started under your personal account is invisible to the work account and vice versa.

You now have two completely separate Claude Code universes that happen to live on the same machine. You must maintain duplicate configurations. Sessions from your personal account are not resumable under your work account. If you start a session working on a project under one account and later open the same directory under the other account, you get a blank slate.

This is the problem altergo solves.

---

## The elegant solution: selective HOME override with symlinks

The insight is that only one thing needs to differ between accounts: the credentials file. Everything else — session history, settings, context, keybindings — you want to share.

altergo implements this with two mechanisms working together:

1. **Override `HOME` to the account directory** so Claude Code reads credentials from `~/.altergo/accounts/<name>/.claude/.credentials.json` (a real, isolated file specific to that account).

2. **Symlink everything else** inside the account's `.claude/` directory back to the corresponding paths inside `~/.claude/` so every account sees the same session history, settings, and context as the primary account.

After `altergo --config` runs, the directory structure looks like this:

```
~/.claude/                          ← Primary account (unmodified)
    .credentials.json               ← Primary credentials (real file)
    projects/                       ← Session history (real directory)
    settings.json                   ← Settings (real file)
    CLAUDE.md                       ← Global instructions (real file)
    keybindings.json                ← Keybindings (real file)
    tasks/ agents/ commands/ skills/ plans/ ...       ← Context directories (real)

~/.altergo/accounts/default/        ← Default account home
    .claude/
        .credentials.json           ← Default account credentials (real, ISOLATED)
        projects/  ─────────────────┐
        tasks/     ─────────────────┤
        session-env/ ───────────────┤─── symlinks → ~/.claude/<name>/
        file-history/ ──────────────┤
        shell-snapshots/ ───────────┤
        agents/ ────────────────────┤
        commands/ ──────────────────┤
        skills/ ────────────────────┤
        plans/ ─────────────────────┤
        cache/ ─────────────────────┘
        settings.json ──────────────── symlink → ~/.claude/settings.json
        CLAUDE.md ──────────────────── symlink → ~/.claude/CLAUDE.md
        keybindings.json ───────────── symlink → ~/.claude/keybindings.json
    .aws/ ───────────────────────────── symlink → ~/.aws/ (if enabled in settings)
    .config/gh/ ────────────────────── symlink → ~/.config/gh/ (if enabled)
    ...

~/.altergo/accounts/work/           ← Named "work" account home
    .claude/
        .credentials.json           ← Work credentials (real, ISOLATED)
        projects/  ─────────────────── symlink → ~/.claude/projects/ (same target!)
        ...
    .aws/ ───────────────────────────── symlink → ~/.aws/ (same shared credentials)
    ...
```

When Claude Code starts under any account and reads its `projects/` directory, it transparently follows the symlink and reads from `~/.claude/projects/` — the same session files every account uses. Sessions are keyed by working directory path, not by account, so they are fully shared.

---

## Why `os.execvpe` and not `subprocess`

The core launch function is:

```python
def launch_claude(account: str = "default", args=None):
    claude_path = _find_claude()
    env = _build_alt_env(account)
    cmd = [claude_path] + (args or [])
    os.execvpe(claude_path, cmd, env)
```

`os.execvpe` replaces the current process image with the new program. It does not fork. The altergo Python process ceases to exist — its code, its stack, its memory are all replaced by Claude Code. Claude Code inherits altergo's PID.

Using `subprocess.run` or `subprocess.Popen` would leave a Python wrapper process alive as the parent. That wrapper would need to:

- Forward signals (SIGINT, SIGTERM, SIGWINCH) to the child
- Pipe stdin/stdout/stderr without corrupting terminal control sequences
- Wait for the child to exit and propagate its exit code
- Avoid interfering with Claude Code's own terminal manipulation (it uses curses/raw mode for its TUI)

None of those problems exist with `os.execvpe`. The handoff is clean: the shell that launched altergo sees Claude Code's PID directly, signals go directly to Claude Code, and the terminal is owned by Claude Code without any intermediary.

This pattern (exec instead of fork+exec) is the correct approach whenever a wrapper's only job is to set up an environment and then get out of the way.

---

## Why `pwd.getpwuid(os.getuid()).pw_dir` and not `os.environ["HOME"]`

The config block at the top of altergo.py reads:

```python
_pw_home = Path(pwd.getpwuid(os.getuid()).pw_dir)
if not _pw_home.exists():
    _pw_home = Path(os.environ["HOME"])

MAIN_HOME = _pw_home
ACCOUNTS_DIR = MAIN_HOME / ".altergo" / "accounts"
```

Consider what happens when you run `altergo` inside an already-running `altergo shell` session. In that context, `$HOME` has already been set to `~/.altergo/accounts/default`. If altergo resolved `MAIN_HOME` from `os.environ["HOME"]`, it would believe the main home is the account directory, set `ACCOUNTS_DIR` to a path inside it, and try to exec Claude Code with `HOME` pointing at a nested, non-existent directory.

The passwd database (`/etc/passwd` on Linux, Directory Services on macOS) is keyed by uid, not by environment variables. It always returns the account's real home directory regardless of what `$HOME` is set to in the current environment. Reading from it makes altergo safely re-entrant: you can run `altergo` from inside an `altergo shell` and it still finds the correct primary home.

The fallback to `os.environ["HOME"]` is only reached if the passwd entry's path does not exist on disk — an edge case in containerized or unusual environments.

---

## The PATH problem and its fix

Claude Code's startup sequence includes a native installation health check. It tests whether `$HOME/.local/bin` is present in `PATH`. With HOME overridden to an account directory, the check looks for `~/.altergo/accounts/<name>/.local/bin` in PATH. That directory was never added to PATH (your shell's PATH was set up before altergo ran), so the check would fail with a spurious warning.

The `_build_alt_env` function handles this:

```python
def _build_alt_env(account: str = "default") -> dict:
    account_home, _ = resolve_account(account)
    env = os.environ.copy()
    env["HOME"] = str(account_home)
    acct_local_bin = account_home / ".local" / "bin"
    if acct_local_bin.exists():
        acct_local_bin_str = str(acct_local_bin)
        path_dirs = env.get("PATH", "").split(":")
        if acct_local_bin_str not in path_dirs:
            env["PATH"] = acct_local_bin_str + ":" + env.get("PATH", "")
    return env
```

The guard `if acct_local_bin.exists()` is a security decision. Without it, altergo would unconditionally prepend a nonexistent path to PATH on every launch — giving a directory that anyone with write access to your home could later populate with malicious binaries higher precedence than all system tools.

The guard means PATH injection only activates when something has actually installed a binary there — specifically, when you have run `claude update` inside an altergo session, which installs the claude binary to `$HOME/.local/bin` (i.e., `~/.altergo/accounts/<name>/.local/bin`). At that point the directory genuinely exists and does contain the correct claude binary.

---

## Account disambiguation

When you run `altergo work`, the word `work` could be:
- An account name (route to the work account)
- A claude flag being passed through (unlikely, but altergo must not break `altergo --dangerously-skip-permissions`)

altergo resolves this with a two-step check in `main()`:

**Step 1 — `_looks_like_account(token)`:**

```python
_KNOWN_COMMANDS = frozenset([
    "shell", "use", "portal",
    "--resume", "--recall", "--search", "--config", "--rename",
    "--teardown", "--settings", "--version", "--use", "--launch",
    "--theme", "--star", "-h", "--help", "--"
])

def _looks_like_account(token: str) -> bool:
    if token.startswith("-"):
        return False
    if token in _KNOWN_COMMANDS:
        return False
    return bool(re.match(r"^[a-zA-Z0-9][a-zA-Z0-9_-]*$", token))
```

Anything starting with `-` is a flag — pass it to claude. Anything in `_KNOWN_COMMANDS` is an altergo subcommand. Anything matching the account name pattern is a candidate account name.

**Step 2 — directory existence check:**

```python
if args and _looks_like_account(args[0]):
    candidate = args[0]
    acct_home = ACCOUNTS_DIR / candidate
    if not acct_home.is_dir():
        print(
            f"altergo: account '{candidate}' not found. "
            f"Run 'altergo --config {candidate}' to create it.",
            file=sys.stderr,
        )
        sys.exit(1)
    account = candidate
    args = args[1:]
```

If the directory does not exist, altergo exits with a clear error and a specific hint. There is no ambiguity: if you mistype an account name (`altergo wokr`), you get a helpful message rather than altergo silently passing `wokr` to claude as a flag.

---

## Auto-migration from v0.4.x (historical)

> **Removed in v0.35.3.** Between v0.5.0 and v0.35.2, altergo auto-detected the v0.4.x layout (`~/.altergo/.claude/` present, `~/.altergo/accounts/` absent) and migrated it in place on first run. The `detect_legacy` / `migrate_legacy` code paths are gone in v0.35.3+. If you are still on a pre-v0.5.0 layout today, see [docs/migration.md](migration.md#archived-migration-notes-v04x--v050) for the archived procedure or open an issue for manual guidance.

---

## Native passthrough: `altergo native`

Sometimes you want the exact opposite of what altergo does: launch your provider with your real `$HOME` intact, no isolation, no symlinks. That is what `altergo native` gives you.

```bash
altergo native              # launch your default provider against $HOME
altergo native gemini       # force a specific provider
```

Under the covers, `altergo native` skips the env-override entirely — `HOME` is left as-is, no symlinks are traversed, no bidirectional MCP merge runs. The provider reads directly from your primary `~/.claude/` (or `~/.gemini/`, `~/.codex/`, `~/.copilot/`). Useful for:

- Quick sanity checks — "is this bug altergo's fault or the provider's?"
- One-off sessions where you explicitly want the primary account and do not care about account switching
- Scripts that want to invoke the provider without disturbing altergo's state

If you find yourself reaching for `altergo native` often, you probably want to reconfigure: `altergo --config <name>` and use the named account path instead.

---

## tmux session persistence

When the **tmux sessions** setting is enabled, every `altergo` launch wraps the provider inside a named tmux window (one per account + provider). Sessions keep running even when the terminal closes or the SSH connection drops, and a second `altergo` from a new login attaches to the existing session instead of starting a fresh one.

This matters most for:

- **Remote development over SSH** — laptop sleeps, wifi flickers, or the SSH tunnel drops. The AI session keeps going on the remote box; you reattach and pick up where you left off.
- **Long-running agent loops** — multi-step agents that take minutes to complete don't die when you close the terminal to do something else.
- **Multi-pane workflows** — tmux's own split-pane/attach semantics compose naturally with altergo's per-account windows.

altergo detects an existing `$TMUX` environment and skips wrapping to avoid nesting sessions; if tmux is not installed it falls back to a plain launch and prints an install hint.

See [docs/settings.md](settings.md#tmux-session-persistence) for how to enable the setting and the keybindings once inside a session.

---

## CLI-credential symlinks: why at `account_home` level

AWS, GCP, Docker, and kubectl credentials are shared across accounts by default — configurable via `altergo --settings`.

The catalog symlinks (`.aws/`, `.config/gh/`, `.docker/`, etc.) are created at `account_home/` level — for example, `~/.altergo/accounts/work/.aws` — not inside the `.claude/` subdirectory.

This is a deliberate design choice. The `.claude/` directory is Claude Code's private data store. Placing CLI tool credentials inside it would be incorrect because:

1. **They are not Claude Code data.** `.aws/` belongs to the AWS CLI. Mixing it into `.claude/` creates a confusing ownership boundary.
2. **Other tools resolve from `$HOME`, not from `$HOME/.claude/`.** When you run `aws` with `HOME=~/.altergo/accounts/work`, the AWS CLI looks for `$HOME/.aws` — which is `~/.altergo/accounts/work/.aws`. Placing the symlink there means the tool finds it without any special configuration.
3. **Claude Code does not need to know about them.** Claude Code reads `$HOME/.claude/`. The catalog symlinks are invisible to it and do not interfere with its operation.

The result: every tool that resolves credentials from `$HOME` automatically finds the correct (shared or isolated) credentials for the active account, without any changes to those tools.

---

## The `altergo shell` command

```python
def launch_shell(account: str = "default"):
    account_home, _ = resolve_account(account)
    env = _build_alt_env(account)
    shell = env.get("SHELL", "/bin/sh")
    shell_name = Path(shell).name
    label = f"altergo:{account}"
    if shell_name in ("bash", "sh"):
        env["PS1"] = f"({label}) {env.get('PS1', r'\u@\h:\w\$ ').lstrip()}"
    elif shell_name == "zsh":
        env["PROMPT"] = f"({label}) {env.get('PROMPT', '%n@%m %~ %# ')}"
    os.execvpe(shell, [shell], env)
```

The primary use case is authenticating tools other than Claude Code with the account. `gh auth login` writes credentials to `~/.config/gh/`. `git config --global` writes to `~/.gitconfig`. All of these resolve `~` from `$HOME` — which with HOME overridden means they read and write into the account directory automatically.

The PS1/PROMPT injection gives a visual `(altergo:work)` prefix on the shell prompt. This matters because there is no other visual indicator that you are running in a different HOME. Without it, you could easily forget you are in the alt context and make changes you intended to make in your primary environment.

Note that the PS1 injection only takes effect if your shell's rc files (`.bashrc`, `.zshrc`) do not set PS1/PROMPT themselves. Most shells' rc files unconditionally set the prompt, overriding what was in the environment. The injection is a best-effort hint — not a guarantee.

Named account variants work the same way:

```bash
altergo work shell          # PS1 shows (altergo:work)
altergo client-a shell      # PS1 shows (altergo:client-a)
```

---

## The `altergo <name> -- <cmd>` passthrough

This is the one-shot version of `altergo shell`. It runs a single command with HOME set to the account directory and then exits:

```bash
altergo work -- gh auth login
altergo work -- git config --global user.email me@work.com
altergo client-a -- terraform login
```

Because it also uses `os.execvpe`, the altergo process is replaced by the target command — there is no wrapper, no overhead, and exit codes propagate correctly to any calling script.

---

## The symlink architecture in detail

### What is shared and why

| Entry | Type | Shared? | Rationale |
|---|---|---|---|
| `.credentials.json` | File | No (isolated) | This is the entire point — each account has its own auth token |
| `.claude.json` | File | No (isolated) | Holds `oauthAccount`; the `mcpServers` section is bidirectionally synced at every `--config` and every launch (see "MCP servers: sync, not symlink" below) |
| `plugins/` | Directory | No (isolated) | Plugin state is per-install |
| `paste-cache/` | Directory | No (isolated) | Ephemeral clipboard state |
| `projects/` | Directory | Yes (symlink) | Sessions are keyed by filesystem path, not by account. All accounts work on the same codebases |
| `tasks/` | Directory | Yes (symlink) | Task context is project-scoped, not account-scoped |
| `agents/` | Directory | Yes (symlink) | Agent definitions should be available from all accounts |
| `commands/` | Directory | Yes (symlink) | Custom slash commands are user-authored, not account-specific |
| `skills/` | Directory | Yes (symlink) | Skills are user-authored content with no credential or session state |
| `plans/` | Directory | Yes (symlink) | Plans are project work context, not account state |
| `session-env/` | Directory | Yes (symlink) | Shell environment snapshots are per-session, not per-account |
| `file-history/` | Directory | Yes (symlink) | File access history is useful for context regardless of which account is active |
| `shell-snapshots/` | Directory | Yes (symlink) | Shell state snapshots are session-scoped |
| `cache/` | Directory | Yes (symlink) | Response cache is content-addressed — sharing it means no account re-fetches what another already fetched |
| `settings.json` | File | Yes (symlink) | You want one set of editor preferences for all accounts |
| `CLAUDE.md` | File | Yes (symlink) | Your global instructions apply regardless of which account is active |
| `keybindings.json` | File | Yes (symlink) | Muscle memory is account-agnostic |

> Every "shared" entry is a symlink to the real target under `~/.claude/`. That means *the same inode*: editing your CLAUDE.md from one account is instantly visible from every other account. There is no sync step because there is no second copy.

### MCP servers: sync, not symlink

`~/.claude.json` is a problem file. It holds two pieces of state that pull in opposite directions:

- **`mcpServers`** — the list of MCP server registrations you add with `claude mcp add`. You want this shared, otherwise every account has to re-register the same servers.
- **`oauthAccount`** — the identity of the currently authenticated Claude account. You *must not* share this; leaking it across accounts would break the whole point of altergo.

Symlinking the file gives you the first half at the cost of the second. Not sharing it gives you the second at the cost of the first. altergo resolves the conflict with a **bidirectional merge**, implemented in `_sync_claude_mcps` (altergo.py:2509-2576):

1. Read `~/.claude.json` (primary) and `~/.altergo/accounts/<name>/.claude.json` (account).
2. Union-merge the `mcpServers` maps from both files. On key collision, the account entry wins — that way, the server you just registered with `claude mcp add` is preserved.
3. Write the merged result back into *both* files, atomically (temp file + rename). `oauthAccount` in each file is left completely untouched.

The merge runs on every `altergo --config` and every Claude launch, so registrations propagate as soon as you next touch any account. Net effect: you register an MCP server once, from any account, and every account sees it. OAuth identity stays per-account.

### The symlink config and teardown contract

`altergo --config` creates symlinks. It skips any entry in the source (`~/.claude/`) that does not yet exist — for example, if you have not yet configured keybindings, `~/.claude/keybindings.json` does not exist, so no symlink is created. Creating a dangling symlink pointing at a nonexistent target would cause Claude Code to behave differently than it would for a fresh install.

`altergo --teardown` removes only the symlinks it created. It does not touch `.credentials.json` or any real files. After teardown, the account directory still exists with its credentials intact — you can re-run `altergo --config` at any time to restore the symlinks.

### Unmanaged state

Two directories accumulate inside the account's `.claude/` from normal Claude Code usage that altergo does not manage:

- **`paste-cache/`** — Ephemeral clipboard / paste buffer state. This being isolated per-account is harmless; paste cache is transient.
- **`plugins/`** — Plugin state. If you install Claude Code plugins, they accumulate separately per account. If you want plugins shared, manually symlink the `plugins/` directory after running `altergo --config`.

`.claude.json` itself is also per-account, but is *not* unmanaged — its `mcpServers` section is merged bidirectionally on every `--config` and every launch. See "MCP servers: sync, not symlink" above.

---

## The session picker TUI

`altergo --resume` (with no session ID) opens an interactive terminal UI built with Python's `curses` module.

### Session discovery

Sessions are JSONL files inside `~/.claude/projects/<encoded-path>/<session-id>.jsonl`. The encoded path is the working directory with `/` replaced by `-`. `format_project_name` strips the path prefix and returns just the last component — the directory name that humans care about.

Subagent sessions (inside a `subagents/` subdirectory) are excluded from the listing. These are internal to Claude Code's multi-agent system; you cannot resume them directly.

Sessions are sorted by `st_mtime` (last modification time), most recent first. Because `projects/` is symlinked to the same target for every account, the session picker shows sessions from all accounts in one unified list.

### Preview extraction

Rather than parsing the entire JSONL file (which can be many megabytes for long sessions), altergo reads only the last 8KB. It scans backward through the lines looking for the most recent `"type": "human"` message. The content field can be either a plain string or a list of typed content blocks (the multi-modal message format) — both cases are handled.

The preview is truncated to 80 characters in the session list, then truncated further in the TUI to fit the terminal width.

### The TUI itself

The curses UI renders three zones:

1. A header row with navigation instructions
2. A column header row
3. The session list (scrollable, one session per row)
4. A footer showing the full session ID and position counter

Navigation follows vim conventions: `j`/`k` for line movement, `g`/`G` for top/bottom, `PgUp`/`PgDn` for page scroll. Arrow keys also work. `Enter` returns the selected session; `q` or `Escape` returns `None` (cancelled).

---

## Data written outside `~/.claude/`

Claude Code writes to several locations beyond `~/.claude/`. With HOME overridden to an account directory, all of these resolve into the account home instead:

| Path | What writes there | Effect with HOME=account directory |
|---|---|---|
| `$HOME/.local/bin/claude` | `claude update` (native install) | Installs a separate account-specific claude binary |
| `~/Library/Application Support/claude/` | macOS only — Electron app support data | Writes to the account directory |
| `$HOME/.gitconfig` | `git config --global` run inside a claude session | Writes to the account directory — separate from your primary git config (unless Git identity sharing is enabled in settings) |
| `$HOME/.config/gh/` | `gh auth login` | Writes account credentials to the account directory (unless GitHub CLI sharing is enabled in settings) |
| `$HOME/.ssh/` | Any SSH operations | Reads from the account directory (unless SSH sharing is enabled in settings) |

---

## The complete data flow

```
1. altergo starts
   │
   ├─ Resolve MAIN_HOME via pwd.getpwuid(os.getuid()).pw_dir
   │  (immune to $HOME being already overridden)
   │
   │  (legacy v0.4.x auto-migration was removed in v0.35.3 — see migration.md)
   │
   ├─ Parse sys.argv
   │  ├─ --config / --teardown / --version / --help → handled, exit
   │  ├─ --recall → session picker TUI → resolve account from session.provider → launch_claude(account, ["--resume", id])
   │  ├─ --resume [id] → pass-through to the provider (handled downstream)
   │  ├─ _looks_like_account(args[0]) → account = args[0]; args = args[1:]
   │  ├─ [account] shell → launch_shell(account)
   │  ├─ [account] -- <cmd> → launch_command(account, args[1:])
   │  └─ anything else → launch_claude(account, args)
   │
2. launch_claude(account, args) called
   │
   ├─ _find_claude() → resolves claude binary path from CURRENT PATH + fallbacks
   │  (before any PATH modification)
   │
   ├─ _build_alt_env(account)
   │  ├─ Copy os.environ
   │  ├─ Set HOME = ~/.altergo/accounts/<account>
   │  └─ If account_home/.local/bin exists: prepend to PATH
   │
   └─ os.execvpe(claude_path, [claude_path] + args, env)
      │
      └─ altergo process IMAGE REPLACED by claude
         Claude Code starts with:
           HOME = ~/.altergo/accounts/<account>
           PATH = (possibly with account .local/bin prepended)
           All other env vars unchanged
         Claude reads:
           ~/.altergo/accounts/<account>/.claude/.credentials.json  (REAL — account credentials)
           ~/.altergo/accounts/<account>/.claude/projects/          (SYMLINK → ~/.claude/projects/)
           ~/.altergo/accounts/<account>/.claude/settings.json      (SYMLINK → ~/.claude/settings.json)
           ~/.altergo/accounts/<account>/.claude/CLAUDE.md          (SYMLINK → ~/.claude/CLAUDE.md)
           ~/.altergo/accounts/<account>/.aws/                      (SYMLINK → ~/.aws/, if enabled)
           ... all other entries via symlinks ...
```

The result: Claude Code authenticates as the named account, but sees exactly the same session history, settings, and context as the primary account. All accounts on the same machine are differentiated only by which credentials file they read.
