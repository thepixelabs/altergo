# Security Policy

## Supported Versions

Only the latest release is supported with security updates.

| Version | Supported |
| ------- | --------- |
| latest  | Yes       |
| older   | No        |

## Reporting a Vulnerability

If you discover a security vulnerability, please report it responsibly.

**Preferred:** Open a [GitHub Security Advisory](https://github.com/thepixelabs/altergo/security/advisories/new) on this repository.

**Alternative:** Email security concerns to the maintainers via the contact information on the [GitHub organization profile](https://github.com/thepixelabs).

Please include:
- A description of the vulnerability
- Steps to reproduce
- Any potential impact

## Response Timeline

Best effort for a volunteer-maintained project:
- Acknowledge within 7 days
- Initial assessment within 14 days
- Fix for confirmed vulnerabilities as soon as practical

## Scope

altergo operates almost entirely locally. It reads session files from `~/.claude/`, manages symlinks on the local filesystem, and launches provider CLIs (`claude`, `gemini`, `codex`, `copilot`) with a modified `HOME`. The only outbound network connection altergo makes itself is the update check described below; the provider CLIs manage their own network traffic independently of altergo.

## Network activity

altergo makes exactly one outbound connection of its own: a daily version check against PyPI.

- **Endpoint:** `https://pypi.org/pypi/altergo/json`
- **Cadence:** At most once per 24 hours (`UPDATE_CACHE_TTL_SECONDS`, `altergo.py:1750`). First launch ever writes a timestamp-only cache record and skips the network entirely — no fetch happens until at least one cache cycle has elapsed.
- **Cache:** `~/.altergo/version_check.json` (file mode `0o600`). Stores `{schema_version, last_check, latest_version}`.
- **Thread model:** Daemon thread kicked off from `maybe_refresh_update_cache()`. It never blocks exit, never prints, and swallows every exception. A broken endpoint writes a timestamp-only record so we don't hammer it on every launch.
- **Hardening:** 3 second socket timeout, 32 KB response cap, 3-redirect cap, TLS enforced by `urllib.request`. The version string returned by PyPI is allowlisted at fetch (`^[0-9a-zA-Z.\-+]{1,32}$`) and again at render time — defence in depth against a poisoned cache or crafted PyPI response.
- **User-Agent:** `altergo/<version> Python/<M.m>`. No hostname, no account name, no path information.
- **Opt-out:** Set `"update_check": false` in `~/.altergo/.altergo.json` or toggle "Check for updates" in `altergo --settings`. When disabled, no connection is made and no cache file is written.

altergo does not collect telemetry, does not contact any other endpoint, and does not transmit session content or credentials.

## Credential storage

altergo's core isolation unit is the per-account `HOME`. Credentials live inside that `HOME` exactly where the provider CLI expects them:

| Provider | Credential file (per-account) |
|---|---|
| Claude Code | `~/.altergo/accounts/<n>/.claude/.credentials.json` |
| Gemini CLI | `~/.altergo/accounts/<n>/.gemini/oauth_creds.json` |
| Codex CLI | `~/.altergo/accounts/<n>/.codex/auth.json` |
| GitHub Copilot | `~/.altergo/accounts/<n>/.copilot/config.json` |

These are **real files** — never symlinked, never shared. Each account is a separate OAuth identity from the provider's point of view.

On macOS, by default altergo blocks each account from writing to the macOS keychain (`isolated` mode, the default since v0.44.0). A per-account `login.keychain-db` is created but kept permanently locked. Security.framework routes provider keychain writes to it and they fail; providers fall back to flat-file credentials. **Nothing lands in your real login keychain by default.** If you opt into `dedicated` mode (`--keychain dedicated`), altergo creates a per-account keychain, stores its unlock password in your real login keychain, and unlocks it at each session start. In that mode, Claude Code stores refresh tokens in the per-account keychain — credentials are keyed to that account's HOME and do not cross-contaminate other altergo accounts.

altergo never reads, copies, or moves `.credentials.json`. `do_teardown` explicitly refuses to remove it.

## Threat model

altergo is a convenience layer on top of per-account `HOME` isolation. It is **not** a sandbox. Understanding exactly what it isolates and what it does not is essential before using it for anything sensitive.

### What altergo isolates

- **Provider OAuth credentials** (`.credentials.json`, `oauth_creds.json`, `auth.json`, `config.json`) — one real file per account.
- **Provider identity metadata** — for Claude, `oauthAccount` inside `.claude.json` is kept per-account even though `mcpServers` in the same file is synced.
- **Any CLI-tool credential not explicitly enabled in the `CATALOG`** — e.g. SSH keys (`.ssh`), git identity (`.gitconfig`), GPG keys (`.gnupg`) are **off by default** and stay real-isolated unless the user enables sharing.
- **The `HOME` environment variable at launch** — every provider read/write rooted at `$HOME` lands in the account's directory, not in the primary `~/`.

### What altergo does NOT isolate

This is the part that matters for threat modelling. The following are all shared across every account by design — that sharing **is the feature** of altergo, but each is also an attack surface:

- **`settings.json`** is symlinked across accounts. Claude's settings can declare **hook scripts** that execute on session start, tool-use, and other events. A hook installed from any account runs in every other account's context. Treat `~/.claude/settings.json` as if every account could write it, because they can.
- **`CLAUDE.md`** (and equivalents like `GEMINI.md`, `AGENTS.md`) is symlinked across accounts. It is part of every session's system prompt. A user — or an agent acting on behalf of a user — editing `CLAUDE.md` in account A immediately changes the system prompt for account B. This is a shared **prompt-injection surface** if any account is under adversarial control.
- **`agents/`, `commands/`, `skills/`, `plans/`, `hooks/`** are symlinked directories. Any account can write agent definitions, custom slash commands, user skills, and (for Copilot) hook scripts that the other accounts will execute. Same cross-account execution vector as `settings.json`.
- **`mcpServers` via bidirectional sync** in `.claude.json`. A malicious MCP server registration — a server pointing to a process under attacker control, or carrying a command that runs on registration — installed in one account propagates to every other Claude account at the next `--config` or launch. See the [MCP server sync](docs/architecture.md#mcp-server-sync) section of the architecture doc for the exact merge rules.
- **`session-env/`, `file-history/`, `shell-snapshots/`, `cache/`, `projects/`, `tasks/`** are all shared. Session history is unified across accounts by design — that is altergo's primary value proposition — but it means no account's conversation history is private from any other account on the same machine.
- **`CATALOG` defaults-on entries** share several cloud-credential directories across accounts by default: `.aws`, `.config/gcloud`, `.azure`, `.docker`, `.kube`, `.terraform.d`, `.config/gh`. If the user's AWS credentials are compromised through one account, every other account has the same credentials. Review and override defaults via `altergo --settings`.

### Trust assumption

**altergo assumes every account configured on this machine is trusted by the same user.** If one account is compromised — via a malicious MCP server, a prompt-injection payload in `CLAUDE.md`, a hook script in `settings.json`, or a writable shared credential — every other account on the same machine can be influenced through the shared surfaces listed above.

altergo is not a defence against adversarial accounts. It is a convenience layer that separates OAuth identities while keeping everything else a single developer typically wants shared (session history, agent configs, cloud credentials).

If you need hard isolation between two identities, use two separate user accounts on the OS, or two separate machines.

## Upgrade safety

- **v0.22.0 `.claude.json` un-symlink** (`_sync_claude_mcps`, `altergo.py:2522-2529`). Accounts created in the short window where `.claude.json` was symlinked via `symlink_home_files` (v0.21.2 → v0.22.0) are upgraded on first run: content read through the link, link removed, content rewritten as a real file with the merged `mcpServers`. Content-preserving and atomic.
- **v0.35.3 removal of unconditional sweep and `migrate_legacy`** (`altergo.py` diff in commit `94f22ad`). The unconditional `_sweep_existing_accounts()` call from `main()` and `launch_claude()` was removed; the function is retained only as a repair helper exercised by tests. The old `_ensure_symlinked_dir` case (d) — silently moving account data into the shared store when the shared store was absent/empty — was the data-loss vector that reversion closed. Current code warns and skips case (d) instead of moving.
- **v2 `account.json` migration** (`load_account_meta`, `altergo.py:1098-1122`). Legacy accounts without `account.json` are treated in memory as `{"version": 2, "provider": "claude"}` on every read. The file is not rewritten until the next `do_config` explicitly calls `save_account_meta` — read-only sessions leave legacy accounts on disk unchanged.
