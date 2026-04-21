# Contributing to Altergo

Thanks for your interest in contributing! Altergo is a small, focused tool and we want to keep it that way.

## Reporting Bugs

Open a [GitHub Issue](https://github.com/thepixelabs/altergo/issues/new?template=bug_report.yml) with:
- Your OS and Python version
- What you expected vs. what happened
- Steps to reproduce

## Suggesting Features

Open a [Feature Request](https://github.com/thepixelabs/altergo/issues/new?template=feature_request.yml). Keep in mind:
- Altergo is intentionally minimal
- Features that add heavy external dependencies will likely be declined

## Development Setup

```bash
git clone https://github.com/thepixelabs/altergo.git
cd altergo
python altergo.py --help
```

The tool lazy-loads a small number of terminal-polish libraries (`rich`, `pyfiglet`) and degrades gracefully if they're absent — a virtual environment is recommended but not strictly required to run against a system Python that happens to have them.

### Linting

```bash
pip install ruff
ruff check altergo.py
ruff format altergo.py
```

### Testing

```bash
pip install pytest
pytest -v
```

## Pull Requests

1. Fork the repo and create a branch from `main`
2. Use [conventional commits](https://www.conventionalcommits.org/) (`feat:`, `fix:`, `docs:`, etc.)
3. Keep changes focused — one PR per concern
4. Ensure `ruff check` and `ruff format --check` pass
5. Open a PR against `main`

## Code Style

- Python 3.10+ compatible (PEP 604 `str | None` syntax is used)
- Keep external dependencies minimal; prefer stdlib
- Core logic lives in `altergo.py`; `altergo_greetings.py` holds the greeting copy
- Use `ruff` defaults (line length 120)
