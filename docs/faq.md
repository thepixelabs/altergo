# FAQ

Short answers to messages and questions that come up while using altergo.

If something here doesn't match what you're seeing, please open an issue — short FAQs only stay short if we keep them honest.

---

## Most users will never see these messages

The repair messages below only appear for accounts in **`private` keychain mode** (the default since v0.45.0; was called `dedicated` in v0.44.x). The `none` mode never produces them.

To check which mode an account uses, look at the `keychain` field in `~/.altergo/accounts/<account>/account.json`. A missing field means `private` (the default). A value of `none` (or old `isolated`) means no keychain is in use.

---

## `altergo: repairing keychain state for '<account>'`

**What it means.** altergo found the keychain for this account in an inconsistent state and fixed it before launching the provider. The launch continues normally after this line.

**What causes it.** Usually one of:

- You reset your Mac login password, or used "Reset Default Keychains" in Keychain Access.
- You restored your home directory (or `~/.altergo/`) from a backup.
- You migrated to a new Mac and copied files across.
- A previous altergo run was interrupted (force-quit, crash, power loss) at the wrong moment.
- You edited entries in Keychain Access by hand.

**What happens to your data.** altergo rebuilds the per-account keychain from scratch. Provider login tokens stored inside it (your Claude Code session, Gemini login, etc.) are gone — you will be asked to log in to that provider again on next launch. Your `account.json`, settings, conversation history, and any other files in the account home are untouched.

**What to do.** Nothing special. Re-run `altergo <account>` and log in to the provider when it prompts you.

---

## `Keychain password mismatch — rebuilding`

**What it means.** altergo found a keychain file for this account, but the stored unlock password no longer works. It cannot recover the contents, so it starts fresh.

**What causes it.** Same list as above — most often a Mac login password reset, a partial restore-from-backup, or a Mac migration where the login keychain wasn't carried over. The keychain file and the unlock password live in two different places; anything that touches one without the other splits them apart.

**What happens to your data.** Provider tokens stored in that keychain are gone. You will log in to the provider again on next launch. Nothing else is touched.

**What to do.** Re-run `altergo <account>` and log in when the provider asks. If this keeps happening for the same account, see "Can I stop seeing this?" below.

---

## `Orphaned keychain file found — rebuilding`

**What it means.** altergo found a keychain file with no matching unlock entry — half a setup. It rebuilds the missing half so the account works again.

**What causes it.** Same family of causes: partial restores, login-password resets, manually deleting items in Keychain Access, or copying only part of an account home to a new machine.

**What happens to your data.** Provider tokens in that keychain are gone. Files outside the keychain are untouched. Log in to the provider again on next launch.

**What to do.** Re-run the account and log back in.

---

## Did I lose any of my data?

No data outside the per-account keychain is touched by these repair paths. Your `account.json`, settings, conversation history, and anything else written to disk inside the account home are still there. The only thing rebuilt is the keychain itself, which holds provider login tokens.

---

## Can I stop seeing this?

Yes. Switch the account to `none` mode (no keychain at all):

```sh
altergo --config <account> --keychain none
```

In `none` mode, altergo blocks the provider from writing tokens to the macOS keychain at all — providers fall back to flat-file credentials under the account's home directory. There is no keychain to drift, so these messages can never appear.

For a full comparison of the two modes, see [`keychain-isolation.md`](./keychain-isolation.md).

---

## I restored from a backup. Should I expect this?

Yes, on the first launch of any `private`-mode account after a restore or a Mac migration. Log back in to the provider once and you are done.
