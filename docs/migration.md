# Migration guide: claude100-resume to altergo

**Applies to:** Anyone who used `claude100-resume` or manually configured `~/claude100-home/` as an alt account home.

If you are coming from a bare shell alias (not `claude100-resume`) — for example `alias claude2='HOME=~/claude2-home claude'` — the same steps apply: copy `.credentials.json` to `~/.altergo/.claude/`, run `altergo --setup`, and remove the alias.

---

## What changed

| | Before | After |
|-|--------|-------|
| Tool name | `claude100-resume` | `altergo` |
| Alt home directory | `~/claude100-home/` | `~/.altergo/` |
| Shell alias | `alias claude100='HOME=$HOME/claude100-home claude'` in `~/.zshrc` | No alias needed — `altergo` handles it |

The new setup does not auto-detect `~/claude100-home/`. If you skip migration, `altergo --setup` creates a fresh `~/.altergo/` with no credentials, and you will be prompted to log in again with your alt account.

---

## Migration steps

### 1. Copy your alt credentials to the new location

```bash
mkdir -p ~/.altergo/.claude
cp ~/claude100-home/.claude/.credentials.json ~/.altergo/.claude/.credentials.json
```

If you also had a `settings.json` or other config files unique to the alt account (not symlinks), copy those too:

```bash
# Check what is real vs. a symlink before copying
ls -la ~/claude100-home/.claude/
```

Only copy files that are regular files, not symlinks. The symlinks will be recreated by `altergo --setup`.

### 2. Run the new setup

```bash
altergo --setup
```

This creates the symlink structure inside `~/.altergo/.claude/` so both accounts share session history.

### 3. Remove the old alias from `~/.zshrc`

Open `~/.zshrc` and delete the line:

```
alias claude100='HOME=$HOME/claude100-home claude'
```

Then reload your shell:

```bash
source ~/.zshrc
```

### 4. Verify the migration works

```bash
altergo --version   # should print the installed version
altergo --list      # should show your sessions
altergo             # should launch Claude Code with alt credentials
```

### 5. Remove the old home directory (optional)

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

Two directories in particular — `paste-cache/` and `plugins/` — are written by Claude Code but are not in altergo's symlink list. `paste-cache/` is ephemeral and safe to ignore. If `plugins/` exists and you use Claude Code plugins, you may want to manually symlink it after setup:

```bash
# Only do this if plugins/ exists in your primary ~/.claude/ and you want it shared
ln -s ~/.claude/plugins ~/.altergo/.claude/plugins
```

See [architecture.md](architecture.md#unmanaged-not-tracked-by-altergo) for the full explanation of unmanaged state.

---

## Git author identity

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

## Troubleshooting

**`altergo --list` shows no sessions after migration**

The symlinks inside `~/.altergo/.claude/` may not have been created yet. Run `altergo --setup` and check the output for errors.

**`altergo` asks me to log in**

The credentials file was not copied or is not being read. Verify the file exists and is valid JSON:

```bash
cat ~/.altergo/.claude/.credentials.json
```

If the file is missing, repeat step 1. If it is present but login still fails, the credentials may have expired — log in interactively and the file will be refreshed.

**Old `claude100` alias still runs**

You still have the alias active in the current shell session. Either open a new terminal or run `source ~/.zshrc` after removing the alias from the file.

---

## Further reading

- [how-it-works.md](how-it-works.md) — Full technical explanation of the selective HOME override and symlink architecture
- [architecture.md](architecture.md) — Directory layout reference and symlink table
