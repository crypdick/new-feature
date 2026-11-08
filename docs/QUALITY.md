# Quality

Run the same checks used in pull requests and releases:

```bash
uv run prek run --all-files
```

Checks cover static analysis, formatting, secrets, packaging, pytest, and a strict
MkDocs build. Tests require 100% package coverage with branch measurement enabled.
Review automatic fixes before accepting them.

`prek.toml` defines checks; `pyproject.toml` holds settings and coverage exclusions.

CI also validates GitHub Actions workflows with `actionlint` before quality and
release jobs. For workflow changes, run `actionlint` from the repository root.

Keep actions pinned to full commit SHAs verified against upstream releases, with
matching version comments. Keep actionlint pinned with its matching SHA-256
checksum; update both when upgrading.
