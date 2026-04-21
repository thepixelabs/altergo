# Settings

**Applies to:** altergo v0.40.0+

Run `altergo --settings` to open the multi-page settings TUI. All settings are global — they apply to every account.

---

## Pages

The settings TUI has three pages, navigated with arrow keys, `h`/`l`, or `Tab`.

### Appearance

Theme selection with live preview. Moving the cursor over a theme immediately recolors the entire TUI so you can see how it looks before saving. Color swatches next to each theme show the gradient stops.

| Theme | Description |
|---|---|
| Ocean | Calm cyan and indigo — the original altergo palette |
| Forest | Calming moss and sage — grounded green tones |
| Lavender | Soft violet and periwinkle — gentle on the eyes |
| Sunset | Warm rose and ember — dusk palette |
| Mono | Grayscale — minimal, distraction-free |
| Rainbow | Every color, still readable |

This page also has:

- **Banner font picker** — choose the figlet font used for the altergo wordmark. Live preview of the selected font.
- **Animation pack picker** — choose the spinner style used during provider handoff. A live frame of the selected pack is shown as you navigate.
- **Randomize theme** — toggle automatic theme rotation and set the frequency (rarely ↔ often). When enabled, altergo rotates through themes every N sessions as configured.
- **Launch animation** toggle — turn the launch spinner on or off entirely.

### Behavior

Toggle switches for launch and session messages:

| Setting | Default | Effect |
|---|---|---|
| Update checker | On | Check PyPI for new altergo versions daily |
| Greeting messages | On | Show a time-of-day greeting beneath the banner on launch |
| Goodbye messages | On | Print a witty one-liner to stderr after each session ends |
| tmux sessions | Off | Wrap every session in a named tmux window so it survives SSH disconnects and can be reattached later |

### Credentials

Share CLI tool credentials between your main home and all altergo accounts. Each entry is a symlink from the account home to the corresponding directory in your real home.

Items marked with a warning icon have security implications — the warning is shown in the footer when you highlight them.

**On by default:** AWS, Google Cloud, Azure, Docker, Kubernetes, Terraform, GitHub CLI.

**Off by default:** GitLab CLI, npm, SSH keys, Git identity, GPG keys, and every entry in the Package Managers category (below).

#### Package managers

All package-manager entries ship **off by default** — each account gets a clean install cache. Turn on only the ones you explicitly want shared.

| Entry | Paths shared when enabled | Notes |
|---|---|---|
| **pip (Python)** | `.pip`, `.config/pip`, `.pypirc`, `.local/lib`, `.local/bin` | Shares PyPI credentials and user-installed packages/scripts |
| **cargo (Rust)** | `.cargo` | Shares the entire cargo dir: registry cache, installed binaries, credentials |
| **gem (Ruby)** | `.gem`, `.gemrc` | — |
| **yarn** | `.yarn`, `.yarnrc.yml`, `.yarnrc` | — |
| **pnpm** | `.pnpmrc`, `.local/share/pnpm` | — |
| **composer (PHP)** | `.composer` | Shares Composer auth tokens, config, and global packages |
| **go modules** | `go`, `.config/go` | Shares the Go module cache and go env config. Can be large |
| **Maven (Java)** | `.m2` | Includes `settings.xml` credentials and the local repo cache |
| **Gradle (Java)** | `.gradle` | — |
| **Bundler (Ruby)** | `.bundle` | — |

---

## Keyboard shortcuts

