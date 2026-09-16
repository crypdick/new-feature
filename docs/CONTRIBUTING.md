# Contributing

These instructions are for people changing `new-feature` itself.

## Development

Install Python 3.13 or newer, Git, and uv, then install the locked development dependencies:

```bash
uv sync --locked --all-groups
```

Follow the repository's `CONVENTIONS.md` for design principles. Keep entry points thin,
test observable behavior, and use named domain modules instead of catch-all files such
as `utils.py` or `helpers.py`. See [Architecture](ARCHITECTURE.md) for the code layout
and [Quality](QUALITY.md) for the required checks.

## Releases

Every push to `main`, including docs-only changes, runs quality gates and publishes
an automatic release. CI preserves an unpublished manual version; otherwise it
increments the latest patch with `uv version`, updating `pyproject.toml` and
`uv.lock` together. It verifies and commits that version before publishing to PyPI
and creating the GitHub release. Manual bumps remain available with
`uv version --bump patch` (or `minor`/`major`).

Retries reuse the release commit without another bump. Superseded runs defer to
the newer push. The bot's version commit does not trigger another workflow run.
Pull requests run quality gates without publishing.

The release workflow can also run manually to recover from a partial release.

## Documentation

The documentation site uses the repository's `README.md` as its homepage and generates
its API reference from package docstrings. Keep the README focused on installing,
configuring, and using `new-feature`; put contributor instructions here and implementation
details in [Architecture](ARCHITECTURE.md).

`scripts/generate_api_docs.py` copies the README and design conventions into virtual
site pages, builds the module index, and defines navigation under Using new-feature,
Contributing, and Internals. Module pages are discovered from package source files.
Edit the source Markdown and docstrings, not generated files under `site/`.

Build the site before committing documentation changes:

```bash
uv run mkdocs build --strict
```

To preview the site locally with live reload, run `uv run mkdocs serve`. Pushing to
`main` builds and deploys the site through GitHub Pages.
