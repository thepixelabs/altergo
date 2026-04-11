# How altergo works

**Applies to:** altergo v0.16.0+  
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

After `altergo --setup` runs, the directory structure looks like this:

```
~/.claude/                          ← Primary account (unmodified)
    .credentials.json               ← Primary credentials (real file)
    projects/                       ← Session history (real directory)
    settings.json                   ← Settings (real file)
    CLAUDE.md                       ← Global instructions (real file)
    keybindings.json                ← Keybindings (real file)
    tasks/ agents/ plans/ ...       ← Context directories (real)

~/.altergo/accounts/default/        ← Default account home
    .claude/
        .credentials.json           ← Default account credentials (real, ISOLATED)
        projects/  ─────────────────┐
        tasks/     ─────────────────┤
        session-env/ ───────────────┤─── symlinks → ~/.claude/<name>/
        file-history/ ──────────────┤
        shell-snapshots/ ───────────┤
        agents/ ────────────────────┤
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
    "shell", "--resume", "--list", "--setup", "--teardown",
    "--settings", "--version", "-h", "--help", "--"
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
            f"Run 'altergo --setup --name {candidate}' to create it.",
            file=sys.stderr,
        )
        sys.exit(1)
    account = candidate
    args = args[1:]
```

If the directory does not exist, altergo exits with a clear error and a specific hint. There is no ambiguity: if you mistype an account name (`altergo wokr`), you get a helpful message rather than altergo silently passing `wokr` to claude as a flag.

---

## Auto-migration from v0.4.x

On first run after upgrading from v0.4.x, altergo detects the old layout and migrates it automatically, with no user action required.

### Detection

```python
def detect_legacy() -> bool:
    old_claude = MAIN_HOME / ".altergo" / ".claude"
    return old_claude.exists() and not ACCOUNTS_DIR.exists()
```

The trigger is precise: the old `~/.altergo/.claude/` directory exists AND the new `~/.altergo/accounts/` directory does not. A fresh v0.5.0 install (no prior data) returns `False`. A system that has already been migrated returns `False`. Only the exact v0.4.x layout triggers migration.

### Why non-interactive

The migration runs inside `main()` before any argument parsing. It prints a 4-line visible block to stdout:

```
altergo: layout migrated for v0.5.0 N-account support
  ~/.altergo/  →  ~/.altergo/accounts/default/
  Backup preserved at ~/.altergo/.legacy-backup/
  See https://altergo.pixelabs.net/docs/migration-0.5 for details
```

It also writes `~/.altergo/accounts/default/MIGRATED.txt` as a permanent audit trail recording the version, timestamp, old and new paths, and rollback instructions.

It does not ask for confirmation. The reasons:

1. The migration is safe and fully reversible (backup is always created).
2. Requiring user confirmation would break scripts and aliases that invoke `altergo` programmatically.
3. The old layout is unambiguous — there is no scenario where this detection misfires on a v0.5.0 install.

### The two-step rename and why `/tmp/`

```python
def migrate_legacy() -> None:
    old_root = MAIN_HOME / ".altergo"
    tmp_path = Path(f"/tmp/altergo-migrate-{os.getpid()}")
    old_root.rename(tmp_path)                     # Step 1: atomic on same filesystem
    ACCOUNTS_DIR.mkdir(parents=True, exist_ok=True)  # Step 2: create new layout
    default_home = ACCOUNTS_DIR / "default"
    tmp_path.rename(default_home)                 # Step 3: move into place
    backup_path = MAIN_HOME / ".altergo" / ".legacy-backup"
    shutil.copytree(str(default_home), str(backup_path), symlinks=True)  # Step 4: backup
    (default_home / "MIGRATED.txt").write_text(...)  # Step 5: audit trail
    print("altergo: layout migrated ...")         # Step 6: 4-line visible block
```

`~/.altergo` is renamed to `/tmp/altergo-migrate-<pid>/` in one atomic operation. This ensures that if the process is interrupted after step 1, the data is not lost — it sits in `/tmp/` under a PID-qualified name rather than in a partially-overwritten state. The PID qualifier prevents collisions if multiple altergo processes somehow run simultaneously on the same machine.

### The backup

Step 4 copies `accounts/default/` to `~/.altergo/.legacy-backup/` with `symlinks=True` — existing symlinks inside the default account are preserved as symlinks in the backup, not resolved and copied. The backup is read-only insurance: if something goes wrong after migration, you can restore by removing `accounts/default/` and copying `.legacy-backup/` back into place.

The backup is preserved through the entire v0.5.x series. It will be removed in v0.6.0.

---

## SYMLINK_HOME_DIRS placement: why at `account_home` level

Isolates Claude credentials. Shares AWS, GCP, Docker, and kubectl by default.

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
| `projects/` | Directory | Yes (symlink) | Sessions are keyed by filesystem path, not by account. All accounts work on the same codebases |
| `tasks/` | Directory | Yes (symlink) | Task context is project-scoped, not account-scoped |
| `agents/` | Directory | Yes (symlink) | Agent definitions should be available from all accounts |
| `plans/` | Directory | Yes (symlink) | Plans are project work context, not account state |
| `session-env/` | Directory | Yes (symlink) | Shell environment snapshots are per-session, not per-account |
| `file-history/` | Directory | Yes (symlink) | File access history is useful for context regardless of which account is active |
| `shell-snapshots/` | Directory | Yes (symlink) | Shell state snapshots are session-scoped |
| `cache/` | Directory | Yes (symlink) | Response cache is content-addressed — sharing it means no account re-fetches what another already fetched |
| `settings.json` | File | Yes (symlink) | You want one set of editor preferences for all accounts |
| `CLAUDE.md` | File | Yes (symlink) | Your global instructions apply regardless of which account is active |
| `keybindings.json` | File | Yes (symlink) | Muscle memory is account-agnostic |

### The symlink setup and teardown contract

`altergo --setup` creates symlinks. It skips any entry in the source (`~/.claude/`) that does not yet exist — for example, if you have not yet configured keybindings, `~/.claude/keybindings.json` does not exist, so no symlink is created. Creating a dangling symlink pointing at a nonexistent target would cause Claude Code to behave differently than it would for a fresh install.

`altergo --teardown` removes only the symlinks it created. It does not touch `.credentials.json` or any real files. After teardown, the account directory still exists with its credentials intact — you can re-run `altergo --setup` at any time to restore the symlinks.

### Unmanaged state

Two directories accumulate inside the account's `.claude/` from normal Claude Code usage that altergo does not manage:

- **`paste-cache/`** — Ephemeral clipboard / paste buffer state. This being isolated per-account is harmless; paste cache is transient.
- **`plugins/`** — Plugin state. If you install Claude Code plugins, they accumulate separately per account. If you want plugins shared, manually symlink the `plugins/` directory after running setup.

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
   ├─ migrate_legacy() — no-op if already on new layout
   │
   ├─ Parse sys.argv
   │  ├─ --setup / --teardown / --list / --version / --help → handled, exit
   │  ├─ --resume (no id) → session picker TUI → select → launch_claude("default", ["--resume", id])
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
