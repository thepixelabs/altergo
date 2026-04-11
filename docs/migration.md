# Migration guide

---

## Upgrading from altergo v0.4.x to v0.5.0

**Applies to:** Anyone upgrading an existing altergo v0.4.x installation.

v0.5.0 introduced N-account support. The directory layout changed:

| | v0.4.x | v0.5.0 |
|-|--------|--------|
| Alt account home | `~/.altergo/` | `~/.altergo/accounts/default/` |
| Alt `.claude/` dir | `~/.altergo/.claude/` | `~/.altergo/accounts/default/.claude/` |
| Settings file | `~/.altergo/.altergo.json` (inside alt home) | `~/.altergo/.altergo.json` (above `accounts/`, global) |

### Auto-migration: no action required for most users

On the first run after upgrading, altergo detects the old layout and migrates it automatically. You do not need to do anything. The migration runs before any command is processed and prints the following 4-line block:

```
altergo: layout migrated for v0.5.0 N-account support
  ~/.altergo/  →  ~/.altergo/accounts/default/
  Backup preserved at ~/.altergo/.legacy-backup/
  See https://altergo.pixelabs.net/docs/migration-0.5 for details
```

After that block, altergo continues normally. All your existing sessions, credentials, and symlinks are preserved under the new path. A `MIGRATED.txt` file is also written to `~/.altergo/accounts/default/MIGRATED.txt` as a permanent audit trail — it records the altergo version, timestamp, old and new paths, and rollback instructions.

### What the migration does

1. Renames `~/.altergo/` to a temporary path (`/tmp/altergo-migrate-<pid>/`)
2. Creates the new `~/.altergo/accounts/` directory
3. Moves the temporary directory to `~/.altergo/accounts/default/`
4. Copies the migrated content to `~/.altergo/.legacy-backup/` as a backup
5. Writes `~/.altergo/accounts/default/MIGRATED.txt` as an audit trail
6. Prints the 4-line migration block to stdout

The use of `/tmp/` as a staging area means the rename is atomic. If the process is interrupted between steps 1 and 3, your data sits safely in `/tmp/` under a PID-qualified name — nothing is lost.

### Note about settings

The settings file (`~/.altergo/.altergo.json`) was located inside `~/.altergo/` in v0.4.x. After migration, `~/.altergo/` becomes `~/.altergo/accounts/default/`, so the old settings file is now at `~/.altergo/accounts/default/.altergo.json`. The new settings file location is `~/.altergo/.altergo.json` (above `accounts/`).

This means your credential-sharing preferences reset to defaults after migration. The new location is intentional — settings are now global across all accounts rather than per-account.

To reconfigure, run:

```bash
altergo --settings
```

### Verifying migration worked

```bash
# Should show your account directory at the new path
ls ~/.altergo/accounts/default/.claude/

# Should show your sessions (session files are shared, so nothing changed here)
altergo --list

# Should launch with your existing credentials
altergo
```

If `altergo` asks you to log in, check that the credentials file survived the migration:

```bash
cat ~/.altergo/accounts/default/.claude/.credentials.json
```

If the file is present and valid, the credentials are intact — the login prompt may be a transient auth expiry rather than a migration issue.

### Rollback procedure

The backup at `~/.altergo/.legacy-backup/` is a complete copy of the pre-migration state. To restore:

```bash
# 1. Remove the migrated account directory
rm -rf ~/.altergo/accounts/

# 2. Copy the backup back to the original location
cp -R ~/.altergo/.legacy-backup ~/.altergo-restore
mv ~/.altergo-restore ~/.altergo

# 3. Downgrade altergo to v0.4.x
pip install "altergo==0.4.*"
```

The backup is preserved through the entire v0.5.x series. It will be removed in v0.6.0.

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
altergo --list      # should show your sessions
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

See [architecture.md](architecture.md#unmanaged-not-tracked-by-altergo) for the full explanation of unmanaged state.

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

**`altergo --list` shows no sessions after migration**

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
