# CHANGELOG


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

- **footer**: Clean up footer — remove duplicate MIT text, add ❤️ 👾, make License a proper link
  ([`d42e7be`](https://github.com/thepixelabs/altergo/commit/d42e7bee6167870ec519ce32cb88f08fb4bdd770))

Co-Authored-By: Claude Sonnet 4.6 <noreply@anthropic.com>

- **footer**: Purple heart, remove duplicate GitHub link, keep MIT License
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
