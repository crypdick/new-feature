# new-feature

Create isolated Git worktrees with their own ports, database names, and setup commands.
Work on a feature, merge it, then remove its worktree and resources.

## Install

Install Python 3.13 or newer, Git, and uv, then install new-feature:

```bash
uv tool install new-feature
```

To configure your repository with a coding agent, install Codex or Claude Code and
make its executable available on `PATH`. From your checkout, start setup:

```bash
new-feature setup --agent codex
```

The agent inspects the project and asks for approval before changing configuration
or installing optional hooks. Run setup again to review an existing integration.
You can also configure the tool yourself.

## Usage

Start from a repository with at least one commit:

```bash
new-feature my-feature --no-agent
cd .worktrees/my-feature
# Edit and commit your changes here.
cd ../..
new-feature merge my-feature
new-feature teardown my-feature
```

Run lifecycle commands from the original checkout or a managed feature worktree.
Commands use the owning checkout's configuration and manifest. Ordinary linked worktrees
keep their own lifecycle state unless a manifest explicitly manages them. Use feature
worktrees for edits and commits. If you're already in a coding agent session, use the
printed absolute worktree path for the agent's tools.

To launch an agent in the worktree, use `new-feature my-feature --agent claude`.
Without `--agent`, creation uses `default_agent` if configured. Use `--no-agent`
to suppress it, including when you're already in an agent session.

`new-feature NAME` is shorthand for `new-feature create NAME`. Replace `NAME` with
your feature name. Names become branch and directory slugs. Use explicit `create`
when the name matches a command, such as `new-feature create setup`.

Inspect features, check their state, or get command help:

```bash
new-feature list
new-feature doctor
new-feature doctor --repair
new-feature create my-feature --dry-run
new-feature COMMAND --help
```

Replace `COMMAND` with a command name. Dry runs print environment values without
creating a worktree or reserving values.

## Project configuration

All settings are optional. Put shared settings in `.new-feature.toml`:

```toml
target_branch = "main"
setup = ["uv sync"]
pre_merge = ["uv run pytest"]
post_merge = ["uv run pytest"]
teardown = []

[env]
WEB_PORT = { allocate = "port", min = 3000, max = 3999 }
WORKER_ID = { allocate = "integer", min = 1, max = 15 }
DATABASE_NAME = { allocate = "name", prefix = "myapp", max_length = 63 }
CACHE_NAMESPACE = { allocate = "slug", prefix = "myapp" }
CACHE_DIR = { allocate = "path", base = ".new-feature/cache" }
APP_ENV = { value = "development" }
```

`target_branch` is the branch features start from and merge into.
Keep personal preferences in the ignored `.new-feature.local.toml`:

```toml
default_agent = "codex"
pull_before_create = true
push = true
agents = { custom = ["custom-agent", "--prompt"] }
```

Configuration loads in this order, with later sources overriding earlier ones:

1. `~/.config/new-feature/config.toml`, which accepts only `default_agent`.
   If you set `XDG_CONFIG_HOME`, its path is `$XDG_CONFIG_HOME/new-feature/config.toml`.
2. `.new-feature.toml`, or `[tool.new-feature]` in `pyproject.toml` if `.new-feature.toml` is absent.
3. `.new-feature.local.toml`, which also works on its own.

Local values and command lists replace shared values. Entries in `agents` and `env`
override by name. In `pyproject.toml`, use `[tool.new-feature.env]` instead of `[env]`.
You can also put agent, pull, and push preferences in shared configuration as repository defaults.

By default, new-feature uses `main` as the target branch, launches no agent, skips
pull and push, and runs no commands or allocations. With `pull_before_create = true`,
it fast-forwards the clean target checkout using its upstream. With `push = true`,
it pushes the merged target branch to `origin`.

Codex and Claude have built-in aliases, which `agents` can add to or override.
`--agent` accepts a configured name or an executable command, such as
`--agent "custom-agent --prompt"`, parsed without a shell.
The generated prompt is the final argument. Override it with `create_prompt` or
`setup_prompt` in configuration, or `--prompt` for one invocation.

Lifecycle commands run sequentially in a shell. `setup`, `pre_merge`, and `teardown`
run in the feature worktree. `post_merge` runs in the original checkout before committing.
A nonzero exit stops the operation.

Commands and launched agents receive allocated values plus `NEW_FEATURE_NAME`,
`NEW_FEATURE_SLUG`, `NEW_FEATURE_BRANCH`, `NEW_FEATURE_WORKTREE`, and `NEW_FEATURE_REPO_ROOT`.
Existing shells and agent sessions don't inherit these values. Run manual commands with
`new-feature exec NAME -- COMMAND ...` to restore the recorded environment and working
directory, for example `new-feature exec my-feature -- uv run pytest`. Names normalize
to exact slugs; partial matches are rejected. Standard input, output, and errors are
inherited, and the child's exit code is returned (128 + signal for signal termination).
Arguments run without a shell; use `sh -c` explicitly for shell expansion or pipelines.

Multiple `exec` commands can run in one feature, such as a server and its tests.
Creation, merge, teardown, and repair of that feature are refused while an `exec`
command runs. Interrupted commands terminate their process group.

Port reservations span all port variables in this repository. Availability checks don't
hold ports open or reserve them against other repositories or programs. Integer reservations
are per variable. Without explicit bounds, ports use 1024-65535 and integers use 0-65535.

