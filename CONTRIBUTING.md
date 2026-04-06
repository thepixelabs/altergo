# Contributing to Altergo

Thanks for your interest in contributing! Altergo is a small, focused tool and we want to keep it that way.

## Reporting Bugs

Open a [GitHub Issue](https://github.com/thepixelabs/altergo/issues/new?template=bug_report.yml) with:
- Your OS and Python version
- What you expected vs. what happened
- Steps to reproduce

## Suggesting Features

Open a [Feature Request](https://github.com/thepixelabs/altergo/issues/new?template=feature_request.yml). Keep in mind:
- Altergo is intentionally minimal — zero dependencies, single file
- Features that add external dependencies will likely be declined

## Development Setup

```bash
git clone https://github.com/thepixelabs/altergo.git
cd altergo
python altergo.py --help
```

No virtual environment needed — the tool uses only the Python standard library.

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

- Python 3.9+ compatible
- No external dependencies
- Single-file architecture — everything lives in `altergo.py`
- Use `ruff` defaults (line length 120)
