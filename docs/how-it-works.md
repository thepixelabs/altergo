# How altergo works

**Applies to:** altergo v0.4.0  
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

There is no built-in support for multiple accounts. If you have a personal Claude Max subscription and a work subscription (or two Max plans under different organizations), you cannot switch between them from a single terminal. The `~/.claude/.credentials.json` file holds the active session for exactly one account at a time.

The naive workaround is to keep a second home directory and switch to it when you want the other account. The problem is that approach also loses everything else in `~/.claude/` — your session history, settings, keybindings, CLAUDE.md, and all the accumulated context that makes Claude Code actually useful.

---

## The naive solution and why it fails

The simplest approach is a shell alias:

```bash
alias claude-work='HOME=~/work-claude-home claude'
```

This does achieve credential isolation: when Claude Code starts, it reads `$HOME/.claude/.credentials.json`, so pointing `HOME` at a different directory means it authenticates as a different account.

But it also means the work account sees an entirely different `~/.claude/`. Its `projects/` is empty. Its `settings.json` has defaults. Your CLAUDE.md instructions are not there. The keybindings you spent time configuring are gone. Every session you started under your personal account is invisible to the work account and vice versa.

You now have two completely separate Claude Code universes that happen to live on the same machine. You must maintain duplicate configurations. Sessions from your personal account are not resumable under your work account and vice versa. If you start a session working on a project under one account and later open the same directory under the other account, you get a blank slate.

This is the problem altergo solves.

---

## The elegant solution: selective HOME override with symlinks

The insight is that only one thing needs to differ between accounts: the credentials file. Everything else — session history, settings, context, keybindings — you want to share.

altergo implements this with two mechanisms working together:

1. **Override `HOME` to `~/.altergo/`** so Claude Code reads credentials from `~/.altergo/.claude/.credentials.json` (a real, isolated file specific to the alt account).

2. **Symlink everything else** inside `~/.altergo/.claude/` back to the corresponding paths inside `~/.claude/` so the alt account sees the same session history, settings, and context as the primary account.

After `altergo --setup` runs, the directory structure looks like this:

```
~/.claude/                          ← Primary account (unmodified)
    .credentials.json               ← Primary credentials (real file)
    projects/                       ← Session history (real directory)
    settings.json                   ← Settings (real file)
    CLAUDE.md                       ← Global instructions (real file)
    keybindings.json                ← Keybindings (real file)
    tasks/ agents/ plans/ ...       ← Context directories (real)

~/.altergo/                         ← Alt account home
    .claude/
        .credentials.json           ← Alt credentials (real file, ISOLATED)
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
```

When Claude Code starts and reads `~/.altergo/.claude/projects/`, it transparently follows the symlink and reads from `~/.claude/projects/` — the same session files the primary account uses. Sessions are keyed by working directory path, not by account, so they are fully shared.

---

## Why `os.execvpe` and not `subprocess`

The core launch function is:

```python
def launch_claude(args=None):
    claude_path = shutil.which("claude")
    if not claude_path:
        sys.exit("altergo: 'claude' not found in PATH")
    env = _build_alt_env()
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
ALT_HOME = MAIN_HOME / ".altergo"
```

Consider what happens when you run `altergo` inside an already-running `altergo shell` session. In that context, `$HOME` has already been set to `~/.altergo`. If altergo resolved MAIN_HOME from `os.environ["HOME"]`, it would believe the main home is `~/.altergo`, set `ALT_HOME` to `~/.altergo/.altergo`, and then try to exec Claude Code with `HOME=~/.altergo/.altergo` — which does not exist and has no credentials.

The passwd database (`/etc/passwd` on Linux, Directory Services on macOS) is keyed by uid, not by environment variables. It always returns the account's real home directory regardless of what `$HOME` is set to in the current environment. Reading from it makes altergo safely re-entrant: you can run `altergo` from inside an `altergo shell` and it still finds the correct primary home.

The fallback to `os.environ["HOME"]` is only reached if the passwd entry's path does not exist on disk — an edge case in containerized or unusual environments where the passwd record is present but the directory was not created.

---

## The PATH problem and its fix

Claude Code's startup sequence includes a native installation health check. It tests whether `$HOME/.local/bin` is present in `PATH`. With HOME overridden to `~/.altergo`, the check looks for `~/.altergo/.local/bin` in PATH. That directory was never added to PATH (your shell's PATH was set up before altergo ran), so the check would fail with a spurious warning:

```
Native installation exists but ~/.local/bin is not in your PATH.
```

The `_build_alt_env` function handles this:

