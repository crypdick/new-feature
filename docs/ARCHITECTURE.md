# Architecture

The Python package lives in `src/new_feature/`. Start with these modules:

- `app.py` and `cli_parser.py`: entry point, signals, and argument parsing.
- `cli.py`: create, merge, teardown, and inspection workflows.
- `config.py` and `allocator.py`: configuration and environment allocation.
- `manifest.py`: feature records and locks.
- `git.py` and `commands.py`: Git and shell execution.
- `feature_state.py` and `recovery.py`: inspection and repair.
- `agent.py`: agent selection, prompts, and launch.
- `hook_policy.py`, `rule_checker.py`, and `hook_install.py`: worktree policy, neutral i-insist checker, and provider-rule installation.

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

## Agent guards

- Worktrees: route creation and removal through `new-feature`.
- Target edits: require a feature branch, except before the first commit or for the ignored, untracked root `.new-feature.local.toml`.
- Target merges: require `new-feature merge`; feature-branch merges, `--continue`, `--abort`, `--quit`, help, and `git commit` remain allowed.
- Scope: recognize Git directory options and simple `cd` commands, not arbitrary scripts, Git aliases, or shell file writes.
- Installation: `install-rules` installs or upgrades i-insist to at least 0.4.0 from PyPI, runs `i-insist ensure` to verify enabled hooks. i-insist runs the rules; setup atomically replaces only the provider-owned registration. There are no per-rule user customizations.
- Only `install-rules` is supported, with `--global` for user-level installs. Native guard commands and installer aliases are rejected rather than interpreted as feature names. The provider does not read or migrate native hook settings; i-insist owns harness registration.
- Checker protocol: JSON `null` allows; a nonempty string denies and supplies the message. Policy-loading and Git process exceptions propagate to the checker boundary, which exits nonzero so i-insist blocks and reports stderr.
- Overrides: accept `I insist` anywhere in the latest human message; i-insist owns approval.

The generated module reference describes internals, not a stable external Python API.
See [Contributing](CONTRIBUTING.md) for development and [Quality](QUALITY.md) for checks.
