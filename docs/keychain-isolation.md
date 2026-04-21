# Keychain isolation (macOS, opt-in)

**Applies to:** altergo v0.40.0+  
**Audience:** macOS users who want per-account credential separation at the keychain level.

For the short version, see the [Keychain isolation section in the README](../README.md#keychain-isolation-macos-opt-in). For the full threat model and security scope, see [SECURITY.md — Keychain isolation](../SECURITY.md#keychain-isolation-macos-opt-in).

---

## 1. What this solves

By default, altergo isolates AI-provider credentials by placing each account's credential files (`.credentials.json`, `oauth_creds.json`, etc.) in separate account home directories. On macOS, provider CLIs may also store tokens in the system keychain. When they do, all accounts on the same macOS user share a single keychain — so a token written by Claude Code under one account sits in the same keychain as tokens written under every other account.

Keychain isolation gives each altergo account its own `login.keychain-db`. When Claude Code (or any tool launched via altergo) stores a token, it lands in that account's private keychain. Other altergo accounts cannot see it directly.

This is a workflow convenience, not a hard security boundary. See the threat model section below.

---

## 2. Opt in / opt out

**Enable isolation for an account:**

```bash
altergo --config <name> --keychain isolated
```

Or run `altergo --config <name>` interactively — altergo will prompt whether to enable keychain isolation.

**Disable isolation and revert to shared:**

```bash
altergo --config <name> --keychain shared
```

When you flip an account from `isolated` back to `shared`, altergo deletes the per-account keychain file and the login-keychain unlock entry. The cleanup is complete — no orphan files remain.

**Default:** `shared` on upgrade and for all new accounts unless you explicitly pass `--keychain isolated`. Existing accounts are not changed.

**Rerunning `--config` without a `--keychain` flag** preserves the existing setting.

**`altergo native`** bypasses keychain isolation entirely and runs the provider under the real `$HOME`.

---

## 3. On-disk layout

When isolation is enabled for an account named `<name>`, altergo creates:

| Path | What it is |
|---|---|
| `~/.altergo/accounts/<name>/Library/Keychains/login.keychain-db` | The per-account keychain file. Created once; reused on every subsequent launch. |
| `~/.altergo/accounts/<name>/Library/Preferences/com.apple.security.plist` | Plist that tells the macOS Security framework to use the per-account keychain for processes with `HOME` set to this account. Uses the `~/Library/Keychains/login.keychain` tilde-form (`DLDBSearchList`). |
| Login keychain entry (your real user login keychain) | Generic-password entry: service `com.altergo.account-unlock`, account `<name>`. Stores the random unlock password for this account's keychain. |

The plist uses the `~/Library/Keychains/login.keychain` form (without `-db`) — this matches what macOS itself writes and is what the Security framework resolves. The on-disk keychain file name ends in `-db`; both forms work.

The `account.json` for an isolated account includes a `keychain` key:

```json
{
  "version": 3,
  "providers": ["claude"],
  "default_provider": "claude",
  "created": "2026-04-21T10:00:00",
  "keychain": "isolated"
}
```

The `keychain` key is absent when `shared` (the default).

---

## 4. Lifecycle

**Create** — `altergo --config <name> --keychain isolated` runs `_create_account_keychain`:

1. Generate a 64-character hex password via `secrets.token_bytes(32).hex()`.
2. Create the keychain file: `security create-keychain -p <password> <path>`.
3. Write `com.apple.security.plist` via `plistlib`.
4. Store the unlock password in your real login keychain: `security add-generic-password -s com.altergo.account-unlock -a <name> -w <password> -T /usr/bin/security`.

If the keychain file already exists (idempotent re-run), altergo reuses it and skips creation. If the file exists but the unlock entry is missing (orphan), altergo warns and aborts — it cannot recover the password. See the troubleshooting section.

**Activate** — every `altergo <name>` launch calls `_unlock_account_keychain` inside `_build_alt_env`:

1. Read the unlock password from the real login keychain (silent — login keychain is already unlocked, no prompt).
2. Unlock the per-account keychain with that password.

The keychain stays unlocked for the duration of the session, matching macOS's own login keychain behavior.

**Downgrade** — `altergo --config <name> --keychain shared`:

1. Delete the per-account keychain: `security delete-keychain <path>`.
2. Delete the login-keychain unlock entry: `security delete-generic-password -s com.altergo.account-unlock -a <name>`.
3. Remove `Library/Keychains/` and `Library/Preferences/` from the account home.
4. Rewrite `account.json` without the `keychain` key.

**Delete account** — `do_delete_account` runs the same keychain cleanup before removing the account home directory.

---

## 5. Threat model and non-goals

altergo supports opt-in per-account keychain isolation on macOS. When enabled for an account, altergo creates a dedicated `login.keychain-db` for that account under the account home and stores its unlock password as a generic-password entry in your real user login keychain (service `com.altergo.account-unlock`). Activation is silent — no Touch ID prompt, works over SSH and in automation — because reading from an already-unlocked login keychain doesn't prompt.

**This is workflow isolation, not cryptographic separation.** Any process running under your macOS user can read your login keychain (which is already unlocked during your session) and therefore derive any altergo account's keychain password. If you need hard isolation between accounts — e.g., client work under NDA — use separate macOS user accounts. altergo's keychain isolation is complementary to, not a replacement for, OS-level user separation.

**Explicit non-goals:**

- **No Touch ID ACL on the unlock entry.** Touch ID gating would break SSH sessions and automation. macOS's own login keychain doesn't gate reads on Touch ID; neither does altergo.
- **No broker process or launchd agent.** No incremental benefit — activation reads from an already-unlocked login keychain.
- **No Secure-Enclave wrapping of the unlock password.** The threat model is the same as the native login keychain, which doesn't SE-wrap either.

For hard isolation between identities, use two separate macOS user accounts.

---

## 6. Troubleshooting

**"login keychain is locked" error on launch**

Your real user login keychain is locked (unusual — this normally happens only when the screen is locked). Unlock your login keychain first:

```bash
security unlock-keychain ~/Library/Keychains/login.keychain-db
```

Then relaunch.

**"no unlock entry found" error**

The `com.altergo.account-unlock` entry for this account is missing from your login keychain. This can happen if you manually deleted it or restored from a backup that didn't include keychain data.

altergo cannot recover the unlock password. The per-account keychain is effectively orphaned. See the recovery procedure below.

**Orphaned keychain recovery**

If the keychain file exists but the unlock password entry is gone:

```bash
# Remove the orphaned keychain file
rm -rf ~/.altergo/accounts/<name>/Library/Keychains/login.keychain-db

# Recreate it (altergo will generate a new password and store it)
altergo --config <name> --keychain isolated
```

Any credentials that were stored only in the orphaned keychain are lost. Credentials that are also stored in flat credential files (`.credentials.json`, etc.) are unaffected.

**Password mismatches cannot self-heal**

If the unlock password in the login keychain does not match the password the per-account keychain was created with, `security unlock-keychain` returns `errSecAuthFailed`. altergo exits with an error. There is no automatic recovery — the keychain was created with a different password and there is no way to derive it. Use the orphaned keychain recovery procedure above.
