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

CI also runs `actionlint` on every GitHub Actions workflow before the quality and
release jobs, on pull requests and pushes to `main`. For local workflow changes,
install `actionlint` and run `actionlint` from the repository root. The workflow
pins its actionlint release and verifies the downloaded archive's SHA-256 checksum.
Update both values together when upgrading it.

All workflow actions use full commit SHA pins with version comments. When upgrading
an action, verify the new commit against its upstream release and update both the
pin and comment.
