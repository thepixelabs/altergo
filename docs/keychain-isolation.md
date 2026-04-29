# Keychain modes (macOS)

**Applies to:** altergo v0.44.0+ (previous name: "keychain isolation", v0.41.0+)  
**Audience:** macOS users who want to understand how altergo interacts with the macOS keychain.

> **v0.44.0 behavior change:** The default keychain mode is now `isolated` (blocking). altergo no longer plants any entry in your real login keychain by default — providers fall back to flat-file credentials. The previous default (`system`, same as `isolated`) and the old opt-in mode (`isolated`, now called `dedicated`) are both preserved as-is; only the names changed. See [migration notes](#switching-modes) below.

For the short version, see the [Keychain modes section in the README](../README.md#keychain-modes-macos). For the threat model and security scope, see the [Threat model and non-goals](#5-threat-model-and-non-goals) section below.

---

## 1. What this is

altergo runs each account under a separate `HOME` directory, which isolates file-based credentials. On macOS, some provider CLIs also write tokens to the macOS keychain. altergo gives you two options for how to handle that:

- **`isolated` (default since v0.44.0):** altergo blocks each account from writing to the macOS keychain. A per-account `login.keychain-db` is created but never unlocked — Security.framework routes keychain writes to it and they fail with `errSecAuthFailed`. Providers fall back to flat-file credentials under the account's HOME. **Nothing lands in your real login keychain.** This is the safe default for most users.

- **`dedicated` (opt-in):** Each account gets its own `login.keychain-db` under its account home, unlocked at session start. Tokens written to the keychain by that account's provider CLI land there, not in the keychain shared by your other accounts. This is what v0.43.x called `isolated`.

**Which should I pick?**

Use `isolated` (the default) unless your provider CLI requires keychain writes to function (most fall back to flat files gracefully). Use `dedicated` if you need strict per-account keychain separation.

`altergo native` bypasses keychain mode entirely and runs the provider under the real `$HOME`.

This is workflow isolation, not cryptographic separation. See the [threat model section](#5-threat-model-and-non-goals) for what that means in practice.

---

## 2. Modes

### `isolated` (default)

```bash
altergo --config <account> --keychain isolated
```

Or run `altergo --config <account>` interactively and hit Enter (default: No, keep `isolated`).

What altergo creates:

- `Library/Preferences/com.apple.security.plist` — routes Security.framework keychain operations to the per-account keychain.
- `Library/Keychains/login.keychain-db` — a permanently locked per-account keychain. Created with a random password that is immediately discarded; nothing can unlock it.

No `com.altergo.account-unlock` entry is planted in your real login keychain. When a provider tries to write a token to the keychain, it gets `errSecAuthFailed` and falls back to writing a flat-file credential (e.g. `.credentials.json`, `oauth_creds.json`).

### `dedicated` (opt-in)

```bash
altergo --config <account> --keychain dedicated
```

Or answer "y" to the keychain mode prompt during interactive `--config`.

What altergo creates in addition to the files above:

- A `com.altergo.account-unlock` generic-password entry in your **real** login keychain, storing the random unlock password for this account's keychain.

At every `altergo <account>` launch, altergo reads the unlock password from the real login keychain (silent — no prompt) and unlocks the per-account keychain so providers can read and write tokens normally.

### Deprecated aliases

`--keychain system` and `--keychain shared` are deprecated aliases that resolve to `isolated`. They emit a warning to stderr and will be removed in v0.46.0.

---

## 3. Dev tool credentials (gh, aws, gcloud) — shared by design

altergo symlinks dev tool config dirs (`.config/gh`, `.aws`, `.config/gcloud`, and others) from each account's HOME back to your real `$HOME` by default. This is **independent of keychain mode** — the two settings do not interact.

What this means in practice:

- `gh`, `aws`, and `gcloud` work in every altergo account without re-authenticating.
- Your existing logins, project configs, and profiles are available across all accounts.
- In `isolated` keychain mode (the default), keychain writes from these tools are blocked, but they fall back to flat-file credentials — which are already in your real `$HOME` via the symlink, so everything still works.

**This is intentional.** altergo isolates **AI provider credentials** (Claude, Codex, Gemini, Copilot), not your dev infrastructure. You have one GitHub login, one AWS profile, one gcloud config — there is no reason to re-auth those in every account.

If you do need per-account isolation for `gh`, `aws`, or `gcloud` (e.g., consulting with multiple client AWS accounts), toggle those entries off individually in `altergo --settings` → Credentials.

### Keychain search list hygiene

macOS's `security create-keychain` command silently appends each new keychain file to the user's global keychain search list (`~/Library/Preferences/com.apple.security.plist`), regardless of where the file is created. Without intervention, this would pollute your real `$HOME` search list with every altergo per-account keychain, causing native-mode tools to encounter locked keychains during token lookups.

altergo prevents this by capturing and restoring the real search list around every keychain creation — your global search list always contains only your real login keychain and any keychains you added yourself.

---

## 4. On-disk layout

### Both modes

| Path | What it is |
|---|---|
| `~/.altergo/accounts/<account>/Library/Keychains/login.keychain-db` | The per-account keychain file. In `isolated` mode: permanently locked; never stores tokens. In `dedicated` mode: unlocked at launch; stores provider tokens. |
| `~/.altergo/accounts/<account>/Library/Preferences/com.apple.security.plist` | Plist that tells the macOS Security framework to use the per-account keychain for processes with `HOME` set to this account. Uses the `~/Library/Keychains/login.keychain` tilde-form (`DLDBSearchList`). |

### Dedicated mode only

| Path | What it is |
|---|---|
| Login keychain entry (your real user login keychain) | Generic-password entry: service `com.altergo.account-unlock`, account `<account>`. Stores the random unlock password for this account's keychain. |

### How the dedicated unlock flow works

In dedicated mode, every `altergo <account>` launch silently unlocks the per-account keychain by:

1. Reading the random unlock password from your **real login keychain** via `security find-generic-password -s com.altergo.account-unlock -a <account> -w`.
2. Using that password to unlock the **per-account keychain** at `~/.altergo/accounts/<account>/Library/Keychains/login.keychain-db` via `security unlock-keychain -p <password>`.

For step 1 to succeed silently (no GUI password prompt), altergo grants two layers of permission to the unlock entry when it's created:

- **ACL:** `add-generic-password -T /usr/bin/security` adds the `security` binary to the entry's access control list.
- **Partition list:** `set-generic-password-partition-list -S apple-tool:,apple:` pins the entry's partition list (a macOS Sierra+ enforcement layer) so the ACL grant is durable across keychain search-list changes, OS updates, and other state shifts.

If altergo only set the ACL without the partition list, future reads would intermittently re-prompt for your login password whenever the cached partition state was invalidated. The partition-list pinning is what makes silent unlock reliable.

When you create or reconfigure a dedicated account, altergo runs `set-generic-password-partition-list`, which itself requires authorization — macOS will prompt for your login keychain password **once** at creation time. After that, all subsequent launches are silent.

### `account.json` shape

```json
{
  "version": 3,
  "providers": ["claude"],
  "default_provider": "claude",
  "created": "2026-04-23T10:00:00",
  "keychain": "isolated"
}
```

Legal values: `"isolated"` | `"dedicated"`. Accounts with no `keychain` key are treated as `isolated` (the default).

---

## 5. Lifecycle

### Create (`dedicated` mode)

1. Generate a 64-character hex password via `secrets.token_bytes(32).hex()`.
2. Create the keychain file: `security create-keychain -p <password> <path>`.
3. Write `com.apple.security.plist` via `plistlib`.
4. Store the unlock password: `security add-generic-password -s com.altergo.account-unlock -a <account> -w <password> -T /usr/bin/security`.

### Create (`isolated` mode)

1. Generate a 64-character hex password (discarded immediately after the next step).
2. Create the keychain file: `security create-keychain -p <password> <path>`. Password is never stored anywhere.
3. Write `com.apple.security.plist`.

The keychain is permanently locked from altergo's perspective. Provider writes fail → flat-file fallback.

### Activate

- **dedicated:** every `altergo <account>` launch calls `_unlock_account_keychain`, reads the unlock password from the real login keychain, and unlocks the per-account keychain. Silent, no prompt.
- **isolated:** no unlock step. The keychain stays locked; Security.framework routes writes to it which fail.

### Switching modes

**`dedicated` → `isolated`:**

1. Remove `com.altergo.account-unlock` from your real login keychain. This is the "zero footprint" step — nothing from this account lives in your real login keychain after the switch.
2. Keep `Library/Keychains/login.keychain-db` on disk (preserve-and-reuse).
3. Write/keep `com.apple.security.plist`.
4. Rewrite `account.json` with `"keychain": "isolated"`.

Note: tokens that were stored in the per-account keychain are no longer accessible (the unlock entry is gone). Flat-file credentials are unaffected. Re-upgrading to `dedicated` later creates a fresh keychain; providers will need to re-authenticate into flat files.

**`isolated` → `dedicated`:**

1. Re-create the keychain and unlock entry (same as fresh `dedicated` creation).
2. Write `account.json` with `"keychain": "dedicated"`.

### Delete account

`altergo --delete-account <account>` tears down all keychain artifacts unconditionally based on file/entry presence, not the `keychain` meta flag. If `Library/Keychains/login.keychain-db` exists or a `com.altergo.account-unlock` entry is present, altergo removes both before deleting the account home directory.

---

## 6. Threat model and non-goals

By default (`isolated` mode), altergo does **not** plant any entry in your real login keychain. Providers fall back to flat-file credentials. This is a net-positive security posture: the attack surface on the real login keychain is zero for isolated accounts.

In `dedicated` mode, altergo stores one generic-password entry per account in your real login keychain (the unlock password). Any process running under your macOS user can read your login keychain (which is already unlocked during your session) and derive any altergo account's keychain password. This is the same threat model as the macOS login keychain itself.

**This is workflow isolation, not cryptographic separation.** If you need hard isolation between accounts — e.g., client work under NDA — at present the boundary is OS-level user separation.

**Explicit non-goals:**

- **No Touch ID ACL on the unlock entry.** Touch ID gating would break SSH sessions and automation. macOS's own login keychain doesn't gate reads on Touch ID; neither does altergo.
- **No broker process or launchd agent.** No incremental benefit — activation reads from an already-unlocked login keychain.
- **No Secure-Enclave wrapping of the unlock password.** The threat model is the same as the native login keychain, which doesn't SE-wrap either.

---

## 7. Troubleshooting

**"login keychain is locked" error on launch (dedicated mode only)**

Your real user login keychain is locked (unusual — this normally happens only when the screen is locked). Unlock your login keychain first:

```bash
security unlock-keychain ~/Library/Keychains/login.keychain-db
```

Then relaunch.

**"no unlock entry found" error (dedicated mode only)**

The `com.altergo.account-unlock` entry for this account is missing from your login keychain. Re-run `--config --keychain dedicated` to rebuild:

```bash
altergo --config <account> --keychain dedicated
```

**Orphaned keychain file (C present, D absent) in dedicated mode**

If the keychain file exists but the unlock entry is gone, altergo detects this, prints "Orphaned keychain file found — rebuilding", removes the unrecoverable file, and creates a fresh keychain. Credentials stored only in the orphaned file are lost; flat-file credentials are unaffected.

**Password mismatch in dedicated mode**

If the unlock password in the login keychain does not match the per-account keychain's password, `security unlock-keychain` returns `errSecAuthFailed`. altergo exits with an error. Recovery:

```bash
altergo --config <account> --keychain dedicated
```

**Switching back to isolated after dedicated**

```bash
altergo --config <account> --keychain isolated
```

This removes the unlock entry from your real login keychain. Tokens that were stored only in the per-account keychain are no longer accessible. Flat-file credentials are unaffected.

For plain-language explanations of repair messages you may see at launch, see [FAQ](./faq.md).
