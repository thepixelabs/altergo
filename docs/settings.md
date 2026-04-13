# Settings

**Applies to:** altergo v0.16.0+

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

This page also has a **Launch animation** toggle that controls whether the star spinner plays during provider handoff.

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

**Off by default:** GitLab CLI, npm, SSH keys, Git identity, GPG keys.

---

## Keyboard shortcuts

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

## CLI shortcuts

You do not need to open the settings TUI for every change. These CLI flags modify the same settings file:

```sh
# Set theme directly
altergo --theme sunset

# Toggle update checker
altergo --update-check off
altergo --update-check on

# Cycle themes live in the launcher
# Press 't' while in the launcher TUI
```

---

## Settings file

All settings are stored in `~/.altergo/.altergo.json`. This file is above the `accounts/` directory and shared across all accounts. It is written atomically (temp file + rename) so it is never in a partial state.

```json
{
  "version": 1,
  "theme": "ocean",
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

Missing keys fall back to their defaults (`tmux_session` defaults to `false`; all other boolean settings default to `true`; theme defaults to `"ocean"`). The `shared` dict only stores entries that differ from catalog defaults — an empty `shared` object means everything is at its default.

Editing this file by hand is supported. Changes take effect on the next `altergo` invocation.