Use `name` for database identifiers, with `max_length` set to your database's identifier length limit.
Use `slug` for readable namespaces in the form `prefix-feature-slug`. Paths return
`base/feature-slug` without creating directories. Relative paths resolve from the
command's working directory.

## Lifecycle

Creating an active feature again reuses its worktree and environment without
rerunning setup. If setup fails, new-feature attempts cleanup. If cleanup fails or
`doctor` reports `setup-incomplete`, save needed work, then tear down and recreate
the feature.

The `new-feature merge NAME` command requires clean feature and target checkouts
and refuses merge conflicts. Failed merges attempt to restore the target checkout
and remove non-ignored untracked files created there. Rollback doesn't undo
external effects such as database changes.

Pass additional arguments after `NAME` to `git merge`, for example
`new-feature merge NAME --no-ff --no-edit`. When Git arguments are supplied,
they are passed as-is, and new-feature skips its default conflict preflight so
Git's merge options control conflict handling. Git may commit or fast-forward
before post-merge checks; failed merges or checks still attempt rollback.

Merge-check failures print a log path under `.new-feature/diagnostics/merge-failures/`.
If push fails, rerun merge to retry. Merge leaves the worktree in place. Run teardown
afterward, before creating another feature with the same name.

Teardown runs your cleanup commands, then removes the worktree and branch. If
cleanup fails, removal stops even with `--force`. Use `--force` only to discard
uncommitted or unmerged work deliberately, or bypass process protection. If the
feature record is missing, teardown skips configured cleanup and can still remove the worktree.

Use `new-feature teardown NAME --dry-run` to preview the absolute worktree path,
branch, target, cleanup commands, removal actions, and refusal reasons. Preview
exits 1 when preflight refuses teardown and 0 otherwise. It runs no cleanup and
creates no lock files or reservations. Concurrent changes can invalidate its
snapshot, and preview cannot predict cleanup failure. `--force --dry-run` previews
forced removal; cleanup failure still stops real removal.

On Linux, teardown also refuses processes owned by your user whose working
directory is the worktree or a directory beneath it. It checks before cleanup and
again immediately before removal. Stop those processes or use
`--force`, which bypasses this check without stopping them. Process protection is
best effort: it skips processes that disappear or have unreadable `/proc/PID/cwd`,
does not find processes that only hold open files or work elsewhere, and cannot
prevent processes entering the worktree after the scan. An unavailable `/proc`
scan refuses teardown unless `--force` is supplied.

If you tear down the worktree containing your shell's current directory, change back
to the original checkout afterward; a CLI cannot move its parent shell.

Teardown accepts `patch-equivalent` branches, whose patches already exist in the
target, except branches with unmerged merge commits.

Use `new-feature doctor --repair` to clean up stale feature records and branches
whose worktrees no longer exist. Repair preserves unmerged work and unreadable
worktrees. It doesn't recreate missing worktrees. Doctor exits nonzero while issues remain.

`list --json` (also `status --json`) and `doctor --json` emit one JSON document on
stdout. Diagnostics remain on stderr. `schema_version` is `1`; successful reports
contain `command` (`list` or `doctor`), `ok`, and a `features` array sorted by slug. List's `ok` means
inspection succeeded; doctor's `ok` means no feature has remaining issues.
Each feature includes `name`, `slug`, `branch`, `target_branch`, absolute `worktree`,
lifecycle `status`, human `state`, `issues`, `worktree_exists`, `branch_exists`,
`clean`, `integration`, `config_drift`, `setup_incomplete`, and `worktree_error`.
`clean` and `integration` are null when unavailable; `worktree_error` is null when
inspection succeeds. Integration is `merged`, `patch-equivalent`, or `unmerged`.
Lifecycle status is `initializing`, `active`, or `merged`. Issue labels are
`setup-incomplete`, `missing-worktree`, `worktree-error`, `missing-branch`, `dirty`,
`unmerged`, and `config-drift`. Allocated environment values are omitted.

Doctor also includes `repairs`, an array of `{"slug": "...", "message": "..."}`.
`doctor --repair --json` reports remaining features after repair. Expected command
failures emit `{"schema_version": 1, "error": {"code": "command-failed", "message": "..."}}`
and exit 1. Invalid inspection arguments with `--json` emit the same error envelope
with code `invalid-arguments` and exit 2. Doctor still exits 1 while reported issues remain.
Treat documented field names, issue labels, and error codes as stable within
schema version 1; accept additional fields and inspect `issues` and `integration`
instead of parsing human `state` or messages.

Setup and creation ignore `.new-feature/`, `.worktrees/`, and `*.local.toml` locally
without changing your tracked `.gitignore` file.

## Agent guards

Install optional hooks to keep coding agents on feature branches and require
`new-feature` for worktree creation, removal, and merging into the target branch:

```bash
new-feature install-rules           # tracked .i-insist/new-feature.toml
new-feature install-rules --global  # ~/.i-insist/new-feature.toml
```

The installer also sets up i-insist. Restart your coding agent and review `/hooks`
after installation. Reinstalling replaces generated rule files, so leave them unmodified.

If a guard blocks an action, follow its error message. To approve an override,
include `I insist` in a human message.