```python
def _build_alt_env():
    env = os.environ.copy()
    env["HOME"] = str(ALT_HOME)
    alt_local_bin = ALT_HOME / ".local" / "bin"
    if alt_local_bin.exists():
        alt_local_bin_str = str(alt_local_bin)
        path_dirs = env.get("PATH", "").split(":")
        if alt_local_bin_str not in path_dirs:
            env["PATH"] = alt_local_bin_str + ":" + env.get("PATH", "")
    return env
```

The guard `if alt_local_bin.exists()` is not defensive boilerplate — it is a security decision. Without it, altergo would unconditionally prepend `~/.altergo/.local/bin` to PATH on every launch. That directory does not exist by default. An attacker with write access to your home directory (or a compromised process running as you) could drop a malicious binary named `git`, `python`, or any other commonly executed tool into `~/.altergo/.local/bin` and have it execute with highest PATH precedence the next time you run `altergo`.

The guard means the injection only activates when something has actually installed a binary there — specifically, when you have run `claude update` inside an altergo session, which installs the claude binary to `$HOME/.local/bin`, which with HOME overridden means `~/.altergo/.local/bin/claude`. At that point the directory genuinely exists and does contain the claude binary that should be found first.

There is a second subtlety: `shutil.which("claude")` runs *before* `_build_alt_env()` modifies PATH. This is intentional. The claude binary that altergo resolves is the one visible on the system PATH at the moment the user runs `altergo` — typically `~/.local/bin/claude` from the primary account's native install. Resolving the path before modifying PATH ensures that if `~/.altergo/.local/bin/claude` exists (a separate alt-account native install), it does not shadow the primary binary and cause confusion about which version is running.

---

## The `altergo shell` command

```python
def launch_shell():
    env = _build_alt_env()
    shell = env.get("SHELL", "/bin/sh")
    shell_name = Path(shell).name
    if shell_name in ("bash", "sh"):
        env["PS1"] = f"(altergo) {env.get('PS1', r'\u@\h:\w\$ ').lstrip()}"
    elif shell_name == "zsh":
        env["PROMPT"] = f"(altergo) {env.get('PROMPT', '%n@%m %~ %# ')}"
    print(_c(36, f"Entering altergo shell (HOME={ALT_HOME})"))
    print(_c(2, "Run 'exit' or Ctrl-D to return to your primary account.\n"))
    os.execvpe(shell, [shell], env)
```

The primary use case for `altergo shell` is authenticating tools other than Claude Code with the alt account. `gh auth login` writes credentials to `~/.config/gh/`. `git config --global` writes to `~/.gitconfig`. SSH uses `~/.ssh/`. npm reads `~/.npmrc`. All of these resolve `~` from `$HOME` — which with HOME overridden to `~/.altergo` means they read and write into `~/.altergo/` automatically.

Once you run `altergo shell` and authenticate those tools, the credentials persist in `~/.altergo/` and are available for every subsequent `altergo` invocation.

The PS1/PROMPT injection gives a visual `(altergo)` prefix on the shell prompt. This matters because there is no other visual indicator that you are running in a different HOME. Without it, you could easily forget you are in the alt context and make changes (edit a global git config, install a package) that you intended to make in your primary environment.

Note that the PS1 injection only takes effect if your shell's rc files (`.bashrc`, `.zshrc`) do not set PS1/PROMPT themselves. Most shells' rc files unconditionally set the prompt, overriding what was in the environment. The injection is a best-effort hint — not a guarantee.

---

## The `altergo -- <cmd>` passthrough

```python
def launch_command(cmd_args):
    if not cmd_args:
        print(_c(31, "altergo -- requires a command. ..."), file=sys.stderr)
        sys.exit(1)
    env = _build_alt_env()
    os.execvpe(cmd_args[0], cmd_args, env)
```

This is the one-shot version of `altergo shell`. It runs a single command with HOME set to `~/.altergo` and then exits. Useful for scripting or for single operations you do not want to enter a subshell for:

```bash
altergo -- gh auth login
altergo -- gh auth status
altergo -- git config --global user.email me@work.com
altergo -- ssh-add ~/.altergo/.ssh/id_ed25519
```

Because it also uses `os.execvpe`, the altergo process is replaced by the target command — there is no wrapper, no overhead, and exit codes propagate correctly to any calling script.

---

## The symlink architecture in detail

### What is shared and why

