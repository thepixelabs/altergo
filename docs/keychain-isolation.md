# Keychain isolation (macOS, opt-in)

**Applies to:** altergo v0.41.0+ (preserve-and-reuse semantics: v0.43.0+)  
**Audience:** macOS users who want per-account credential separation at the keychain level.

> **v0.43.0 behavior change:** Switching an account from `isolated` back to `system` no longer deletes the per-account keychain file. The file is preserved on disk so a future re-upgrade can reuse it and recover stored tokens. If you read this doc while running v0.41.0 or v0.42.x, downgrade was destructive — re-upgrading on those versions created a fresh keychain.

For the short version, see the [Keychain isolation section in the README](../README.md#keychain-isolation-macos-opt-in). For the threat model and security scope, see the [Threat model and non-goals](#5-threat-model-and-non-goals) section below.

---

## 1. What this is

altergo runs each account under a separate `HOME` directory, which isolates file-based credentials. On macOS, some provider CLIs also write tokens directly to the system keychain. Those keychain entries are keyed by service name — and when all your altergo accounts share the same system keychain, tokens from different accounts can co-exist in the same store.

Keychain isolation gives each account its own private keychain file. Tokens written by that account stay in that account's keychain and are not visible to other altergo accounts.

You do not need this for most setups. The two modes are:

- **`system` (default):** All accounts share your regular macOS login keychain. Provider tokens are still separated at the file level (`.credentials.json`, etc.); the keychain is shared. This is correct for most users.
- **`isolated`:** Each account gets its own `login.keychain-db` under its account home. Tokens written to the keychain by that account's provider CLI land there, not in the system keychain shared by your other accounts.

**Which should I pick?**

Use `system` (the default) unless you have a specific reason to keep keychain state separate between identities. Most users never need `isolated`. `altergo native` bypasses keychain isolation entirely regardless of this setting.

This is a workflow convenience, not a hard security boundary. See the [threat model section](#5-threat-model-and-non-goals) for what that means in practice.

---

## 2. Opt in / opt out

**Enable isolation for an account:**

```bash
altergo --config <account> --keychain isolated
```

Or run `altergo --config <account>` interactively — altergo will prompt whether to enable keychain isolation. Answering "y" is equivalent to passing `--keychain isolated`.

**Disable isolation and revert to system (default) keychain:**

```bash
altergo --config <account> --keychain system
```

`--keychain shared` is a deprecated alias for `--keychain system` and will be removed in the next minor version. It prints a warning to stderr and behaves identically.

When you flip an account from `isolated` back to `system`, altergo removes the per-account `com.apple.security.plist` so runtime Security.framework routing falls back to the real user's login keychain. The per-account `login.keychain-db` file and the `com.altergo.account-unlock` entry in your real login keychain are preserved on disk so a future re-upgrade can reuse them.

**Default:** `system` on upgrade and for all new accounts unless you explicitly pass `--keychain isolated`. Existing accounts are not changed.

**Rerunning `--config` without a `--keychain` flag** preserves the existing setting.

**`altergo native`** bypasses keychain isolation entirely and runs the provider under the real `$HOME`.

**How keychain mode appears in the UI:**

- `altergo --config` (interactive picker) shows a `  ·  keychain: isolated` suffix on each account row that has isolation enabled. Accounts in `system` mode show no suffix.
- `altergo --config <account>` prints `Current keychain: isolated` or `Current keychain: system (default)` at the top of the config run, before any changes are applied.

---

## 3. On-disk layout

When isolation is enabled for an account named `<account>`, altergo creates:

| Path | What it is |
|---|---|
| `~/.altergo/accounts/<account>/Library/Keychains/login.keychain-db` | The per-account keychain file. Created once; reused on every subsequent launch. |
| `~/.altergo/accounts/<account>/Library/Preferences/com.apple.security.plist` | Plist that tells the macOS Security framework to use the per-account keychain for processes with `HOME` set to this account. Uses the `~/Library/Keychains/login.keychain` tilde-form (`DLDBSearchList`). |
| Login keychain entry (your real user login keychain) | Generic-password entry: service `com.altergo.account-unlock`, account `<account>`. Stores the random unlock password for this account's keychain. |

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

Accounts that have not been explicitly configured for keychain mode (or were created before this feature) have no `keychain` key. After any `--config` run on v0.41.0+, the key is always written: `"keychain": "isolated"` or `"keychain": "system"`.

---

## 4. Lifecycle

**Create** — `altergo --config <account> --keychain isolated` runs `_create_account_keychain`:

1. Generate a 64-character hex password via `secrets.token_bytes(32).hex()`.
2. Create the keychain file: `security create-keychain -p <password> <path>`.
3. Write `com.apple.security.plist` via `plistlib`.
4. Store the unlock password in your real login keychain: `security add-generic-password -s com.altergo.account-unlock -a <account> -w <password> -T /usr/bin/security`.

If you enable isolation on an account that already has tokens stored in the system keychain, those tokens are not carried over — the per-account keychain starts empty. You will need to re-authenticate with each provider once after enabling isolation.

If the keychain file already exists and the unlock entry is present and valid (idempotent re-run), altergo reuses it and skips creation. If the file exists but the unlock entry is missing (orphan), altergo prints a warning, deletes the orphaned keychain file, and rebuilds from scratch. Any tokens stored in the orphaned keychain are lost.

**Activate** — every `altergo <account>` launch calls `_unlock_account_keychain` inside `_build_alt_env`:

1. Read the unlock password from the real login keychain (silent — login keychain is already unlocked, no prompt).
2. Unlock the per-account keychain with that password.

The keychain stays unlocked for the duration of the session, matching macOS's own login keychain behavior.

**Downgrade** — `altergo --config <account> --keychain system`:

1. Remove `Library/Preferences/com.apple.security.plist` from the account home. This is the only file that routes Security.framework to the per-account keychain; removing it causes keychain operations under `HOME=<account_home>` to fall through to the real user's login keychain.
2. Leave `Library/Keychains/login.keychain-db` on disk.
3. Leave the `com.altergo.account-unlock` entry in the real login keychain.
4. Rewrite `account.json` with `"keychain": "system"`.

Rationale: a mode toggle switches which keychain is active, not whether your stored tokens survive. If you want the data gone, use `altergo --delete-account <account>`.

**Re-upgrade** — `altergo --config <account> --keychain isolated` on an account that was previously downgraded:

Any tokens that were stored in the per-account keychain before the downgrade are immediately accessible again — no re-authentication required. altergo detects that `Library/Keychains/login.keychain-db` already exists and that the `com.altergo.account-unlock` unlock entry is still present in the real login keychain, prints "Keychain already exists, reusing", rewrites `com.apple.security.plist`, and updates `account.json` with `"keychain": "isolated"`. No new keychain is created and no new unlock password is generated.

If the file exists but the unlock entry is missing (a true orphan, not a preserved downgrade), altergo prints a warning, deletes the orphaned keychain file, and rebuilds from scratch. Any tokens stored only in the orphaned keychain are lost.

**Delete account** — `altergo --delete-account <account>` tears down keychain artifacts unconditionally based on file-presence, not the `keychain` meta flag. If `Library/Keychains/login.keychain-db` exists or the `com.altergo.account-unlock` entry is present in the real login keychain, altergo removes both before deleting the account home directory. This ensures that a keychain preserved by a prior downgrade is still cleaned up when the account is removed.

---

## 5. Threat model and non-goals

altergo supports opt-in per-account keychain isolation on macOS. When enabled for an account, altergo creates a dedicated `login.keychain-db` for that account under the account home and stores its unlock password as a generic-password entry in your real user login keychain (service `com.altergo.account-unlock`). Activation is silent — no Touch ID prompt, works over SSH and in automation — because reading from an already-unlocked login keychain doesn't prompt.

**This is workflow isolation, not cryptographic separation.** Any process running under your macOS user can read your login keychain (which is already unlocked during your session) and therefore derive any altergo account's keychain password. If you need hard isolation between accounts — e.g., client work under NDA — at present the boundary is OS-level user separation; altergo's keychain isolation is complementary to, not a replacement for, that.

**Explicit non-goals:**

- **No Touch ID ACL on the unlock entry.** Touch ID gating would break SSH sessions and automation. macOS's own login keychain doesn't gate reads on Touch ID; neither does altergo.
- **No broker process or launchd agent.** No incremental benefit — activation reads from an already-unlocked login keychain.
- **No Secure-Enclave wrapping of the unlock password.** The threat model is the same as the native login keychain, which doesn't SE-wrap either.

---

## 6. Troubleshooting

**"login keychain is locked" error on launch**

Your real user login keychain is locked (unusual — this normally happens only when the screen is locked). Unlock your login keychain first:

```bash
security unlock-keychain ~/Library/Keychains/login.keychain-db
```

Then relaunch.

**"no unlock entry found" error**

The `com.altergo.account-unlock` entry for this account is missing from your login keychain. This can happen if you manually deleted it from Keychain Access or restored from a backup that excluded keychain data. altergo cannot recover the unlock password. See the recovery procedure below.

**Keychain file on disk after downgrade — this is expected**

If you downgraded an account with `--keychain system`, `Library/Keychains/login.keychain-db` remains on disk alongside a `com.altergo.account-unlock` entry in your real login keychain. This is intentional: altergo's preserve-and-reuse design keeps those files so a future `--keychain isolated` can restore them without losing stored tokens. You do not need to clean them up manually; `altergo --delete-account <account>` removes them when you delete the account.

**True orphan: keychain file present but unlock entry missing**

This is different from the expected post-downgrade state. A true orphan is when the keychain file exists but the `com.altergo.account-unlock` entry is gone — for example, after manually deleting it from Keychain Access, or restoring from a backup that excluded keychain data.

altergo detects this automatically and self-heals: re-running `--config --keychain isolated` prints "Orphaned keychain file found — rebuilding", removes the unrecoverable file, and creates a fresh keychain with a new password.

```bash
altergo --config <account> --keychain isolated
```

Any credentials that were stored only in the unrecoverable keychain file are lost. Credentials stored in flat credential files (`.credentials.json`, etc.) are unaffected.

**Password mismatches cannot self-heal**

If the unlock password in the login keychain does not match the password the per-account keychain was created with, `security unlock-keychain` returns `errSecAuthFailed`. altergo exits with an error. There is no automatic recovery — the keychain was created with a different password and there is no way to derive it. Use the recovery procedure above.
