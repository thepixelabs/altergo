# SSH access and the OAuth token bridge

**Audience:** users who SSH into their Mac and need `keychain`-mode accounts to authenticate without a GUI prompt.

---

## Why SSH and the macOS keychain don't get along

macOS Keychain items with restrictive access classes require the device to be unlocked through a GUI session. Reading them from a process not launched by the GUI session triggers a consent dialog that hangs until someone clicks Allow at the physical machine. Over SSH there's no GUI to surface that dialog, and the read fails.

altergo's `keychain` mode stores each per-account keychain's unlock password as a generic-password entry in your real login keychain, with `/usr/bin/security` on the ACL via `-T`. At launch, `security` reads that password and unlocks the per-account keychain. The first time may show a one-time "Always Allow" dialog at the desktop — click it once and you never see it again, including from SSH.

For SSH where even that one-time click never happens (headless servers, automation), altergo offers an **OAuth token bridge** that bypasses the keychain entirely.

---

## How the bridge works

Claude Code accepts `CLAUDE_CODE_OAUTH_TOKEN` as a fully valid OAuth credential, skipping the keychain. altergo stores a long-lived token per account at:

```
~/.altergo/accounts/<account>/.claude/.oauth-token
```

At every launch, `_build_alt_env` reads that file and sets `CLAUDE_CODE_OAUTH_TOKEN` in the subprocess environment before handing off to the provider binary. The keychain path is never taken.

The token file is per-account. A globally exported `CLAUDE_CODE_OAUTH_TOKEN` in your `.zshrc` cannot leak between accounts: altergo always sets the variable from the per-account file (overriding the shell value) or strips it entirely for accounts with no token.

---

## Setup

### During `altergo --config`

After picking `keychain` mode, altergo offers to generate a token:

```
  OAuth token (SSH bridge)
  Generating one now lets claude auth over SSH without
  hitting the keychain. You can run this any time later
  with: altergo --setup-token <account>
  Generate an OAuth token now? [Y/n]
```

Press Enter to proceed. altergo runs `claude setup-token` as a child process, which prints an authorization URL. Open it in any browser (your phone works), approve, paste the token back when prompted:

```
  Paste the token below (starts with sk-ant-oat01-…):
  token: sk-ant-oat01-…

  ✓ token saved   /Users/you/.altergo/accounts/work/.claude/.oauth-token
```

### Any time later

```bash
altergo --setup-token <account>
```

Same flow. Use this after skipping the offer, after revoking a token, or to rotate.

For the `native` account, the token is written to `~/.claude/.oauth-token` (your real home).

---

## Per-account isolation

Each account has its own token file. `work` and `personal` keep separate Claude identities:

```
~/.altergo/accounts/work/.claude/.oauth-token       ← work identity
~/.altergo/accounts/personal/.claude/.oauth-token   ← personal identity
```

`altergo work` sets the work token; `altergo personal` sets the personal token; neither leaks into the other or into `altergo native`. Accounts with no token file get `CLAUDE_CODE_OAUTH_TOKEN` stripped from the environment, so a globally-exported value can never accidentally authenticate as the wrong account.

---

## Other providers

Gemini, Codex, and Copilot don't need the bridge — their credentials live in flat files inside the per-account dot-dir, readable from any shell session including SSH. The OAuth token bridge is Claude-only.

| Provider | Credential file | Path |
|---|---|---|
| Gemini CLI | `oauth_creds.json` | `<account_home>/.gemini/oauth_creds.json` |
| Codex CLI | `auth.json` | `<account_home>/.codex/auth.json` |
| GitHub Copilot | `config.json` | `<account_home>/.copilot/config.json` |

---

## Rotate, revoke

Delete the file and re-run setup:

```bash
rm ~/.altergo/accounts/work/.claude/.oauth-token
altergo --setup-token work
```

To revoke: do it at [console.anthropic.com](https://console.anthropic.com), then delete the local file and generate a new one. altergo doesn't auto-detect revocation — if `claude` starts returning auth errors after revoking, the local file is stale.

---

## Security

- File mode: `0600` (owner read/write only). Account home is user-owned.
- Token scope: same as a regular Claude Code login.
- Stored plaintext, not encrypted at rest beyond filesystem permissions — same posture as SSH keys and browser cookies in your home directory.

---

## Troubleshooting

**Token paste rejected.** Token must start with `sk-ant-oat01-`. Common causes: copied only part of the token; non-monospace context introduced invisible characters; word-wrapped display. Paste into a plain text editor first to verify, then re-run `--setup-token`.

**`claude` binary not on PATH.** `--setup-token` needs `claude` visible in the current session. Common locations that may not be on the SSH PATH:

```
~/.local/bin/claude
~/.npm-global/bin/claude
/opt/homebrew/bin/claude
/usr/local/bin/claude
```

**Account not found.** Run `altergo --config <account>` first.

**Token ignored at launch.** If you set `CLAUDE_CODE_OAUTH_TOKEN` globally, altergo overrides it with the per-account file (or strips it). Confirm:

```bash
cat ~/.altergo/accounts/work/.claude/.oauth-token
```
