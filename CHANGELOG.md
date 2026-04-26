# CHANGELOG


## v0.44.3 (2026-04-26)

### Bug Fixes

- **yolo-resume**: Consume any non-flag token as session id; route explicit provider on native
  ([#34](https://github.com/thepixelabs/altergo/pull/34),
  [`6458888`](https://github.com/thepixelabs/altergo/commit/6458888162a39197aa3ee95689f8b0b2caaba2f5))

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


## v0.44.2 (2026-04-26)

### Bug Fixes

- **yolo-resume**: Defer to portal handler when 'portal' is in args
  ([#33](https://github.com/thepixelabs/altergo/pull/33),
  [`d8de17b`](https://github.com/thepixelabs/altergo/commit/d8de17ba30bd3a02a369ef2a93f9184210dc3234))

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

### Documentation

- **landing**: Tmux + stale-claim fixes, plus GA4 with GDPR consent
  ([#32](https://github.com/thepixelabs/altergo/pull/32),
  [`b9e9a33`](https://github.com/thepixelabs/altergo/commit/b9e9a33446aa73fb42d4ad32ce68add5bd1c4d0e))

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


## v0.44.1 (2026-04-25)

### Bug Fixes

- **native**: Pass --yolo-resume through + add --default-provider
  ([#30](https://github.com/thepixelabs/altergo/pull/30),
  [`678d760`](https://github.com/thepixelabs/altergo/commit/678d760ff103b28d758c3090c843cac21e88c147))

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


## v0.44.0 (2026-04-24)

### Documentation

- Fix 4K ghost drift in persistent section, drop fixed page-wide ghost
  ([`8a4758f`](https://github.com/thepixelabs/altergo/commit/8a4758f5b80690c0a4b1f6f8abe671d4157350a2))

Two independent landing-page fixes:

- #persistent > .container now position:relative so the ghost-wrap's right:-60px anchors to the
  1160px content column instead of the full-width section. On ultrawide/4K viewports the ghost was
  sliding all the way to the viewport's right edge, far from the copy.

- Removed the fixed, centered #ghost-bg-fixed layer that sat behind every section with low opacity.
  Per-section atmosphere (.orb, .persistent-ghost-wrap, data-rain, .gits-illustration) already
  carries the visual weight; the global fixed layer was just noise.

- Reframe landing copy so account-name examples don't read as subcommands
  ([`fb29873`](https://github.com/thepixelabs/altergo/commit/fb29873b31eb8242d024eff046baae80e32d07a8))

Renaming the placeholder from 'backup' to 'secondary' wasn't enough — any single word after
  'altergo' parses as a subcommand to a first-time reader. Hero now describes the outcome without
  showing a command. Step 3 and the docs notes use an explicit <account> placeholder. Feature card
  drops the inline example and frames it as 'the name you chose'. Install block pairs 'work' + 'pro'
  so both names obviously look like user-picked labels. Reference table uses frame-then-example
  wording. Reduced-motion fallback matches the animated scene convention.

### Features

- **keychain**: Flip default to isolated (blocking) + rename old isolated → dedicated
  ([#29](https://github.com/thepixelabs/altergo/pull/29),
  [`ae80855`](https://github.com/thepixelabs/altergo/commit/ae808558dec9ef799e24d4018701131603368c34))

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


## v0.43.1 (2026-04-23)

### Bug Fixes

- **yolo-resume**: Honor explicit account token
  ([#28](https://github.com/thepixelabs/altergo/pull/28),
  [`bb56ba3`](https://github.com/thepixelabs/altergo/commit/bb56ba38eb2712cfee550d176fa6f2c754d73a10))

`altergo <account> --yolo-resume <id>` was silently dropping the leading account token because the
  yolo-resume intercept runs before the normal account-parsing block. Native users hit an
  account-picker prompt that didn't even list 'native'. Parse a leading account from the residual
  args inside the yolo-resume handler, accepting 'native' or any existing account dir, and forward
  remaining tokens through to the launch.

### Documentation

- Inject PyPI count at build time, float why-card icons, add favicon
  ([`e6a95a9`](https://github.com/thepixelabs/altergo/commit/e6a95a9ee39a0447d1a333faff43528d2acb839f))

Client-side fetches to pypistats/shields were hitting 429s from shared visitor IPs; moving the
  lookup into the Pages build runs it once per deploy (plus a daily scheduled refresh) and falls
  back to the committed value if upstream is down. Also reflows why-card icons with float +
  shape-outside so the title/body wrap around the badge instead of stacking under it, and caps the
  pypi-stat pill width so a long injected count can't blow out the header row.

- Rename 'backup' placeholder account to 'secondary' in examples
  ([`bc3d6dd`](https://github.com/thepixelabs/altergo/commit/bc3d6ddcf6370fd2c524eff2ad70449fcacf2d59))

The landing page used 'backup' as the example account name throughout (hero, step 3, feature card,
  install block, reference table, static fallback). With altergo being a credentials-management
  tool, 'altergo backup' reads like a subcommand verb instead of 'launch the account called backup'.
  Renamed to 'secondary' everywhere — clearly a noun, unambiguously an account identifier.

- Unify why-card layout, swap cross-platform for keychain card, strip em-dashes
  ([`90cfb7a`](https://github.com/thepixelabs/altergo/commit/90cfb7aaf7152ff6a4e834ab3fb5c9c67aaa4a72))

why-card icons now use the same plain float+margin mechanic as feature-icon instead of the
  shape-outside / display:inline / ::after nbsp / clearfix stack that was there. Cross-platform card
  replaced with a keychain-isolated credentials card, since the landing page had no mention of the
  per-account keychain feature. Also replaced every em-dash in the file with commas, colons, or
  periods depending on context, and cleaned up the comma splices the bulk pass introduced.

- **keychain**: Lead with meaning, document UX surfaces, reframe ceiling
  ([#27](https://github.com/thepixelabs/altergo/pull/27),
  [`be4ba44`](https://github.com/thepixelabs/altergo/commit/be4ba441882fc6b2c30d060ef5fd638b50dfe2e8))

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


## v0.43.0 (2026-04-23)

### Documentation

- Rename <name> placeholder to <account> in help and docs
  ([`a9440c4`](https://github.com/thepixelabs/altergo/commit/a9440c4f2bdc1ac38f27bde369258e2b516a1a2f))

The <name> placeholder in the help menu and documentation was ambiguous ("name of what?"); <account>
  is self-describing. Also rename <name> to <theme> in --theme usage for the same reason.

### Features

- **keychain**: Preserve-and-reuse downgrade + reconciler state machine
  ([#26](https://github.com/thepixelabs/altergo/pull/26),
  [`7d660fc`](https://github.com/thepixelabs/altergo/commit/7d660fc53ea68380dc863953548c13ae25e8475b))

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


## v0.42.0 (2026-04-22)

### Features

- **docs**: Add ghost_duality image and update landing page
  ([`c27860a`](https://github.com/thepixelabs/altergo/commit/c27860ad211467cfc80f32841902186aa49e3ee6))


## v0.41.0 (2026-04-21)

### Features

- **docs**: Ghost in the Shell landing page redesign
  ([`fbf8276`](https://github.com/thepixelabs/altergo/commit/fbf82763cf4fbb26be204893c9e45afbb1789eac))

Complete visual overhaul of docs/index.html with GITS anime aesthetic: - Dark navy/cyan/indigo
  palette with neural mesh canvas background - AI-generated GITS-style scene images for hero,
  sections, and ghost character - Animated terminal mockup cycling 6 diverse altergo workflow scenes
  - Light/dark/system theme toggle with full light-mode blue slate palette - GITS-styled mobile
  hamburger drawer with numbered links and theme switcher - Hero parallax, data-rain overlay,
  floating ghost circle with glow animations - Transparent feature cards, full-bleed section
  backgrounds, radial mask fades


## v0.40.2 (2026-04-21)

### Documentation

- Remove zero-deps/single-file messaging, add keychain-isolation guide
  ([`f35412b`](https://github.com/thepixelabs/altergo/commit/f35412b8e5dea7d23c6beb2a3007ed48968b5172))

### Refactoring

- Altergo.py code-quality overhaul ([#25](https://github.com/thepixelabs/altergo/pull/25),
  [`a30981b`](https://github.com/thepixelabs/altergo/commit/a30981b62c652c027bb85084261bed0701faa5de))

- Strip all section-banner comments (# --- X ---, # ── X ──────) throughout; labels with non-obvious
  content converted to plain comments - Trim verbose multi-paragraph docstrings to single-sentence
  summaries - Delete dead _build_anim_pack_frames / _get_anim_pack_frames and their
  _ANIM_PACK_FRAMES_CACHE global (settings preview feature never wired up) - Rename is_enabled →
  _is_enabled (private helper, no public callers) - Net reduction: ~530 lines; 256/256 tests pass


## v0.40.1 (2026-04-21)

### Bug Fixes

- --add-provider must not pool credentials into MAIN_HOME
  ([#24](https://github.com/thepixelabs/altergo/pull/24),
  [`97c460b`](https://github.com/thepixelabs/altergo/commit/97c460b3fc80935a4a9b583e90c29a6755e97eec))

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

### Documentation

- Overhaul for v0.40.0 — multi-provider, recall across 4 providers, cwd-on-recall, bookmark rebind
  ([`dfb83c8`](https://github.com/thepixelabs/altergo/commit/dfb83c8d571bc3c465226de5bf288ddf54b97110))

- README: new picker keybindings table (b bookmark, * starred-only); multi-provider recall section;
  add-provider quickstart line; cwd-on-recall mention in features table - architecture.md: corrected
  line count, v3 schema field table, disk-write trigger bullets, per-provider session-format table -
  how-it-works.md: four-provider problem statement; AddProvider reconciliation section citing
  _reconcile_orphan_dot_dir; exact nav-footer string; provider filter + starred filter composition -
  migration.md: v0.40.0 section expanded with cwd-on-recall entry and b/* rebind before/after -
  settings.md: cross-link to picker keybindings in how-it-works


## v0.40.0 (2026-04-20)

### Features

- Multi-provider altergo accounts ([#23](https://github.com/thepixelabs/altergo/pull/23),
  [`9c31513`](https://github.com/thepixelabs/altergo/commit/9c3151350ac42b8dacec35fcb4ee3b8540ebf0c7))

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


## v0.39.1 (2026-04-19)

### Bug Fixes

- Simplify --help divider and drop launcher keys section
  ([#19](https://github.com/thepixelabs/altergo/pull/19),
  [`d7e2871`](https://github.com/thepixelabs/altergo/commit/d7e28714bf46b66241b1c3f4c1e697c376334635))

* fix: simplify --help divider and drop launcher keys section

Remove the shimmering divider animation in show_help() — it blocked the terminal for ~1.6s and
  overwrote left-column text that extended past the fixed divider column. Divider is now pinned to
  the widest left row so it renders as a single straight line regardless of row overflow. Also drop
  the "Launcher keys" section from both the two-column and single-column layouts.

* style: ruff format


## v0.39.0 (2026-04-17)

### Features

- Accept session ID with --yolo-resume ([#18](https://github.com/thepixelabs/altergo/pull/18),
  [`d08102d`](https://github.com/thepixelabs/altergo/commit/d08102d16368046ceb03195f13917854b9e76918))

Previously `altergo --yolo-resume <uuid>` silently passed the UUID through as a positional arg, so
  providers received it as the first user prompt of the resumed session instead of using it to pick
  a specific session.

Now --yolo-resume accepts an optional session ID in either form: --yolo-resume=<ID> --yolo-resume
  <ID> (only if the following token is UUID-shaped)

When an ID is provided, it is substituted into each provider's resume_by_id template:
  claude/gemini/copilot use `--resume <ID>`, codex uses the `resume <ID>` subcommand. With no ID the
  flag continues to resume the most recent session. A non-UUID trailing token is left alone so
  prompts passed on the command line still work.


## v0.38.0 (2026-04-17)

### Documentation

- Align tagline, document MCP sync, catch up to v0.37
  ([`636b238`](https://github.com/thepixelabs/altergo/commit/636b238f770204bc8514d00e7c8070f924bfaca7))

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

### Features

- Add --yolo/--yolo-resume flags and rename --list to --recall
  ([`f0e7d6a`](https://github.com/thepixelabs/altergo/commit/f0e7d6a0ee31708e2bfa1c77354f1f14f8567a05))

- --yolo translates to provider-native skip-permissions flag (claude:
  --dangerously-skip-permissions, gemini/copilot: --yolo, codex:
  --dangerously-bypass-approvals-and-sandbox). - --yolo-resume additionally resumes the last session
  per provider (codex uses the `resume --last` subcommand form). - --recall opens the cross-account
  session picker; bare --resume now passes through to the provider's own native resume UI. - Picker
  gets a theme hotkey (t), separator row, and recall-session title; animated nav footer removed. -
  Tests cover flag translation per provider and updated smoke suite.


## v0.37.1 (2026-04-16)

### Refactoring

- Unify goodbye bank into altergo_greetings + add test coverage
  ([`9f8998a`](https://github.com/thepixelabs/altergo/commit/9f8998a007d36bdaafa33fc0f7dae92e66d363e9))

Move the _GOODBYE list from altergo.py into altergo_greetings.GOODBYES (alongside GREETINGS — both
  are session-message copy sharing the same voice rules). Expose pick_goodbye(). altergo.py now
  imports from the greetings module instead of owning its own copy.

Tests: rename section to 'Session messages module', fix the (emoji, text) tuple unpacking in the
  length-cap check, add goodbye bank tests (count, shape, pick_goodbye round-trip), and add a
  regression test that bans number-word + AM/PM/o'clock callouts so window-wide sentences cannot lie
  by 1–2 hours.


## v0.37.0 (2026-04-16)

### Features

- Expand greetings bank + banner above the launcher
  ([#17](https://github.com/thepixelabs/altergo/pull/17),
  [`42346bb`](https://github.com/thepixelabs/altergo/commit/42346bb265cd5c088eeba67d2bb435a15c8eadf2))

- Grow greetings bank 80 → 400 (10 → 50 per window across 8 time windows); update the panel-lock
  test accordingly. - interactive_launcher() now calls show_banner() at the top of each loop
  iteration so the picker is framed by the themed figlet, matching interactive_settings().


## v0.36.0 (2026-04-16)

### Features

- Two-column help, looping launcher, share commands/skills
  ([#15](https://github.com/thepixelabs/altergo/pull/15),
  [`4d8aed4`](https://github.com/thepixelabs/altergo/commit/4d8aed4286564b160d4813a50c684400d2cd5f7a))

- Redesign --help into a two-column layout with a shimmering divider, terminal-width aware (fallback
  to single column below 118 cols). - Launcher loops back to the menu after each session exits;
  launch_claude/launch_shell/launch_command now return the child exit code and callers own sys.exit.
  - Native chips appear for any provider whose binary is on PATH, no longer gated on a pre-existing
  dot-dir in MAIN_HOME. - Share commands/ and skills/ across accounts via symlink, matching agents/
  and plans/. - Tests updated to match the new native-chip and launch return-code contracts.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>


## v0.35.3 (2026-04-14)

### Bug Fixes

- Remove legacy migration, startup sweep, and --update-check arg
  ([#14](https://github.com/thepixelabs/altergo/pull/14),
  [`94f22ad`](https://github.com/thepixelabs/altergo/commit/94f22add4d2ed3fd28399ec4b7a638c674e61279))

* fix: remove legacy migration, startup sweep, and --update-check arg

- Remove detect_legacy() and migrate_legacy() — all users are already on the N-account layout; the
  migration code is dead weight - Remove unconditional _sweep_existing_accounts() calls from main()
  and launch_claude() — sweep now only runs from --config where it is actually needed - Harden
  _ensure_symlinked_dir case (d): warn and skip instead of silently moving account data to the
  shared store, which was the mechanism that could cause account data loss on upgrade - Remove
  --update-check CLI argument entirely; update check toggle is now only accessible via the settings
  panel (altergo --settings)

* test: remove tests for deleted migrate_legacy and --update-check arg


## v0.35.2 (2026-04-14)

### Bug Fixes

- **tmux**: Disable mouse capture so UI scroll works behind terminal
  ([`853236b`](https://github.com/thepixelabs/altergo/commit/853236b2512f097dc51a2010df577abb8a5d0f1f))


## v0.35.1 (2026-04-14)

### Bug Fixes

- **tmux**: Avoid session name collisions by appending -N suffix
  ([`8e01bd4`](https://github.com/thepixelabs/altergo/commit/8e01bd4ed53780a9de88ef6947747bce11b1eaa3))


## v0.35.0 (2026-04-14)

### Features

- **account**: Add native passthrough account that launches with real $HOME
  ([`46255fe`](https://github.com/thepixelabs/altergo/commit/46255fe4e05c577fd7ab2ba7fd514412d51e36ec))

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


## v0.34.0 (2026-04-14)

### Features

- **cli**: Add --rename command and make account name positional in --config
  ([`19dd994`](https://github.com/thepixelabs/altergo/commit/19dd994580717b6a34e34bfe8e0c973c2e273eab))

* feat(cli): add --rename command and make account name positional in --config

- `altergo --config <name>` replaces `altergo --config --name <name>` - New `altergo --rename <old>
  <new>` command renames an account directory - All help text, hints, and error messages updated to
  use new syntax

* test: update tmux session name and --config syntax assertions


## v0.33.2 (2026-04-13)

### Bug Fixes

- **cli**: Validate arguments before launch and add launch messages
  ([`ae71297`](https://github.com/thepixelabs/altergo/commit/ae71297f9a98ec906fa6d38da2c464b886d7099c))


## v0.33.1 (2026-04-13)

### Bug Fixes

- Slow down card shimmer effect, spread delays to avoid simultaneous triggers
  ([`dbbf5bb`](https://github.com/thepixelabs/altergo/commit/dbbf5bbd5c4b8f28740bf0b61c09e72f9c2a2d5b))


## v0.33.0 (2026-04-13)

### Features

- Add tmux session persistence section to landing page
  ([`2678b17`](https://github.com/thepixelabs/altergo/commit/2678b17948dc773b096d8bd3ccdfaab9829ab811))


## v0.32.0 (2026-04-13)

### Features

- Tmux session persistence for SSH workflows ([#11](https://github.com/thepixelabs/altergo/pull/11),
  [`8bc332a`](https://github.com/thepixelabs/altergo/commit/8bc332ad68528be4d91098ba15ca30bef3153849))

* feat: tmux session persistence for SSH workflows

Add a tmux_session setting (default off) that wraps every provider session in a named tmux window.
  Sessions survive SSH disconnects and can be reattached with tmux attach -t <name>. Detects $TMUX
  to avoid nesting; falls back gracefully with a brew install hint if tmux is absent.

- _tmux_available(), _tmux_session_name(), _build_tmux_cmd() helpers - launch_claude, launch_shell,
  launch_command all honour the setting - Behavior page in settings TUI gains a tmux sessions toggle
  - docs/settings.md: new tmux persistence section + key reference - 9 new tests covering defaults,
  persistence, name format, cmd structure

* fix: ruff formatting


## v0.31.1 (2026-04-13)

### Bug Fixes

- Wrap long line in home-change notice print
  ([`7370288`](https://github.com/thepixelabs/altergo/commit/73702885b34ea22cda5f8652f5ce817e35d21f86))


## v0.31.0 (2026-04-13)

### Features

- Show account email in banner, add package manager catalog entries, home change notice
  ([`101bd33`](https://github.com/thepixelabs/altergo/commit/101bd331cdf5cb70d21558f035c8e63de1e8aa25))

- Display email address next to account name in the banner (reads from .claude.json, Codex JWT, or
  Gemini oauth_creds) - Add pip, cargo, gem, yarn, pnpm, composer, go modules, Maven, Gradle,
  Bundler to CATALOG - Add one-time animated home isolation notice (home_change_notice_if_needed)
  shown on first launch


## v0.30.0 (2026-04-12)

### Bug Fixes

- Resolve all ruff lint errors (E741, I001, F841, E501)
  ([`76165b9`](https://github.com/thepixelabs/altergo/commit/76165b9f0629cc5dc8e13a1c9eccf29dbd80bce0))

Rename ambiguous variable `l` to `ln` in logo list comprehensions, sort Rich/urllib import blocks,
  remove unused logo_left/logo_width/DIM/project variables, and wrap long lines in help text, nav
  string, and frozenset literal.

### Documentation

- Add version badge next to logo in nav
  ([`a655cbf`](https://github.com/thepixelabs/altergo/commit/a655cbf6ebac0f503769dcec0fb6eceaa3546428))

### Features

- One account one provider — remove multi-provider bundling (v0.22.0)
  ([`e635bf9`](https://github.com/thepixelabs/altergo/commit/e635bf9de1bdeaa4484964bc6e00f9301a80842e))

- Strip providers list from account.json; each account now has exactly one provider - Replace
  multi-select provider TUI with single-select picker - Remove 'use' subcommand (replaced with clear
  error pointing to --config) - v2 account.json schema: {"version": 2, "provider": "<id>"} -
  Auto-upgrade legacy accounts (no account.json) on first launch - Per-provider sweep in
  _sweep_existing_accounts using v2 single-provider metadata - Restore _sync_claude_mcps for
  bidirectional MCP server sync (from eef91f6) - Version bump to 0.22.0

- Per-provider sweep in _sweep_existing_accounts, fix --provider help text
  ([`0b31efc`](https://github.com/thepixelabs/altergo/commit/0b31efc532a631886fa69758c1c429ae0b8b208e))

- Provider filter+sort in --resume, per-page gradient nav
  ([`9c3b1e9`](https://github.com/thepixelabs/altergo/commit/9c3b1e9d0cc624c467c2690cb94fc6c3378ea4c3))

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


## v0.22.0 (2026-04-12)

### Features

- Bidirectional mcpServers sync across accounts, preserves per-account oauthAccount
  ([`eef91f6`](https://github.com/thepixelabs/altergo/commit/eef91f68c58de90588fb8f4b455e0f6ed235c1bc))


## v0.21.2 (2026-04-11)

### Bug Fixes

- Sync .claude.json across accounts via symlink_home_files
  ([`84b45ca`](https://github.com/thepixelabs/altergo/commit/84b45caefdea2c4628ca2f03d42b797c69a3cfcd))


## v0.21.1 (2026-04-11)

### Bug Fixes

- Rename --setup to --config and add `<name> use <provider>` subcommand
  ([`4e496d9`](https://github.com/thepixelabs/altergo/commit/4e496d903a30fbc6e8f15e5dfda341d7ef72d426))


## v0.21.0 (2026-04-11)

### Bug Fixes

- Apply all landing page scenario pivot changes correctly
  ([`b6e9b7f`](https://github.com/thepixelabs/altergo/commit/b6e9b7fec52675b4297b7cf665305b0984307b3c))

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

- Replace tier-implying account names with neutral examples
  ([`87b8334`](https://github.com/thepixelabs/altergo/commit/87b8334b17616908ea7aa3b8259edf4dd317f2b2))

`altergo pro` and `altergo personal` in CLI snippets accidentally read as altergo product tiers.
  Replace with `altergo backup` (and `work` in multi-example contexts) throughout — hero, features,
  how-it-works, install snippets, commands table, and terminal animation.

Multi-example listings like `personal, pro, sideproject` (showing that names are user-defined) are
  left unchanged.

Co-Authored-By: Claude Sonnet 4.6 <noreply@anthropic.com>

### Features

- Interactive provider picker and default-provider resolution
  ([`c831f73`](https://github.com/thepixelabs/altergo/commit/c831f73ffb002049d184e867124301c06a223f65))

Replace the numbered-checkbox provider prompt with a curses-based arrow/ radio picker (Space
  toggles, d sets default, Enter/s saves). Persist the chosen default in account.json via a new
  default_provider field with back-fill for pre-existing accounts. launch_claude now resolves the
  default provider from meta so altergo <account> and bare altergo (with an active account) both
  launch directly without requiring an explicit provider argument. Style the first-run onboarding
  copy with theme accent colors and add a short Rich spinner beat so it no longer renders as plain
  white text.

- Pivot landing page to flow-continuity hooks
  ([`6a3fa2e`](https://github.com/thepixelabs/altergo/commit/6a3fa2e925e7227bd1392f2f44db92ff1bd2a51b))

Lead with rate-limit continuity as the #1 scenario hook — the moment you hit a wall mid-session and
  need to keep going without losing context. Add thinker/executor and client isolation as secondary
  scenarios.

- docs/index.html: new hero headline, new #when section with 3 scenario cards, updated #why heading,
  updated meta description, new nav link - README.md: new tagline, why section, before/after table
  leading with the rate-limit moment - docs/launch/positioning.md: full rewrite with ranked
  scenarios and tone rules (never say cheaper/bypass — frame as flow continuity) -
  docs/how-it-works.md: expand problem statement with new scenarios

Co-Authored-By: Claude Sonnet 4.6 <noreply@anthropic.com>


## v0.20.2 (2026-04-11)

### Refactoring

- Remove work/employer framing, replace with personal/pro/sideproject
  ([`6805302`](https://github.com/thepixelabs/altergo/commit/68053023827f9fedb28ef7d53620f694b216d40a))

Removes all "work account" and employer-related copy to avoid implying users can mix company-paid
  sessions with personal ones. Examples now use personal, pro, and sideproject — framing that fits
  individual makers and tinkerers.


## v0.20.1 (2026-04-11)

### Refactoring

- Reposition copy for makers/tinkerers, replace corporate account examples
  ([`67e6ff5`](https://github.com/thepixelabs/altergo/commit/67e6ff5cc50b11cdd07a6fddc07e855cb66a6b68))

Switch all example account names from mine/acme/clientco to personal/work/sideproject. Rewrite hero
  subtitle and Why section to speak to individual devs rather than businesses. Replace "accidentally
  billed to wrong account" with the real dev pain point: not knowing which account you're running as
  until you hit a rate limit.


## v0.20.0 (2026-04-10)

### Features

- Multi-provider rebrand, messaging cleanup, site polish
  ([`0d5024f`](https://github.com/thepixelabs/altergo/commit/0d5024f21179df1808bd7f5155b936c2084e26e3))

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


## v0.19.0 (2026-04-10)

### Features

- Positional provider syntax, gradient help titles, theme-aware goodbye
  ([`078ae33`](https://github.com/thepixelabs/altergo/commit/078ae330128e8b2467c3b2ee3e3307e08c81ad70))

- Replace `altergo <account> --provider <name>` with positional `altergo <account> <provider>` for
  simpler launch-time provider selection - Add _gradient_ansi() helper for True Color per-character
  gradients in non-curses output (reuses theme banner stops) - Rewrite show_help() with gradient
  section titles driven by active theme, simplified structure (5 sections, removed redundant
  Examples block) - Remove hardcoded _GOODBYE_GRADIENT; goodbye message now uses active theme's
  banner gradient like the greeting


## v0.18.0 (2026-04-10)

### Features

- Random theme rotation, settings UX polish
  ([`34c4889`](https://github.com/thepixelabs/altergo/commit/34c48892a3d52a998f5de36465daf94d41c94d92))

- Add random theme toggle with frequency slider (often↔rarely) to Appearance settings page — rotates
  theme automatically every N sessions - Fix theme auto-select: cursor movement now updates
  selection marker (◆) so save always reflects what the user sees - Consolidate 6 redundant
  load/save helpers into generic _load_bool_setting - Single atomic write in interactive_settings
  instead of 5+ separate saves - Gradient accent fade on settings separator line - Expanded footer
  nav hints with vim keybindings


## v0.17.1 (2026-04-10)

### Bug Fixes

- Suppress noisy output when applying settings on quit
  ([`b8d69f1`](https://github.com/thepixelabs/altergo/commit/b8d69f1bc2b937e8e1d1a2923bbff8cc5e678341))

### Documentation

- Add settings TUI guide, update architecture for v0.16
  ([`e775199`](https://github.com/thepixelabs/altergo/commit/e775199207c915a61a22c6cc9ebedd19fde8da22))

- New docs/settings.md covering the three-page settings TUI - Update docs/architecture.md with
  current code structure, settings schema, and dependency list - Update version references from
  v0.5.0 to v0.16.0+


## v0.17.0 (2026-04-10)

### Features

- Multi-page settings TUI with live theme preview
  ([`c5ed3c5`](https://github.com/thepixelabs/altergo/commit/c5ed3c56107829b8c932e6df5e0a44c8d7b4791f))

Replace the single-page credentials settings screen with a three-page TUI accessed via altergo
  --settings:

- Appearance: theme picker with live color preview, gradient swatches, and launch animation toggle -
  Behavior: toggles for greeting messages, goodbye messages, and update checker - Credentials:
  shared CLI credentials (upgraded visual style)

Navigation via arrow keys, h/l, Tab between pages. Themes auto-select on cursor movement with
  instant color recoloring. All settings saved in a single atomic write to .altergo.json.


## v0.16.1 (2026-04-10)

### Bug Fixes

- Use star spinner for launch animation across all themes
  ([`1f0a7cb`](https://github.com/thepixelabs/altergo/commit/1f0a7cbea024ca686b09312efc37c80e94979a80))


## v0.16.0 (2026-04-10)

### Features

- Full-text conversation search with project filtering and quoted phrases
  ([`c4b4a95`](https://github.com/thepixelabs/altergo/commit/c4b4a95e84473a6b560bbaf6833f65e243a7c62a))

- Add `altergo --search` for searching across all session conversation history - Three-phase TUI:
  project filter → search input → scrollable results - Case-insensitive matching, "quoted phrases"
  for exact matches, AND logic - Results sorted newest-to-oldest with snippet previews and role
  indicators - Animated progress bar with braille spinner during scanning - Add `/` search hint to
  help text navigation section


## v0.15.1 (2026-04-10)

### Bug Fixes

- Smooth gradient on greeting/goodbye messages, add picker search
  ([`6a535a5`](https://github.com/thepixelabs/altergo/commit/6a535a5baa36493e45fcc915b6b163d67e543584))

- Replace chunked two-color fade with per-character interpolated gradient on greeting text, goodbye
  messages, and onboarding logo - Goodbye messages now show emoji + purple-blue-cyan-green gradient
  instead of dim text with "altergo" prefix - Add vim-style / search to the resume session picker
  with live filtering


## v0.15.0 (2026-04-10)

### Features

- Per-message emoji, gradient greetings, left-aligned banner, first-run onboarding
  ([`6c9bf07`](https://github.com/thepixelabs/altergo/commit/6c9bf076ba458b241f77a72b869895f521c6b20f))


## v0.14.0 (2026-04-10)

### Features

- Opt-out version checker, hourly greetings, launch-handoff spinners
  ([`d8d0407`](https://github.com/thepixelabs/altergo/commit/d8d04072706a9cfae44de1e2b605ba97595e3edd))

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


## v0.13.0 (2026-04-10)

### Features

- Show short version tag to the right of the banner logo
  ([`b9c7493`](https://github.com/thepixelabs/altergo/commit/b9c74933fddcbac57460985e63d7ae382567c667))

Renders v<version> vertically centered against the figlet block, in the theme's mid gradient stop so
  it reads as part of the logo. Pinned to the logo's natural width so it hugs the figlet rather than
  drifting to the terminal's right edge.


## v0.12.0 (2026-04-10)

### Features

- Add color themes with live launcher cycle
  ([`d9773a9`](https://github.com/thepixelabs/altergo/commit/d9773a937a5a53ab682c2bec933eff6f34c33eba))

Introduces a THEMES catalog (ocean, forest, lavender, sunset, mono, rainbow) that drives every
  colored surface: help, list, settings, session picker, launcher, banner, and shell prompt. Themes
  persist in .altergo.json, can be cycled live in the launcher with 't', set via 'altergo --theme
  <name>', and route through a runtime C(role) lookup instead of hardcoded constants.

Also shows the altergo banner on --list, --setup, --settings and --theme so the logo is present
  across every top-level screen, and drops the redundant 'account: <name>' prefix line now that the
  banner shows the active account directly under the logo.


## v0.11.0 (2026-04-10)

### Features

- Show altergo logo with account name above each launch
  ([`ae99d63`](https://github.com/thepixelabs/altergo/commit/ae99d63917a9152e55e7dc0e2b263ccde1a09ee0))

Render the gradient figlet banner before handing off to the provider CLI or account shell, with the
  active account name centered directly beneath the logo and framed by ASCII stars in the same blue
  palette. Makes the current identity visible at a glance on every session start.


## v0.10.1 (2026-04-09)

### Bug Fixes

- Show goodbye message after provider exits, not before launch
  ([`21ba651`](https://github.com/thepixelabs/altergo/commit/21ba65124fc7f8f8819d62a47ff64e54c4904d47))


## v0.10.0 (2026-04-09)

### Features

- V0.9.0 — active account pointer, wire launcher, restructure help
  ([`48f535a`](https://github.com/thepixelabs/altergo/commit/48f535a40c44d49f9d3a3407b409b6a9a3241548))

- Add --use <name> to persist active account in ~/.altergo/.altergo.json - Bare altergo now
  resolves: explicit arg → active_account → single account → launcher → error - Wire
  interactive_launcher() as default entry when multiple accounts exist - Add 'd' key in launcher to
  set active account with confirmation flash - Show active account indicator in launcher header -
  --resume respects active_account when multiple accounts exist - Restructure --help into Quick
  Start / Account Management / Session / Advanced / Examples / Navigation - Fix save_settings() to
  merge-write (preserves active_account alongside shared credentials) - Remove 'default' from
  reserved names — no longer special-cased - _prompt_account_name() no longer defaults to the string
  'default'


## v0.9.0 (2026-04-09)

### Features

- Rich-pyfiglet banner, redesigned help/TUI, provider launcher, goodbye messages
  ([`1aa3ac4`](https://github.com/thepixelabs/altergo/commit/1aa3ac4067bfe21ff111e6b4917d7886aa014ab2))

- Add show_banner() with smslant font gradient (#00d7ff→#005fd7) via rich-pyfiglet - Standardize
  color tokens (_C_COMMAND, _C_ARG, _C_HEADER, _C_DIM, etc.) - Rewrite show_help() with new palette,
  section separators, and split arg coloring - Add 15-message _GOODBYE pool printed before every
  os.execvpe() handoff - Add interactive provider+account launcher TUI (_draw_launcher,
  build_launcher_menu) shown automatically when no args given and 2+ accounts exist - Resume picker:
  size column (7-char, amber warning >10MB), (no prompt) dim fallback - Add size_warn color pair
  (amber 220) to _picker_attrs


## v0.8.1 (2026-04-09)

### Bug Fixes

- --resume always launched with hardcoded default account
  ([`1ad5b1b`](https://github.com/thepixelabs/altergo/commit/1ad5b1bfb159727fe1a4bbac27cd154265f7c887))


## v0.8.0 (2026-04-09)

### Features

- **setup**: Interactive account name + multi-provider selection
  ([`9d1a9e6`](https://github.com/thepixelabs/altergo/commit/9d1a9e6c2f28b8f072c8c8399fc28aa4cab0ec0b))

--setup now prompts for account name when no --name is given (TTY), shows a numbered provider
  checklist with installed binaries pre-checked, and wires only the selected providers'
  dotdirs/symlinks.

New flags: --setup --provider <p>[,<p>] specify providers non-interactively <account> --provider <p>
  select provider at launch time

Provider manifests (claude, gemini) drive all setup/teardown/launch logic. Accounts persist their
  provider list in account.json. Existing accounts without account.json are treated as claude-only.


## v0.7.1 (2026-04-09)

### Bug Fixes

- Clarify setup/teardown help text and add Accounts section
  ([`c1f43cb`](https://github.com/thepixelabs/altergo/commit/c1f43cb649a2ef19eb1247882409a3bf518f8f2c))


## v0.7.0 (2026-04-07)

### Bug Fixes

- Safer migration backup order, additional edge-case tests
  ([`25c2711`](https://github.com/thepixelabs/altergo/commit/25c27118925e06fb3d25014583815e67cc482d23))

### Features

- **resume**: Rich session picker with preview pane and animated nav
  ([`ebb7b41`](https://github.com/thepixelabs/altergo/commit/ebb7b41657179e187d6e8a8f196e34b92164be09))

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


## v0.6.0 (2026-04-07)

### Bug Fixes

- Apply CEO messaging feedback — tagline, migration output, credential sharing note
  ([`e6b57e5`](https://github.com/thepixelabs/altergo/commit/e6b57e5a4e5f6c248896a6843d000e4d83eb352f))

- Tagline: 'Your other Claude.' → 'Switch Claude identities. Keep your context.' - migrate_legacy():
  print 4-line visible block + write MIGRATED.txt audit file (CEO: silent one-liner is wrong for a
  one-time destructive rename) - do_setup(): add 'Isolates Claude. Shares AWS/GCP/Docker by
  default.' footer - tests/conftest.py: force local altergo.py over installed site-packages -
  test_migrate_legacy_prints_once: update assertion for new multi-line output

- **ci**: Repair release pipeline, homebrew-bump YAML, pip-audit, drop py3.9
  ([`34adc5e`](https://github.com/thepixelabs/altergo/commit/34adc5e79366d6a0a0e8f48327761380040afc3e))

- release.yml: pass GH_TOKEN as checkout token so credentials persist on the origin remote;
  semantic-release's plain 'git push' now auths - homebrew-bump.yml: replace heredocs with { echo; }
  blocks — heredoc terminators at col 0 broke the YAML run: | literal block scalar - ci.yml +
  pyproject.toml: drop Python 3.9 (EOL 2025-10); code uses PEP 604 'str | None' which is 3.10+ -
  security.yml: remove invalid pip-audit --require-hashes=false (--require-hashes is a boolean flag,
  no argument)

### Documentation

- Apply CEO messaging feedback — credential sharing framing, migration output
  ([`5bfe70f`](https://github.com/thepixelabs/altergo/commit/5bfe70fbea4bdb6b23e3fdae15d06d62c7daab23))

- New altergo wordmark + README rewrite for v0.5.0
  ([`00f766e`](https://github.com/thepixelabs/altergo/commit/00f766e2ce77683605bb2c24d3ad853600e5aaeb))

Add docs/logo-dark.svg and docs/logo-light.svg with the cyan-blade wordmark (alt+r indigo, e+go
  contrast, glowing skewed blade between t and e). Reference them via <picture> at the top of
  README.md for light/dark adaptation.

Rewrite README to match the landing page (v0.5.0): pipx and safer curl install, named-account-first
  quick start, full command table, --settings TUI explanation, complete symlink list, macOS Keychain
  note, CD badge beside CI.

Co-Authored-By: Claude Opus 4.6 (1M context) <noreply@anthropic.com>

- Update all docs for v0.5.0 N-account support
  ([`07a276d`](https://github.com/thepixelabs/altergo/commit/07a276d29f9945ec34a7a260db381903424540c8))

- Update README for v0.5.0 N-account support
  ([`24406de`](https://github.com/thepixelabs/altergo/commit/24406de64418f492e4b5a578d0cc70a3e05fc85b))

- Update tagline to 'Switch Claude identities. Keep your context.'
  ([`a8e2179`](https://github.com/thepixelabs/altergo/commit/a8e2179610ae811cff33a3bbb5f0f0b6c173fa5a))

### Features

- N-account support — named accounts, auto-migration, --setup --name
  ([`9518362`](https://github.com/thepixelabs/altergo/commit/9518362866ad8670212e738b0978c6a0dd2708a2))

- ACCOUNTS_DIR layout: ~/.altergo/accounts/<name>/ replaces single ~/.altergo/ - resolve_account(),
  validate_account_name(), list_accounts() helpers - Auto-migration: detects legacy
  ~/.altergo/.claude/ layout, renames to accounts/default/ on first run, preserves backup at
  ~/.altergo/.legacy-backup/ - _looks_like_account() disambiguates account names from claude
  pass-through args - altergo <name> routes to named account; unknown name prints actionable error -
  --setup --name <name> and --teardown --name <name> support - All launchers and
  do_setup/do_teardown parameterized over account name - SYMLINK_HOME_DIRS credential symlinks
  created at account_home level - show_help() updated with named account examples

- Update landing page for v0.5.0 N-account support
  ([`bc9e1e6`](https://github.com/thepixelabs/altergo/commit/bc9e1e6066b62e486b542ce0fb920343d62778b3))

- Update landing page for v0.5.0 N-account support
  ([`3205a2a`](https://github.com/thepixelabs/altergo/commit/3205a2ae44677aa5046bc10bcb3692d08facddf9))


## v0.5.0 (2026-04-07)

### Documentation

- Add architecture and how-it-works reference pages (need v0.5.0 update)
  ([`fbbee77`](https://github.com/thepixelabs/altergo/commit/fbbee77ce82e4a11a7467e46e4c15770d30772d9))

- Update for v0.5.0 settings TUI and credential sharing
  ([`a4162fe`](https://github.com/thepixelabs/altergo/commit/a4162fedc962632f01d6763d73bfcef1c2ea8e47))

- Add --settings command to command reference and features section - Document per-tool credential
  sharing (catalog, default-on/off categories) - Reframe altergo shell and altergo -- as power-user
  escape hatches - Document ~/.altergo/.altergo.json settings persistence path - Update migration
  guide

Co-Authored-By: Claude Sonnet 4.6 <noreply@anthropic.com>

### Features

- Colored --help with OSC 8 links, pixelabs branding, bump pyproject to v0.5.0
  ([`57e585e`](https://github.com/thepixelabs/altergo/commit/57e585e827fc7e5ba28e5c7e204147d13eddabbf))

- Replace print(__doc__) with show_help() — colored output via existing _c() helper, clickable OSC 8
  hyperlinks to pixelabs.net and claude.ai/code - Attribution footer: non-affiliation disclaimer +
  Claude trademark notice - Bump pyproject.toml version to 0.5.0 to match altergo.py

- Settings TUI for configuring shared CLI credentials
  ([`a2dff54`](https://github.com/thepixelabs/altergo/commit/a2dff5431482384b072a9e81bdbe37a2619bd413))

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


## v0.4.0 (2026-04-07)

### Bug Fixes

- Bump version to 0.4.0, add smoke tests to fix CI no-tests exit 5
  ([`a50e336`](https://github.com/thepixelabs/altergo/commit/a50e3362338b14e97140b3982c41fa5229a9c27d))

- Footer nav element was inheriting nav{position:fixed;top:0} — change to div
  ([`2781aed`](https://github.com/thepixelabs/altergo/commit/2781aed4f110f3a7c8129c69cf067d5d5df4f6c9))

The bare 'nav' CSS selector applied to ALL nav elements including the footer's <nav
  class="footer-links">, causing it to teleport to the top of the viewport above the main navigation
  bar.

Co-Authored-By: Claude Sonnet 4.6 <noreply@anthropic.com>

- **footer**: Clean up footer — remove duplicate license text, add ❤️ 👾, make License a proper link
  ([`d42e7be`](https://github.com/thepixelabs/altergo/commit/d42e7bee6167870ec519ce32cb88f08fb4bdd770))

Co-Authored-By: Claude Sonnet 4.6 <noreply@anthropic.com>

- **footer**: Purple heart, remove duplicate GitHub link, keep PolyForm Shield 1.0.0 License
  ([`b642a6c`](https://github.com/thepixelabs/altergo/commit/b642a6c08c585ea5946c028a75d1b6d9948de123))

Co-Authored-By: Claude Sonnet 4.6 <noreply@anthropic.com>

- **ui**: Comprehensive mobile/tablet responsive fixes for landing page
  ([`61a0547`](https://github.com/thepixelabs/altergo/commit/61a0547d9c4f26694f89d1a5de3aa9aa189505d2))

- Hero: reduced gap on narrow screens, terminal shrinks gracefully, buttons meet 44px touch target
  minimum - Nav: hamburger and theme toggle bumped to 44×44px, mobile overlay uses safe-area insets
  for notched iPhones - Why-cards: 3→2col at 900px, 2→1col at 580px (better tablet portrait) - Docs
  section: cmd-table disables nowrap below 500px so long commands wrap; code/path strings get
  overflow-wrap to prevent horizontal scroll - Install: reduced inner padding at 375px to avoid
  double-compound margins - Footer: stacks left-aligned below 600px, divider dots hidden - All
  sections: padding reduced at ≤500px for comfortable mobile spacing - Added safe-area-inset support
  for landscape iPhone/iPad notches

Co-Authored-By: Claude Sonnet 4.6 <noreply@anthropic.com>

### Features

- Add shell + passthrough commands, custom SVG icons, docs section
  ([`3d078cc`](https://github.com/thepixelabs/altergo/commit/3d078cc325dff4c15675683b44e96d9a40991a26))

- altergo shell: opens an interactive $SHELL with HOME=~/.altergo so users can run gh auth login,
  git config, ssh-keygen, etc. in the alt account context; credentials persist across sessions -
  altergo -- <cmd> [args...]: runs any single command in alt HOME context without entering an
  interactive shell - landing page: replace all emoji icons with custom inline SVG icons for both
  why-cards (3) and feature-items (6); visually on-brand - landing page: add full Documentation
  section with command reference table, credentials/Keychain explanation, symlink map, compatibility
  note, and disclaimer link - README: document new commands with usage examples

Co-Authored-By: Claude Sonnet 4.6 <noreply@anthropic.com>

- Colored CLI output, clickable pixelabs.net link, fix docs
  ([`869b839`](https://github.com/thepixelabs/altergo/commit/869b839386380992d80149fc926fc2194b8d8349))

- ANSI colors in --setup, --teardown, --list (TTY-only, pipes unaffected) - OSC 8 clickable
  hyperlink to pixelabs.net in setup/teardown header - Fix README and migration.md: remove 'altergo
  new', correct picker usage - Green ✓ for success, yellow ⚠ for warnings, cyan for headers


## v0.1.0 (2026-04-06)

### Bug Fixes

- Altergo is now a transparent claude wrapper — no more auto-picker
  ([`cae42d3`](https://github.com/thepixelabs/altergo/commit/cae42d32afcc4d8599d5534ef5a2b217236c2812))

- altergo (no args) → claude (starts new session) - altergo [any flags] → claude [any flags] (full
  pass-through) - altergo --resume → opens interactive session picker - altergo --resume <id> →
  resumes session directly - removed 'altergo new' subcommand (redundant, just use altergo)

### Features

- Initial release of altergo v0.1.0
  ([`e166a95`](https://github.com/thepixelabs/altergo/commit/e166a9554cb82c423b993925f5081278153d44a9))

Your other Claude — switch Claude Code identities without losing a thought. Zero dependencies,
  interactive TUI, symlink-based session sharing.
