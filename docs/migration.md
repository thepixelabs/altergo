# Migration guide

This page covers syntax changes and one-time migrations that apply when you upgrade altergo. Live, supported paths are at the top; archived notes for old releases are at the bottom.

---

## v0.41.0 — opt-in keychain isolation (macOS)

**Applies to:** macOS users upgrading to v0.41.0+.

The default is `shared` — no behavior change on upgrade. Existing accounts continue to work exactly as before.

To opt in for an account:

```bash
altergo --config <account> --keychain isolated
```

To revert:

```bash
altergo --config <account> --keychain shared
```

Reverting triggers automatic cleanup — altergo deletes the per-account `login.keychain-db` and the `com.altergo.account-unlock` entry from your login keychain. No manual steps required.

See [docs/keychain-isolation.md](keychain-isolation.md) for the full guide.

---

## v0.40.0 — multi-provider accounts, `--recall` across all providers, cwd-on-recall, `b`/`*` rebind

**Applies to:** Anyone upgrading to v0.40.0+.

### `account.json` v2 → v3 schema

No user action is required. v2 `account.json` files (`{"version": 2, "provider": "claude"}`) load forever without being rewritten. The file on disk flips to v3 only when you mutate the account via one of the new provider-management commands:

```bash
altergo <account> --add-provider codex
altergo <account> --remove-provider codex
altergo <account> --default-provider gemini
```

A v2 account that you never mutate will remain on disk as a v2 file indefinitely — all v0.40.0+ code reads it correctly.

The intended path to go from a single-provider account to multi-provider is `--add-provider`, which also handles any orphan-data reconciliation.

### `--recall` now aggregates all four providers

`altergo --recall` and `altergo --search` now scan Claude Code, Codex CLI, Gemini CLI, and GitHub Copilot sessions in one picker. No configuration required — providers that are not installed on your machine are silently skipped.

Use `f` in the picker to cycle the provider filter and narrow to a specific provider.

### cwd-on-recall

Resumed sessions now launch with the provider CLI's working directory set to the session's saved cwd. Pick a session from any directory and the provider reopens inside the project tree it was running in. If the original directory no longer exists, altergo prints a dim notice and falls back to your current directory.

### Picker keybinding changes: `b` and `*`

| Key | v0.39.x | v0.40.0+ |
|---|---|---|
| `b` | (unbound) | Bookmark (toggle star) on the highlighted row |
| `*` | Toggle star on highlighted row | Toggle starred-only filter |

If you have muscle memory for pressing `*` to bookmark a session, use `b` instead. The `*` key now shows only starred sessions (a filter), which is the more common use case after building up a bookmark collection.

---

## v0.34.0 — CLI syntax change: positional `--config <account>`

**Applies to:** Anyone upgrading across v0.34.0.

The old `altergo --config --name <n>` form is gone. Use the positional form:

```bash
# Old (pre-v0.34.0) — no longer accepted
altergo --config --name personal

# New (v0.34.0+)
altergo --config personal
```

Also introduced: `altergo --rename <old> <new>` for renaming an existing account without losing credentials or history. Update any aliases, scripts, or CI jobs that still pass `--name`.

---

## v0.22.0 — `.claude.json` silent unsymlink

**Applies to:** Anyone who had `~/.altergo/accounts/<account>/.claude/.claude.json` as a symlink before v0.22.0 (created by older altergo versions that treated it as shared).

