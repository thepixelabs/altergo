# Settings

Run `altergo --settings` to open the multi-page TUI. All settings are global — they apply to every account.

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

`altergo --settings` TUI:

| Key | Action |
|---|---|
| `j` / `k` / Arrow up/down | Navigate within page |
| `h` / `l` / Arrow left/right / `Tab` | Switch pages |
| `Space` | Toggle setting |
| `s` | Save and exit |
| `q` / `Esc` | Cancel |
| `PgUp` / `PgDn` | Scroll (Credentials page) |

---

## tmux session persistence

`altergo --settings` → **Behavior** → **tmux sessions** wraps every launch in a named tmux window. SSH disconnects don't kill the session; reattach with `tmux attach -t <name>` from any new login. Session names follow `<project>/<account>/<provider>`. altergo detects `$TMUX` and skips wrapping inside an existing session. Without tmux installed, it falls back to a plain launch with an install hint (`brew install tmux`).

| Key | Action |
|---|---|
| `Ctrl-b d` | Detach (leave running, return to shell) |
| `tmux ls` | List active sessions |
| `tmux attach -t <name>` | Reattach |

---

## First-run home-change notice

The first interactive `altergo` launch on a given machine shows a one-time full-screen notice explaining the HOME-isolation model (each account gets its own HOME; package managers see clean caches by default). Press any key to dismiss. Non-TTY launches skip it.

To re-trigger on a new machine, remove the marker file in `~/.altergo/`.

---

## Keychain mode (macOS)

Per-account, stored in `account.json` (not in the global settings TUI). The default since v1.2.0 is `keychain` — each account gets its own keychain, unlocked silently at launch. Opt out with `none`:

```bash
altergo --config <account> --keychain keychain   # per-account keychain (default)
altergo --config <account> --keychain none       # block keychain writes; flat-file fallback
```

Full guide: [keychain-isolation.md](keychain-isolation.md).

---

## CLI shortcuts

```sh
altergo --theme sunset    # set theme directly
# press 't' inside the launcher TUI to cycle themes live
```

---

## Settings file

`~/.altergo/.altergo.json` — global, above `accounts/`, atomic writes.

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

Missing keys fall back to defaults: `tmux_session`/`random_theme_enabled` default to `false`, `random_theme_frequency` defaults to `3`, other booleans default to `true`, theme defaults to `"ocean"`. The `shared` dict only stores entries that differ from catalog defaults.

Per-account `keychain` mode is in `account.json`, not here. Editing by hand is supported — changes take effect on the next launch.