| Entry | Type | Shared? | Rationale |
|---|---|---|---|
| `.credentials.json` | File | No (isolated) | This is the entire point — each account has its own auth token |
| `projects/` | Directory | Yes (symlink) | Sessions are keyed by filesystem path, not by account. Both accounts work on the same codebases |
| `tasks/` | Directory | Yes (symlink) | Task context is project-scoped, not account-scoped |
| `agents/` | Directory | Yes (symlink) | Agent definitions should be available from both accounts |
| `plans/` | Directory | Yes (symlink) | Plans are project work context, not account state |
| `session-env/` | Directory | Yes (symlink) | Shell environment snapshots are per-session, not per-account |
| `file-history/` | Directory | Yes (symlink) | File access history is useful for context regardless of which account is active |
| `shell-snapshots/` | Directory | Yes (symlink) | Shell state snapshots are session-scoped |
| `cache/` | Directory | Yes (symlink) | Response cache is content-addressed — sharing it means neither account re-fetches what the other already fetched |
| `settings.json` | File | Yes (symlink) | You want one set of editor preferences for both accounts |
| `CLAUDE.md` | File | Yes (symlink) | Your global instructions apply regardless of which account is active |
| `keybindings.json` | File | Yes (symlink) | Muscle memory is account-agnostic |

### The symlink setup and teardown contract

`altergo --setup` creates symlinks. It skips any entry in the source (`~/.claude/`) that does not yet exist — for example, if you have not yet configured keybindings, `~/.claude/keybindings.json` does not exist, so no symlink is created. This is deliberate: creating a dangling symlink pointing at a nonexistent target would cause Claude Code to behave differently than it would for a fresh install.

`altergo --teardown` removes only the symlinks it created. It does not touch `~/.altergo/.claude/.credentials.json` or any real files. After teardown, `~/.altergo/` still exists with its credentials intact — you can re-run `altergo --setup` at any time to restore the symlinks.

### Unmanaged state

Two directories accumulate inside `~/.altergo/.claude/` from normal Claude Code usage that altergo does not manage:

- **`paste-cache/`** — Ephemeral clipboard / paste buffer state. This being isolated per-account is harmless; paste cache is transient.
- **`plugins/`** — Plugin state. If you install Claude Code plugins, they accumulate separately in `~/.altergo/.claude/plugins/` and `~/.claude/plugins/`. This isolation is probably unintentional — plugin configuration is similar to `settings.json` in that you likely want it shared. If this matters to you, manually symlink `~/.altergo/.claude/plugins/` to `~/.claude/plugins/` after running setup, or open an issue requesting it be added to `SYMLINK_DIRS`.

---

## The session picker TUI

`altergo --resume` (with no session ID) opens an interactive terminal UI built with Python's `curses` module. Here is how it works from the outside in.

### Session discovery

```python
def get_sessions():
    sessions = []
    projects_dir = MAIN_CLAUDE / "projects"
    for project_dir in projects_dir.iterdir():
        if not project_dir.is_dir():
            continue
        for f in project_dir.iterdir():
            if f.suffix != ".jsonl" or f.parent.name == "subagents":
                continue
            session_id = f.stem
            mod_time = f.stat().st_mtime
            ...
```

Sessions are JSONL files inside `~/.claude/projects/<encoded-path>/<session-id>.jsonl`. The encoded path is the working directory with `/` replaced by `-` (e.g., `/home/user/Documents/git/dispatch` becomes `-Users-netz-Documents-git-dispatch`). `format_project_name` strips the path prefix and returns just the last component — the directory name that humans care about.

Subagent sessions (inside a `subagents/` subdirectory) are excluded from the listing. These are internal to Claude Code's multi-agent system; you cannot resume them directly.

Sessions are sorted by `st_mtime` (last modification time), most recent first. The first entry in the list is always the session you were most recently working in.

### Preview extraction

```python
def get_session_preview(jsonl_path):
    with open(jsonl_path, "rb") as f:
        f.seek(0, 2)
        size = f.tell()
        f.seek(max(0, size - 8192))
        tail = f.read().decode("utf-8", errors="replace")

    for line in tail.strip().split("\n"):
        obj = json.loads(line)
        if obj.get("type") == "human" and isinstance(obj.get("message"), dict):
            content = obj["message"].get("content", "")
            if isinstance(content, str) and content.strip():
                last_msg = content.strip()
            elif isinstance(content, list):
                for block in content:
                    if block.get("type") == "text":
                        last_msg = block["text"].strip()
```

Rather than parsing the entire JSONL file (which can be many megabytes for long sessions), altergo reads only the last 8KB. It scans backward through the lines looking for the most recent `"type": "human"` message. The content field can be either a plain string or a list of typed content blocks (the multi-modal message format) — both cases are handled.

