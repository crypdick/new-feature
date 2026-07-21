# Quality

## Current Grade

| Area | Grade | Notes |
| --- | --- | --- |
| `src/new_feature/` | A- | Strict Ruff, mypy, runtime type checking, and 100% coverage gates are active. |
| `tests/` | A- | Tests are wired to public behavior and run under pytest with xdist, timeout, and coverage. |
| Quality gates | A | Ruff, mypy, vulture, deptry, detect-secrets, prek hygiene, and strictify custom hooks are configured. |

## Maintenance

`uv run prek run --all-files` is the canonical aggregate quality gate used locally and before
publishing a release.

Keep this scorecard focused on real modules. When new domain areas appear, add rows for their coverage, type safety, complexity, and test health.
