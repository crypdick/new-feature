# Architecture

`new-feature` is a Python 3.13 package with production-oriented quality gates installed from the beginning.

## Codemap

- `src/new_feature/` contains importable application code.
- `src/new_feature/app.py` owns the current executable behavior.
- `src/new_feature/codex_hook.py` owns the Codex `PreToolUse` target-branch policy.
- `src/new_feature/codex_install.py` merges that policy into the current repository's Codex hook configuration.
- `main.py` is a thin local entry point that delegates to the package.
- `tests/` contains public-behavior tests.
- `scripts/pre_commit_hooks/` contains repository-local quality gates copied from strictify.
- `scripts/generate_api_docs.py` generates the documentation homepage and API pages at build time.
- `mkdocs.yml` owns the documentation-site configuration.
- `pyproject.toml` owns package metadata and Python tool configuration.
- `.pre-commit-config.yaml` wires the checks developers should run before commits.

## Invariants

- Keep entry points thin. Put behavior in named package modules.
- Tests exercise public behavior rather than private implementation details.
- Package coverage must stay at 100%.
- Prefer typed boundaries and explicit domain names over anonymous primitive plumbing.
- Do not add junk-drawer modules such as `utils.py`, `helpers.py`, or `misc.py`.
