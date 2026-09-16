# Quality

Run the same checks used in pull requests and releases:

```bash
uv run prek run --all-files
```

The gate runs linting, formatting, type checks, dependency checks, secret scanning,
package checks, pytest, and a strict MkDocs build. Tests require 100% package coverage
with branch measurement enabled. Inspect automatic formatting changes and rerun as needed.

`prek.toml` defines the checks. `pyproject.toml` holds their settings and coverage
exclusions. Package imports also enable beartype runtime checks.

Test observable behavior through public interfaces. Coverage alone doesn't establish
correctness.
