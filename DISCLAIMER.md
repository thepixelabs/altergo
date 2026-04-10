# Disclaimer

**altergo** is fair-code software released under the [PolyForm Shield 1.0.0 License](./LICENSE).
This disclaimer supplements (but does not replace) the PolyForm Shield 1.0.0 License terms.

## No Warranty

This software is provided **"as is"**, without warranty of any kind. There is no
guarantee that it will work correctly, continuously, or at all. The authors and
contributors are not liable for any damages resulting from its use -- including
but not limited to data loss, corrupted configurations, or broken workflows.

In plain terms: if something goes wrong, you cannot hold the maintainers responsible.

## Data Risk Warning

altergo modifies your filesystem. Specifically, it creates and removes **symlinks**
inside provider data directories (`~/.claude/`, `~/.gemini/`, `~/.codex/`, `~/.copilot/`)
and `~/.altergo/`. While the tool is designed to avoid destructive operations, bugs
or unexpected edge cases could affect the accessibility of your sessions or conversation
history for any supported provider.

**Before first use, back up your provider data directories.** For Claude Code users,
a simple `cp -r ~/.claude ~/.claude-backup` is enough. Apply the same precaution for
any other provider you use with altergo. This gives you a recovery path if anything
goes sideways.

altergo does not intentionally delete conversation data. However, symlink
operations that fail partway through -- due to permission issues, disk errors, or
interruptions -- could leave your configuration in an inconsistent state.

## Not a Subscription Authenticator

altergo manages local credential files and environment isolation only. It does not
intercept, proxy, relay, or reuse authentication tokens from any provider's
subscription service. It does not route requests through any provider's API on your
behalf. Users are responsible for ensuring their use of altergo complies with each
provider's terms of service.

## No Guarantee of Compatibility

altergo depends on the internal file and directory structure used by each supported
provider. Any provider may change this structure at any time without notice. Such
changes could cause altergo to behave incorrectly or stop working entirely for that
provider.

The maintainers will make reasonable efforts to keep up with changes, but there is
no guarantee of timely updates or continued compatibility with any specific version
of any supported tool.

## Not Affiliated with Any Provider

altergo is an independent, community-built tool. It is **not** developed, endorsed,
sponsored, or supported by any of the companies whose products it works with.

Trademark acknowledgments:
- "Claude" and "Claude Code" are trademarks of Anthropic, PBC.
- "Gemini" and "Gemini CLI" are trademarks of Google LLC.
- "Codex" and "Codex CLI" are trademarks of OpenAI, LLC.
- "GitHub Copilot" is a trademark of GitHub, Inc.

Any issues with altergo should be directed to this project's issue tracker, not to
any provider's support channels.

## Use at Your Own Risk

By using altergo, you acknowledge that:

- You understand it modifies filesystem symlinks in your home directory.
- You are responsible for maintaining backups of any data you consider important.
- The software may break without warning if any supported provider's internals change.
- The maintainers have no obligation to fix bugs, respond to issues, or continue development.

This is a tool built by developers, for developers, in good faith. But it comes
with no safety net beyond what you set up yourself.

---

Copyright (c) 2026 thepixelabs. Released under the PolyForm Shield 1.0.0 License.
