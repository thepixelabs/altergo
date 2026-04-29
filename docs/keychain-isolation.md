# Keychain modes (macOS)

**Applies to:** altergo v0.46.0+ (previous name: "keychain isolation", v0.41.0+)  
**Audience:** macOS users who want to understand how altergo interacts with the macOS keychain.

> **v0.46.0 breaking change:** All legacy `--keychain` aliases (`dedicated`, `isolated`, `system`, `shared`) have been removed. Only `private` and `none` are accepted. Accounts with legacy values in `account.json` will see a one-time warning and be treated as `private`. Run `altergo --config <account>` to normalize. See [migration notes](migration.md#v0460--keychain-alias-removal--cancel-warning) for details.

> **v0.45.0 rename (history):** The keychain modes were renamed for clarity. `dedicated` → `private`; `isolated` → `none`. Default flipped to `private`.

For the short version, see the [Keychain modes section in the README](../README.md#keychain-modes-macos). For the threat model and security scope, see the [Threat model and non-goals](#6-threat-model-and-non-goals) section below.

---

## 1. What this is

altergo runs each account under a separate `HOME` directory, which isolates file-based credentials. On macOS, some provider CLIs also write tokens to the macOS keychain. altergo gives you two options for how to handle that:

- **`private` (default since v0.45.0):** Each account gets its own `login.keychain-db` under its account home, unlocked silently at session start. Tokens written to the keychain by that account's provider CLI land there, not in the keychain shared by your other accounts. This is what v0.44.x called `dedicated`.

- **`none` (opt-out):** altergo blocks each account from writing to the macOS keychain. A per-account `login.keychain-db` is created but never unlocked — Security.framework routes keychain writes to it and they fail with `errSecAuthFailed`. Providers fall back to flat-file credentials under the account's HOME. **Nothing lands in your real login keychain.** This is what v0.44.x called `isolated`.

**Which should I pick?**

Use `private` (the default) for clean per-account keychain isolation. Use `none` if you prefer all credentials in flat files under the account's HOME (e.g., to keep the real login keychain completely untouched, or if your provider falls back to flat files anyway).

`altergo native` bypasses keychain mode entirely and runs the provider under the real `$HOME`.

This is workflow isolation, not cryptographic separation. See the [threat model section](#6-threat-model-and-non-goals) for what that means in practice.

---

## 2. Modes

### `private` (default)

```bash
altergo --config <account> --keychain private
```

Or run `altergo --config <account>` interactively and hit Enter (default: Yes, enable `private`).

What altergo creates:

- `Library/Preferences/com.apple.security.plist` — routes Security.framework keychain operations to the per-account keychain.
- `Library/Keychains/login.keychain-db` — the per-account keychain file.
- A `com.altergo.account-unlock` generic-password entry in your **real** login keychain, storing the random unlock password for this account's keychain.

At every `altergo <account>` launch, altergo reads the unlock password from the real login keychain (silent — no prompt) and unlocks the per-account keychain so providers can read and write tokens normally.

### `none` (opt-out)

```bash
altergo --config <account> --keychain none
```

Or answer "n" to the keychain mode prompt during interactive `--config`.

> **Warning:** In `none` mode, macOS may prompt apps for a keychain password they don't have. **Always click Cancel — never "Reset To Defaults".** Clicking "Reset To Defaults" destroys your real login keychain and the credentials stored in it — it is completely unrelated to altergo and cannot be undone. Cancel is always safe.

What altergo creates:

- `Library/Preferences/com.apple.security.plist` — routes Security.framework keychain operations to the per-account keychain.
- `Library/Keychains/login.keychain-db` — a permanently locked per-account keychain. Created with a random password that is immediately discarded; nothing can unlock it.

No `com.altergo.account-unlock` entry is planted in your real login keychain. When a provider tries to write a token to the keychain, it gets `errSecAuthFailed` and falls back to writing a flat-file credential (e.g. `.credentials.json`, `oauth_creds.json`).

### Removed aliases (v0.46.0)

`--keychain system`, `--keychain shared`, `--keychain dedicated`, and `--keychain isolated` were removed in v0.46.0. Only `private` and `none` are accepted by the CLI. Accounts with legacy values in `account.json` are treated as `private` with a one-time warning on load; run `altergo --config <account>` to normalize the stored value.

---

## 3. Dev tool credentials (gh, aws, gcloud) — shared by design

altergo symlinks dev tool config dirs (`.config/gh`, `.aws`, `.config/gcloud`, and others) from each account's HOME back to your real `$HOME` by default. This is **independent of keychain mode** — the two settings do not interact.

What this means in practice:

- `gh`, `aws`, and `gcloud` work in every altergo account without re-authenticating.
- Your existing logins, project configs, and profiles are available across all accounts.
- In `none` keychain mode, keychain writes from these tools are blocked, but they fall back to flat-file credentials — which are already in your real `$HOME` via the symlink, so everything still works.

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
| `~/.altergo/accounts/<account>/Library/Keychains/login.keychain-db` | The per-account keychain file. In `none` mode: permanently locked; never stores tokens. In `private` mode: unlocked at launch; stores provider tokens. |
| `~/.altergo/accounts/<account>/Library/Preferences/com.apple.security.plist` | Plist that tells the macOS Security framework to use the per-account keychain for processes with `HOME` set to this account. Uses the `~/Library/Keychains/login.keychain` tilde-form (`DLDBSearchList`). |

### Private mode only

| Path | What it is |
|---|---|
| Login keychain entry (your real user login keychain) | Generic-password entry: service `com.altergo.account-unlock`, account `<account>`. Stores the random unlock password for this account's keychain. |

### How the private unlock flow works

In private mode, every `altergo <account>` launch silently unlocks the per-account keychain by:

1. Reading the random unlock password from your **real login keychain** via `security find-generic-password -s com.altergo.account-unlock -a <account> -w`.
2. Using that password to unlock the **per-account keychain** at `~/.altergo/accounts/<account>/Library/Keychains/login.keychain-db` via `security unlock-keychain -p <password>`.

For step 1 to succeed silently (no GUI password prompt), altergo grants two layers of permission to the unlock entry when it's created:

- **ACL:** `add-generic-password -T /usr/bin/security` adds the `security` binary to the entry's access control list.
- **Partition list:** `set-generic-password-partition-list -S apple-tool:,apple:` pins the entry's partition list (a macOS Sierra+ enforcement layer) so the ACL grant is durable across keychain search-list changes, OS updates, and other state shifts.

If altergo only set the ACL without the partition list, future reads would intermittently re-prompt for your login password whenever the cached partition state was invalidated. The partition-list pinning is what makes silent unlock reliable.

When you create or reconfigure a private account, altergo runs `set-generic-password-partition-list`, which itself requires authorization — macOS will prompt for your login keychain password **once** at creation time. After that, all subsequent launches are silent.

### `account.json` shape

```json
{
  "version": 3,
  "providers": ["claude"],
  "default_provider": "claude",
  "created": "2026-04-23T10:00:00",
  "keychain": "private"
}
```

Legal values: `"private"` | `"none"`. Accounts with no `keychain` key are treated as `private` (the default since v0.45.0). Legacy values (`dedicated`, `isolated`, `system`, `shared`) are coerced to `private` on load with a one-time warning; they are normalized on the next `--config` touch.

---

## 5. Lifecycle

### Create (`private` mode)

1. Generate a 64-character hex password via `secrets.token_bytes(32).hex()`.
2. Create the keychain file: `security create-keychain -p <password> <path>`.
3. Write `com.apple.security.plist` via `plistlib`.
4. Store the unlock password: `security add-generic-password -s com.altergo.account-unlock -a <account> -w <password> -T /usr/bin/security`.

### Create (`none` mode)

1. Generate a 64-character hex password (discarded immediately after the next step).
2. Create the keychain file: `security create-keychain -p <password> <path>`. Password is never stored anywhere.
3. Write `com.apple.security.plist`.

The keychain is permanently locked from altergo's perspective. Provider writes fail → flat-file fallback.

### Activate

- **private:** every `altergo <account>` launch calls `_unlock_account_keychain`, reads the unlock password from the real login keychain, and unlocks the per-account keychain. Silent, no prompt.
- **none:** no unlock step. The keychain stays locked; Security.framework routes writes to it which fail.

### Switching modes

**`private` → `none`:**

1. Remove `com.altergo.account-unlock` from your real login keychain. This is the "zero footprint" step — nothing from this account lives in your real login keychain after the switch.
2. Keep `Library/Keychains/login.keychain-db` on disk (preserve-and-reuse).
3. Write/keep `com.apple.security.plist`.
4. Rewrite `account.json` with `"keychain": "none"`.

Note: tokens that were stored in the per-account keychain are no longer accessible (the unlock entry is gone). Flat-file credentials are unaffected. Re-upgrading to `private` later creates a fresh keychain; providers will need to re-authenticate into flat files.

**`none` → `private`:**

1. Re-create the keychain and unlock entry (same as fresh `private` creation).
2. Write `account.json` with `"keychain": "private"`.

### Delete account

`altergo --delete-account <account>` tears down all keychain artifacts unconditionally based on file/entry presence, not the `keychain` meta flag. If `Library/Keychains/login.keychain-db` exists or a `com.altergo.account-unlock` entry is present, altergo removes both before deleting the account home directory.

---

## 6. Threat model and non-goals

In `private` mode, altergo stores one generic-password entry per account in your real login keychain (the unlock password). Any process running under your macOS user can read your login keychain (which is already unlocked during your session) and derive any altergo account's keychain password. This is the same threat model as the macOS login keychain itself.

In `none` mode, altergo does **not** plant any entry in your real login keychain. Providers fall back to flat-file credentials. This is a net-positive security posture: the attack surface on the real login keychain is zero for none-mode accounts.

**This is workflow isolation, not cryptographic separation.** If you need hard isolation between accounts — e.g., client work under NDA — at present the boundary is OS-level user separation.

**Explicit non-goals:**

- **No Touch ID ACL on the unlock entry.** Touch ID gating would break SSH sessions and automation. macOS's own login keychain doesn't gate reads on Touch ID; neither does altergo.
- **No broker process or launchd agent.** No incremental benefit — activation reads from an already-unlocked login keychain.
- **No Secure-Enclave wrapping of the unlock password.** The threat model is the same as the native login keychain, which doesn't SE-wrap either.

---

## 7. Troubleshooting

**"login keychain is locked" error on launch (private mode only)**

Your real user login keychain is locked (unusual — this normally happens only when the screen is locked). Unlock your login keychain first:

```bash
security unlock-keychain ~/Library/Keychains/login.keychain-db
```

Then relaunch.

**"no unlock entry found" error (private mode only)**

The `com.altergo.account-unlock` entry for this account is missing from your login keychain. Re-run `--config --keychain private` to rebuild:

```bash
altergo --config <account> --keychain private
```

**Orphaned keychain file (C present, D absent) in private mode**

If the keychain file exists but the unlock entry is gone, altergo detects this, prints "Orphaned keychain file found — rebuilding", removes the unrecoverable file, and creates a fresh keychain. Credentials stored only in the orphaned file are lost; flat-file credentials are unaffected.

**Password mismatch in private mode**

If the unlock password in the login keychain does not match the per-account keychain's password, `security unlock-keychain` returns `errSecAuthFailed`. altergo exits with an error. Recovery:

```bash
altergo --config <account> --keychain private
```

**Switching back to none after private**

```bash
altergo --config <account> --keychain none
```

This removes the unlock entry from your real login keychain. Tokens that were stored only in the per-account keychain are no longer accessible. Flat-file credentials are unaffected.

**Using old names (`dedicated`, `isolated`, `system`, `shared`)**

All legacy `--keychain` values were removed in v0.46.0. Use the canonical names:

```bash
altergo --config <account> --keychain private   # per-account keychain
altergo --config <account> --keychain none      # flat files only
```

Accounts with legacy values in `account.json` from before v0.46.0 will still load — altergo prints a one-time warning and treats them as `private`. Run `altergo --config <account>` to normalize the stored value.

For plain-language explanations of repair messages you may see at launch, see [FAQ](./faq.md).
