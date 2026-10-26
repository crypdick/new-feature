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
cd "$(new-feature path my-feature)"
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
Without `--agent`, creation uses `default_agent` if configured. Creation infers
`--no-agent` when `CODEX_CI=1` or `CLAUDE_CODE_CHILD_SESSION=1`, so commands issued
by Codex or Claude Code reuse the current agent session and print the worktree path.
Explicit `--agent` overrides this inference; `--prompt` in a detected session requires
explicit `--agent`. `setup` still launches its selected agent.
Use `--no-agent` to suppress launch in other runners or terminals. Detection uses
these environment markers, not TTY availability or `TERM`.

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

## Navigation and shell completion

`new-feature path NAME` prints only the absolute worktree path. It accepts an
exact normalized feature name, verifies the checkout and recorded branch, and
fails for missing or mismatched worktrees. Use it for shell navigation or agent
tool paths:

```bash
cd "$(new-feature path my-feature)"
```

Load completion in your shell, or add the matching command to its startup file:

```bash
# Bash
source <(new-feature completion bash)
# Zsh, after compinit
source <(new-feature completion zsh)
# Fish
new-feature completion fish | source
```

Completion suggests commands and managed feature names. Scripts query the
current repository when completing feature names; generating a script works
outside a repository.

## Existing branches

Create a managed checkout from an existing local or remote-tracking branch:

```bash
new-feature create review-fix --from origin/fix/parser --json
new-feature changes review-fix
# Review the checkout before running project code.
new-feature create review-fix --bootstrap --no-agent
```

`--from` uses refs already present locally and does not fetch or pull. The new
checkout starts with lifecycle status `inert`: no setup commands, file copying,
or agent launch. Import disables Git hooks, filters, and filesystem monitors. Change inspection
also disables these callbacks; inert status and teardown checks disable them too. `--from` cannot be combined with `--bootstrap`, `--agent`, or `--prompt`.

A matching local branch, such as `create fix-parser --from fix-parser`, is
attached directly and remains after teardown. Other source branches produce a
new branch named after the feature slug; teardown removes that new branch.
The configured target branch still determines integration and merge destination.

