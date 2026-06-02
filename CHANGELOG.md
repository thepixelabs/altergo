# CHANGELOG

Releases are tagged on GitHub. For full commit details on any version, run `git log v<version>` or browse the [releases page](https://github.com/thepixelabs/altergo/releases).

---

## v1.4.0 (2026-05-29)

- **feat:** surface `--use native` in first-run onboarding. The first-run screen now presents two side-by-side paths: `altergo --use native` for immediate launch with no setup, and `altergo --config` for named-account setup. `--use` help entry shows `native` as a valid value.

## v1.3.4 (2026-05-28)

- **fix(landing):** replace `pip install` with `pipx install` everywhere on the landing page (hero, step-by-step, code block, copy buttons, JS handler, meta keywords).
- **docs:** drop `pip install` entirely and make the pipx command prominent above the fold. Modern macOS blocks global pip installs by default (PEP 668).

## v1.3.3 (2026-05-28)

- **fix(tui):** remove the BBS shine sweep and twinkle from the nav bar — replaced with a plain static renderer for visual consistency with the rest of the TUI.
- **docs:** promote pipx to the recommended install method in the README with a PEP 668 callout; demote pip.

## v1.3.2 (2026-05-19)

- **fix(keychain):** coerce legacy `private` mode to `keychain` with warning (accounts written by v1.0.x–v1.1.x had `"keychain": "private"` on disk, which silently slipped past `_uses_keychain()` and skipped the keychain unlock step).
- **refactor:** split `altergo.py` monolith into the `altergo/` package. `altergo.py` is now a compatibility stub. 373 tests passing.
- **fix(tmux):** include project segment in session names so altergo-launched sessions match rover-wrapped ones.
- **docs:** canonicalize keychain naming across all docs; restructure landing page commands and feature tiles.

## v1.3.1 (2026-05-15)

- **fix(cli):** `--yolo-resume <id>` respects the active default account instead of always opening the picker.

## v1.3.0 (2026-05-15)

- **feat(cli):** `--yolo-resume` picker now includes `native` when it's the persisted default; press `d` in the picker to set the highlighted row as the new default account. Falls back to a numbered prompt under non-TTY.

## v1.2.3 (2026-05-15)

- **fix(cli):** `altergo --use native` now works (the `--use` handler was rejecting it because `native` has no on-disk directory).
- **ci:** upgrade pip before pip-audit to clear pip-self CVEs.

## v1.2.2 (2026-05-05)

- **fix(keychain):** skip reconcile and unlock when a `keychain`-mode account has an OAuth token (avoids spurious GUI prompts in non-GUI contexts like SSH or tmux).

## v1.2.1 (2026-05-05)

- **fix(keychain):** drop the interactive partition-list pin during `--config` (it required the macOS login password and could crash the flow). Trade-off: one "Always Allow" GUI dialog on first launch.
- **fix(launch):** `_build_alt_env` skips the keychain unlock entirely when a per-account `.oauth-token` file is present.

## v1.2.0 (2026-05-05)

- **feat:** rename keychain mode `private` → `keychain` (canonical since v0.45.0). Legacy `private` coerces with a one-time warning.
- **feat:** `altergo --setup-token <account>` for claude accounts — generates an SSH-friendly OAuth token file under the account home, bypasses the macOS keychain over SSH.
- **feat:** interactive `--config` prompt rewritten — single combined keychain+SSH explanation; offers token setup right after picking `keychain` mode.
- **docs:** new [`docs/ssh-auth.md`](docs/ssh-auth.md).

## v1.1.1 (2026-05-04)

- **release:** version bump to work around a PyPI filename reuse block after a partial v1.1.0 upload.

## v1.1.0 (2026-05-03)

- Republish the v1.x release pipeline after a repo recreate.

## v1.0.2 (2026-04-30)

- **fix(keychain):** print a heads-up before macOS partition-list grant prompts the user, so the dialog doesn't appear out of nowhere.

## v1.0.1 (2026-04-30)

- **fix(keychain):** clarify the "orphaned keychain rebuild" message so users know they'll need to re-authenticate.

## v1.0.0 (2026-04-29)

**Breaking.** `--keychain` only accepts `private` and `none`. All four legacy aliases (`dedicated`, `isolated`, `system`, `shared`) are rejected with a hard CLI error. Accounts with legacy values in `account.json` still load with a one-line warning and are treated as `private`; run `altergo --config <account>` to normalize.

Also: new Cancel-vs-Reset-To-Defaults warning shown whenever `none` mode is activated.

---

## Older releases (pre-1.0)

Pre-v1.0 covered the keychain isolation introduction (v0.41.0), multi-provider accounts (v0.40.0), the N-account layout (v0.5.0), and the original single-account release (v0.4.x). Highlights are in [`docs/migration.md`](docs/migration.md). For full per-version detail see git tags:

```bash
git log --tags --simplify-by-decoration --pretty='format:%cs %d'
```
