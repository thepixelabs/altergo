# CHANGELOG


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
