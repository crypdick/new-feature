# Contributing

Install Python 3.13 or newer, Git, and uv, then install development dependencies:

```bash
uv sync --locked --all-groups
```

Follow `CONVENTIONS.md`. Keep entry points thin, test public behavior, and use domain
modules instead of catch-all files such as `utils.py`. See [Architecture](ARCHITECTURE.md)
for the code layout and [Quality](QUALITY.md) for required checks.

## Releases

Every push to `main`, including documentation changes, runs checks and publishes a
release. CI preserves an unpublished manual version or increments the patch version
with `uv version`, updating `pyproject.toml` and `uv.lock` together. It commits the
version, publishes to PyPI, and creates a GitHub release.

Retries reuse the release commit. Superseded runs defer to the newer push, and bot
version commits don't trigger another run. Pull requests run checks without publishing.
Rerun the workflow manually to recover a partial release.

For a manual version bump, use `uv version --bump patch`, `minor`, or `major`.

## Documentation

The site homepage comes from `README.md`. Edit it for usage, this guide for contribution,
and package docstrings for the API reference. `scripts/generate_api_docs.py` copies README
and conventions into the site and generates module pages and navigation.
Don't edit generated files in `site/`.

Build before committing:

```bash
uv run mkdocs build --strict
```

Use `uv run mkdocs serve` for preview. Pushes to `main` deploy to GitHub Pages.
