# Quality

This page describes checks for contributors to `new-feature`.

`uv run prek run --all-files` is the canonical aggregate quality gate used locally,
in pull requests, and before publishing a release. Some checks automatically format
files; review their changes and rerun the gate when needed.

The gate includes:

- Ruff linting and formatting, mypy, vulture, and deptry.
- Secret scanning, file hygiene, package metadata, and source-distribution checks.
- Repository-local checks for exception handling, file length, and private imports in tests.
- pytest with parallel workers, timeouts, and a 100% package coverage threshold,
  with branch measurement enabled.
- A strict MkDocs build, including generated Python module documentation.

`prek.toml` defines the checks; `pyproject.toml` defines their tool settings and
coverage exclusions. Package imports also enable beartype runtime checks. Test
observable behavior through public interfaces; meeting a coverage threshold alone
does not establish correctness.