The preview is truncated to 80 characters in the session list, then truncated further in the TUI to fit the terminal width.

### The TUI itself

The curses UI (`_draw_picker`) renders three zones:

1. A header row with navigation instructions
2. A column header row
3. The session list (scrollable, one session per row)
4. A footer showing the full session ID and position counter

Navigation follows vim conventions: `j`/`k` for line movement, `g`/`G` for top/bottom, `PgUp`/`PgDn` for page scroll. Arrow keys also work for those who prefer them. `Enter` returns the selected session; `q` or `Escape` returns `None` (cancelled).

When a session is selected, the picker exits and `launch_claude(["--resume", selected["id"]])` is called, which execs claude with the `--resume` flag passing the session ID directly to Claude Code's own resume mechanism.

---

## Data written outside `~/.claude/`

Claude Code writes to several locations beyond `~/.claude/`. With HOME overridden to `~/.altergo/`, all of these resolve into the alt home instead:

| Path | What writes there | Effect with HOME=~/.altergo |
|---|---|---|
| `$HOME/.local/bin/claude` | `claude update` (native install) | Installs a separate alt-account claude binary to `~/.altergo/.local/bin/claude` |
| `~/Library/Application Support/claude/` | macOS only — Electron app support data | Writes to `~/.altergo/Library/Application Support/claude/` |
| `$HOME/.gitconfig` | `git config --global` run inside a claude session | Writes to `~/.altergo/.gitconfig` — separate from your primary git config |
| `$HOME/.config/gh/` | `gh auth login` | Writes alt-account gh credentials to `~/.altergo/.config/gh/` |
| `$HOME/.ssh/` | Any SSH operations | Reads from `~/.altergo/.ssh/` — so the alt account can have separate SSH keys |

The `~/.local/bin/` behavior is worth calling out specifically. If you run `claude update` inside an altergo session, you will have two separate claude binaries: `~/.local/bin/claude` (primary account) and `~/.altergo/.local/bin/claude` (alt account). These may be at different versions. The PATH injection logic in `_build_alt_env` handles this: if `~/.altergo/.local/bin` exists, it is prepended to PATH so the alt-account claude binary takes precedence for alt-account sessions. But `shutil.which("claude")` resolves the path before the PATH modification, so the binary that actually gets exec'd is still determined by the original PATH — the primary account's claude binary. This means `claude update` inside an altergo session updates only the alt-account binary, and the version that runs for altergo is still whatever the primary PATH resolves.

If you want both accounts to always run the same claude version, run updates outside of altergo (in your primary account context).

---

## The complete data flow

Here is the sequence from `altergo [args]` to Claude Code running:

```
1. altergo starts
   │
   ├─ Resolve MAIN_HOME via pwd.getpwuid(os.getuid()).pw_dir
   │  (immune to $HOME being already overridden)
   │
   ├─ Parse sys.argv
   │  ├─ --setup / --teardown / --list / --version / --help → handled, exit
   │  ├─ --resume (no id) → session picker TUI → select → launch_claude(["--resume", id])
   │  ├─ shell → launch_shell()
   │  ├─ -- <cmd> → launch_command(args[1:])
   │  └─ anything else → launch_claude(args)
   │
2. launch_claude(args) called
   │
   ├─ shutil.which("claude") → resolves claude binary path from CURRENT PATH
   │  (before any PATH modification)
   │
   ├─ _build_alt_env()
   │  ├─ Copy os.environ
   │  ├─ Set HOME = ~/.altergo
   │  └─ If ~/.altergo/.local/bin exists: prepend to PATH
   │
   └─ os.execvpe(claude_path, [claude_path] + args, env)
      │
      └─ altergo process IMAGE REPLACED by claude
         Claude Code starts with:
           HOME = ~/.altergo
           PATH = (possibly with ~/.altergo/.local/bin prepended)
           All other env vars unchanged
         Claude reads:
           ~/.altergo/.claude/.credentials.json  (REAL FILE — alt credentials)
           ~/.altergo/.claude/projects/          (SYMLINK → ~/.claude/projects/)
           ~/.altergo/.claude/settings.json      (SYMLINK → ~/.claude/settings.json)
           ~/.altergo/.claude/CLAUDE.md          (SYMLINK → ~/.claude/CLAUDE.md)
           ... all other entries via symlinks ...
```

The result: Claude Code authenticates as the alt account, but sees exactly the same session history, settings, and context as the primary account. The two accounts are differentiated only by which credentials file they read.