`~/.claude.json` holds both `mcpServers` and `oauthAccount`. Symlinking it across accounts leaks OAuth identity, which is a real security problem. In v0.22.0 altergo switched to a **bidirectional merge** for `mcpServers` only — see [how-it-works.md](how-it-works.md#mcp-servers-sync-not-symlink) for the mechanics.

On the first Claude launch after upgrading, altergo atomically replaces any pre-existing `.claude.json` symlink with a real file that preserves the linked content. **No user action is required** — the change is silent and reversible via teardown. If you want to confirm:

```bash
# Should report "regular file", not "symbolic link"
stat -f '%HT' ~/.altergo/accounts/<account>/.claude/.claude.json   # macOS
stat -c '%F'  ~/.altergo/accounts/<account>/.claude/.claude.json   # Linux
```

## v0.22.0 — removal of multi-provider bundling

Also in v0.22.0: the old syntax for bundling providers per account was removed.

```bash
# Old (pre-v0.22.0) — no longer accepted
altergo pro use gemini
altergo --config --name pro --provider claude,gemini

# New (v0.22.0+)
altergo --config pro            # pick the provider interactively
```

Running `altergo <account> use <provider>` today prints a clear error pointing you to `altergo --config`. There is no silent fallback.

---

## Migration guide: claude100-resume to altergo

**Applies to:** Anyone who used `claude100-resume` or manually configured `~/claude100-home/` as an alt account home.

If you are coming from a bare shell alias (not `claude100-resume`) — for example `alias claude2='HOME=~/claude2-home claude'` — the same steps apply: copy `.credentials.json` to `~/.altergo/accounts/default/.claude/`, run `altergo --config`, and remove the alias.

---

### What changed

| | Before | After |
|-|--------|-------|
| Tool name | `claude100-resume` | `altergo` |
| Alt home directory | `~/claude100-home/` | `~/.altergo/accounts/default/` |
| Shell alias | `alias claude100='HOME=$HOME/claude100-home claude'` in `~/.zshrc` | No alias needed — `altergo` handles it |

The new altergo does not auto-detect `~/claude100-home/`. If you skip migration, `altergo --config` creates a fresh `~/.altergo/accounts/default/` with no credentials, and you will be prompted to log in again with your alt account.

---

### Migration steps

#### 1. Copy your alt credentials to the new location

```bash
mkdir -p ~/.altergo/accounts/default/.claude
cp ~/claude100-home/.claude/.credentials.json ~/.altergo/accounts/default/.claude/.credentials.json
```

If you also had a `settings.json` or other config files unique to the alt account (not symlinks), copy those too:

```bash
# Check what is real vs. a symlink before copying
ls -la ~/claude100-home/.claude/
```

Only copy files that are regular files, not symlinks. The symlinks will be recreated by `altergo --config`.

#### 2. Run the new config

```bash
altergo --config
```

This creates the symlink structure inside `~/.altergo/accounts/default/.claude/` so all accounts share session history.

#### 3. Remove the old alias from `~/.zshrc`

Open `~/.zshrc` and delete the line:

```
alias claude100='HOME=$HOME/claude100-home claude'
```

Then reload your shell:

```bash
source ~/.zshrc
```

#### 4. Verify the migration works

```bash
altergo --version   # should print the installed version
altergo --recall    # should show your sessions in the interactive picker
altergo             # should launch Claude Code with alt credentials
```

#### 5. Remove the old home directory (optional)

Once you have confirmed `altergo` works correctly, you can delete the old directory:

```bash
rm -rf ~/claude100-home
```

Do not delete it until you are sure you have copied everything you need. The only file that cannot be recovered without logging in again is `.credentials.json`.

### Checking for unmanaged directories

If you had been using the old alt home for a while, Claude Code may have written directories that altergo does not manage. Check for them before removing the old directory:

```bash
ls ~/claude100-home/.claude/
```

Two directories in particular — `paste-cache/` and `plugins/` — are written by Claude Code but are not in altergo's symlink list. `paste-cache/` is ephemeral and safe to ignore. If `plugins/` exists and you use Claude Code plugins, you may want to manually symlink it after running `altergo --config`:

```bash
# Only do this if plugins/ exists in your primary ~/.claude/ and you want it shared
ln -s ~/.claude/plugins ~/.altergo/accounts/default/.claude/plugins
```

See [architecture.md](architecture.md#unmanaged-written-by-the-provider-cli-not-tracked-by-altergo) for the full explanation of unmanaged state.

---

### Git author identity

When `claude100-resume` launched Claude Code it set `HOME=~/claude100-home`. This also changed what git uses for author name and email (git reads `~/.gitconfig` from `HOME`). If `~/claude100-home/.gitconfig` did not exist or was not configured, git may have fallen back to the system hostname as the author name for commits made during those sessions.

Check recent commits in any affected repo:

```bash
git log --format="%an <%ae>" | head -20
```

If you see unexpected names or email addresses, correct the identity going forward. For a single repo:

```bash
git config user.name "Your Name"
git config user.email "you@example.com"
```

To set it globally (applies to all repos where no local config overrides it):

```bash
git config --global user.name "Your Name"
git config --global user.email "you@example.com"
```

You cannot rewrite already-pushed commits without a force-push and coordination with collaborators. For commits that exist only locally, `git rebase` with `--exec 'git commit --amend --reset-author --no-edit'` can fix them before you push.

---

### Troubleshooting

**`altergo --recall` shows no sessions after migration**

The symlinks inside `~/.altergo/accounts/default/.claude/` may not have been created yet. Run `altergo --config` and check the output for errors.

**`altergo` asks me to log in**

The credentials file was not copied or is not being read. Verify the file exists and is valid JSON:

```bash
cat ~/.altergo/accounts/default/.claude/.credentials.json
```

If the file is missing, repeat step 1. If it is present but login still fails, the credentials may have expired — log in interactively and the file will be refreshed.

**Old `claude100` alias still runs**

You still have the alias active in the current shell session. Either open a new terminal or run `source ~/.zshrc` after removing the alias from the file.

---

### Further reading

- [how-it-works.md](how-it-works.md) — Full technical explanation of the selective HOME override and symlink architecture
- [architecture.md](architecture.md) — Directory layout reference and symlink table

---

## Archived migration notes: v0.4.x → v0.5.0

> **These steps applied to altergo releases v0.5.0 through v0.35.2.** The `detect_legacy` / `migrate_legacy` auto-migration code was **removed in v0.35.3** — altergo no longer detects or rewrites the old layout automatically. If you are upgrading directly from pre-v0.5.0 today, run through the manual steps below, or [file an issue](https://github.com/thepixelabs/altergo/issues) and we will help.

v0.5.0 introduced N-account support. The directory layout changed:

| | v0.4.x | v0.5.0+ |
|-|--------|--------|
| Alt account home | `~/.altergo/` | `~/.altergo/accounts/default/` |
| Alt `.claude/` dir | `~/.altergo/.claude/` | `~/.altergo/accounts/default/.claude/` |
| Settings file | `~/.altergo/.altergo.json` (inside alt home) | `~/.altergo/.altergo.json` (above `accounts/`, global) |

### Manual migration steps (from pre-v0.5.0 today)

1. Move the old alt home into the new `accounts/default/` slot:

    ```bash
    mkdir -p ~/.altergo/accounts
    mv ~/.altergo/.claude ~/.altergo/accounts/default/.claude
    # If you had other dotfiles under ~/.altergo/ (e.g. .aws, .config), move them too:
    # mv ~/.altergo/.aws ~/.altergo/accounts/default/.aws
    ```

2. Reinitialize the symlink structure:

    ```bash
    altergo --config default
    ```

3. Verify:

    ```bash
    altergo --recall    # should show your sessions in the interactive picker
    altergo             # should launch Claude Code with your existing credentials
    ```

### What the old auto-migration did (historical reference)

For the record, the auto-migration in v0.5.0–v0.35.2 performed roughly:

1. Renamed `~/.altergo/` to a temporary path (`/tmp/altergo-migrate-<pid>/`).
2. Created the new `~/.altergo/accounts/` directory.
3. Moved the temporary directory to `~/.altergo/accounts/default/`.
4. Copied the migrated content to `~/.altergo/.legacy-backup/` as a backup.
5. Wrote `~/.altergo/accounts/default/MIGRATED.txt` as an audit trail.
6. Printed a 4-line migration notice to stdout.

If you are on v0.35.2 or older today and want altergo to handle this for you, upgrade to that version first (`pip install "altergo==0.35.2"`), run `altergo` once to trigger the migration, then upgrade to the latest release.
