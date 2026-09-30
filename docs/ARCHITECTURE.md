# Architecture

The Python package lives in `src/new_feature/`. Start with these modules:

- `app.py` and `cli_parser.py`: entry point, signals, and argument parsing.
- `cli.py`: create, merge, teardown, and inspection workflows.
- `config.py` and `allocator.py`: configuration and environment allocation.
- `manifest.py`: feature records and locks.
- `git.py`, `commands.py`, and `execution.py`: Git, shell commands, and feature execution.
- `control_checkout.py`: verified ownership lookup across registered Git worktrees.
- `feature_state.py` and `recovery.py`: inspection and repair.
- `agent.py`: agent selection, prompts, and launch.
- `hook_policy.py`, `rule_checker.py`, and `hook_install.py`: worktree policy,
  neutral i-insist checker, and rule installation for new-feature.

Each original checkout owns its manifest. Creation records `initializing` before setup
and `active` after success. Inspection reports unfinished setup as `setup-incomplete`.
Lifecycle commands resolve the current checkout through Git's worktree inventory and
matching manifest paths and branches. One matching owner selects that checkout;
multiple owners or a branch mismatch fail. Unreadable manifests fail for the current
checkout and ancestors containing it under `.worktrees`; unrelated siblings are skipped.
Unmanaged linked worktrees keep their own state. No owner is inferred from the common
Git directory. The raw Git root resolver used by guards stays checkout-local.

Create, merge, teardown, and repair share a per-feature lock. Manifest updates use a
separate lock. Pre-merge checks can run concurrently for different features, but a
target merge lock serializes checkout changes. On POSIX, `exec` holds a shared `flock`
on the same inode as the exclusive FileLock lifecycle lock. Concurrent commands can
run, while feature mutations fail fast until all commands exit. Command failure and
cancellation release the lock. Commands own a process group for cancellation cleanup.

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

Guards enforce these policies through i-insist:

- Create and remove worktrees through `new-feature`.
- Edit on a feature branch, except before the first commit or when editing the
  ignored, untracked root `.new-feature.local.toml` file.
- Merge into the target branch through `new-feature merge`. Merges on feature
  branches, `--continue`, `--abort`, `--quit`, help, and `git commit` remain allowed.

Guards recognize Git directory options and simple `cd` commands. They don't inspect
arbitrary scripts, Git aliases, or shell file writes.

Installation sets up i-insist from PyPI, verifies enabled hooks, and atomically
replaces the generated rule registration for new-feature. Checkers return JSON `null` to allow
an action or a nonempty denial message to block it. Evaluation errors exit nonzero
so i-insist blocks the action and reports stderr. The i-insist runner handles human
approval through `I insist` in the most recent human message.

The generated module reference describes internals. It doesn't define a stable
external Python API.
See [Contributing](CONTRIBUTING.md) for development and [Quality](QUALITY.md) for checks.
