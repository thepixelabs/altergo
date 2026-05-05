# SSH access and the OAuth token bridge

**Applies to:** altergo v1.1.0+  
**Audience:** Users who SSH into their Mac and need `altergo` accounts that use `keychain` to work without a GUI prompt.

---

## Why SSH and the macOS keychain don't get along

macOS Keychain items created with restrictive access classes (such as `kSecAttrAccessibleWhenUnlockedThisDeviceOnly`) require the device to be unlocked through a GUI session. Reading them from a process that wasn't launched by the GUI session triggers a user-consent prompt that hangs until someone clicks Allow at the physical machine — or times out and fails. Over SSH there is no GUI session to surface that prompt, and the read fails. Claude Code's exact access-class choice is an implementation detail that may change between releases, but the practical effect is consistent: `keychain` mode accounts can't read their stored credentials over SSH. Apple's developer documentation covers the access class semantics at [developer.apple.com/documentation/security/keychain_services](https://developer.apple.com/documentation/security/keychain_services).

## How the two modes differ

`keychain` (the default since v0.45.0) gives each altergo account its own `login.keychain-db`. altergo stores the keychain's unlock password as an entry in your **main** login keychain (with the `apple-tool:` partition list pinned), so at launch `/usr/bin/security` can read that password without a GUI dialog and unlock the per-account keychain silently. **No popups during normal desktop use.** Over SSH, the silent unlock still works in most cases, but a subsequent Keychain read by the provider CLI (e.g., claude re-checking its token) may still trigger a GUI consent dialog because the provider's own Keychain entry isn't pinned to `apple-tool:`. That's the case the OAuth token bridge solves.

`keychain: none` accounts work differently: altergo creates the per-account keychain but deliberately leaves it **locked forever** — no unlock password is stored anywhere. The keychain file exists only to route Security framework credential writes into a dead end, forcing providers to fall back to flat-file storage inside the per-account `HOME`. **macOS may pop an "Allow access" dialog the first time a provider tries to write credentials**, asking for a keychain password the user doesn't have. The correct response is **always Cancel** — never `Reset To Defaults`, which destroys your real login keychain. After Cancel, the provider falls back to writing flat files (mode 0600) and the session continues normally. SSH works the same as the desk because no keychain unlock is ever attempted; the flat files are readable from any user session.

## What the OAuth token bridge does

The bridge bypasses the Keychain entirely for auth. Claude Code supports an environment variable, `CLAUDE_CODE_OAUTH_TOKEN`, which it treats as a fully valid OAuth credential if present, skipping any Keychain lookup. altergo stores a long-lived token in a file at:

```
~/.altergo/accounts/<account>/.claude/.oauth-token
```

At every launch, `_build_alt_env` reads that file and sets `CLAUDE_CODE_OAUTH_TOKEN` in the subprocess environment before handing off to the provider binary. The Keychain path is never taken, so the SSH GUI-prompt problem does not arise.

The token file is per-account and never touches the process environment permanently. A global `CLAUDE_CODE_OAUTH_TOKEN` in your `.zshrc` cannot leak between accounts: altergo explicitly sets the variable from the per-account file (overriding whatever the shell inherited) or strips it entirely for non-native accounts that have no token file.

---

## Setup

### Automatic: during `altergo --config`

`altergo --config <account>` is the single entry point for picking keychain mode. The prompt explains both modes and their SSH implications upfront, so you make one informed choice and altergo handles the rest. Re-running `--config` on an existing account always re-prompts (with the current mode as the default), so you can switch modes any time.

```
  Keychain mode (macOS)
  ─────────────────────
  How this account stores credentials:

    keychain  per-account macOS keychain. Tokens encrypted at rest.
             altergo stores the unlock password in your main login
             keychain and handles unlock silently — no popups at the
             desk during normal use. Over SSH the keychain can't be
             unlocked silently in all cases, so altergo will offer
             to set up an OAuth token bridge after this prompt.

    none     flat files in the account home (mode 0600). The
             per-account keychain is intentionally locked, so when
             a provider tries to write to it macOS will pop an
             'Allow access' dialog asking for a keychain password.
             Always click Cancel — never 'Reset To Defaults'.
             Providers fall back to flat files and your session
             continues. Works over SSH and on the desk identically.

  Details: https://github.com/thepixelabs/altergo/blob/main/docs/ssh-auth.md

  Current: keychain.  Use keychain mode? [Y/n]
```

For an account that's currently `none`, the prompt inverts to `Switch to keychain mode? [y/N]` so the highlighted default matches your existing choice. Either way, pressing Enter keeps the current mode.

If you pick `keychain`, altergo immediately follows up with a short OAuth-bridge offer (no second long explanation — the keychain prompt covered the why):

```
  OAuth token (SSH bridge)
  Generating one now lets claude auth over SSH without
  hitting the keychain. You can run this any time later
  with: altergo --setup-token <account>
  Generate an OAuth token now? [Y/n]
```

Press Enter (or `Y`) to proceed. The flow then:

1. Runs `claude setup-token` as a child process. Claude prints an authorization URL.
2. Open the URL in a browser (your phone works if you are already over SSH), authorize, and the token is printed back to the terminal.
3. altergo prompts you to paste the token:

```
  Generating an SSH-friendly OAuth token

  A browser window will open for confirmation. After the token
  prints to the terminal, copy it and paste it when prompted below.

  Paste the token below (starts with sk-ant-oat01-…):
  token: sk-ant-oat01-…
```

4. altergo validates the prefix and writes the file:

```
  ✓ token saved   /Users/you/.altergo/accounts/work/.claude/.oauth-token
  Subsequent altergo launches for this account will use this token
  even when the macOS keychain is unavailable (e.g. over SSH).
```

If you answer `n` at the prompt, no token is written. The reminder tells you how to set one up later:

```
  Skipped. Run altergo --setup-token work any time to enable it later.
```

### Explicit: `altergo --setup-token <account>`

Run this at any time — after skipping the offer during `--config`, after revoking a token, or to rotate a token:

```bash
altergo --setup-token work
```

The account must already exist (run `altergo --config work` first if it does not). The flow is identical to the automatic path: launches `claude setup-token`, prompts for a paste, validates, writes the file.

For the native account:

```bash
altergo --setup-token native
```

This writes to `~/.claude/.oauth-token` (your real home directory, not an altergo account directory).

#### Full example

```
$ altergo --setup-token work

  Generating an SSH-friendly OAuth token

  A browser window will open for confirmation. After the token
  prints to the terminal, copy it and paste it when prompted below.

[claude setup-token runs here — follow its browser instructions]

  Paste the token below (starts with sk-ant-oat01-…):
  token: sk-ant-oat01-XXXXXXXX…

  ✓ token saved   /Users/you/.altergo/accounts/work/.claude/.oauth-token
  Subsequent altergo launches for this account will use this token
  even when the macOS keychain is unavailable (e.g. over SSH).

$ altergo work --yolo
# works, even over SSH, even with keychain mode enabled
```

---

## Per-account isolation

Each account has its own token file. A user with a `work` account and a `personal` account can have separate Claude identities, each with its own token:

```
~/.altergo/accounts/work/.claude/.oauth-token       ← work identity
~/.altergo/accounts/personal/.claude/.oauth-token   ← personal identity
```

When you run `altergo work`, the `work` token is set in the environment for that process only. When you run `altergo personal`, the `personal` token is set. Neither leaks into the other session, and neither leaks into a subsequent `altergo native` run (which uses the real `$HOME` path instead).

If an account has no token file, `CLAUDE_CODE_OAUTH_TOKEN` is stripped from the subprocess environment, so a token you may have set globally in your shell's rc file cannot accidentally authenticate as the wrong account.

---

## Why the previous approach was a bad idea

Before the per-account model, the `rover --setup-native-ssh` command wrote a single token to `~/.claude/rover-native-token` and advised users to export `CLAUDE_CODE_OAUTH_TOKEN` from `.zshrc`. That global export meant every altergo account, regardless of which identity it was supposed to represent, silently inherited the same token. Whichever account's token you'd last exported won. This cross-account leakage undermined the entire purpose of credential isolation.

The per-account file model fixes this: the environment variable is always set from the correct file (or stripped), never from the shell's ambient state.

---

## What about other providers?

Gemini, Codex, and GitHub Copilot do not need the token bridge.

Their credentials live in flat files inside the per-account dot-directory:

| Provider | Credential file | Path |
|---|---|---|
| Gemini CLI | `oauth_creds.json` | `<account_home>/.gemini/oauth_creds.json` |
| Codex CLI | `auth.json` | `<account_home>/.codex/auth.json` |
| GitHub Copilot | `config.json` | `<account_home>/.copilot/config.json` |

These files are owned by your macOS user and readable from any shell session, including SSH. No Keychain interaction is required. The OAuth token bridge is Claude-only.

---

## Token rotation and revocation

### Rotate

Delete the existing token file and re-run setup:

```bash
rm ~/.altergo/accounts/work/.claude/.oauth-token
altergo --setup-token work
```

### Revoke

If a token is compromised, revoke it at [console.anthropic.com](https://console.anthropic.com). After revoking, delete the local file and generate a new one:

```bash
rm ~/.altergo/accounts/work/.claude/.oauth-token
altergo --setup-token work
```

altergo does not detect a revoked token automatically. If `claude` starts returning authentication errors after a revocation, the token file is stale — delete it and re-run `--setup-token`.

### Multiple accounts

Each account's token file is independent. You can rotate one without affecting the others.

---

## Security

**File permissions.** The token file is written with mode `0600` (owner read/write only). The account home itself is `~/.altergo/accounts/<account>/`, which is a user-owned directory. No other macOS user can read the token.

**Token scope.** The token has the same scope as a regular Claude Code login. It grants access to claude.ai sessions under that Claude account. It does not grant any elevated privileges.

**Revocation.** Revoke at [console.anthropic.com](https://console.anthropic.com) if the token is exposed. Delete the local file after revoking.

**What altergo does not do.** The file is stored in plaintext. It is not encrypted at rest beyond the filesystem permissions. If your macOS user account is compromised, the token is exposed — but so is everything else under your home directory, including your SSH keys and browser cookies. The token is not more sensitive than those.

---

## Troubleshooting

### Token paste rejected

```
  That doesn't look like a Claude OAuth token.
  Expected prefix: sk-ant-oat01-…
  Nothing was written. Re-run when you have the right value.
```

The token must start with `sk-ant-oat01-`. Common causes:

- You copied only part of the token — copy the entire line `claude setup-token` printed.
- You copied from a non-monospace context and invisible characters were introduced — paste into a plain text editor first to verify the value.
- The token display was word-wrapped — verify it is a single unbroken string.

Re-run `altergo --setup-token <account>` when you have the correct value.

### `claude` binary not on PATH

```
  claude binary not found on PATH.
  Install Claude Code first: https://claude.com/code
```

`altergo --setup-token` needs the `claude` binary visible in your current session's PATH. If you installed Claude Code in a non-standard location, ensure that location is on PATH before running the command.

Common install locations that may not be on the SSH session's PATH:

```bash
~/.local/bin/claude        # Claude Code default
~/.npm-global/bin/claude   # npm global prefix
/opt/homebrew/bin/claude   # Homebrew on Apple Silicon
/usr/local/bin/claude      # Homebrew on Intel / manual
```

### File not written

If `--setup-token` exits without writing a file (e.g., a permissions error), you will see:

```
  failed to write token file: [Errno 13] Permission denied: …
```

Check that the account home directory is writable:

```bash
ls -ld ~/.altergo/accounts/work/
ls -ld ~/.altergo/accounts/work/.claude/
```

Both should be owned by your user and writable. If they are not, re-run `altergo --config work` to repair the directory structure.

### Account not found

```
altergo: account 'work' not found. Run 'altergo --config work' first.
```

The account directory does not exist. Run `altergo --config work` to create it, then run `altergo --setup-token work`.

### Token ignored at launch

If you have `CLAUDE_CODE_OAUTH_TOKEN` set in your `.zshrc` or `.bash_profile`, altergo overrides it with the per-account file value (or strips it if no file exists). The shell-level export is never inherited by an altergo account subprocess. This is intentional — see [Per-account isolation](#per-account-isolation).

To confirm which token a given account will use:

```bash
cat ~/.altergo/accounts/work/.claude/.oauth-token
```

### Legacy `rover-native-token` file

If you previously used `rover --setup-native-ssh`, it wrote a token to `~/.claude/rover-native-token`. altergo still reads that file as a fallback for the `native` account, so you do not need to migrate. The file is used automatically; no changes needed. New setups write to `~/.claude/.oauth-token` instead.
