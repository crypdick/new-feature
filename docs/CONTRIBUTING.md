# Contributing

Install Python 3.13 or newer, Git, and uv, then install development dependencies:

```bash
uv sync --locked --all-groups
```

See [Design conventions](CONVENTIONS.md) for repository design principles,
[Architecture](ARCHITECTURE.md) for the code layout, and [Quality](QUALITY.md)
for required checks.

## Releases

Every push to `main`, including documentation changes, runs checks and releases to
PyPI and GitHub. CI preserves an unpublished manual version or uses `uv version`
to increment the patch version, then commits `pyproject.toml` and `uv.lock` together.

Pull requests run checks without publishing. To recover a partial release, rerun
the workflow manually.

For manual bumps, use `uv version --bump patch` (or `minor` / `major`) to keep both
version files in sync.

## Documentation

Keep usage in `README.md` (the site homepage), contribution guidance here, design
principles in `CONVENTIONS.md`, and API reference text in package docstrings.
Site generation and navigation live in `scripts/generate_api_docs.py`; `site/` is
generated output, not an editing source.

Build the documentation site:

```bash
uv run mkdocs build --strict
```

Preview the site with `uv run mkdocs serve`. Pushes to `main` deploy to GitHub Pages.