Use `path` and `changes` to inspect an inert checkout. Explicit `--bootstrap`
runs setup and activates it, with normal agent selection unless `--no-agent`
is supplied. Merge and `exec` require activation. Failed bootstrap preserves the
checkout and returns it to `inert` so you can inspect and retry. Teardown of an
inert checkout skips configured cleanup commands and retains normal file and
process protection.

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
auto-teardown = true
agents = { custom = ["custom-agent", "--prompt"] }
```

Configuration loads in this order, with later sources overriding earlier ones:

1. `~/.config/new-feature/config.toml`, which accepts only `default_agent`.
   If you set `XDG_CONFIG_HOME`, its path is `$XDG_CONFIG_HOME/new-feature/config.toml`.
2. `.new-feature.toml`, or `[tool.new-feature]` in `pyproject.toml` if `.new-feature.toml` is absent.
3. `.new-feature.local.toml`, which also works on its own.

Local values and command lists replace shared values. Entries in `agents` and `env`
override by name. In `pyproject.toml`, use `[tool.new-feature.env]` instead of `[env]`.
You can also put agent, pull, push, and automatic teardown preferences in shared configuration as repository defaults.

By default, new-feature uses `main` as the target branch, launches no agent, skips
pull and push, and runs no commands or allocations. With `pull_before_create = true`,
it fast-forwards the clean target checkout using its upstream. With `push = true`,
it pushes the merged target branch to `origin`. With `auto-teardown = true`, it runs
teardown after a successful merge, local file transfer, and any configured push.
Automatic teardown defaults to false.

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
and refuses merge conflicts. Incoming tracked paths are checked for collisions with existing local paths,
including ignored files in the target checkout. `--include-untracked` permits local files in the feature
worktree while still requiring committed changes to tracked files. Failed merges restore the target checkout only while Git state still matches the
tool-owned merge. Intervening commits, branch changes, edits, or new non-ignored
files stop automatic recovery and remain intact for manual review. An exact
merge commit completed during checks is accepted without another commit.
Rollback doesn't undo
external effects such as database changes.

Pass additional arguments after `NAME` to `git merge`, for example
`new-feature merge NAME --no-ff --no-edit`. When Git arguments are supplied,
they are passed as-is, and new-feature skips its default conflict preflight so
Git's merge options control conflict handling. Git may commit or fast-forward
before post-merge checks; failed merges or checks still attempt rollback.
`--help` and `-h` show wrapper help even after `NAME`, without running checks,
merging, pushing, or tearing down. A successful Git command that neither integrates
the branch nor prepares changes for a merge commit is treated as a failure.

Merge-check failures print a log path under `.new-feature/diagnostics/merge-failures/`.
If push fails, rerun merge to retry. By default, merge leaves the worktree in place.
Run teardown afterward, before creating another feature with the same name.

With `auto-teardown = true`, merge runs normal teardown automatically, including
for an already-merged feature. Failed merge checks, local file transfer, or push
skip teardown. Teardown failure returns nonzero and leaves the completed merge
intact; resolve the reported issue, then rerun merge or run teardown directly.
Automatic teardown uses the same safety checks as manual teardown and never
uses `--force`. Stop other processes in the feature worktree first; processes with
working directories inside it block removal. That includes your shell, so run
merge from the original checkout.

Teardown runs your cleanup commands, then removes the worktree and owned branch. If
cleanup fails, removal stops even with `--force`. Use `--force` only to discard
uncommitted or unmerged work deliberately, or bypass process protection. Normal
teardown refuses local files without identical copies in the original checkout,
except paths designated safe to delete. Checks run before cleanup and immediately
before removal; configured cleanup commands remain responsible for their own effects. If the
feature record is missing, teardown skips configured cleanup and can still remove the worktree.

Use `new-feature teardown NAME --dry-run` to preview the absolute worktree path,
branch, target, cleanup commands, removal actions, and refusal reasons. Preview
exits 1 when preflight refuses teardown and 0 otherwise. It runs no cleanup and
creates no lock files or reservations. Concurrent changes can invalidate its
snapshot, and preview cannot predict cleanup failure. `--force --dry-run` previews
forced removal; cleanup failure still stops real removal.

On Linux, teardown also refuses processes owned by your user whose working
directory is the worktree or a directory beneath it, except new-feature itself,
which moves to the original checkout before removal. It checks before cleanup and
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

Preview batch cleanup of integrated features in the current repository:

```bash
new-feature prune --merged --dry-run
new-feature prune --merged --json
```

`--merged` is required and selects merged or patch-equivalent branches using
local Git evidence. Unmerged features are skipped. Every removal uses normal
teardown, including configured cleanup, preservation of local files, branch
ownership, and process checks. There is no force or expiration policy. Other
candidates continue after a refusal. Missing worktrees require doctor repair.

JSON reports contain `schema_version: 1`, `command: "prune"`, `ok`, `dry_run`,
and a slug-sorted `features` array. Each entry contains `slug`, `branch`, absolute
`worktree`, `outcome`, and a `reasons` array. Outcomes are `removed`, `would-remove`,
`skipped`, or `refused`. Refusals return exit 1; otherwise exit 0. Preview creates
no locks or reservations and runs no cleanup. Actual removal rechecks each
candidate under its feature lock; concurrent changes can invalidate a preview.

Use `new-feature doctor --repair` to clean up stale feature records and branches
whose worktrees no longer exist. Repair preserves unmerged work and unreadable
worktrees. It doesn't recreate missing worktrees. Doctor exits nonzero while issues remain.

`list --json` (also `status --json`) and `doctor --json` emit one JSON document on
stdout. Diagnostics remain on stderr. `schema_version` is `1`; successful reports
contain `command` (`list` or `doctor`), `ok`, and a `features` array sorted by slug. List's `ok` means
inspection succeeded; doctor's `ok` means no feature has remaining issues.
Each feature includes `name`, `slug`, `branch`, `target_branch`, absolute `worktree`,
lifecycle `status`, human `state`, `issues`, `worktree_exists`, `branch_exists`,
`clean`, `integration`, `config_drift`, `setup_incomplete`, `worktree_error`, and
`generation`, and `owns_branch`.
`clean` and `integration` are null when unavailable; `worktree_error` is null when
inspection succeeds. Integration is `merged`, `patch-equivalent`, or `unmerged`.
Lifecycle status is `initializing`, `active`, `merged`, or `inert`. Issue labels are
`inert`, `setup-incomplete`, `missing-worktree`, `worktree-error`, `missing-branch`, `dirty`,
`unmerged`, and `config-drift`. Allocated environment values are omitted.

Doctor also includes `repairs`, an array of `{"slug": "...", "message": "..."}`.
`doctor --repair --json` reports remaining features after repair. Expected command
failures emit `{"schema_version": 1, "error": {"code": "command-failed", "message": "..."}}`
and exit 1. Invalid arguments for supported JSON commands emit the same error envelope
with code `invalid-arguments` and exit 2. Doctor still exits 1 while reported issues remain.
Treat documented field names, issue labels, and error codes as stable within
schema version 1; accept additional fields and inspect `issues` and `integration`
instead of parsing human `state` or messages.

### Creation JSON

`new-feature create NAME --json` (or `new-feature NAME --json`) emits one JSON
document after creation and optional agent launch. Setup, Git, and agent stdout
is routed to stderr, leaving stdout suitable for parsing. `--json` cannot be
combined with creation's `--dry-run`.

The result contains `schema_version: 1`, `command: "create"`, `ok`, `status`
(`created` or `reused`), `feature`, `agent_exit_code`, and `agent_error`. The
feature contains `name`, `slug`, `branch`, `target_branch`, absolute `worktree`,
and lifecycle `status`. Allocated environment values are omitted.

`agent_exit_code` is null when no agent launches. A successful agent has exit
code 0 and null `agent_error`. Failed agent launch or execution sets `ok: false`
and `agent_error` to `{"code": "agent-failed", "message": "..."}`, returns nonzero,
and retains the feature identity and prepared worktree. Setup and creation
failures use the `command-failed` envelope described above.

### Changed files

Inspect one exact managed feature without running project code:

```bash
new-feature changes my-feature
new-feature changes my-feature --json
new-feature changes my-feature --expected-generation TOKEN --json
```

JSON contains `schema_version: 1`, `command: "changes"`, `ok`, `slug`, `branch`,
absolute `worktree`, `generation`, `observed_at`, and `changes`. The `changes`
object contains `state` (`clean` or `modified`), `summary`, and sorted `files`.
Each file has `path`, changed `index` and/or `worktree` states, and `original_path`
for renames or copies. States include `modified`, `added`, `deleted`, `renamed`,
`copied`, `type-changed`, `unmerged`, and `untracked`. Ignored files are omitted.
`files` is empty for a clean worktree. Inspection bypasses external filters, so
filtered files may conservatively appear changed when ordinary Git status would
consider their normalized contents unchanged.

Summary counts are `modified`, `added`, `deleted`, `renamed`, `untracked`,
`staged`, and `conflicts`; staged counts overlap the other categories. Copies
and type changes count as modified. Obtain a generation token from inventory
and pass it through `--expected-generation` to reject a replaced feature.
Legacy records have null generation; recreate the feature before using this guard.
Inspection also checks checkout identity before and after reading Git status;
a replacement detected during inspection fails instead of returning stale data.
Inspection creates coordination lock files while leaving feature and Git state
unchanged. This is a point-in-time snapshot; it does not prevent subsequent file edits.
Failures use the shared JSON error envelope and return nonzero.

Setup and creation ignore `.new-feature/`, `.worktrees/`, and `*.local.toml` locally
without changing your tracked `.gitignore` file.

## Local file transfer

Use an explicit flag to preserve local work alongside a Git merge:

```bash
new-feature merge my-feature --include-untracked
new-feature teardown my-feature
```

The flag copies ordinary untracked files and Git-ignored files to the same relative
paths in the original checkout. It never stages or commits them. Originals remain
in the feature worktree until teardown. Existing destination files must have identical
contents and permission bits; differing files, tracked paths, symlinks, and nested
repositories stop transfer. Initialized submodules are checked for local files;
transfer into tracked submodule paths is refused.

File conflicts are checked before merging. Copies happen after successful merge
checks and the Git commit, before an optional push. If copying fails, the Git merge
stays completed, originals and completed copies remain, and rerunning the command
retries missing copies. The flag also works when the branch is already merged.
Without the flag, merge does not transfer local files. As usual, a new Git merge
requires a clean target checkout; ordinary untracked copies there may need to be
ignored, committed, or moved before merging further commits.

Teardown removes local files only when identical regular-file copies exist in the
original checkout, or their paths are explicitly disposable. It verifies contents
and permissions again after cleanup commands. `--dry-run` reports refusals;
`--force` deliberately discards unpreserved files. Excluded files are disposable
whether or not `--include-untracked` was used.

Configure extra disposable paths in `.new-feature.toml`, `.new-feature.local.toml`,
or `[tool.new-feature]` in `pyproject.toml`:

```toml
safe_to_delete = ["scratch/", "*.log", "/temporary-output/"]
```

Patterns use Git ignore syntax. A trailing `/` matches directories, a leading `/`
anchors to the checkout root, and patterns without slashes match at any depth.
Negation (`!`) is not supported. Patterns also apply within each initialized
submodule. Local configuration replaces the shared list; built-in exclusions always
apply. Matching files are excluded from transfer and may be deleted by normal
teardown, so list only disposable paths.

Built-in disposable paths are `.new-feature/`, `.worktrees/`, `__pycache__/`,
`.venv/`, `venv/`, `node_modules/`, `.pytest_cache/`, `.hypothesis/`, `.mypy_cache/`, `.ruff_cache/`,
`.cache/`, `build/`, `dist/`, `site/`, `*.egg-info/`, and `htmlcov/`. Built-in file
patterns are `*.pyc`, `*.pyo`, `.coverage`, `.coverage.*`, `*.tmp`, `*.swp`, and `*~`.
Environment paths named `.venv` or `venv` are also disposable when they are
symlinks; teardown removes the link without following it or deleting its target.

Local file checks are best effort; stop writers before transfer or teardown.

## Agent guards

Install optional hooks to keep coding agents on feature branches and require
`new-feature` for worktree creation, removal, and merging into the target branch.
Ignored, untracked files can be edited directly on the target branch; tracked files
remain protected even inside ignored directories.

```bash
new-feature install-rules           # tracked .i-insist/new-feature.toml
new-feature install-rules --global  # ~/.i-insist/new-feature.toml
```

The installer also sets up i-insist. Restart your coding agent and review `/hooks`
after installation. Reinstalling replaces generated rule files, so leave them unmodified.

If a guard blocks an action, follow its error message. To approve an override,
include `I insist` in a human message.
