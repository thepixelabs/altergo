# Migration guide

Live, supported upgrade paths only. Older notes are summarized at the bottom — see [CHANGELOG.md](../CHANGELOG.md) and git history for details.

---

## v1.2.0 — keychain mode rename + SSH OAuth bridge

**macOS only.** The per-account-keychain mode was renamed from `private` to `keychain`. The other mode (`none`) is unchanged.

| Pre-v1.2.0 | v1.2.0+ | Behavior |
|---|---|---|
| `private` (default) | `keychain` (default) | Per-account keychain, unlocked silently at launch |
| `none` | `none` | No keychain writes; flat-file fallback |

Also new: `altergo --setup-token <account>` for claude accounts generates an OAuth token file under the account home, so `keychain`-mode accounts work over SSH (where macOS Security refuses keychain reads). The interactive `--config` flow offers token setup right after picking `keychain` mode. See [ssh-auth.md](ssh-auth.md).

### Automatic migration

Existing accounts keep working:

- `"keychain": "private"` on disk → coerced to `"keychain"` in memory with a one-time stderr warning.
- `"keychain": "none"` on disk → unchanged.
- No `keychain` key → still defaults to per-account keychain (now under the name `keychain`).
- All older aliases (`dedicated`, `isolated`, `system`, `shared`) → coerced to `keychain` with a one-time warning.

Re-run `altergo --config <account>` to write the new canonical value and silence the warning.

### CLI

```bash
altergo --config <account> --keychain keychain   # per-account keychain
altergo --config <account> --keychain none       # flat files only
```

Old `--keychain private` is rejected at the CLI. Update any scripts or aliases.

### SSH bridge

If you SSH into your Mac with `keychain`-mode accounts:

```bash
altergo --setup-token <account>
```

Open the printed URL on any device, approve, paste the token back. Future launches over SSH skip the keychain entirely.

---

## v1.0.0 — keychain alias removal

**Breaking.** `--keychain` no longer accepts `dedicated`, `isolated`, `system`, or `shared`. The CLI accepts only the canonical names (which later became `keychain` / `none` in v1.2.0).

Accounts whose `account.json` still contains a legacy value load with a one-time stderr warning. Run `altergo --config <account>` to normalize.

Also in v1.0.0: a Cancel-vs-Reset-To-Defaults warning is shown whenever you activate `none` mode (interactively or via `--keychain none`). Cancel is always safe. Never click "Reset To Defaults" — that destroys your real login keychain.

---

## v0.40.0 — multi-provider accounts

One account can now host multiple providers. `account.json` bumped from v2 to v3:

```json
{
  "version": 3,
  "providers": ["claude", "codex"],
  "default_provider": "claude",
  "created": "2026-04-20T18:32:11"
}
```

**No user action required.** v2 files (`{"version": 2, "provider": "claude"}`) load forever via `_coerce_meta_v3`. The file on disk only flips to v3 when you mutate the account:

```bash
altergo <account> --add-provider codex
altergo <account> --remove-provider codex
altergo <account> --default-provider gemini
```

Also new in v0.40.0:

- `altergo --recall` and `--search` aggregate sessions across all four providers in one picker. Press `f` to filter by provider.
- Resumed sessions launch in the session's saved cwd. If the directory no longer exists, altergo prints a dim notice and falls back to your current cwd.
- Picker keybindings changed: `b` bookmarks the highlighted row, `*` toggles a starred-only filter. In v0.39.x, `*` bookmarked.

---

## Archived notes

Older migrations are summarized in [CHANGELOG.md](../CHANGELOG.md). If you're upgrading across a much older version and run into trouble, [open an issue](https://github.com/thepixelabs/altergo/issues) and we'll help.

Highlights:

- **v0.46.0** — removed `--keychain dedicated`/`isolated`/`system`/`shared` aliases (rejected at the CLI; accounts with legacy values on disk are coerced with a warning).
- **v0.45.0** — keychain modes renamed `dedicated → private`, `isolated → none`; default flipped to `private` (later `keychain` in v1.2.0).
- **v0.44.0** — keychain default flipped to `isolated` (blocking); `isolated` → `dedicated` rename for the opt-in per-account keychain.
- **v0.41.0** — opt-in per-account macOS keychain introduced; see [keychain-isolation.md](keychain-isolation.md).
- **v0.34.0** — `altergo --config --name <n>` → `altergo --config <account>` (positional). Old syntax removed.
- **v0.22.0** — `.claude.json` switched from symlinked to real-file-with-bidirectional-`mcpServers`-merge. Pre-existing symlinks are silently replaced on first launch; no user action required.
- **v0.5.0** — N-account layout introduced (`~/.altergo/accounts/<name>/`). Auto-migration from the v0.4.x single-account layout existed through v0.35.2 and was removed in v0.35.3. If you're still on a pre-v0.5.0 layout: pin to v0.35.2 (`pip install altergo==0.35.2`), run `altergo` once to trigger the auto-migration, then upgrade.
