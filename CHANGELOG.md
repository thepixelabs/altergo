# CHANGELOG


## v1.1.0 (2026-05-03)

### Features

- Republish v1.x release pipeline after repo recreate
  ([`c149e21`](https://github.com/thepixelabs/altergo/commit/c149e21bb7c1c53ac4637cf338bfff62b7bd47a9))

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>


## v1.0.2 (2026-04-30)

### Bug Fixes

- **keychain**: Print heads-up before partition list grant prompts user
  ([#45](https://github.com/thepixelabs/altergo/pull/45),
  [`47c88d8`](https://github.com/thepixelabs/altergo/commit/47c88d8c083241dfdcffa178717be2421c6f24c5))

When altergo creates a private-mode account it calls set-generic-password-partition-list, which
  prompts the user for their login password to authorize the change. Without context, the user sees
  "security wants to make changes" appear out of nowhere and may be confused about what's being
  asked. Print a single dim line beforehand when running in a TTY so the user knows the prompt is
  coming and what to type.


## v1.0.1 (2026-04-30)

### Bug Fixes

- **keychain**: Clarify that orphaned keychain rebuild loses tokens
  ([#44](https://github.com/thepixelabs/altergo/pull/44),
  [`5113fa0`](https://github.com/thepixelabs/altergo/commit/5113fa02f98c9117d567b9c43a0ca450bbd49932))

When _create_account_keychain hits Case 3 (keychain file present but no unlock entry in real login
  keychain), it deletes the keychain file and rebuilds. Any tokens stored in the orphan are
  unrecoverable since we have no way to unlock it.

The previous message ("Orphaned keychain file found — rebuilding") didn't tell the user that
  re-authentication is needed. Update the message to explicitly call out the data loss so users
  aren't surprised when their provider asks them to log in again on the next launch.


## v1.0.0 (2026-04-29)

### Features

- **keychain**: Drop legacy mode aliases (dedicated/isolated/system/shared) + add Cancel warning
  ([#43](https://github.com/thepixelabs/altergo/pull/43),
  [`d8e39a6`](https://github.com/thepixelabs/altergo/commit/d8e39a6f311258c010fd241fb4399cdfed85f0a4))

BREAKING CHANGE: --keychain now only accepts 'private' and 'none'. All four legacy aliases
  (dedicated, isolated, system, shared) are rejected with a hard error at the CLI level. Accounts
  with legacy values in account.json still load but emit a one-line warning to stderr and are
  treated as 'private'; run `altergo --config <name>` to normalize.

- CLI parser: any old alias → argparse-style error, exit 2 - _coerce_meta_v3: legacy on-disk values
  → 'private' + stderr warning - do_config: removed internal alias normalisation; validates
  'private'/'none' only - _reconcile_keychain_state / _apply_keychain_mode: removed legacy
  desired/mode normalisation; callers now always pass canonical values - New _warn_none_mode_cancel
  helper: 3-line interactive warning + 1-line non-interactive stderr note shown whenever 'none' mode
  is activated - docs: keychain-isolation.md §2 Cancel warning blockquote; faq.md Cancel/Reset Q&A;
  README.md cancel-warning callout; migration.md v0.46.0 section - tests: alias-acceptance tests
  replaced by rejection tests; migration coercion tests updated to verify warning emission +
  'private' fallback

### Breaking Changes

- **keychain**: --keychain now only accepts 'private' and 'none'. All four legacy aliases
  (dedicated, isolated, system, shared) are rejected with a hard error at the CLI level. Accounts
  with legacy values in account.json still load but emit a one-line warning to stderr and are
  treated as 'private'; run `altergo --config <name>` to normalize.


## v0.45.0 (2026-04-29)

### Features

- **keychain**: Rename modes to private/none, flip default to private
  ([#42](https://github.com/thepixelabs/altergo/pull/42),
  [`ce0fa7a`](https://github.com/thepixelabs/altergo/commit/ce0fa7a78bd1592b46a2ce46b8a630ee5031580f))

- Canonical names: dedicated → private, isolated → none - Silent backwards-compat:
  dedicated/isolated accepted on read (CLI + account.json) without warning, normalised to
  private/none on next write - system/shared deprecated aliases keep their stderr warning (→ v0.46.0
  removal) - Default flipped: absent keychain key + --config with no --keychain flag now resolves to
  private (was none/isolated since v0.44.0), eliminating the confusing macOS system dialog that
  appeared for locked-keychain accounts - Internal helpers: _is_keychain_private/_is_keychain_none
  added; _is_keychain_dedicated/_is_keychain_isolated kept as compat wrappers -
  _reconcile_keychain_state and _apply_keychain_mode accept and normalise both old and new
  desired/mode values transparently - All user-facing strings (help text, prompts, picker rows,
  error messages, comments, docstrings) updated to private/none vocabulary - account.json writes:
  "keychain": "private" or "keychain": "none" - Version bump: 0.44.6 → 0.45.0 - Tests: updated all
  41 affected references; added 9 new tests including the 3 spec-required ones (alias parse,
  account.json canonical names, default=private for fresh accounts) - Docs: keychain-isolation.md,
  README.md, migration.md (new §), faq.md, CHANGELOG.md all updated


## v0.44.7 (2026-04-29)

### Bug Fixes

- **keychain**: Pin partition list on dedicated unlock entry to prevent re-prompts
  ([#41](https://github.com/thepixelabs/altergo/pull/41),
  [`9b6815a`](https://github.com/thepixelabs/altergo/commit/9b6815a916a0200abbc5e3aa7eabf85cc1922182))

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
  [`6b11c33`](https://github.com/thepixelabs/altergo/commit/6b11c337265c5a8dc8e3f580a49ec6f24b02a02b))

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
  [`ccb7cb3`](https://github.com/thepixelabs/altergo/commit/ccb7cb392d0ff48bcf3d56699ac5607896dae40f))

- README + keychain-isolation.md: document that gh/aws/gcloud symlinks are independent of keychain
  mode and shared by design (AI provider credentials are what gets isolated, not dev infrastructure)
  - docs/keychain-isolation.md: new §3 with full explanation; renumber subsequent sections -
  settings TUI credentials page: render ⚠ icon in amber+bold instead of plain text, and show warning
  tooltip in amber+bold instead of amber+dim


## v0.44.5 (2026-04-28)

### Bug Fixes

- **landing**: Swap stale 'open source' phrasing to fair-code
  ([`957758a`](https://github.com/thepixelabs/altergo/commit/957758a7ea2a5f79023c5b1a22532f842a4f2b25))

Two leftover strings on the landing page were still describing altergo as 'open source' —
  technically inaccurate under PolyForm Shield 1.0.0 (which is source-available / fair-code, not OSI
  open source). Updated meta description and footer to match the project's actual licensing posture.

### Documentation

- Add keychain repair FAQ and relicense to PolyForm Shield 1.0.0
  ([#37](https://github.com/thepixelabs/altergo/pull/37),
  [`1c4a32d`](https://github.com/thepixelabs/altergo/commit/1c4a32d8a0f45e9a6a1cdbe164a8d4a0671484ea))

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
  [`947456f`](https://github.com/thepixelabs/altergo/commit/947456f5cea383f24c86c62fd97c70744da34779))

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
  ([`c677ab8`](https://github.com/thepixelabs/altergo/commit/c677ab8c0299842f8a75292c934dde884752caf6))

- Altergo is now a transparent claude wrapper — no more auto-picker
  ([`2845e1f`](https://github.com/thepixelabs/altergo/commit/2845e1f3444122a646a8e32e383ede40d51f350a))

- altergo (no args) → claude (starts new session) - altergo [any flags] → claude [any flags] (full
  pass-through) - altergo --resume → opens interactive session picker - altergo --resume <id> →
  resumes session directly - removed 'altergo new' subcommand (redundant, just use altergo)

- Apply all landing page scenario pivot changes correctly
  ([`efbd2bb`](https://github.com/thepixelabs/altergo/commit/efbd2bbb74eef11f28297852381256890bc8c8b1))

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
  ([`9d87acb`](https://github.com/thepixelabs/altergo/commit/9d87acbbf4d6f5ffc56a9619d1a90737744ffe28))

- Tagline: 'Your other Claude.' → 'Switch Claude identities. Keep your context.' - migrate_legacy():
  print 4-line visible block + write MIGRATED.txt audit file (CEO: silent one-liner is wrong for a
  one-time destructive rename) - do_setup(): add 'Isolates Claude. Shares AWS/GCP/Docker by
  default.' footer - tests/conftest.py: force local altergo.py over installed site-packages -
  test_migrate_legacy_prints_once: update assertion for new multi-line output

- Bump version to 0.4.0, add smoke tests to fix CI no-tests exit 5
  ([`1c6e8b4`](https://github.com/thepixelabs/altergo/commit/1c6e8b418024d459d35b2114e34c3156e7f55802))

- Clarify setup/teardown help text and add Accounts section
  ([`73d18a1`](https://github.com/thepixelabs/altergo/commit/73d18a14776023acef8f6758e4a84e325de0d889))

- Footer nav element was inheriting nav{position:fixed;top:0} — change to div
  ([`170e83a`](https://github.com/thepixelabs/altergo/commit/170e83ac4a84e4973ddbc37d431d994caa644fac))

The bare 'nav' CSS selector applied to ALL nav elements including the footer's <nav
  class="footer-links">, causing it to teleport to the top of the viewport above the main navigation
  bar.

Co-Authored-By: Claude Sonnet 4.6 <noreply@anthropic.com>

- Remove legacy migration, startup sweep, and --update-check arg
  ([#14](https://github.com/thepixelabs/altergo/pull/14),
  [`23c16a5`](https://github.com/thepixelabs/altergo/commit/23c16a55b7f0f09f6c5d80853bbb22b0a93cc901))

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
  ([`bc50933`](https://github.com/thepixelabs/altergo/commit/bc50933a26222963aa06f40d7b245c0baa8b3d22))

- Replace tier-implying account names with neutral examples
  ([`89b7b4d`](https://github.com/thepixelabs/altergo/commit/89b7b4dfebc0aef966aa4185b3cfe18b1d8a2e6e))

`altergo pro` and `altergo personal` in CLI snippets accidentally read as altergo product tiers.
  Replace with `altergo backup` (and `work` in multi-example contexts) throughout — hero, features,
  how-it-works, install snippets, commands table, and terminal animation.

Multi-example listings like `personal, pro, sideproject` (showing that names are user-defined) are
  left unchanged.

Co-Authored-By: Claude Sonnet 4.6 <noreply@anthropic.com>

- Resolve all ruff lint errors (E741, I001, F841, E501)
  ([`c13e1be`](https://github.com/thepixelabs/altergo/commit/c13e1bec91844af53b1e344844cb66bcd04bac91))

Rename ambiguous variable `l` to `ln` in logo list comprehensions, sort Rich/urllib import blocks,
  remove unused logo_left/logo_width/DIM/project variables, and wrap long lines in help text, nav
  string, and frozenset literal.

- Safer migration backup order, additional edge-case tests
  ([`d733156`](https://github.com/thepixelabs/altergo/commit/d733156fcee652b26ef7547a5f398d8dbbb9e8d8))

- Show goodbye message after provider exits, not before launch
  ([`3cbdaa6`](https://github.com/thepixelabs/altergo/commit/3cbdaa6f3557040e92844785176072a9493e70e9))

- Simplify --help divider and drop launcher keys section
  ([#19](https://github.com/thepixelabs/altergo/pull/19),
  [`4c0a43e`](https://github.com/thepixelabs/altergo/commit/4c0a43e2abecaa2535191826900f3826bd892527))

* fix: simplify --help divider and drop launcher keys section

Remove the shimmering divider animation in show_help() — it blocked the terminal for ~1.6s and
  overwrote left-column text that extended past the fixed divider column. Divider is now pinned to
  the widest left row so it renders as a single straight line regardless of row overflow. Also drop
  the "Launcher keys" section from both the two-column and single-column layouts.

* style: ruff format

- Slow down card shimmer effect, spread delays to avoid simultaneous triggers
  ([`b793eea`](https://github.com/thepixelabs/altergo/commit/b793eea705b00af141d2f15637445e7790d4b456))

- Smooth gradient on greeting/goodbye messages, add picker search
  ([`ce4a4e1`](https://github.com/thepixelabs/altergo/commit/ce4a4e1fa5ccc016e0edb8dbafbb3295540be21c))

- Replace chunked two-color fade with per-character interpolated gradient on greeting text, goodbye
  messages, and onboarding logo - Goodbye messages now show emoji + purple-blue-cyan-green gradient
  instead of dim text with "altergo" prefix - Add vim-style / search to the resume session picker
  with live filtering

- Suppress noisy output when applying settings on quit
  ([`0a62a45`](https://github.com/thepixelabs/altergo/commit/0a62a451d462d64546b7cfefc8eba4fbdaef876d))

- Sync .claude.json across accounts via symlink_home_files
  ([`3a986a2`](https://github.com/thepixelabs/altergo/commit/3a986a29f3c8cdd963f1361fee36f11cb3f47055))

- Use star spinner for launch animation across all themes
  ([`6094339`](https://github.com/thepixelabs/altergo/commit/60943396a435eeb0d9636dc5cc58b9192b847900))

- Wrap long line in home-change notice print
  ([`2759568`](https://github.com/thepixelabs/altergo/commit/275956805559d7fcb50c742fafdfd024e9306639))

- **ci**: Repair release pipeline, homebrew-bump YAML, pip-audit, drop py3.9
  ([`c29be1f`](https://github.com/thepixelabs/altergo/commit/c29be1fbf2f005ee5999c02fb040c1a7afeb1772))

- release.yml: pass GH_TOKEN as checkout token so credentials persist on the origin remote;
  semantic-release's plain 'git push' now auths - homebrew-bump.yml: replace heredocs with { echo; }
  blocks — heredoc terminators at col 0 broke the YAML run: | literal block scalar - ci.yml +
  pyproject.toml: drop Python 3.9 (EOL 2025-10); code uses PEP 604 'str | None' which is 3.10+ -
  security.yml: remove invalid pip-audit --require-hashes=false (--require-hashes is a boolean flag,
  no argument)

- **cli**: Validate arguments before launch and add launch messages
  ([`bfd17e5`](https://github.com/thepixelabs/altergo/commit/bfd17e5519f81cf894b418bbbecb0fd7e7461695))

- **footer**: Clean up footer — remove duplicate license text, add ❤️ 👾, make License a proper link
  ([`eac964a`](https://github.com/thepixelabs/altergo/commit/eac964a883112d8232961cdf154b3f0030257c38))

Co-Authored-By: Claude Sonnet 4.6 <noreply@anthropic.com>

- **footer**: Purple heart, remove duplicate GitHub link, keep PolyForm Shield 1.0.0 License
  ([`c4bbe43`](https://github.com/thepixelabs/altergo/commit/c4bbe43ee470cf3eb7919af98821a2f9a53f9b9b))

Co-Authored-By: Claude Sonnet 4.6 <noreply@anthropic.com>

- **landing**: Point Stay Connected Rover link to dispatch.pixelabs.net/rover
  ([#36](https://github.com/thepixelabs/altergo/pull/36),
  [`55ae409`](https://github.com/thepixelabs/altergo/commit/55ae4096a2f0485984ed70d516471545391730da))

- **native**: Pass --yolo-resume through + add --default-provider
  ([#30](https://github.com/thepixelabs/altergo/pull/30),
  [`20b220e`](https://github.com/thepixelabs/altergo/commit/20b220e7e5e31b2123046dbe0dc41f2175f58af7))

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
  ([`18ea91c`](https://github.com/thepixelabs/altergo/commit/18ea91c23829dcd70070951f87fc55c7472b99ad))

- **tmux**: Disable mouse capture so UI scroll works behind terminal
  ([`3e1ec13`](https://github.com/thepixelabs/altergo/commit/3e1ec1325249b13d97d76429f7810db66b9e9133))

- **ui**: Comprehensive mobile/tablet responsive fixes for landing page
  ([`2c92beb`](https://github.com/thepixelabs/altergo/commit/2c92bebc1a13068fabab4aa0fb6d05b6fce4e98c))

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
  [`2d7f126`](https://github.com/thepixelabs/altergo/commit/2d7f126edc2023705414497cea5d55fa8210aae4))

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
  [`e31daca`](https://github.com/thepixelabs/altergo/commit/e31daca303708f369aa56075f68f425891e266e1))

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
  [`f217865`](https://github.com/thepixelabs/altergo/commit/f217865e66f5fd115b02bd40cbb9eee0b0d55b9f))

`altergo <account> --yolo-resume <id>` was silently dropping the leading account token because the
  yolo-resume intercept runs before the normal account-parsing block. Native users hit an
  account-picker prompt that didn't even list 'native'. Parse a leading account from the residual
  args inside the yolo-resume handler, accepting 'native' or any existing account dir, and forward
  remaining tokens through to the launch.

### Documentation

- Add architecture and how-it-works reference pages (need v0.5.0 update)
  ([`e103476`](https://github.com/thepixelabs/altergo/commit/e103476232dfcb0e9fc75edf3c255f5dcfe7ed89))

- Add settings TUI guide, update architecture for v0.16
  ([`91b37a9`](https://github.com/thepixelabs/altergo/commit/91b37a95772ce369fa8b800c280461c7e11f2891))

- New docs/settings.md covering the three-page settings TUI - Update docs/architecture.md with
  current code structure, settings schema, and dependency list - Update version references from
  v0.5.0 to v0.16.0+

- Add version badge next to logo in nav
  ([`2360d30`](https://github.com/thepixelabs/altergo/commit/2360d300e9dd779b6686f851c45819a13f0dacf2))

- Align tagline, document MCP sync, catch up to v0.37
  ([`b97e611`](https://github.com/thepixelabs/altergo/commit/b97e61160dc6452af6184a0e15346a117b263731))

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
  ([`463126a`](https://github.com/thepixelabs/altergo/commit/463126a713bc13df47b617c60fac5a8ce88ccd91))

- Fix 4K ghost drift in persistent section, drop fixed page-wide ghost
  ([`8b667e6`](https://github.com/thepixelabs/altergo/commit/8b667e675f0d9975803841e16456d89079196630))

Two independent landing-page fixes:

- #persistent > .container now position:relative so the ghost-wrap's right:-60px anchors to the
  1160px content column instead of the full-width section. On ultrawide/4K viewports the ghost was
  sliding all the way to the viewport's right edge, far from the copy.

- Removed the fixed, centered #ghost-bg-fixed layer that sat behind every section with low opacity.
  Per-section atmosphere (.orb, .persistent-ghost-wrap, data-rain, .gits-illustration) already
  carries the visual weight; the global fixed layer was just noise.

- Inject PyPI count at build time, float why-card icons, add favicon
  ([`67f9f9e`](https://github.com/thepixelabs/altergo/commit/67f9f9e8c93d12e3d8656267fc26538be56be4a0))

Client-side fetches to pypistats/shields were hitting 429s from shared visitor IPs; moving the
  lookup into the Pages build runs it once per deploy (plus a daily scheduled refresh) and falls
  back to the committed value if upstream is down. Also reflows why-card icons with float +
  shape-outside so the title/body wrap around the badge instead of stacking under it, and caps the
  pypi-stat pill width so a long injected count can't blow out the header row.

- New altergo wordmark + README rewrite for v0.5.0
  ([`cd83e06`](https://github.com/thepixelabs/altergo/commit/cd83e06dc7f38fbfd12ef823c87d33403c9dc3ea))

Add docs/logo-dark.svg and docs/logo-light.svg with the cyan-blade wordmark (alt+r indigo, e+go
  contrast, glowing skewed blade between t and e). Reference them via <picture> at the top of
  README.md for light/dark adaptation.

Rewrite README to match the landing page (v0.5.0): pipx and safer curl install, named-account-first
  quick start, full command table, --settings TUI explanation, complete symlink list, macOS Keychain
  note, CD badge beside CI.

Co-Authored-By: Claude Opus 4.6 (1M context) <noreply@anthropic.com>

- Overhaul for v0.40.0 — multi-provider, recall across 4 providers, cwd-on-recall, bookmark rebind
  ([`3eecc76`](https://github.com/thepixelabs/altergo/commit/3eecc76e075199f76421eaa2903389b48baeea1e))

- README: new picker keybindings table (b bookmark, * starred-only); multi-provider recall section;
  add-provider quickstart line; cwd-on-recall mention in features table - architecture.md: corrected
  line count, v3 schema field table, disk-write trigger bullets, per-provider session-format table -
  how-it-works.md: four-provider problem statement; AddProvider reconciliation section citing
  _reconcile_orphan_dot_dir; exact nav-footer string; provider filter + starred filter composition -
  migration.md: v0.40.0 section expanded with cwd-on-recall entry and b/* rebind before/after -
  settings.md: cross-link to picker keybindings in how-it-works

- Reframe landing copy so account-name examples don't read as subcommands
  ([`2aa8f5d`](https://github.com/thepixelabs/altergo/commit/2aa8f5d19a000dde52f86105a37ceee9310e2bfb))

Renaming the placeholder from 'backup' to 'secondary' wasn't enough — any single word after
  'altergo' parses as a subcommand to a first-time reader. Hero now describes the outcome without
  showing a command. Step 3 and the docs notes use an explicit <account> placeholder. Feature card
  drops the inline example and frames it as 'the name you chose'. Install block pairs 'work' + 'pro'
  so both names obviously look like user-picked labels. Reference table uses frame-then-example
  wording. Reduced-motion fallback matches the animated scene convention.

- Remove zero-deps/single-file messaging, add keychain-isolation guide
  ([`a37c550`](https://github.com/thepixelabs/altergo/commit/a37c550499cc2058ed1740f2499c52f644264a99))

- Rename 'backup' placeholder account to 'secondary' in examples
  ([`9c677cf`](https://github.com/thepixelabs/altergo/commit/9c677cff8393fef31fd1a0d0f3b84a6258222791))

The landing page used 'backup' as the example account name throughout (hero, step 3, feature card,
  install block, reference table, static fallback). With altergo being a credentials-management
  tool, 'altergo backup' reads like a subcommand verb instead of 'launch the account called backup'.
  Renamed to 'secondary' everywhere — clearly a noun, unambiguously an account identifier.

- Rename <name> placeholder to <account> in help and docs
  ([`68bfc35`](https://github.com/thepixelabs/altergo/commit/68bfc3524f41ca4c233c0019e5c878744a7db394))

The <name> placeholder in the help menu and documentation was ambiguous ("name of what?"); <account>
  is self-describing. Also rename <name> to <theme> in --theme usage for the same reason.

- Unify why-card layout, swap cross-platform for keychain card, strip em-dashes
  ([`210e906`](https://github.com/thepixelabs/altergo/commit/210e90646114c86e84a34c5771d3d6cfa551f00d))

why-card icons now use the same plain float+margin mechanic as feature-icon instead of the
  shape-outside / display:inline / ::after nbsp / clearfix stack that was there. Cross-platform card
  replaced with a keychain-isolated credentials card, since the landing page had no mention of the
  per-account keychain feature. Also replaced every em-dash in the file with commas, colons, or
  periods depending on context, and cleaned up the comma splices the bulk pass introduced.

- Update all docs for v0.5.0 N-account support
  ([`47d6471`](https://github.com/thepixelabs/altergo/commit/47d64712cbe6943f4cb4fbdc592201019b1330a1))

- Update for v0.5.0 settings TUI and credential sharing
  ([`478649f`](https://github.com/thepixelabs/altergo/commit/478649f948060094c314ed43c88f90654e17bc6a))

- Add --settings command to command reference and features section - Document per-tool credential
  sharing (catalog, default-on/off categories) - Reframe altergo shell and altergo -- as power-user
  escape hatches - Document ~/.altergo/.altergo.json settings persistence path - Update migration
  guide

Co-Authored-By: Claude Sonnet 4.6 <noreply@anthropic.com>

- Update README for v0.5.0 N-account support
  ([`661de28`](https://github.com/thepixelabs/altergo/commit/661de2807756dbd5c31d76b4f1a5bf92146fe1ff))

- Update tagline to 'Switch Claude identities. Keep your context.'
  ([`e1421c9`](https://github.com/thepixelabs/altergo/commit/e1421c9ef7e579c93939e53e0ba3975f7b360745))

- **keychain**: Lead with meaning, document UX surfaces, reframe ceiling
  ([#27](https://github.com/thepixelabs/altergo/pull/27),
  [`6a722b9`](https://github.com/thepixelabs/altergo/commit/6a722b928bb248227a758d7a3d76bfe8ccf894a6))

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
  [`0c8811c`](https://github.com/thepixelabs/altergo/commit/0c8811c1e6dca372f636a498b8d9aa8ffa4f91dd))

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
  [`cc73720`](https://github.com/thepixelabs/altergo/commit/cc7372071fb1380822c8305e69432efd3839a7ef))

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
  [`fb9fa7a`](https://github.com/thepixelabs/altergo/commit/fb9fa7a0a6ba81db2c6987e91a51771209556566))

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
  ([`458d31a`](https://github.com/thepixelabs/altergo/commit/458d31a889e613291ec366f07a25635b055ec161))

- --yolo translates to provider-native skip-permissions flag (claude:
  --dangerously-skip-permissions, gemini/copilot: --yolo, codex:
  --dangerously-bypass-approvals-and-sandbox). - --yolo-resume additionally resumes the last session
  per provider (codex uses the `resume --last` subcommand form). - --recall opens the cross-account
  session picker; bare --resume now passes through to the provider's own native resume UI. - Picker
  gets a theme hotkey (t), separator row, and recall-session title; animated nav footer removed. -
  Tests cover flag translation per provider and updated smoke suite.

- Add color themes with live launcher cycle
  ([`292b52c`](https://github.com/thepixelabs/altergo/commit/292b52c6b6018f472b0c4b53ca1e6abebbd8a62a))

Introduces a THEMES catalog (ocean, forest, lavender, sunset, mono, rainbow) that drives every
  colored surface: help, list, settings, session picker, launcher, banner, and shell prompt. Themes
  persist in .altergo.json, can be cycled live in the launcher with 't', set via 'altergo --theme
  <name>', and route through a runtime C(role) lookup instead of hardcoded constants.

Also shows the altergo banner on --list, --setup, --settings and --theme so the logo is present
  across every top-level screen, and drops the redundant 'account: <name>' prefix line now that the
  banner shows the active account directly under the logo.

- Add shell + passthrough commands, custom SVG icons, docs section
  ([`92e261b`](https://github.com/thepixelabs/altergo/commit/92e261b282161335bcd40d5a936a28aaee085c8e))

- altergo shell: opens an interactive $SHELL with HOME=~/.altergo so users can run gh auth login,
  git config, ssh-keygen, etc. in the alt account context; credentials persist across sessions -
  altergo -- <cmd> [args...]: runs any single command in alt HOME context without entering an
  interactive shell - landing page: replace all emoji icons with custom inline SVG icons for both
  why-cards (3) and feature-items (6); visually on-brand - landing page: add full Documentation
  section with command reference table, credentials/Keychain explanation, symlink map, compatibility
  note, and disclaimer link - README: document new commands with usage examples

Co-Authored-By: Claude Sonnet 4.6 <noreply@anthropic.com>

- Add tmux session persistence section to landing page
  ([`3ed58ff`](https://github.com/thepixelabs/altergo/commit/3ed58ff3c5a5c9e05d3e81789b25a8b3a387f5a3))

- Bidirectional mcpServers sync across accounts, preserves per-account oauthAccount
  ([`ab6692e`](https://github.com/thepixelabs/altergo/commit/ab6692eea747f7aed5e90b4157d7311d4dc7449c))

- Colored --help with OSC 8 links, pixelabs branding, bump pyproject to v0.5.0
  ([`8a69572`](https://github.com/thepixelabs/altergo/commit/8a69572a709eed7354da5a90aa0527765d09dac7))

- Replace print(__doc__) with show_help() — colored output via existing _c() helper, clickable OSC 8
  hyperlinks to pixelabs.net and claude.ai/code - Attribution footer: non-affiliation disclaimer +
  Claude trademark notice - Bump pyproject.toml version to 0.5.0 to match altergo.py

- Colored CLI output, clickable pixelabs.net link, fix docs
  ([`d094040`](https://github.com/thepixelabs/altergo/commit/d09404078a39d949ceb1dfaea79c6e20b14b31ed))

- ANSI colors in --setup, --teardown, --list (TTY-only, pipes unaffected) - OSC 8 clickable
  hyperlink to pixelabs.net in setup/teardown header - Fix README and migration.md: remove 'altergo
  new', correct picker usage - Green ✓ for success, yellow ⚠ for warnings, cyan for headers

- Expand greetings bank + banner above the launcher
  ([#17](https://github.com/thepixelabs/altergo/pull/17),
  [`45e2f6d`](https://github.com/thepixelabs/altergo/commit/45e2f6d43ceb488154a243c198fd5ea3be9de3a1))

- Grow greetings bank 80 → 400 (10 → 50 per window across 8 time windows); update the panel-lock
  test accordingly. - interactive_launcher() now calls show_banner() at the top of each loop
  iteration so the picker is framed by the themed figlet, matching interactive_settings().

- Full-text conversation search with project filtering and quoted phrases
  ([`9b5ea1c`](https://github.com/thepixelabs/altergo/commit/9b5ea1c77a879760f910e523f4c5f94b790d3e11))

- Add `altergo --search` for searching across all session conversation history - Three-phase TUI:
  project filter → search input → scrollable results - Case-insensitive matching, "quoted phrases"
  for exact matches, AND logic - Results sorted newest-to-oldest with snippet previews and role
  indicators - Animated progress bar with braille spinner during scanning - Add `/` search hint to
  help text navigation section

- Initial release of altergo v0.1.0
  ([`2280977`](https://github.com/thepixelabs/altergo/commit/2280977673028c5bba89202db86ac377a8ce0a0e))

Your other Claude — switch Claude Code identities without losing a thought. Zero dependencies,
  interactive TUI, symlink-based session sharing.

- Interactive provider picker and default-provider resolution
  ([`704902f`](https://github.com/thepixelabs/altergo/commit/704902ff53328bc8124b8cdd6943690816e9ad56))

Replace the numbered-checkbox provider prompt with a curses-based arrow/ radio picker (Space
  toggles, d sets default, Enter/s saves). Persist the chosen default in account.json via a new
  default_provider field with back-fill for pre-existing accounts. launch_claude now resolves the
  default provider from meta so altergo <account> and bare altergo (with an active account) both
  launch directly without requiring an explicit provider argument. Style the first-run onboarding
  copy with theme accent colors and add a short Rich spinner beat so it no longer renders as plain
  white text.

- Multi-page settings TUI with live theme preview
  ([`2145d07`](https://github.com/thepixelabs/altergo/commit/2145d07d5d4187638a1cdd33706d8940d362976e))

Replace the single-page credentials settings screen with a three-page TUI accessed via altergo
  --settings:

- Appearance: theme picker with live color preview, gradient swatches, and launch animation toggle -
  Behavior: toggles for greeting messages, goodbye messages, and update checker - Credentials:
  shared CLI credentials (upgraded visual style)

Navigation via arrow keys, h/l, Tab between pages. Themes auto-select on cursor movement with
  instant color recoloring. All settings saved in a single atomic write to .altergo.json.

- Multi-provider altergo accounts ([#23](https://github.com/thepixelabs/altergo/pull/23),
  [`112c57e`](https://github.com/thepixelabs/altergo/commit/112c57edd551c1291ec2abe75b97effe2de0970b))

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
  ([`ac0c27a`](https://github.com/thepixelabs/altergo/commit/ac0c27adeb7bd6b123fed8e0027b2cdd5fcd4de4))

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
  ([`1a7b126`](https://github.com/thepixelabs/altergo/commit/1a7b12675b82d9031830465fbabcd67bf153c92c))

- ACCOUNTS_DIR layout: ~/.altergo/accounts/<name>/ replaces single ~/.altergo/ - resolve_account(),
  validate_account_name(), list_accounts() helpers - Auto-migration: detects legacy
  ~/.altergo/.claude/ layout, renames to accounts/default/ on first run, preserves backup at
  ~/.altergo/.legacy-backup/ - _looks_like_account() disambiguates account names from claude
  pass-through args - altergo <name> routes to named account; unknown name prints actionable error -
  --setup --name <name> and --teardown --name <name> support - All launchers and
  do_setup/do_teardown parameterized over account name - SYMLINK_HOME_DIRS credential symlinks
  created at account_home level - show_help() updated with named account examples

- One account one provider — remove multi-provider bundling (v0.22.0)
  ([`ff0c845`](https://github.com/thepixelabs/altergo/commit/ff0c8455977a1fc09059603fd4f05679f147a252))

- Strip providers list from account.json; each account now has exactly one provider - Replace
  multi-select provider TUI with single-select picker - Remove 'use' subcommand (replaced with clear
  error pointing to --config) - v2 account.json schema: {"version": 2, "provider": "<id>"} -
  Auto-upgrade legacy accounts (no account.json) on first launch - Per-provider sweep in
  _sweep_existing_accounts using v2 single-provider metadata - Restore _sync_claude_mcps for
  bidirectional MCP server sync (from ab6692e) - Version bump to 0.22.0

- Opt-out version checker, hourly greetings, launch-handoff spinners
  ([`f0acfce`](https://github.com/thepixelabs/altergo/commit/f0acfce2b4b8a0e3e5f4c89dbcbaa0e2d0d0d53b))

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
  ([`754eb9f`](https://github.com/thepixelabs/altergo/commit/754eb9f9a11bff47782a3a359a7480c18aa4efdf))

- Per-provider sweep in _sweep_existing_accounts, fix --provider help text
  ([`5f3c529`](https://github.com/thepixelabs/altergo/commit/5f3c5298a9fc3dfbdd5d741dbb2ba0fe317fe884))

- Pivot landing page to flow-continuity hooks
  ([`e9760f9`](https://github.com/thepixelabs/altergo/commit/e9760f90af455a219a5ac1cf411afa4c0da4c70b))

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
  ([`110d622`](https://github.com/thepixelabs/altergo/commit/110d62226ec591ac74014552b1e762bd680f9915))

- Replace `altergo <account> --provider <name>` with positional `altergo <account> <provider>` for
  simpler launch-time provider selection - Add _gradient_ansi() helper for True Color per-character
  gradients in non-curses output (reuses theme banner stops) - Rewrite show_help() with gradient
  section titles driven by active theme, simplified structure (5 sections, removed redundant
  Examples block) - Remove hardcoded _GOODBYE_GRADIENT; goodbye message now uses active theme's
  banner gradient like the greeting

- Provider filter+sort in --resume, per-page gradient nav
  ([`75d4167`](https://github.com/thepixelabs/altergo/commit/75d4167fa2d0bbeb1f389ab3e4049c8595234594))

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
  ([`1db17f3`](https://github.com/thepixelabs/altergo/commit/1db17f33cd559bf80937a3d41cdcf318ef29a8e2))

- Add random theme toggle with frequency slider (often↔rarely) to Appearance settings page — rotates
  theme automatically every N sessions - Fix theme auto-select: cursor movement now updates
  selection marker (◆) so save always reflects what the user sees - Consolidate 6 redundant
  load/save helpers into generic _load_bool_setting - Single atomic write in interactive_settings
  instead of 5+ separate saves - Gradient accent fade on settings separator line - Expanded footer
  nav hints with vim keybindings

- Rich-pyfiglet banner, redesigned help/TUI, provider launcher, goodbye messages
  ([`870d42b`](https://github.com/thepixelabs/altergo/commit/870d42b4f9f632362e119986ed9a561171b4f6f9))

- Add show_banner() with smslant font gradient (#00d7ff→#005fd7) via rich-pyfiglet - Standardize
  color tokens (_C_COMMAND, _C_ARG, _C_HEADER, _C_DIM, etc.) - Rewrite show_help() with new palette,
  section separators, and split arg coloring - Add 15-message _GOODBYE pool printed before every
  os.execvpe() handoff - Add interactive provider+account launcher TUI (_draw_launcher,
  build_launcher_menu) shown automatically when no args given and 2+ accounts exist - Resume picker:
  size column (7-char, amber warning >10MB), (no prompt) dim fallback - Add size_warn color pair
  (amber 220) to _picker_attrs

- Settings TUI for configuring shared CLI credentials
  ([`cbc2ba3`](https://github.com/thepixelabs/altergo/commit/cbc2ba3e346d753e5c9f874d1c6458342e558746))

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
  ([`fc50ca3`](https://github.com/thepixelabs/altergo/commit/fc50ca3c0b9724106d1bb8b6e980a5bf170dbbab))

- Display email address next to account name in the banner (reads from .claude.json, Codex JWT, or
  Gemini oauth_creds) - Add pip, cargo, gem, yarn, pnpm, composer, go modules, Maven, Gradle,
  Bundler to CATALOG - Add one-time animated home isolation notice (home_change_notice_if_needed)
  shown on first launch

- Show altergo logo with account name above each launch
  ([`f68f354`](https://github.com/thepixelabs/altergo/commit/f68f354b2b1aced8128d86fa01be981feee01c8a))

Render the gradient figlet banner before handing off to the provider CLI or account shell, with the
  active account name centered directly beneath the logo and framed by ASCII stars in the same blue
  palette. Makes the current identity visible at a glance on every session start.

- Show short version tag to the right of the banner logo
  ([`fd08a8f`](https://github.com/thepixelabs/altergo/commit/fd08a8f847bc689da405fe8eb076849f51c468b9))

Renders v<version> vertically centered against the figlet block, in the theme's mid gradient stop so
  it reads as part of the logo. Pinned to the logo's natural width so it hugs the figlet rather than
  drifting to the terminal's right edge.

- Tmux session persistence for SSH workflows ([#11](https://github.com/thepixelabs/altergo/pull/11),
  [`dc63df2`](https://github.com/thepixelabs/altergo/commit/dc63df236ad7b4f72300895150f9544a36912eab))

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
  [`5c83a74`](https://github.com/thepixelabs/altergo/commit/5c83a74d8f70e40fbd70d24dc96aa7165858a43c))

- Redesign --help into a two-column layout with a shimmering divider, terminal-width aware (fallback
  to single column below 118 cols). - Launcher loops back to the menu after each session exits;
  launch_claude/launch_shell/launch_command now return the child exit code and callers own sys.exit.
  - Native chips appear for any provider whose binary is on PATH, no longer gated on a pre-existing
  dot-dir in MAIN_HOME. - Share commands/ and skills/ across accounts via symlink, matching agents/
  and plans/. - Tests updated to match the new native-chip and launch return-code contracts.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>

- Update landing page for v0.5.0 N-account support
  ([`3443366`](https://github.com/thepixelabs/altergo/commit/3443366fbd5431bf9f10a7cf1ce7a8c1061b3207))

- Update landing page for v0.5.0 N-account support
  ([`6a06e43`](https://github.com/thepixelabs/altergo/commit/6a06e43f1d6e8946fd744617349fa72ea6eb7243))

- V0.9.0 — active account pointer, wire launcher, restructure help
  ([`225a54f`](https://github.com/thepixelabs/altergo/commit/225a54f62533d15ad0bee0d35b1705fd051e1242))

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
  ([`af956f4`](https://github.com/thepixelabs/altergo/commit/af956f4c359751aed3d4ae0d293d4c36bb4efa27))

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
  ([`e96f27e`](https://github.com/thepixelabs/altergo/commit/e96f27e1006e3bce2927afae93aa90765aa9971e))

* feat(cli): add --rename command and make account name positional in --config

- `altergo --config <name>` replaces `altergo --config --name <name>` - New `altergo --rename <old>
  <new>` command renames an account directory - All help text, hints, and error messages updated to
  use new syntax

* test: update tmux session name and --config syntax assertions

- **docs**: Add ghost_duality image and update landing page
  ([`38ed179`](https://github.com/thepixelabs/altergo/commit/38ed17923cd805660e4fb555d250606668723ac6))

- **docs**: Ghost in the Shell landing page redesign
  ([`8b0d1a3`](https://github.com/thepixelabs/altergo/commit/8b0d1a3ac3b523419f2f65bc5149beb1ba79095d))

Complete visual overhaul of docs/index.html with GITS anime aesthetic: - Dark navy/cyan/indigo
  palette with neural mesh canvas background - AI-generated GITS-style scene images for hero,
  sections, and ghost character - Animated terminal mockup cycling 6 diverse altergo workflow scenes
  - Light/dark/system theme toggle with full light-mode blue slate palette - GITS-styled mobile
  hamburger drawer with numbered links and theme switcher - Hero parallax, data-rain overlay,
  floating ghost circle with glow animations - Transparent feature cards, full-bleed section
  backgrounds, radial mask fades

- **keychain**: Flip default to isolated (blocking) + rename old isolated → dedicated
  ([#29](https://github.com/thepixelabs/altergo/pull/29),
  [`301bd2b`](https://github.com/thepixelabs/altergo/commit/301bd2b41385ad3fe4970c991285e58b7f35850c))

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
  [`3e49c2f`](https://github.com/thepixelabs/altergo/commit/3e49c2f04865a0c65a68795505126b98c9803159))

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
  ([`8ed9798`](https://github.com/thepixelabs/altergo/commit/8ed9798d028f36fe4bd7138d31e84a33085e94d6))

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
  ([`d4b1609`](https://github.com/thepixelabs/altergo/commit/d4b1609e469cf343863a0d6d6c38d3664722790c))

--setup now prompts for account name when no --name is given (TTY), shows a numbered provider
  checklist with installed binaries pre-checked, and wires only the selected providers'
  dotdirs/symlinks.

New flags: --setup --provider <p>[,<p>] specify providers non-interactively <account> --provider <p>
  select provider at launch time

Provider manifests (claude, gemini) drive all setup/teardown/launch logic. Accounts persist their
  provider list in account.json. Existing accounts without account.json are treated as claude-only.

### Refactoring

- Altergo.py code-quality overhaul ([#25](https://github.com/thepixelabs/altergo/pull/25),
  [`dc3836d`](https://github.com/thepixelabs/altergo/commit/dc3836d37522e31a5ea2a43a124dfe707d8b4758))

- Strip all section-banner comments (# --- X ---, # ── X ──────) throughout; labels with non-obvious
  content converted to plain comments - Trim verbose multi-paragraph docstrings to single-sentence
  summaries - Delete dead _build_anim_pack_frames / _get_anim_pack_frames and their
  _ANIM_PACK_FRAMES_CACHE global (settings preview feature never wired up) - Rename is_enabled →
  _is_enabled (private helper, no public callers) - Net reduction: ~530 lines; 256/256 tests pass

- Remove work/employer framing, replace with personal/pro/sideproject
  ([`faa8479`](https://github.com/thepixelabs/altergo/commit/faa847923beaf0d82644d79a3de5d42eac420d60))

Removes all "work account" and employer-related copy to avoid implying users can mix company-paid
  sessions with personal ones. Examples now use personal, pro, and sideproject — framing that fits
  individual makers and tinkerers.

- Reposition copy for makers/tinkerers, replace corporate account examples
  ([`2e56771`](https://github.com/thepixelabs/altergo/commit/2e56771a4b690ec63ea94fcc66904f10a5cd2642))

Switch all example account names from mine/acme/clientco to personal/work/sideproject. Rewrite hero
  subtitle and Why section to speak to individual devs rather than businesses. Replace "accidentally
  billed to wrong account" with the real dev pain point: not knowing which account you're running as
  until you hit a rate limit.

- Unify goodbye bank into altergo_greetings + add test coverage
  ([`450b4a6`](https://github.com/thepixelabs/altergo/commit/450b4a6f609e765726ebbc745cb983e163339676))

Move the _GOODBYE list from altergo.py into altergo_greetings.GOODBYES (alongside GREETINGS — both
  are session-message copy sharing the same voice rules). Expose pick_goodbye(). altergo.py now
  imports from the greetings module instead of owning its own copy.

Tests: rename section to 'Session messages module', fix the (emoji, text) tuple unpacking in the
  length-cap check, add goodbye bank tests (count, shape, pick_goodbye round-trip), and add a
  regression test that bans number-word + AM/PM/o'clock callouts so window-wide sentences cannot lie
  by 1–2 hours.
