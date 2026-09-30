# Quality

Run the same checks used in pull requests and releases:

```bash
uv run prek run --all-files
```

The quality checks cover linting, formatting, type checks, dependency checks, secret
scanning, package checks, pytest, and a strict MkDocs build. Tests require 100%
package coverage with branch measurement enabled. Inspect automatic formatting
changes and rerun as needed.

The `prek.toml` file defines the checks. The `pyproject.toml` file holds their
settings and coverage exclusions.
