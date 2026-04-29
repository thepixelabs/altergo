# CHANGELOG


## v0.45.0 (2026-04-30)

### Features

- **keychain**: Rename modes to `private`/`none` and flip default to `private`

  `dedicated` → `private` (per-account keychain, unlocked at session start).
  `isolated` → `none` (no keychain; flat-file credentials only).

  Both old names are accepted silently as backwards-compat aliases — no warning,
  no manual migration required. On-disk values coerce in memory; the canonical
  name is written on the next `--config` touch.

  Default flipped: absent `keychain` key and `--config` without `--keychain` now
  default to `private` (was `none`/`isolated` since v0.44.0). The macOS system
  dialog that appeared when providers tried to write to the permanently-locked
  isolated keychain is eliminated — `private` mode unlocks silently.

  `--keychain system` and `--keychain shared` remain deprecated with a warning
  (removal in v0.46.0). `--keychain dedicated` and `--keychain isolated` are
  now silent backwards-compat aliases (no warning).

  Internal helpers `_is_keychain_dedicated` and `_is_keychain_isolated` remain
  as backwards-compat wrappers for `_is_keychain_private` and `_is_keychain_none`.

  See [docs/migration.md](docs/migration.md#v0450--keychain-mode-rename-private--none).


## v0.44.7 (2026-04-29)

### Bug Fixes

- **keychain**: Pin partition list on dedicated unlock entry to prevent re-prompts
  ([#41](https://github.com/thepixelabs/altergo/pull/41),
  [`5aef7b4`](https://github.com/thepixelabs/altergo/commit/5aef7b4a9284987c5cb11f24679fd3c537e3badf))

When altergo creates a dedicated-mode unlock entry it sets the ACL via 'add-generic-password -T
  /usr/bin/security'. Sierra+ enforces a second layer called the partition list, and without
  explicit pinning the default partition state is fragile — it can be invalidated by keychain
  search-list changes, macOS updates, or a single Deny click, after which 'find-generic-password -w'
  starts re-prompting for the login password on every dedicated account launch.

Fix: after add-generic-password, run set-generic-password-partition-list

with apple-tool:,apple: so the ACL grant for /usr/bin/security is durable across all of those state
  shifts. The set-partition-list call itself requires authorization and may prompt once at account
  creation time — acceptable since --config is interactive. After that, every 'altergo <account>'
  launch is silent.

docs: add a "How the dedicated unlock flow works" section to keychain-isolation.md explaining the
  two-layer ACL/partition model and why the one-time creation prompt is necessary.

Existing dedicated entries created before this fix still need a one-time manual partition-list grant
  — a future migration in --config could auto-repair, but for now users running into prompts can fix
  manually: security set-generic-password-partition-list \ -S apple-tool:,apple: -s
  com.altergo.account-unlock -a <account>


## v0.44.6 (2026-04-29)

### Bug Fixes

- **keychain**: Prevent per-account keychains from polluting real HOME search list
  ([#40](https://github.com/thepixelabs/altergo/pull/40),
  [`cbd0b5c`](https://github.com/thepixelabs/altergo/commit/cbd0b5c597287ef146607adfeb3cbfa24118bc71))

* fix(keychain): prevent per-account keychains from polluting real HOME search list

security create-keychain silently appends the new keychain to the user's global DLDBSearchList in
  ~/Library/Preferences/com.apple.security.plist. Over time this filled the real $HOME search list
  with locked altergo per-account keychains, causing native-mode tools (gh, aws, gcloud) to
  encounter errSecAuthFailed on keychain writes and fall back to flat files even when the real login
  keychain was fully accessible.

Fix: _sec_create_keychain captures the real search list before creation and restores it after, so
  the per-account keychain file is created in the right place without leaving a breadcrumb in the
  user's global list.

Also adds _prune_altergo_keychains_from_search_list for one-time cleanup of stale entries from
  existing installs (callable ad-hoc if needed).

docs: explain the search list hygiene behaviour in keychain-isolation.md

* fix(keychain): use ACCOUNTS_DIR constant in prune helper

### Documentation

- **settings**: Clarify catalog sharing intent + fix warn icon visibility
  ([#39](https://github.com/thepixelabs/altergo/pull/39),
  [`3146747`](https://github.com/thepixelabs/altergo/commit/3146747ece3e1095fc4c021be087499bb0ab3491))

- README + keychain-isolation.md: document that gh/aws/gcloud symlinks are independent of keychain
  mode and shared by design (AI provider credentials are what gets isolated, not dev infrastructure)
  - docs/keychain-isolation.md: new §3 with full explanation; renumber subsequent sections -
  settings TUI credentials page: render ⚠ icon in amber+bold instead of plain text, and show warning
  tooltip in amber+bold instead of amber+dim


## v0.44.5 (2026-04-28)

### Bug Fixes

- **landing**: Swap stale 'open source' phrasing to fair-code
  ([`15d8d25`](https://github.com/thepixelabs/altergo/commit/15d8d25be64b1168ddaf7f40c1fd82375c0f1ebd))

Two leftover strings on the landing page were still describing altergo as 'open source' —
  technically inaccurate under PolyForm Shield 1.0.0 (which is source-available / fair-code, not OSI
  open source). Updated meta description and footer to match the project's actual licensing posture.

### Documentation

- Add keychain repair FAQ and relicense to PolyForm Shield 1.0.0
  ([#37](https://github.com/thepixelabs/altergo/pull/37),
  [`3fde668`](https://github.com/thepixelabs/altergo/commit/3fde6682b496f4d7869e7c95d097149cb02e05ca))

FAQ - New docs/faq.md with plain-language entries for the three keychain repair stderr messages
  users may see at launch in dedicated keychain mode (repairing keychain state, password mismatch,
  orphaned keychain file). Each entry covers what it means, common causes, what happens to provider
  tokens, and what to do. - Linked from README keychain row and from docs/keychain-isolation.md
  troubleshooting section.

License - Replace prior license with PolyForm Shield 1.0.0 (fair-code, source-available, noncompete
  clause). - Update pyproject.toml license field to read from LICENSE file. - Update README badge,
  add License section, footer wording. - Update DISCLAIMER.md (header, footer copyright line). -
  Update docs/index.html JSON-LD license URL. - Update docs/disclaimer-snippet.html, launch posts. -
  CHANGELOG historical entries left untouched (accurate at time of writing).


## v0.44.4 (2026-04-26)

### Bug Fixes

- --add-provider must not pool credentials into MAIN_HOME
  ([#24](https://github.com/thepixelabs/altergo/pull/24),
  [`60098cc`](https://github.com/thepixelabs/altergo/commit/60098cc210386a88cf58e77ef28337336d6f5108))

_reconcile_orphan_dot_dir was iterating every child of account_home/<dot>/ and moving it into
  MAIN_HOME/<dot>/. That includes auth.json / oauth_creds.json / .credentials.json — the per-account
  credential files — and any local state (sqlite dbs, per-account caches). Pooling them into
  MAIN_HOME defeats altergo's isolation model: two accounts sharing one provider dot-dir in MAIN
  would end up sharing identity.

The fix restricts migration to the shared catalog only: PROVIDERS[id]["symlink_dirs"] +
  ["symlink_files"]. Everything else — credentials, local sqlite state, unknown children — stays in
  place as a real file/dir under account_home/<dot>/. That matches the existing
  _apply_provider_setup contract: only catalog entries get symlinked.

Also removed the trailing rmdir of the account-local dot-dir — it still holds credentials after
  reconciliation, so the dir must remain.

Added test_add_provider_preserves_credentials_per_account that asserts auth.json and logs_2.sqlite
  stay account-local while sessions/ migrates.

- --resume always launched with hardcoded default account
  ([`02ba620`](https://github.com/thepixelabs/altergo/commit/02ba620f3b1607f914f7e63843f90fc678e89444))

- Altergo is now a transparent claude wrapper — no more auto-picker
  ([`599fcc6`](https://github.com/thepixelabs/altergo/commit/599fcc6de4790e3f4dab8a99682a62be77057004))

- altergo (no args) → claude (starts new session) - altergo [any flags] → claude [any flags] (full
  pass-through) - altergo --resume → opens interactive session picker - altergo --resume <id> →
  resumes session directly - removed 'altergo new' subcommand (redundant, just use altergo)

- Apply all landing page scenario pivot changes correctly
  ([`d094fe0`](https://github.com/thepixelabs/altergo/commit/d094fe0c573edce87c67e41fd26d1022cdd48778))

Previous commits had copy failures between worktrees — changes weren't persisting. This commit
  applies everything cleanly in one pass:

- Hero h1: "Don't break flow. Switch accounts." - Hero subtitle: rate-limit/mid-session scenario
  with `altergo backup` - New #when section: three scenario cards (Rate-limited, Thinker/sprinter,
  Clients/credentials) with nav links (desktop + mobile) - Why section: "Never lose your flow."
  heading + updated subtitle - All CLI examples: `altergo pro` → `altergo backup`, `altergo
  personal` → `altergo backup`, `--name personal` → `--name work`, `--name pro` → `--name backup`
  (14+ occurrences across HTML, JS, data-copy attrs) - Meta description updated - Multi-name lists
  like `personal, pro, sideproject` left unchanged

Co-Authored-By: Claude Sonnet 4.6 <noreply@anthropic.com>

- Apply CEO messaging feedback — tagline, migration output, credential sharing note
  ([`1d8970a`](https://github.com/thepixelabs/altergo/commit/1d8970a0d8540ef962d58fa74242b46918221fe9))

- Tagline: 'Your other Claude.' → 'Switch Claude identities. Keep your context.' - migrate_legacy():
  print 4-line visible block + write MIGRATED.txt audit file (CEO: silent one-liner is wrong for a
  one-time destructive rename) - do_setup(): add 'Isolates Claude. Shares AWS/GCP/Docker by
  default.' footer - tests/conftest.py: force local altergo.py over installed site-packages -
  test_migrate_legacy_prints_once: update assertion for new multi-line output

- Bump version to 0.4.0, add smoke tests to fix CI no-tests exit 5
  ([`b34af26`](https://github.com/thepixelabs/altergo/commit/b34af267275eb876e05870e1eea798829498e046))

- Clarify setup/teardown help text and add Accounts section
  ([`4b8b26d`](https://github.com/thepixelabs/altergo/commit/4b8b26d365c2c636d0fb04ba2882484ab2ca340f))

- Footer nav element was inheriting nav{position:fixed;top:0} — change to div
  ([`45ef4e5`](https://github.com/thepixelabs/altergo/commit/45ef4e5c8b58c2d7d16337eaf74b9b60a5e3d1fc))

The bare 'nav' CSS selector applied to ALL nav elements including the footer's <nav
  class="footer-links">, causing it to teleport to the top of the viewport above the main navigation
  bar.

Co-Authored-By: Claude Sonnet 4.6 <noreply@anthropic.com>

- Remove legacy migration, startup sweep, and --update-check arg
  ([#14](https://github.com/thepixelabs/altergo/pull/14),
  [`e88160d`](https://github.com/thepixelabs/altergo/commit/e88160d0d600d3ff6d0fedd161acebed63b46206))

* fix: remove legacy migration, startup sweep, and --update-check arg

- Remove detect_legacy() and migrate_legacy() — all users are already on the N-account layout; the
  migration code is dead weight - Remove unconditional _sweep_existing_accounts() calls from main()
  and launch_claude() — sweep now only runs from --config where it is actually needed - Harden
  _ensure_symlinked_dir case (d): warn and skip instead of silently moving account data to the
  shared store, which was the mechanism that could cause account data loss on upgrade - Remove
  --update-check CLI argument entirely; update check toggle is now only accessible via the settings
  panel (altergo --settings)

* test: remove tests for deleted migrate_legacy and --update-check arg

- Rename --setup to --config and add `<name> use <provider>` subcommand
  ([`8d8eb86`](https://github.com/thepixelabs/altergo/commit/8d8eb86c705621a06871741bfa67535cc8336f74))

- Replace tier-implying account names with neutral examples
  ([`5d85368`](https://github.com/thepixelabs/altergo/commit/5d85368b58e16d14bc6695dde63df2cd6b68d938))

`altergo pro` and `altergo personal` in CLI snippets accidentally read as altergo product tiers.
  Replace with `altergo backup` (and `work` in multi-example contexts) throughout — hero, features,
  how-it-works, install snippets, commands table, and terminal animation.

Multi-example listings like `personal, pro, sideproject` (showing that names are user-defined) are
  left unchanged.

Co-Authored-By: Claude Sonnet 4.6 <noreply@anthropic.com>

- Resolve all ruff lint errors (E741, I001, F841, E501)
  ([`ba7c82e`](https://github.com/thepixelabs/altergo/commit/ba7c82e5cafd3a9e08c134d05a7ef3349fcb67f5))

Rename ambiguous variable `l` to `ln` in logo list comprehensions, sort Rich/urllib import blocks,
  remove unused logo_left/logo_width/DIM/project variables, and wrap long lines in help text, nav
  string, and frozenset literal.

- Safer migration backup order, additional edge-case tests
  ([`199bdce`](https://github.com/thepixelabs/altergo/commit/199bdced3a4bffb25ae2f32fe09306daf430ec3c))

- Show goodbye message after provider exits, not before launch
  ([`9f0af02`](https://github.com/thepixelabs/altergo/commit/9f0af0224c2ca813d305c10c88d0feed471a5af8))

- Simplify --help divider and drop launcher keys section
  ([#19](https://github.com/thepixelabs/altergo/pull/19),
  [`9c42309`](https://github.com/thepixelabs/altergo/commit/9c42309052bda60addf14fb36f2b0a43aacb350f))

* fix: simplify --help divider and drop launcher keys section

Remove the shimmering divider animation in show_help() — it blocked the terminal for ~1.6s and
  overwrote left-column text that extended past the fixed divider column. Divider is now pinned to
  the widest left row so it renders as a single straight line regardless of row overflow. Also drop
  the "Launcher keys" section from both the two-column and single-column layouts.

* style: ruff format

- Slow down card shimmer effect, spread delays to avoid simultaneous triggers
  ([`3ed55d0`](https://github.com/thepixelabs/altergo/commit/3ed55d03f37cf9020ed9af3560041e1d83492d8c))

- Smooth gradient on greeting/goodbye messages, add picker search
  ([`acf8d71`](https://github.com/thepixelabs/altergo/commit/acf8d71d87895912734ec3d08ca06af2465d194b))

- Replace chunked two-color fade with per-character interpolated gradient on greeting text, goodbye
  messages, and onboarding logo - Goodbye messages now show emoji + purple-blue-cyan-green gradient
  instead of dim text with "altergo" prefix - Add vim-style / search to the resume session picker
  with live filtering

- Suppress noisy output when applying settings on quit
  ([`5409267`](https://github.com/thepixelabs/altergo/commit/540926713d0879a33fe05de50806ef9c94db2246))

- Sync .claude.json across accounts via symlink_home_files
  ([`27a82fe`](https://github.com/thepixelabs/altergo/commit/27a82fe2237fcd304357c8a750b31c931484e2cc))

- Use star spinner for launch animation across all themes
  ([`ff9c01c`](https://github.com/thepixelabs/altergo/commit/ff9c01c2b2b837e6c55f7fff34049a9cc9618c05))

- Wrap long line in home-change notice print
  ([`90f8e9c`](https://github.com/thepixelabs/altergo/commit/90f8e9c8f456f82d754b6bc88beae3f1c7cf24d4))

- **ci**: Repair release pipeline, homebrew-bump YAML, pip-audit, drop py3.9
  ([`a4354bd`](https://github.com/thepixelabs/altergo/commit/a4354bd28a99b2257db07a28765fc98284f26f6a))

- release.yml: pass GH_TOKEN as checkout token so credentials persist on the origin remote;
  semantic-release's plain 'git push' now auths - homebrew-bump.yml: replace heredocs with { echo; }
  blocks — heredoc terminators at col 0 broke the YAML run: | literal block scalar - ci.yml +
  pyproject.toml: drop Python 3.9 (EOL 2025-10); code uses PEP 604 'str | None' which is 3.10+ -
  security.yml: remove invalid pip-audit --require-hashes=false (--require-hashes is a boolean flag,
  no argument)

- **cli**: Validate arguments before launch and add launch messages
  ([`8d16eb6`](https://github.com/thepixelabs/altergo/commit/8d16eb6a2e6b828e533209c08602f83a58bd742a))

- **footer**: Clean up footer — remove duplicate license text, add ❤️ 👾, make License a proper link
  ([`af45f7a`](https://github.com/thepixelabs/altergo/commit/af45f7a2b4431db70d4f768a8174088ad1db1024))

Co-Authored-By: Claude Sonnet 4.6 <noreply@anthropic.com>

- **footer**: Purple heart, remove duplicate GitHub link, keep PolyForm Shield 1.0.0 License
  ([`09fc18d`](https://github.com/thepixelabs/altergo/commit/09fc18db3e154fa66bdd86c50d659b052507d448))

Co-Authored-By: Claude Sonnet 4.6 <noreply@anthropic.com>

- **landing**: Point Stay Connected Rover link to dispatch.pixelabs.net/rover
  ([#36](https://github.com/thepixelabs/altergo/pull/36),
  [`dd87606`](https://github.com/thepixelabs/altergo/commit/dd87606ea45170f495a0beed9fb15dcef3aa41be))

- **native**: Pass --yolo-resume through + add --default-provider
  ([#30](https://github.com/thepixelabs/altergo/pull/30),
  [`e4fa7f8`](https://github.com/thepixelabs/altergo/commit/e4fa7f8cdae2418d8c2c6fef9f686f278cf834b0))

* fix(native): pass --yolo-resume through to provider + add --default-provider

altergo native --yolo-resume was opening altergo's own session picker. Native sessions live in the
  real $HOME and the provider already has its own resume mechanism, so altergo now hands
  --yolo-resume [<id>] straight to launch_claude where _translate_yolo_flags renders the
  provider-native flags.

Native also now supports a persisted default provider, stored in SETTINGS_FILE (native has no
  per-account account.json by design):

altergo native --default-provider gemini

launch_claude reads the pin first; if its binary is on PATH it wins, otherwise it falls back to the
  existing dot-dir + binary auto-detect so a stale pin never blocks launch.

* feat(native): pick default provider from --config TUI

Pressing Enter on the native row in the --config picker now opens the provider picker (cancellable
  via q/Esc) and persists the choice via save_native_default_provider. The 'd' key still sets native
  as the default account, so both affordances coexist:

Enter = pick default provider d = set as default account

_prompt_provider_picker grew an opt-in allow_cancel=True kwarg so the native flow can distinguish
  'cancel' from 'kept current'; the existing managed-account caller is unchanged.

* ci(security): suppress pip-audit CVE-2026-3219 (no fix available)

pip-audit started failing 2026-04-25 on a newly-published CVE against pip 26.0.1 itself, with no fix
  version listed. pip is the runner-shipped toolchain, not a dependency altergo bundles or installs
  at runtime — and altergo has no runtime deps at all. Suppress the advisory with a comment pointing
  to revisit once an upstream fix lands.

- **tmux**: Avoid session name collisions by appending -N suffix
  ([`ca9f070`](https://github.com/thepixelabs/altergo/commit/ca9f07006ff7b8a34287da6dc1b33464f5662620))

- **tmux**: Disable mouse capture so UI scroll works behind terminal
  ([`78fca30`](https://github.com/thepixelabs/altergo/commit/78fca307cfbe56b0115776a1efa47a65a32d273a))

- **ui**: Comprehensive mobile/tablet responsive fixes for landing page
  ([`70126c9`](https://github.com/thepixelabs/altergo/commit/70126c98d202f0428cb371da10c67629971f7629))

- Hero: reduced gap on narrow screens, terminal shrinks gracefully, buttons meet 44px touch target
  minimum - Nav: hamburger and theme toggle bumped to 44×44px, mobile overlay uses safe-area insets
  for notched iPhones - Why-cards: 3→2col at 900px, 2→1col at 580px (better tablet portrait) - Docs
  section: cmd-table disables nowrap below 500px so long commands wrap; code/path strings get
  overflow-wrap to prevent horizontal scroll - Install: reduced inner padding at 375px to avoid
  double-compound margins - Footer: stacks left-aligned below 600px, divider dots hidden - All
  sections: padding reduced at ≤500px for comfortable mobile spacing - Added safe-area-inset support
  for landscape iPhone/iPad notches

Co-Authored-By: Claude Sonnet 4.6 <noreply@anthropic.com>

- **yolo-resume**: Consume any non-flag token as session id; route explicit provider on native
  ([#34](https://github.com/thepixelabs/altergo/pull/34),
  [`c7e93da`](https://github.com/thepixelabs/altergo/commit/c7e93da95b0e5e3d6dc0c07d88d7fdf87292e299))

* fix(yolo-resume): consume any non-flag token after --yolo-resume as session id

Two related bugs surfaced when running the user's actual command shape:

altergo native claude --yolo-resume delete-persona-heartbeat-wrapper

1. _extract_yolo_resume only consumed the trailing token as a session id when it matched a strict
  UUID regex. claude (and other providers) accept named-session aliases like
  'delete-persona-heartbeat-wrapper' that aren't UUID-shaped, so the alias fell through and was
  forwarded to the provider as a chat prompt instead of a --resume target. Relax the rule: any token
  that doesn't start with '-' is the session id; the provider validates.

2. The native --yolo-resume shortcut consumed an explicit account but ignored a subsequent provider
  token, so 'claude' (the explicit provider) was passed to launch_claude as positional argv. Detect
  a leading provider token in _yr_rest and route it to launch_claude as provider= instead.

Also: native --yolo-resume no longer requires any managed accounts to exist (native is the
  passthrough account; the no-accounts check now runs only on the non-native fallthrough path).

Updated UUID-strict tests to reflect the new "any non-flag token" rule and added regression tests
  for the kebab-alias shape.

* style: ruff format

- **yolo-resume**: Defer to portal handler when 'portal' is in args
  ([#33](https://github.com/thepixelabs/altergo/pull/33),
  [`5579b11`](https://github.com/thepixelabs/altergo/commit/5579b11437902283e0c0cfbbfa7896b47c5f725d))

The global --yolo-resume interceptor at the top of main() doesn't know that 'portal' is a
  subcommand. For \`altergo portal native claude --yolo-resume\` it stripped the flag, opened
  altergo's session picker, then handed launch_claude args=['--resume', <id>,
  '--dangerously-skip-permissions', 'portal', 'native', 'claude'] — the leftover positionals ended
  up as provider argv junk after --resume.

Same shape for \`altergo native portal --yolo-resume\` (account-prefix form) and the *-with-id
  variants.

Bail out of the global interceptor when 'portal' or 'shell' appears in the args after extracting
  --yolo-resume — those subcommands have their own parsers that already forward --yolo-resume
  cleanly through launch_claude / _translate_yolo_flags.

- **yolo-resume**: Honor explicit account token
  ([#28](https://github.com/thepixelabs/altergo/pull/28),
  [`3e833c5`](https://github.com/thepixelabs/altergo/commit/3e833c5462c8b84fd6feaf376fbee737f7242a56))

`altergo <account> --yolo-resume <id>` was silently dropping the leading account token because the
  yolo-resume intercept runs before the normal account-parsing block. Native users hit an
  account-picker prompt that didn't even list 'native'. Parse a leading account from the residual
  args inside the yolo-resume handler, accepting 'native' or any existing account dir, and forward
  remaining tokens through to the launch.

### Documentation

- Add architecture and how-it-works reference pages (need v0.5.0 update)
  ([`1fe22d4`](https://github.com/thepixelabs/altergo/commit/1fe22d4380db7d2face2844d027e70fe3c2c352d))

- Add settings TUI guide, update architecture for v0.16
  ([`e5998c3`](https://github.com/thepixelabs/altergo/commit/e5998c3e7cb85eccfb69f1b5143da6852749c8fc))

- New docs/settings.md covering the three-page settings TUI - Update docs/architecture.md with
  current code structure, settings schema, and dependency list - Update version references from
  v0.5.0 to v0.16.0+

- Add version badge next to logo in nav
  ([`88b0c0d`](https://github.com/thepixelabs/altergo/commit/88b0c0dead08ef0e79642a3c07c6c19322158e87))

- Align tagline, document MCP sync, catch up to v0.37
  ([`b88c0fe`](https://github.com/thepixelabs/altergo/commit/b88c0fe87b0d77ccb1248ac5f6ba268e799f45e0))

Three-pass audit (tech-writer + CEO + CTO). Closes an ~18-release doc lag, documents the
  bidirectional MCP-sync model (previously invisible to users), aligns the tagline across all public
  surfaces, and adds a threat model to SECURITY.md.

Canonical tagline: "Don't break flow. Switch accounts." Applied to README, launch/*, brand/identity,
  pyproject.toml, altergo.py --help banner, Makefile, docs/index.html.

README / how-it-works / architecture: - Replace stale '--config --name <n>' with positional form -
  Remove removed subcommand '<name> use <provider>' (v0.22.0) - Add 'altergo native', '--rename',
  '--search', '<name> <provider>' - Complete symlinked-items list (adds tasks/, commands/, skills/)
  - New section: MCP servers, sync not symlink - New section: tmux session persistence - Provider
  matrix for Claude/Gemini/Codex/Copilot - Account-lifecycle walkthrough - ASCII diagram:
  real-isolated vs shared-inode vs merged

SECURITY.md: - Fix inaccurate 'no network connections' claim (PyPI update checker fetches once per
  24h) - Add threat model: shared settings.json hooks, shared CLAUDE.md prompt surface, MCP
  propagation, default-on cloud catalog - Document single-user multi-account trust assumption

migration.md: archive v0.5.0 auto-migration (removed v0.35.3), add v0.22.0 .claude.json
  silent-unsymlink note.

settings.md: remove '--update-check' CLI block (removed v0.35.3), add home-change-notice section,
  enumerate package-manager catalog.

- Apply CEO messaging feedback — credential sharing framing, migration output
  ([`ae570da`](https://github.com/thepixelabs/altergo/commit/ae570da063067e6cbd8f1c7423b2203b375293eb))

- Fix 4K ghost drift in persistent section, drop fixed page-wide ghost
  ([`e43b106`](https://github.com/thepixelabs/altergo/commit/e43b10607a2d471753adf0ffc8e01adf03734851))

Two independent landing-page fixes:

- #persistent > .container now position:relative so the ghost-wrap's right:-60px anchors to the
  1160px content column instead of the full-width section. On ultrawide/4K viewports the ghost was
  sliding all the way to the viewport's right edge, far from the copy.

- Removed the fixed, centered #ghost-bg-fixed layer that sat behind every section with low opacity.
  Per-section atmosphere (.orb, .persistent-ghost-wrap, data-rain, .gits-illustration) already
  carries the visual weight; the global fixed layer was just noise.

- Inject PyPI count at build time, float why-card icons, add favicon
  ([`d40ea2d`](https://github.com/thepixelabs/altergo/commit/d40ea2d2b797d37f5be264ab697e6afddc6f4df5))

Client-side fetches to pypistats/shields were hitting 429s from shared visitor IPs; moving the
  lookup into the Pages build runs it once per deploy (plus a daily scheduled refresh) and falls
  back to the committed value if upstream is down. Also reflows why-card icons with float +
  shape-outside so the title/body wrap around the badge instead of stacking under it, and caps the
  pypi-stat pill width so a long injected count can't blow out the header row.

- New altergo wordmark + README rewrite for v0.5.0
  ([`5bc6fc1`](https://github.com/thepixelabs/altergo/commit/5bc6fc155b6e01ba066176fc445935dd61a08080))

Add docs/logo-dark.svg and docs/logo-light.svg with the cyan-blade wordmark (alt+r indigo, e+go
  contrast, glowing skewed blade between t and e). Reference them via <picture> at the top of
  README.md for light/dark adaptation.

Rewrite README to match the landing page (v0.5.0): pipx and safer curl install, named-account-first
  quick start, full command table, --settings TUI explanation, complete symlink list, macOS Keychain
  note, CD badge beside CI.

Co-Authored-By: Claude Opus 4.6 (1M context) <noreply@anthropic.com>

- Overhaul for v0.40.0 — multi-provider, recall across 4 providers, cwd-on-recall, bookmark rebind
  ([`50e3279`](https://github.com/thepixelabs/altergo/commit/50e32790d3749f18a9050823d11567f5764b9298))

- README: new picker keybindings table (b bookmark, * starred-only); multi-provider recall section;
  add-provider quickstart line; cwd-on-recall mention in features table - architecture.md: corrected
  line count, v3 schema field table, disk-write trigger bullets, per-provider session-format table -
  how-it-works.md: four-provider problem statement; AddProvider reconciliation section citing
  _reconcile_orphan_dot_dir; exact nav-footer string; provider filter + starred filter composition -
  migration.md: v0.40.0 section expanded with cwd-on-recall entry and b/* rebind before/after -
  settings.md: cross-link to picker keybindings in how-it-works

- Reframe landing copy so account-name examples don't read as subcommands
  ([`5c75c8e`](https://github.com/thepixelabs/altergo/commit/5c75c8e5b3247986ee4b1213055a73a8d7e2b7dc))

Renaming the placeholder from 'backup' to 'secondary' wasn't enough — any single word after
  'altergo' parses as a subcommand to a first-time reader. Hero now describes the outcome without
  showing a command. Step 3 and the docs notes use an explicit <account> placeholder. Feature card
  drops the inline example and frames it as 'the name you chose'. Install block pairs 'work' + 'pro'
  so both names obviously look like user-picked labels. Reference table uses frame-then-example
  wording. Reduced-motion fallback matches the animated scene convention.

- Remove zero-deps/single-file messaging, add keychain-isolation guide
  ([`aa0597b`](https://github.com/thepixelabs/altergo/commit/aa0597bd30cc8d6e19a806fe0521ad55cf2e14a4))

- Rename 'backup' placeholder account to 'secondary' in examples
  ([`539c626`](https://github.com/thepixelabs/altergo/commit/539c6268eae4fd436e3a15fbd35aaf3075aa3dfc))

The landing page used 'backup' as the example account name throughout (hero, step 3, feature card,
  install block, reference table, static fallback). With altergo being a credentials-management
  tool, 'altergo backup' reads like a subcommand verb instead of 'launch the account called backup'.
  Renamed to 'secondary' everywhere — clearly a noun, unambiguously an account identifier.

- Rename <name> placeholder to <account> in help and docs
  ([`c01d1fd`](https://github.com/thepixelabs/altergo/commit/c01d1fd67fa837d89253e9f5fbd8ad10f75a245b))

The <name> placeholder in the help menu and documentation was ambiguous ("name of what?"); <account>
  is self-describing. Also rename <name> to <theme> in --theme usage for the same reason.

- Unify why-card layout, swap cross-platform for keychain card, strip em-dashes
  ([`653e564`](https://github.com/thepixelabs/altergo/commit/653e5643926a203b4c6a8c6ae2ac41c0133c2963))

why-card icons now use the same plain float+margin mechanic as feature-icon instead of the
  shape-outside / display:inline / ::after nbsp / clearfix stack that was there. Cross-platform card
  replaced with a keychain-isolated credentials card, since the landing page had no mention of the
  per-account keychain feature. Also replaced every em-dash in the file with commas, colons, or
  periods depending on context, and cleaned up the comma splices the bulk pass introduced.

- Update all docs for v0.5.0 N-account support
  ([`f58ac41`](https://github.com/thepixelabs/altergo/commit/f58ac41da6573286dfe9d442629ab5437b747ab4))

- Update for v0.5.0 settings TUI and credential sharing
  ([`52f419b`](https://github.com/thepixelabs/altergo/commit/52f419b23ef53f46ccecf3d2c1b43a404d25cee4))

- Add --settings command to command reference and features section - Document per-tool credential
  sharing (catalog, default-on/off categories) - Reframe altergo shell and altergo -- as power-user
  escape hatches - Document ~/.altergo/.altergo.json settings persistence path - Update migration
  guide

Co-Authored-By: Claude Sonnet 4.6 <noreply@anthropic.com>

- Update README for v0.5.0 N-account support
  ([`879615a`](https://github.com/thepixelabs/altergo/commit/879615abd462a3e9b017889aedc7ad2bfeb0a9de))

- Update tagline to 'Switch Claude identities. Keep your context.'
  ([`8d811d3`](https://github.com/thepixelabs/altergo/commit/8d811d30be4bde7f1cdd92d0e7a2f1fa1bb9318e))

- **keychain**: Lead with meaning, document UX surfaces, reframe ceiling
  ([#27](https://github.com/thepixelabs/altergo/pull/27),
  [`60e8096`](https://github.com/thepixelabs/altergo/commit/60e80965ebac32b9e260ead228031bf30d2ffa46))

Clarity pass on the keychain isolation docs (README section + docs/keychain-isolation.md). Triggered
  by a review loop — the original docs were technically correct but opened with implementation
  detail (login.keychain-db, DLDBSearchList, com.altergo.account-unlock) before helping a reader
  understand the two modes or decide which to pick.

Changes: - Open with plain-English framing of system vs isolated; add a minimal "which should I
  pick?" prose block (not a callout — the decision is asymmetric and a box primes second-guessing).
  - Document the UX surfaces: the interactive picker's "keychain: isolated" row suffix and the
  "Current keychain:" line at the top of --config. - Clarify that enabling isolation on an existing
  account starts with an empty keychain (one re-auth needed). - State the interactive "y" prompt is
  equivalent to --keychain isolated. - Reorder the Re-upgrade block to lead with the outcome (prior
  tokens immediately accessible) before the mechanism. - Reframe "use separate macOS user accounts"
  from a permanent ceiling to today's path — no roadmap commitment, but leaves room for future
  stronger isolation (e.g. SE-wrap) without creating retroactive credibility problems. - Remove a
  third redundant mention of the same escape hatch that read apologetic. - Bump "Applies to" stamp
  to v0.41.0+ and add a v0.43.0 note for the preserve-and-reuse semantics change. - Fix dead
  cross-ref to SECURITY.md#keychain-isolation-macos-opt-in (that anchor doesn't exist) — point to
  in-doc §5 instead. - Correct three statements that didn't match the current code: the keychain key
  is always written (not absent in system mode); orphan handling now auto-rebuilds (not "warns and
  aborts"); §6 manual rm recovery step removed (reconciler handles it).

- **landing**: Re-pitch Stay Connected around Rover + altergo
  ([#35](https://github.com/thepixelabs/altergo/pull/35),
  [`03f6674`](https://github.com/thepixelabs/altergo/commit/03f6674a78f3ae941a6669de1518da837da8ac43))

Rework the persistent sessions section to feature Rover as the way you get back into a tmux-backed
  altergo session, replacing the old "type tmux attach" framing. Adds a cyan link to
  rover.pixelabs.net in the subtitle and swaps two of the four feature cards:

- "Detach and return" (Ctrl-b d, tmux attach -t) -> "Rover is already waiting" (auto-launches on SSH
  login) - "Named automatically" (tmux ls trivia) -> "Pick or start, no typing" (Enter / A / Y
  keymap)

"Survives disconnects" and "All providers" cards are kept. Layout, reveal classes, shimmer styles,
  and the persistent-ghost composition are unchanged. New SVG icons match the existing line-art
  style.

- **landing**: Tmux + stale-claim fixes, plus GA4 with GDPR consent
  ([#32](https://github.com/thepixelabs/altergo/pull/32),
  [`672ee73`](https://github.com/thepixelabs/altergo/commit/672ee736131992110a0ebaf9fe8ba22ab93e33ae))

* docs(landing): fix tmux 'always on' framing and several stale claims

- Persistent section: tmux is opt-in via --settings or one-shot via altergo portal, not "every
  altergo session". - tmux session name format is <account>/<provider>, not the imagined
  altergo-<account>-<provider>-<id>; demo terminal scene updated to match. - Replace "Silent
  Auto-migration" feature card (described the v0.4.x → v0.5.0 path that was removed in v0.35.3) with
  an accurate "Quiet upgrades" card covering today's silent schema + keychain coercions. - Commands
  table: --recall is the cross-account picker; --resume passes through to the provider's native
  resume UI (or resumes by id). - "Three commands to go" step 3: same fix — --recall, not --resume.

* docs(landing): add Google Analytics (GA4) with GDPR consent banner and privacy modal

- Inject gtag.js with Consent Mode v2 defaulted to denied for all storage signals -
  Bottom-of-viewport consent banner (Accept/Decline) themed for dark/light - Persist choice in
  localStorage (altergo_consent_v1); no banner flash on return visits - Privacy modal triggered from
  banner Learn more and footer Privacy link, with inline manage cookie preferences button that
  re-opens the banner - Modal is fully responsive (mobile-friendly padding, scroll, max-height) and
  dismissible via X, backdrop click, or ESC

### Features

- Accept session ID with --yolo-resume ([#18](https://github.com/thepixelabs/altergo/pull/18),
  [`a10d6e1`](https://github.com/thepixelabs/altergo/commit/a10d6e1092fe0b486b1ee5482e6052d89f1624fb))

Previously `altergo --yolo-resume <uuid>` silently passed the UUID through as a positional arg, so
  providers received it as the first user prompt of the resumed session instead of using it to pick
  a specific session.

Now --yolo-resume accepts an optional session ID in either form: --yolo-resume=<ID> --yolo-resume
  <ID> (only if the following token is UUID-shaped)

When an ID is provided, it is substituted into each provider's resume_by_id template:
  claude/gemini/copilot use `--resume <ID>`, codex uses the `resume <ID>` subcommand. With no ID the
  flag continues to resume the most recent session. A non-UUID trailing token is left alone so
  prompts passed on the command line still work.

- Add --yolo/--yolo-resume flags and rename --list to --recall
  ([`1c155b0`](https://github.com/thepixelabs/altergo/commit/1c155b0f66e683ed6b2cf0b4ea8303c1af12868b))

- --yolo translates to provider-native skip-permissions flag (claude:
  --dangerously-skip-permissions, gemini/copilot: --yolo, codex:
  --dangerously-bypass-approvals-and-sandbox). - --yolo-resume additionally resumes the last session
  per provider (codex uses the `resume --last` subcommand form). - --recall opens the cross-account
  session picker; bare --resume now passes through to the provider's own native resume UI. - Picker
  gets a theme hotkey (t), separator row, and recall-session title; animated nav footer removed. -
  Tests cover flag translation per provider and updated smoke suite.

- Add color themes with live launcher cycle
  ([`febbdb5`](https://github.com/thepixelabs/altergo/commit/febbdb57b651c23a8a3f134dc7bbfacd69820e35))

Introduces a THEMES catalog (ocean, forest, lavender, sunset, mono, rainbow) that drives every
  colored surface: help, list, settings, session picker, launcher, banner, and shell prompt. Themes
  persist in .altergo.json, can be cycled live in the launcher with 't', set via 'altergo --theme
  <name>', and route through a runtime C(role) lookup instead of hardcoded constants.

Also shows the altergo banner on --list, --setup, --settings and --theme so the logo is present
  across every top-level screen, and drops the redundant 'account: <name>' prefix line now that the
  banner shows the active account directly under the logo.

- Add shell + passthrough commands, custom SVG icons, docs section
  ([`ef7abb1`](https://github.com/thepixelabs/altergo/commit/ef7abb1b9d98c8ed8cb976e9c86210a0a2a0c90e))

- altergo shell: opens an interactive $SHELL with HOME=~/.altergo so users can run gh auth login,
  git config, ssh-keygen, etc. in the alt account context; credentials persist across sessions -
  altergo -- <cmd> [args...]: runs any single command in alt HOME context without entering an
  interactive shell - landing page: replace all emoji icons with custom inline SVG icons for both
  why-cards (3) and feature-items (6); visually on-brand - landing page: add full Documentation
  section with command reference table, credentials/Keychain explanation, symlink map, compatibility
  note, and disclaimer link - README: document new commands with usage examples

Co-Authored-By: Claude Sonnet 4.6 <noreply@anthropic.com>

- Add tmux session persistence section to landing page
  ([`ce847e2`](https://github.com/thepixelabs/altergo/commit/ce847e20eeff021be4209a2c51ef53cb8b935165))

- Bidirectional mcpServers sync across accounts, preserves per-account oauthAccount
  ([`0bf4cff`](https://github.com/thepixelabs/altergo/commit/0bf4cff9d7bef641ac51569cd71a8d76c1fb4bd3))

- Colored --help with OSC 8 links, pixelabs branding, bump pyproject to v0.5.0
  ([`c1f9666`](https://github.com/thepixelabs/altergo/commit/c1f966645f49d45a1701f81a47c423a06c44e185))

- Replace print(__doc__) with show_help() — colored output via existing _c() helper, clickable OSC 8
  hyperlinks to pixelabs.net and claude.ai/code - Attribution footer: non-affiliation disclaimer +
  Claude trademark notice - Bump pyproject.toml version to 0.5.0 to match altergo.py

- Colored CLI output, clickable pixelabs.net link, fix docs
  ([`965832c`](https://github.com/thepixelabs/altergo/commit/965832cf92b9a5d414245a3fd39f3b6f7e29d72d))

- ANSI colors in --setup, --teardown, --list (TTY-only, pipes unaffected) - OSC 8 clickable
  hyperlink to pixelabs.net in setup/teardown header - Fix README and migration.md: remove 'altergo
  new', correct picker usage - Green ✓ for success, yellow ⚠ for warnings, cyan for headers

- Expand greetings bank + banner above the launcher
  ([#17](https://github.com/thepixelabs/altergo/pull/17),
  [`3dabf0a`](https://github.com/thepixelabs/altergo/commit/3dabf0aff40bfe79e0c6cef3197fa5908a691d5a))

- Grow greetings bank 80 → 400 (10 → 50 per window across 8 time windows); update the panel-lock
  test accordingly. - interactive_launcher() now calls show_banner() at the top of each loop
  iteration so the picker is framed by the themed figlet, matching interactive_settings().

- Full-text conversation search with project filtering and quoted phrases
  ([`33622ef`](https://github.com/thepixelabs/altergo/commit/33622ef87549b4b99a90ecb77b97e1221cebc399))

- Add `altergo --search` for searching across all session conversation history - Three-phase TUI:
  project filter → search input → scrollable results - Case-insensitive matching, "quoted phrases"
  for exact matches, AND logic - Results sorted newest-to-oldest with snippet previews and role
  indicators - Animated progress bar with braille spinner during scanning - Add `/` search hint to
  help text navigation section

- Initial release of altergo v0.1.0
  ([`6c8fad9`](https://github.com/thepixelabs/altergo/commit/6c8fad9504392a6801e9e6087bfdff0c314c57f5))

Your other Claude — switch Claude Code identities without losing a thought. Zero dependencies,
  interactive TUI, symlink-based session sharing.

- Interactive provider picker and default-provider resolution
  ([`105f273`](https://github.com/thepixelabs/altergo/commit/105f2739e2ae64fc98c58bbb02747993d5274b05))

Replace the numbered-checkbox provider prompt with a curses-based arrow/ radio picker (Space
  toggles, d sets default, Enter/s saves). Persist the chosen default in account.json via a new
  default_provider field with back-fill for pre-existing accounts. launch_claude now resolves the
  default provider from meta so altergo <account> and bare altergo (with an active account) both
  launch directly without requiring an explicit provider argument. Style the first-run onboarding
  copy with theme accent colors and add a short Rich spinner beat so it no longer renders as plain
  white text.

- Multi-page settings TUI with live theme preview
  ([`355ce3a`](https://github.com/thepixelabs/altergo/commit/355ce3acf971b2f25970e692bcf7cd08ffc8769c))

Replace the single-page credentials settings screen with a three-page TUI accessed via altergo
  --settings:

- Appearance: theme picker with live color preview, gradient swatches, and launch animation toggle -
  Behavior: toggles for greeting messages, goodbye messages, and update checker - Credentials:
  shared CLI credentials (upgraded visual style)

Navigation via arrow keys, h/l, Tab between pages. Themes auto-select on cursor movement with
  instant color recoloring. All settings saved in a single atomic write to .altergo.json.

- Multi-provider altergo accounts ([#23](https://github.com/thepixelabs/altergo/pull/23),
  [`b1c2a1d`](https://github.com/thepixelabs/altergo/commit/b1c2a1dd20d4259e4d3a519de2aa092e7a712b00))

* fix: launch resumed sessions in the session's saved cwd

Thread an optional cwd parameter through launch_claude and _build_tmux_cmd so --recall and --search
  resume the provider CLI in the directory where the session originally ran. Invalid/missing paths
  fall back to None with a dim notice rather than aborting.

* feat: scan Gemini, Codex, and Copilot sessions in --recall

Adds per-provider session discoverers (_discover_codex_sessions, _discover_gemini_sessions,
  _discover_copilot_sessions) alongside the existing Claude discoverer, unified under
  get_sessions(). Each discoverer yields fully-populated session dicts (id, project, cwd, modified,
  size_mb, path, topic, provider, starred). Per-provider head scanners extract topic and cwd from
  each format. load_session_preview now dispatches by provider so the preview pane works for all
  four. format_project_name passes plain labels through without dash-decoding. Includes 20 new unit
  tests covering all providers, edge cases (sentinel skip, string content, fallback paths), and the
  preview dispatch.

* feat: add starred-only filter and rebind star toggle to b

Press * in the recall picker to toggle a starred-only view (orthogonal to provider filter and
  search). Press b to bookmark/unbookmark the highlighted session. Title bar, status bar, and nav
  footer all reflect the new state. _apply_resume_view gains a starred_only parameter.

* feat: multi-provider altergo accounts

Let one altergo account declare multiple providers (Claude Code, Gemini CLI, Codex, Copilot) instead
  of being pinned to one. account.json schema bumps to v3:

{"version": 3, "providers": ["claude", "codex"], "default_provider": "claude"}

v2 files (`{"provider": "claude"}`) load forever without being rewritten — disk flips to v3 only
  when the user mutates the account via one of the new commands.

New CLI: altergo <name> --add-provider <id> altergo <name> --remove-provider <id> [--yes] altergo
  <name> --default-provider <id>

--add-provider reconciles any account-local orphan data for that provider (from pre-multi-provider
  era shells that wrote under the account's isolated .codex/.gemini/.copilot) by merging it into
  MAIN_HOME. MAIN wins on collision; losers preserved under <dot_dir>.orphaned/<timestamp>/ —
  nothing silently destroyed.

Launcher renders a multi-provider account under each of its providers; picking a chip launches with
  that provider explicitly. launch_claude gains a membership guard that refuses explicit `--provider
  X` for an account that does not host X (with a remediation hint).

No UX regression for existing single-provider accounts — opt-in and additive.

- Multi-provider rebrand, messaging cleanup, site polish
  ([`cd0f874`](https://github.com/thepixelabs/altergo/commit/cd0f8746554d769b35d6160fe3abe3b7269927a4))

- Reposition from Claude-only to multi-provider (Claude Code, Gemini CLI, Codex, Copilot) - New
  tagline: 'Switch AI identities. Keep your context.' - Replace work/personal account examples with
  mine/acme/clientco (accounts separate logins, not conversations) - Remove misleading 'mixing work
  and personal sessions' framing from README - Add local-first messaging: conversations saved by AI
  tool, altergo makes them searchable/resumable - Expand DISCLAIMER to cover all 4 providers with
  trademark acknowledgments - Reduce section padding 80px -> 56px on landing page - Fix code block
  overflow wrapping for curl install command - Simplify Credentials & Auth docs card - Trim command
  reference to highest-value commands - Fix link colors in Compatibility card to use site cyan - Add
  multi-provider command examples to reference table - Update pyproject.toml description and
  keywords for all providers

- N-account support — named accounts, auto-migration, --setup --name
  ([`33d5705`](https://github.com/thepixelabs/altergo/commit/33d5705a7c4d0cdfe06e7c7ed2afdee91ca143b9))

- ACCOUNTS_DIR layout: ~/.altergo/accounts/<name>/ replaces single ~/.altergo/ - resolve_account(),
  validate_account_name(), list_accounts() helpers - Auto-migration: detects legacy
  ~/.altergo/.claude/ layout, renames to accounts/default/ on first run, preserves backup at
  ~/.altergo/.legacy-backup/ - _looks_like_account() disambiguates account names from claude
  pass-through args - altergo <name> routes to named account; unknown name prints actionable error -
  --setup --name <name> and --teardown --name <name> support - All launchers and
  do_setup/do_teardown parameterized over account name - SYMLINK_HOME_DIRS credential symlinks
  created at account_home level - show_help() updated with named account examples

- One account one provider — remove multi-provider bundling (v0.22.0)
  ([`8778e11`](https://github.com/thepixelabs/altergo/commit/8778e11850f40596d5f59765657a62f5616ef910))

- Strip providers list from account.json; each account now has exactly one provider - Replace
  multi-select provider TUI with single-select picker - Remove 'use' subcommand (replaced with clear
  error pointing to --config) - v2 account.json schema: {"version": 2, "provider": "<id>"} -
  Auto-upgrade legacy accounts (no account.json) on first launch - Per-provider sweep in
  _sweep_existing_accounts using v2 single-provider metadata - Restore _sync_claude_mcps for
  bidirectional MCP server sync (from 0bf4cff) - Version bump to 0.22.0

- Opt-out version checker, hourly greetings, launch-handoff spinners
  ([`d2fc5c2`](https://github.com/thepixelabs/altergo/commit/d2fc5c2af2ec15dfe645d2740e0aaa0fd66b2a0b))

Adds three features designed as a panel (CEO, product, system-architect, security, creative) and
  implemented in a single pass:

Version checker (opt-out, consent on first launch): - Daemon-threaded PyPI fetch with 3s timeout,
  32KB response cap, and 3-redirect cap. Stdlib urllib only — no new runtime deps. -
  Stale-while-revalidate cache at ~/.altergo/version_check.json with 24h TTL, schema versioning, and
  chmod 0600. - Version string double-sanitized (fetch + render) against strict allowlist to block
  ANSI-injection from crafted PyPI responses or a poisoned cache file. - Inline nag in the banner
  version column: v0.13.0 → v0.14.0 in the theme warn color, plus a dim "upgrade: pip install -U
  altergo" line. - altergo --update-check [on|off] toggles persistently. One-time consent notice on
  first launch satisfies security-engineer's GDPR concerns about the opt-out default.

Time-of-day greetings (altergo_greetings.py): - 80 witty lines across 8 three-hour windows, seeded
  per-minute so a quick relaunch is stable. Lazy-imported inside launch paths only so --help /
  --version never pay the cost. - Day-of-week nature icon rotation (🌊🌿⛰️🌳🔥🌄🌑) with ASCII fallback
  for non-UTF-8 terminals. - Rendered only on launch paths (launch_claude / launch_shell /
  interactive_launcher), never on --help / --list / --version so scripted/piped output stays
  grep-able.

Launch-handoff spinners (reusing Rich built-ins): - Account-line stars animate via
  rich.spinner.Spinner inside Live for a capped 0.7s before subprocess.run, per-theme (ocean→dots,
  forest→arc, rainbow→aesthetic, etc). Skipped for codex (too fast). - _status_wrap helper wraps the
  slow get_sessions scan (~1.7s), do_setup symlink creation, and the --settings apply loop with a
  themed Rich status line.

Also drops the redundant hardcoded curses palette in _picker_attrs — previous commit already routed
  colors through THEMES but the new code reads theme-agnostic helpers consistently.

72 tests pass (18 new): version parser/comparator, sanitizer boundary cases, cache roundtrip and
  schema guard, settings persistence, greeting bank counts and length caps, window tiling,
  per-minute stability, and theme→spinner coverage.

- Per-message emoji, gradient greetings, left-aligned banner, first-run onboarding
  ([`394f0ba`](https://github.com/thepixelabs/altergo/commit/394f0ba9004a9cda4f8d6a3dc7482cc1a42ed728))

- Per-provider sweep in _sweep_existing_accounts, fix --provider help text
  ([`accae07`](https://github.com/thepixelabs/altergo/commit/accae0760153c5aea36ea731fd8781ba12133b2a))

- Pivot landing page to flow-continuity hooks
  ([`cd50e07`](https://github.com/thepixelabs/altergo/commit/cd50e070154307af56f453d9edce7249a7ca2d08))

Lead with rate-limit continuity as the #1 scenario hook — the moment you hit a wall mid-session and
  need to keep going without losing context. Add thinker/executor and client isolation as secondary
  scenarios.

- docs/index.html: new hero headline, new #when section with 3 scenario cards, updated #why heading,
  updated meta description, new nav link - README.md: new tagline, why section, before/after table
  leading with the rate-limit moment - docs/launch/positioning.md: full rewrite with ranked
  scenarios and tone rules (never say cheaper/bypass — frame as flow continuity) -
  docs/how-it-works.md: expand problem statement with new scenarios

Co-Authored-By: Claude Sonnet 4.6 <noreply@anthropic.com>

- Positional provider syntax, gradient help titles, theme-aware goodbye
  ([`0babe77`](https://github.com/thepixelabs/altergo/commit/0babe77505b4aaf3369f798494905d61533c3953))

- Replace `altergo <account> --provider <name>` with positional `altergo <account> <provider>` for
  simpler launch-time provider selection - Add _gradient_ansi() helper for True Color per-character
  gradients in non-curses output (reuses theme banner stops) - Rewrite show_help() with gradient
  section titles driven by active theme, simplified structure (5 sections, removed redundant
  Examples block) - Remove hardcoded _GOODBYE_GRADIENT; goodbye message now uses active theme's
  banner gradient like the greeting

- Provider filter+sort in --resume, per-page gradient nav
  ([`8158649`](https://github.com/thepixelabs/altergo/commit/8158649478bcb02b03c28b631959610fc7bd3adf))

Feature 1 — resume TUI: - `get_sessions()` now tags each session dict with a `provider` field by
  scanning ACCOUNTS_DIR accounts via `_build_provider_map()`, which resolves each account's provider
  dot-dir/projects/ tree to match JSONL files. Sessions not attributable to any alt-provider account
  fall back to "claude". - New `_apply_resume_view()` helper applies provider filter → search → sort
  in one pass, keeping all filter/sort logic out of the draw loop. - `_draw_picker()` gains: f key —
  cycle provider filter (all → claude → gemini → codex → copilot → all) s key — cycle sort mode
  (time → project → provider) g key — toggle group mode (inserts divider lines between
  project+provider groups) status bar on row 1 showing active filter/sort/group + key hints provider
  tag appended to the project column in each session row

Feature 2 — per-page gradient nav tint: - Added `_PAGE_TINTS` dict mapping page names to gradient
  t-offsets (0.0–1.0). - `_picker_attrs(page="default")` now accepts a page parameter and, on
  256-color terminals, picks a point on the theme's banner gradient for `nav_base`, giving each
  page's nav sweep a distinct shade. - All `_picker_attrs()` call sites updated with their page
  name: resume, settings, launcher, search, onboarding.

Co-Authored-By: Claude Sonnet 4.6 <noreply@anthropic.com>

- Random theme rotation, settings UX polish
  ([`5152869`](https://github.com/thepixelabs/altergo/commit/51528693fb56dda84c002ef077c1267f3373df42))

- Add random theme toggle with frequency slider (often↔rarely) to Appearance settings page — rotates
  theme automatically every N sessions - Fix theme auto-select: cursor movement now updates
  selection marker (◆) so save always reflects what the user sees - Consolidate 6 redundant
  load/save helpers into generic _load_bool_setting - Single atomic write in interactive_settings
  instead of 5+ separate saves - Gradient accent fade on settings separator line - Expanded footer
  nav hints with vim keybindings

- Rich-pyfiglet banner, redesigned help/TUI, provider launcher, goodbye messages
  ([`5b97389`](https://github.com/thepixelabs/altergo/commit/5b97389dd6dd00b729c1d5ed888aae56f595789b))

- Add show_banner() with smslant font gradient (#00d7ff→#005fd7) via rich-pyfiglet - Standardize
  color tokens (_C_COMMAND, _C_ARG, _C_HEADER, _C_DIM, etc.) - Rewrite show_help() with new palette,
  section separators, and split arg coloring - Add 15-message _GOODBYE pool printed before every
  os.execvpe() handoff - Add interactive provider+account launcher TUI (_draw_launcher,
  build_launcher_menu) shown automatically when no args given and 2+ accounts exist - Resume picker:
  size column (7-char, amber warning >10MB), (no prompt) dim fallback - Add size_warn color pair
  (amber 220) to _picker_attrs

- Settings TUI for configuring shared CLI credentials
  ([`8efb55c`](https://github.com/thepixelabs/altergo/commit/8efb55c7acb8950ee55fa40c7efa058d04854e39))

Add interactive --settings screen (curses, arrow keys + space to toggle) organised by category:
  Cloud Providers, Containers, Infrastructure, VCS, Package Managers, and Identity. Settings persist
  to ~/.altergo/.altergo.json as a minimal overlay (only non-default values written). Applying
  settings diffs current symlink state and creates or removes symlinks idempotently.

Catalog covers AWS, gcloud, Azure, Docker, Kubernetes, Terraform, GitHub CLI, GitLab CLI, npm, SSH
  keys, git identity, and GPG keys. Identity entries are off by default with in-TUI warnings.
  Cloud/container entries are on by default.

Also: - Migrate from hardcoded SYMLINK_HOME_DIRS to the catalog in setup/teardown - Auto-migrate
  wholesale ~/.config symlink to per-tool managed dir on first run - Fix shutil.which guard in
  launch_command (same fix as launch_claude)

Co-Authored-By: Claude Sonnet 4.6 <noreply@anthropic.com>

- Show account email in banner, add package manager catalog entries, home change notice
  ([`b6d149f`](https://github.com/thepixelabs/altergo/commit/b6d149fe46d8bdbf0ff4da16d8784ec6474fbf58))

- Display email address next to account name in the banner (reads from .claude.json, Codex JWT, or
  Gemini oauth_creds) - Add pip, cargo, gem, yarn, pnpm, composer, go modules, Maven, Gradle,
  Bundler to CATALOG - Add one-time animated home isolation notice (home_change_notice_if_needed)
  shown on first launch

- Show altergo logo with account name above each launch
  ([`f4c4f60`](https://github.com/thepixelabs/altergo/commit/f4c4f60208293100a3372af30653757fd7bbf88b))

Render the gradient figlet banner before handing off to the provider CLI or account shell, with the
  active account name centered directly beneath the logo and framed by ASCII stars in the same blue
  palette. Makes the current identity visible at a glance on every session start.

- Show short version tag to the right of the banner logo
  ([`d09b028`](https://github.com/thepixelabs/altergo/commit/d09b028d366ce4684d20dde58f55c1aa9bad746d))

Renders v<version> vertically centered against the figlet block, in the theme's mid gradient stop so
  it reads as part of the logo. Pinned to the logo's natural width so it hugs the figlet rather than
  drifting to the terminal's right edge.

- Tmux session persistence for SSH workflows ([#11](https://github.com/thepixelabs/altergo/pull/11),
  [`37bbc80`](https://github.com/thepixelabs/altergo/commit/37bbc8086fd14f0bab45e3fc7ffe8eecb02d68f9))

* feat: tmux session persistence for SSH workflows

Add a tmux_session setting (default off) that wraps every provider session in a named tmux window.
  Sessions survive SSH disconnects and can be reattached with tmux attach -t <name>. Detects $TMUX
  to avoid nesting; falls back gracefully with a brew install hint if tmux is absent.

- _tmux_available(), _tmux_session_name(), _build_tmux_cmd() helpers - launch_claude, launch_shell,
  launch_command all honour the setting - Behavior page in settings TUI gains a tmux sessions toggle
  - docs/settings.md: new tmux persistence section + key reference - 9 new tests covering defaults,
  persistence, name format, cmd structure

* fix: ruff formatting

- Two-column help, looping launcher, share commands/skills
  ([#15](https://github.com/thepixelabs/altergo/pull/15),
  [`3dacca2`](https://github.com/thepixelabs/altergo/commit/3dacca29377869fa1ab33712095fb9687c931add))

- Redesign --help into a two-column layout with a shimmering divider, terminal-width aware (fallback
  to single column below 118 cols). - Launcher loops back to the menu after each session exits;
  launch_claude/launch_shell/launch_command now return the child exit code and callers own sys.exit.
  - Native chips appear for any provider whose binary is on PATH, no longer gated on a pre-existing
  dot-dir in MAIN_HOME. - Share commands/ and skills/ across accounts via symlink, matching agents/
  and plans/. - Tests updated to match the new native-chip and launch return-code contracts.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>

- Update landing page for v0.5.0 N-account support
  ([`3484c88`](https://github.com/thepixelabs/altergo/commit/3484c88eada95e478c3c846852e36a08cd1d239f))

- Update landing page for v0.5.0 N-account support
  ([`466d1d2`](https://github.com/thepixelabs/altergo/commit/466d1d2863440253e8fcff28b6dd7d8d16d1c083))

- V0.9.0 — active account pointer, wire launcher, restructure help
  ([`d0d428f`](https://github.com/thepixelabs/altergo/commit/d0d428ffbcfe3f1c228bcf3f57d82a067f45e039))

- Add --use <name> to persist active account in ~/.altergo/.altergo.json - Bare altergo now
  resolves: explicit arg → active_account → single account → launcher → error - Wire
  interactive_launcher() as default entry when multiple accounts exist - Add 'd' key in launcher to
  set active account with confirmation flash - Show active account indicator in launcher header -
  --resume respects active_account when multiple accounts exist - Restructure --help into Quick
  Start / Account Management / Session / Advanced / Examples / Navigation - Fix save_settings() to
  merge-write (preserves active_account alongside shared credentials) - Remove 'default' from
  reserved names — no longer special-cased - _prompt_account_name() no longer defaults to the string
  'default'

- **account**: Add native passthrough account that launches with real $HOME
  ([`6381e87`](https://github.com/thepixelabs/altergo/commit/6381e87cb1a8e328b12559d9f8a79d6cc990a03a))

* feat(account): add native passthrough account that launches with real \$HOME

Introduces the reserved account name 'native' as a zero-isolation launch path. Running 'altergo
  native' (or 'altergo native <provider>') launches the provider using the real \$HOME without any
  directory change, symlinks, or altergo-managed dot-dirs.

Key behaviours: - resolve_account('native') returns (MAIN_HOME, MAIN_CLAUDE) -
  _build_alt_env('native') returns os.environ.copy() unchanged - Provider is auto-detected from
  binary + dot-dir presence in MAIN_HOME - 'altergo portal native' works correctly in tmux mode -
  HOME-change notice is suppressed (no HOME change is happening) - _sync_claude_mcps skipped
  (account_home == MAIN_HOME, self-merge) - do_config/do_teardown reject 'native' with a clear error
  - Launcher injects a native chip for each provider whose binary and dot-dir exist in MAIN_HOME -
  Help menu documents 'altergo native' and 'altergo native <provider>' - 19 new tests; 127 total
  passing

* fix(lint): remove spurious f-prefix from shell native banner string

* fix(lint): apply ruff format

- **cli**: Add --rename command and make account name positional in --config
  ([`cf883a9`](https://github.com/thepixelabs/altergo/commit/cf883a97687c90df07e54d9d07c7ddb97ae081c6))

* feat(cli): add --rename command and make account name positional in --config

- `altergo --config <name>` replaces `altergo --config --name <name>` - New `altergo --rename <old>
  <new>` command renames an account directory - All help text, hints, and error messages updated to
  use new syntax

* test: update tmux session name and --config syntax assertions

- **docs**: Add ghost_duality image and update landing page
  ([`8fde66c`](https://github.com/thepixelabs/altergo/commit/8fde66c31d59c028b48c45206b88d965bde8adfb))

- **docs**: Ghost in the Shell landing page redesign
  ([`bce239b`](https://github.com/thepixelabs/altergo/commit/bce239b76008892a9d067dab9bb7d25a8cd424d8))

Complete visual overhaul of docs/index.html with GITS anime aesthetic: - Dark navy/cyan/indigo
  palette with neural mesh canvas background - AI-generated GITS-style scene images for hero,
  sections, and ghost character - Animated terminal mockup cycling 6 diverse altergo workflow scenes
  - Light/dark/system theme toggle with full light-mode blue slate palette - GITS-styled mobile
  hamburger drawer with numbered links and theme switcher - Hero parallax, data-rain overlay,
  floating ghost circle with glow animations - Transparent feature cards, full-bleed section
  backgrounds, radial mask fades

- **keychain**: Flip default to isolated (blocking) + rename old isolated → dedicated
  ([#29](https://github.com/thepixelabs/altergo/pull/29),
  [`e4cbe84`](https://github.com/thepixelabs/altergo/commit/e4cbe84f13974e0dd06596e295467ac820900af5))

* feat(keychain): flip default to isolated (blocking) + rename old isolated → dedicated

- New default keychain mode is 'isolated': altergo creates a permanently locked per-account keychain
  so providers fall back to flat-file creds. Nothing lands in the real login keychain by default. -
  Old 'isolated' (per-account keychain + unlock entry) is now 'dedicated'. Users who were on
  --keychain isolated retain the same behavior; the value stays 'isolated' on disk and is treated as
  blocking mode going forward. Re-opt-in with --keychain dedicated. - --keychain system and
  --keychain shared are deprecated aliases → isolated; both emit a stderr deprecation warning and
  will be removed in v0.46.0. - Migration in _coerce_meta_v3: 'system'/'shared' → 'isolated'
  (in-memory). - _apply_keychain_mode new helper orchestrates mode transitions with pre-flight meta
  stamp for crash safety. - _create_account_keychain gains plant_unlock_entry parameter; two thin
  wrappers _create_account_keychain_dedicated and _create_account_keychain_isolated. -
  _build_alt_env gates on _is_keychain_dedicated (not old _is_keychain_isolated). - Reconciler
  rewritten for isolated/dedicated/legacy three-way state machine. - 17 new tests in
  test_keychain.py; existing tests updated for new semantics. Total: 80 keychain tests, 276 overall
  (all green).

- Docs: README, CHANGELOG, SECURITY, keychain-isolation.md, migration.md, settings.md,
  architecture.md, how-it-works.md, index.html all updated. - Version bumped to 0.44.0.

* style: apply ruff format

- **keychain**: Preserve-and-reuse downgrade + reconciler state machine
  ([#26](https://github.com/thepixelabs/altergo/pull/26),
  [`f5da264`](https://github.com/thepixelabs/altergo/commit/f5da2641490ea3d89bed1bf8e106b53d8810e124))

* feat(keychain): preserve-and-reuse downgrade + reconciler state machine

- Preserve-and-reuse on `--keychain isolated → system`: only the per-account plist is removed;
  keychain file + login-keychain unlock entry preserved. Full cleanup moves to `--delete-account`. -
  Rename `shared` → `system`; old name accepted as deprecated alias (stderr warning, one-minor
  window). - New `_reconcile_keychain_state` heals 14 reachable partial-state combinations across
  (A=meta, B=plist, C=keychain file, D=unlock entry). - `_create_account_keychain` restructured into
  5-case reconciler (reuse / wrong-password rebuild / orphan-C rebuild / stale-D rebuild / fresh).
  Removes the old orphan early-return-and-ask-user-to-rm dead-end. - `do_delete_account` gates on
  file-presence (B OR C OR D), not meta — prevents artifact leaks when deleting a
  preserved-but-currently-system account. - `_delete_account_keychain` also unlinks B. - Meta
  normalization: `keychain` key always written (`"isolated"` or `"system"`). Legacy absent still
  read as system. - Write order: meta written before keychain artifacts, so crashes mid-upgrade are
  self-healing via the reconciler on next launch. - Surface keychain mode in the `--config` picker
  and at the top of the `--config` flow. - Fix pre-existing E501 lint violation at altergo.py:6983.
  - Tests: rewrote 6 dead-route tests, added 5 P0 reconciler tests. 65 keychain tests, 261 total,
  all passing. - Docs: updated across keychain-isolation.md, architecture.md, how-it-works.md,
  settings.md, migration.md, README.md.

* fix(tests): mock _sec in test_do_delete_account_continues_on_keychain_error

do_delete_account's file-presence probe calls _sec before the _delete_account_keychain mock fires.
  On Linux CI runners without /usr/bin/security, the probe raised KeychainError and aborted the test
  before reaching the intended assertion.

- **resume**: Rich session picker with preview pane and animated nav
  ([`ca782ad`](https://github.com/thepixelabs/altergo/commit/ca782adf4669d78cd13a57b7e4bc194b243384d5))

Replace the minimal resume picker with a richer TUI:

- New columns: Project (indigo), When (relative time, gray), Topic (first real user message,
  responsive width) — Size dropped from default view. Topic gets all leftover terminal width with a
  minimum of 40 chars. - Preview pane: p/Tab/Space opens a full-screen preview showing session
  metadata plus the first 4 user/assistant turns, labeled and word-wrapped, with truncation
  indicators. Enter from preview resumes that session. Enter from the list still fast-path resumes.
  - Colors: 256-color palette uses brand-adjacent indices (cyan 51, indigo 105, gray 244, white
  231). Falls back to 8/16-color, then to monochrome A_REVERSE/A_BOLD/A_DIM on dumb terminals. -
  Session metadata line is no longer dimmed — uses default fg so it's actually readable. - Animated
  nav line: BBS-style shine sweep moves across the help text (12fps via curses.timeout(80)),
  separator dots twinkle on a staggered per-position cycle, and "pixelabs" is rendered in brand
  indigo bold. Degrades to A_BOLD/A_REVERSE on no-color terminals. - Performance: cheap
  first-N-lines scan per session (stops at the first real user prompt), tool_result-only user turns
  filtered out, preview content lazily loaded and cached per session id. Tested against 787 real
  sessions with no perceptible delay.

Co-Authored-By: Claude Opus 4.6 (1M context) <noreply@anthropic.com>

- **setup**: Interactive account name + multi-provider selection
  ([`a48cc65`](https://github.com/thepixelabs/altergo/commit/a48cc657dd5874f511d88f8e36f775b52eaa8961))

--setup now prompts for account name when no --name is given (TTY), shows a numbered provider
  checklist with installed binaries pre-checked, and wires only the selected providers'
  dotdirs/symlinks.

New flags: --setup --provider <p>[,<p>] specify providers non-interactively <account> --provider <p>
  select provider at launch time

Provider manifests (claude, gemini) drive all setup/teardown/launch logic. Accounts persist their
  provider list in account.json. Existing accounts without account.json are treated as claude-only.

### Refactoring

- Altergo.py code-quality overhaul ([#25](https://github.com/thepixelabs/altergo/pull/25),
  [`d338964`](https://github.com/thepixelabs/altergo/commit/d338964f726994225fd380a0570a8f736a63ade5))

- Strip all section-banner comments (# --- X ---, # ── X ──────) throughout; labels with non-obvious
  content converted to plain comments - Trim verbose multi-paragraph docstrings to single-sentence
  summaries - Delete dead _build_anim_pack_frames / _get_anim_pack_frames and their
  _ANIM_PACK_FRAMES_CACHE global (settings preview feature never wired up) - Rename is_enabled →
  _is_enabled (private helper, no public callers) - Net reduction: ~530 lines; 256/256 tests pass

- Remove work/employer framing, replace with personal/pro/sideproject
  ([`dc84d82`](https://github.com/thepixelabs/altergo/commit/dc84d8257ad0f1d6c12eed07f4c7785397882fb2))

Removes all "work account" and employer-related copy to avoid implying users can mix company-paid
  sessions with personal ones. Examples now use personal, pro, and sideproject — framing that fits
  individual makers and tinkerers.

- Reposition copy for makers/tinkerers, replace corporate account examples
  ([`57e9407`](https://github.com/thepixelabs/altergo/commit/57e9407452052efbe3d7c963afc9665f37b2c7d8))

Switch all example account names from mine/acme/clientco to personal/work/sideproject. Rewrite hero
  subtitle and Why section to speak to individual devs rather than businesses. Replace "accidentally
  billed to wrong account" with the real dev pain point: not knowing which account you're running as
  until you hit a rate limit.

- Unify goodbye bank into altergo_greetings + add test coverage
  ([`b9ba5ac`](https://github.com/thepixelabs/altergo/commit/b9ba5ac6e8da3d36556011b2ab9471a5526c850a))

Move the _GOODBYE list from altergo.py into altergo_greetings.GOODBYES (alongside GREETINGS — both
  are session-message copy sharing the same voice rules). Expose pick_goodbye(). altergo.py now
  imports from the greetings module instead of owning its own copy.

Tests: rename section to 'Session messages module', fix the (emoji, text) tuple unpacking in the
  length-cap check, add goodbye bank tests (count, shape, pick_goodbye round-trip), and add a
  regression test that bans number-word + AM/PM/o'clock callouts so window-wide sentences cannot lie
  by 1–2 hours.
