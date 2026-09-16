# Architecture

This page describes the implementation for people changing `new-feature` itself.
The package requires Python 3.13 or newer.

## Codemap

- `src/new_feature/` contains importable application code.
- `src/new_feature/app.py` is the installed CLI entry point and handles termination signals.
- `src/new_feature/cli_parser.py` and `help_text.py` define command syntax and help.
- `src/new_feature/cli.py` dispatches commands and coordinates creation, merge, teardown, and inspection.
- `src/new_feature/config.py` parses configuration and resolves global, shared, and local precedence.
- `src/new_feature/allocator.py` derives environment values and checks existing reservations.
- `src/new_feature/manifest.py` stores feature records and supplies operation locks.
- `src/new_feature/git.py` wraps Git commands; `commands.py` runs configured shell commands.
- `src/new_feature/feature_state.py` inspects worktrees and integration; `recovery.py` handles safe repairs.
- `src/new_feature/agent.py` selects agent commands, builds prompts, and launches agents.
- `src/new_feature/hook_policy.py` owns the provider-neutral managed-worktree policy.
- `src/new_feature/agent_hook.py` adapts Codex and Claude Code `PreToolUse` payloads to that policy.
- `src/new_feature/hook_install.py` merges the guard into a repository's Codex or Claude Code hook configuration.
- `main.py` and `src/new_feature/__main__.py` delegate to the installed entry point.
- `tests/` contains public-behavior tests.
- `scripts/prek_hooks/` contains repository-local quality gates copied from strictify.
- `scripts/generate_api_docs.py` generates root-document copies, Python module pages, and site navigation at build time.
- `mkdocs.yml` configures the documentation theme, plugins, and repository URLs.
- `pyproject.toml` owns package metadata and Python tool configuration.
- `prek.toml` wires the checks developers should run before commits.

## Lifecycle state and concurrency

Each control checkout owns its `.new-feature/manifest.toml`. Feature records store the
branch, worktree path, target branch, allocated environment, configuration fingerprint,
and lifecycle status. They are not automatically resolved through Git's common directory.

Creation holds the feature operation lock through setup. It writes an `initializing`
record before setup and marks it `active` only after setup succeeds. Inspection reports
an unfinished record as `setup-incomplete`. Create, merge, teardown, and doctor repair
use the same per-feature lock; manifest reads and writes that mutate state use a separate
manifest lock.

Different features can run pre-merge checks concurrently. Target checkout changes are
serialized by the target merge lock. Target checkout selection must succeed before
rollback ownership begins: only then is the original revision captured for restoration
if merge, post-merge checks, commit, or manifest bookkeeping fails. Push happens after
that rollback scope, so a push failure retains the local merge.

Git ancestry determines whether a feature is already integrated; the manifest's `merged`
status alone does not skip a merge when new commits exist. Teardown and repair also
recognize patch-equivalent branches, but reject unmerged merge commits whose conflict
resolutions cannot be represented by patch comparison.

See [Contributing](CONTRIBUTING.md) for change guidelines and [Quality](QUALITY.md)
for required checks. The generated Python module reference describes implementation
symbols; it is not a promise of a stable external Python API.
