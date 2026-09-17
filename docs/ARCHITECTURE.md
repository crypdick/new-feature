# Architecture

The Python package lives in `src/new_feature/`. Start with these modules:

- `app.py` and `cli_parser.py`: entry point, signals, and argument parsing.
- `cli.py`: create, merge, teardown, and inspection workflows.
- `config.py` and `allocator.py`: configuration and environment allocation.
- `manifest.py`: feature records and locks.
- `git.py` and `commands.py`: Git and shell execution.
- `feature_state.py` and `recovery.py`: inspection and repair.
- `agent.py`: agent selection, prompts, and launch.
- `hook_policy.py`, `rule_checker.py`, and `hook_install.py`: worktree policy, neutral i-insist checker, and provider-rule installation. `agent_hook.py` retains legacy entrypoints for older installations.

Each original checkout owns its manifest. Creation records `initializing` before setup
and `active` after success. Inspection reports unfinished setup as `setup-incomplete`.

Create, merge, teardown, and repair share a per-feature lock. Manifest updates use a
separate lock. Pre-merge checks can run concurrently for different features, but a
target merge lock serializes checkout changes.

Merge selects the target checkout before capturing the revision for rollback. Failures
during merge, post-merge checks, commit, or bookkeeping trigger restoration. Push happens
outside that scope, so push failure retains the local merge.

Git ancestry determines integration. The manifest's `merged` status doesn't hide later
commits. Teardown and repair also accept patch-equivalent branches, excluding unmerged
merge commits whose conflict resolutions patch comparison can't represent.

Inspection reports unreadable worktrees as `worktree-error` and leaves them untouched.
`list` still succeeds, while `doctor` exits nonzero.

Git commands, lifecycle commands, and agents ignore inherited Git repository-location
overrides. Their working directory selects the repository. Transport, authentication,
and explicitly configured lifecycle environment values remain available.

The generated module reference describes internals, not a stable external Python API.
See [Contributing](CONTRIBUTING.md) for development and [Quality](QUALITY.md) for checks.
