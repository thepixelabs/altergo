# Keychain modes (macOS)

**Audience:** macOS users who want to understand how altergo interacts with the system keychain.

Two modes, set per-account in `account.json`:

- **`keychain` (default).** Each account gets its own `login.keychain-db`, unlocked silently at session start. Tokens written by that account's provider land in its own keychain, not the one shared with your other accounts.
- **`none` (opt-out).** A per-account `login.keychain-db` is created but never unlocked. Security.framework routes keychain writes to it; they fail; providers fall back to flat-file credentials under the account's HOME. **Nothing lands in your real login keychain.**

`altergo native` bypasses keychain mode entirely and runs the provider under the real `$HOME`.

This is workflow isolation, not cryptographic separation — see [§5 threat model](#5-threat-model) below.

> **Legacy names.** Older versions called these `private`/`none` (v1.0.x–v1.1.x) and `dedicated`/`isolated`/`system`/`shared` (before v0.45.0). All legacy values in `account.json` coerce to `keychain` with a one-time stderr warning; the CLI only accepts `keychain` and `none`. Run `altergo --config <account>` to normalize.

---

## 2. Modes

### `keychain` (default)

```bash
altergo --config <account> --keychain keychain
```

Or pick `Yes` at the interactive `--config` prompt.

altergo creates:

- `Library/Keychains/login.keychain-db` — the per-account keychain.
- `Library/Preferences/com.apple.security.plist` — routes Security.framework operations to the per-account keychain when `HOME` is set to this account.
- A `com.altergo.account-unlock` generic-password entry in your **real** login keychain, storing the random unlock password.

At every launch, altergo reads the unlock password from your real login keychain (silent) and unlocks the per-account keychain.

**Over SSH** the Security framework refuses keychain reads in non-GUI sessions, so the silent unlock can't run. For claude accounts, altergo offers `altergo --setup-token <account>` right after you pick `keychain` mode — with a token present, the launch path skips the keychain entirely. Full SSH story: [ssh-auth.md](ssh-auth.md).

### `none`

```bash
altergo --config <account> --keychain none
```

> **Warning.** macOS may prompt apps for a keychain password they don't have. **Always click Cancel — never "Reset To Defaults".** Reset destroys your real login keychain. Cancel is always safe.

altergo creates the same plist and per-account keychain file, but the keychain is permanently locked (the random password is discarded). No entry is planted in your real login keychain. Provider keychain writes get `errSecAuthFailed` and fall back to flat-file credentials (`.credentials.json`, `oauth_creds.json`, etc.).

---

## 3. On-disk layout

| Path | Notes |
|---|---|
| `~/.altergo/accounts/<account>/Library/Keychains/login.keychain-db` | Per-account keychain. `none`: permanently locked. `keychain`: unlocked at launch. |
| `~/.altergo/accounts/<account>/Library/Preferences/com.apple.security.plist` | Routes Security.framework to the per-account keychain. Uses the `~/Library/Keychains/login.keychain` tilde-form. |
| Real login keychain entry: `com.altergo.account-unlock` / `<account>` | `keychain` mode only. Stores the random unlock password. |
| `~/.altergo/accounts/<account>/.claude/.oauth-token` | Optional. Written by `altergo --setup-token <account>`. When present, skips the keychain unlock entirely. |

### Search-list hygiene

`security create-keychain` silently appends the new keychain to the user's global search list in `~/Library/Preferences/com.apple.security.plist`. Without intervention, this would pollute your real search list with every per-account keychain. altergo captures and restores the real search list around every create call.

### Dev tools (gh, aws, gcloud) are shared by design

Catalog symlinks (`.config/gh`, `.aws`, `.config/gcloud`, …) live at the account-home level and are independent of keychain mode. altergo isolates **AI provider credentials**, not dev infrastructure. Toggle per-tool in `altergo --settings` → Credentials if you need per-account isolation.

### `account.json`

```json
{
  "version": 3,
  "providers": ["claude"],
  "default_provider": "claude",
  "created": "2026-04-23T10:00:00",
  "keychain": "keychain"
}
```

Legal: `"keychain"` | `"none"`. Absent key = `keychain`. Legacy values coerce on load with a one-time warning.

---

## 4. Lifecycle

### Create

- **`keychain`:** generate a random 64-char hex password, run `security create-keychain`, write `com.apple.security.plist`, store the unlock password in your real login keychain via `add-generic-password -T /usr/bin/security`. For claude accounts, offer `--setup-token` to add the SSH bridge.
- **`none`:** same but the unlock password is discarded immediately — the keychain stays permanently locked.

### Activate (at every launch)

- **`keychain` (no token):** read unlock password from real login keychain (silent), unlock the per-account keychain. The first time may show a one-time "Always Allow" GUI dialog from macOS; click it once and it persists across all contexts (including SSH).
- **`keychain` (with `.oauth-token`):** skip the unlock entirely. Token-in-env makes the keychain irrelevant; this is what makes SSH work.
- **`none`:** no unlock. Keychain writes from providers fail and they fall back to flat files.

### Switch modes

`altergo --config <account> --keychain <mode>` rewrites `account.json`. Switching `keychain → none` removes the `com.altergo.account-unlock` entry from your real login keychain (zero-footprint), preserves the keychain file on disk, and providers re-authenticate into flat files on next launch. Switching `none → keychain` recreates the unlock entry.

### Delete account

`altergo --delete-account <account>` tears down keychain artifacts unconditionally based on file presence (not the `keychain` flag), then removes the account home. Any `.oauth-token` goes with the account directory.

---

## 5. Threat model

In `keychain` mode, altergo stores one generic-password entry per account in your real login keychain (the unlock password). Any process running as your macOS user can read your login keychain while it's unlocked — same threat model as the macOS login keychain itself.

In `none` mode, altergo plants nothing in your real login keychain. Net-positive security posture: zero attack surface on the real login keychain for none-mode accounts.

**This is workflow isolation, not cryptographic separation.** For hard isolation (e.g. client work under NDA), use OS-level user separation.

Explicit non-goals:

- No Touch ID ACL on the unlock entry — would break SSH and automation. macOS's own login keychain doesn't gate reads on Touch ID either.
- No broker process or launchd agent — no incremental benefit.
- No Secure-Enclave wrapping — the native login keychain doesn't either.

---

## 6. Troubleshooting

**"login keychain is locked" on launch (`keychain` mode).** Unlock your real login keychain first:

```bash
security unlock-keychain ~/Library/Keychains/login.keychain-db
```

**"no unlock entry found" (`keychain` mode).** Rebuild:

```bash
altergo --config <account> --keychain keychain
```

**Orphaned keychain file.** altergo prints "Orphaned keychain file found — rebuilding", removes it, and creates a fresh one. Credentials stored only in the orphan are lost; flat files are unaffected.

**SSH session fails to authenticate (`keychain` mode, no token).** Set up the bridge once:

```bash
altergo --setup-token <account>
```

Subsequent launches over SSH skip the keychain entirely. Full flow: [ssh-auth.md](ssh-auth.md).

**Repair messages at launch (`altergo: repairing keychain state for '<account>'`, etc.).** Plain-language explanations in [FAQ](./faq.md).
