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

Altergo operates entirely locally. It reads session files from `~/.claude/`, manages symlinks on the local filesystem, and launches the `claude` CLI with a modified HOME. It makes no network connections, collects no telemetry, and transmits no data.