These shortcuts apply to the `altergo --settings` TUI only. For the `altergo --recall` session picker, see [how-it-works.md — The session picker TUI](how-it-works.md#the-session-picker-tui).

| Key | Action |
|---|---|
| `j` / `k` / Arrow up/down | Navigate items within the current page |
| `h` / `l` / Arrow left/right | Switch between pages |
| `Tab` / `Shift+Tab` | Switch between pages |
| `Space` | Toggle a setting on or off |
| `s` | Save all changes and exit |
| `q` / `Esc` | Cancel — discard all changes and exit |
| `PgUp` / `PgDn` | Scroll (Credentials page) |

---

## tmux session persistence

**Where it lives:** `altergo --settings` → **Behavior** → **tmux sessions**. See the [README](../README.md#next-steps) for the one-line pitch.

When **tmux sessions** is enabled, every `altergo` invocation wraps the provider session in a dedicated tmux window. This means:

- **SSH disconnects are safe** — the AI session keeps running on the host machine even if your terminal app closes or the connection drops.
- **Reattach from anywhere** — open a new SSH session, run `tmux ls` to list active sessions, and `tmux attach -t <session-name>` to reconnect.
- **Session names** follow the pattern `altergo-<account>-<provider>-<id>` (e.g. `altergo-work-claude-a3f9b2`) so they are easy to identify.
- **Already inside tmux?** altergo detects the `$TMUX` environment variable and skips the wrapper to avoid nesting sessions.
- **tmux not installed?** altergo falls back to a plain session and prints an install hint (`brew install tmux`).

Quick reference once inside a tmux session:

| Key | Action |
|---|---|
| `Ctrl-b d` | Detach — leave the session running, return to shell |
| `Ctrl-b [` | Scroll mode — use arrow keys to scroll back |
| `tmux ls` | List all running sessions (run from any shell) |
| `tmux attach -t <name>` | Reattach to a session by name |

---

## The home-change notice (first-run, one-time)

**Introduced in v0.31.0.** The first time you launch any account on a given machine, altergo shows a short, full-screen animated notice explaining the HOME-isolation model — that each account runs in its own HOME folder, and that package managers (pip, cargo, gem, yarn, and friends) do not see packages installed in your main account by default.

- **When it fires:** once per machine, on your first interactive `altergo` launch. Non-TTY launches (scripts, CI, `altergo -- <cmd>`) skip the animation entirely.
- **How to dismiss:** press any key. The notice fades out and altergo continues with its normal banner.
- **State:** altergo writes a marker flag so the notice is never shown a second time, even if the animation is interrupted with Ctrl-C.
- **Why you cannot turn it back on:** the notice is a one-time education step, not a recurring toggle. If you want to see it again (for example, on a new machine), the marker lives alongside the settings file under `~/.altergo/` — remove it by hand to re-trigger.

If the notice prompts you to share a package manager across accounts, the shortcut is `altergo --settings` → **Credentials** → **Package Managers**.

---

## Keychain isolation (macOS, per-account)

Keychain isolation is a **per-account** setting stored in `account.json`, not in the global `.altergo.json`. It does not appear in the `altergo --settings` TUI.

Toggle it via the CLI:

```bash
altergo --config <name> --keychain isolated   # enable
altergo --config <name> --keychain shared     # disable and clean up
```

Or answer "y" to the keychain isolation prompt during interactive `altergo --config <name>`.

See [docs/keychain-isolation.md](keychain-isolation.md) for the full guide.

---

## CLI shortcuts

You do not need to open the settings TUI for every change. These CLI flags modify the same settings file:

```sh
# Set theme directly
altergo --theme sunset

# Cycle themes live in the launcher
# Press 't' while in the launcher TUI
```

> **Removed in v0.35.3:** the `altergo --update-check off` / `altergo --update-check on` flags were removed. The update-checker toggle lives in `altergo --settings` → **Behavior** → **Update checker** only.

---

## Settings file

All settings are stored in `~/.altergo/.altergo.json`. This file is above the `accounts/` directory and shared across all accounts. It is written atomically (temp file + rename) so it is never in a partial state.

```json
{
  "version": 1,
  "theme": "ocean",
  "banner_font": "smslant",
  "animation_pack": "dots",
  "random_theme_enabled": false,
  "random_theme_frequency": 3,
  "update_check": true,
  "show_greeting": true,
  "show_goodbye": true,
  "launch_animation": true,
  "tmux_session": false,
  "active_account": "work",
  "shared": {
    "ssh": true,
    "gitconfig": false
  }
}
```

Missing keys fall back to their defaults (`tmux_session` defaults to `false`; `random_theme_enabled` defaults to `false`; `random_theme_frequency` defaults to `3`; all other boolean settings default to `true`; theme defaults to `"ocean"`). The `shared` dict only stores entries that differ from catalog defaults — an empty `shared` object means everything is at its default.

The `keychain` setting is **not** in this file — it lives in `account.json` per account.

Editing this file by hand is supported. Changes take effect on the next `altergo` invocation.
