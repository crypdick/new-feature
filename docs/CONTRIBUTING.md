# Contributing

Install Python 3.13 or newer, Git, and uv, then install development dependencies:

```bash
uv sync --locked --all-groups
```

See `CONVENTIONS.md` for repository design principles,
[Architecture](ARCHITECTURE.md) for the code layout, and [Quality](QUALITY.md)
for required checks.

## Releases

Every push to `main`, including documentation changes, runs checks and publishes a
release. CI preserves an unpublished manual version or increments the patch version
with `uv version`, updating `pyproject.toml` and `uv.lock` together. It commits the
version, publishes to PyPI, and creates a GitHub release.

Pull requests run checks without publishing. To recover a partial release, rerun
the workflow manually.

For a manual version bump, use `uv version --bump patch`. Replace `patch` with
`minor` or `major` for those version increments.

## Documentation

The site homepage comes from `README.md`. Edit `README.md` for usage instructions,
this guide for contribution instructions, and package docstrings for the API reference.
Edit `CONVENTIONS.md` for design principles. Don't edit generated files in `site/`.
For site generation and navigation, edit `scripts/generate_api_docs.py`.

Build the documentation site:

```bash
uv run mkdocs build --strict
```

Preview the site with `uv run mkdocs serve`. Pushes to `main` deploy to GitHub Pages.
