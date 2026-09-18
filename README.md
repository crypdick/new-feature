# new-feature

Create isolated Git worktrees with their own ports, database names, and setup commands.
Work on a feature, merge it, then remove its worktree and resources.

## Install

Requires Python 3.13 or newer, Git, and uv:

```bash
uv tool install new-feature
```

To have a coding agent configure your repository, install Codex or Claude Code on
`PATH`, then run this from your checkout:

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

Run lifecycle commands from the original checkout. Use the feature worktree for edits
and commits.
For an existing coding agent, use the printed absolute worktree path for its tools.

To launch an agent in the worktree, use `new-feature my-feature --agent claude`.
Without `--agent`, creation uses `default_agent` if configured. Use `--no-agent`
to suppress it, including when you're already in an agent session.

`new-feature NAME` is shorthand for `new-feature create NAME`. Names become branch
and directory slugs. Use explicit `create` when the name matches a command, such as
`new-feature create setup`.

For inspection and command help:

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

Local scalars and command lists replace shared values. Entries in `agents` and `env`
override by name. In `pyproject.toml`, use `[tool.new-feature.env]` instead of `[env]`.
You can also put agent, pull, and push preferences in shared configuration as repository defaults.

Defaults: target branch `main`, no agent, no pull or push, and no commands or allocations.
Pull fast-forwards the clean target checkout using its upstream. Push sends the merged
target branch to `origin`.

Codex and Claude have built-in aliases, which `agents` can add to or override.
`--agent` accepts a configured name or an executable command, such as
`--agent "custom-agent --prompt"`, parsed without a shell.
The generated prompt is the final argument. Override it with `create_prompt` or
`setup_prompt` in configuration, or `--prompt` for one invocation.

Lifecycle commands are sequential shell strings. `setup`, `pre_merge`, and `teardown`
run in the feature worktree. `post_merge` runs in the original checkout before committing.
A nonzero exit stops the operation.

Commands and launched agents receive allocated values plus `NEW_FEATURE_NAME`,
`NEW_FEATURE_SLUG`, `NEW_FEATURE_BRANCH`, `NEW_FEATURE_WORKTREE`, and `NEW_FEATURE_REPO_ROOT`.
Existing shells and agent sessions don't inherit these values. Read them from
`.new-feature/manifest.toml` for manual commands.

Port reservations span all port variables in this repository. Availability checks don't
hold ports open or reserve them against other repositories or programs. Integer reservations
are per variable. Without explicit bounds, ports use 1024-65535 and integers use 0-65535.

Use `name` for a deterministic identifier with a hash suffix and optional `max_length`,
or `slug` for `prefix-feature-slug`. Paths return `base/feature-slug` without creating
directories. Relative paths resolve from the command's working directory.

## Lifecycle

Creation reuses an active feature's worktree and environment without rerunning setup.
Without an agent, it prints a shell-quoted `cd` command. Setup failure triggers forced
teardown. If cleanup fails or `doctor` reports `setup-incomplete`, preserve needed work,
then tear down and recreate the feature. For a missing branch or worktree, run
`new-feature doctor --repair` before retrying creation.

Commit your feature changes before merging, and keep the target checkout clean.
Merge checks for conflicts and runs your configured checks before committing.
Features already included in the target history skip checks, including features merged
outside this tool. Additional commits go through checks before merging. Failed merges
attempt to restore the target revision and remove non-ignored untracked files created there.
Rollback doesn't undo external effects such as database changes.

Merge-check failures print a log path under `.new-feature/diagnostics/merge-failures/`.
If push fails, rerun merge to retry. Commits added since the last merge go through checks first.
A successful merge leaves the worktree in place: run teardown afterward, before
creating another feature with the same name.

Teardown removes the worktree, branch, and manifest entry after cleanup commands succeed.
A cleanup failure stops removal even with `--force`. Use `--force` only to discard
uncommitted or unmerged work deliberately.
If the manifest entry is missing, teardown can still remove `.worktrees/NAME`, but it
skips configured cleanup because the recorded environment is unavailable.

`patch-equivalent` means the target contains the feature's patches despite different
ancestry. Teardown accepts these branches, except those with unmerged merge commits.
Use `doctor --repair` to clean up stale records and branches whose worktrees are gone.
Repair preserves unmerged work and unreadable worktrees. Doctor exits nonzero while
issues remain. Repair doesn't recreate missing worktrees.

Setup and creation add `.new-feature/`, `.worktrees/`, and `*.local.toml` to Git's local
`info/exclude`. These local ignore rules leave tracked `.gitignore` files unchanged.

## Agent guards

Includes hooks that make coding copilots use `new-feature` instead of raw Git
commands for worktree creation, removal, and merging into the target branch.

```bash
new-feature install-rules           # tracked .i-insist/new-feature.toml
new-feature install-rules --global  # ~/.i-insist/new-feature.toml
```

Setup requires i-insist 0.4.0 or later and upgrades older runners. It atomically
replaces new-feature's generated rule registration; installed rule files are not
user customization files. Checkers own denial messages and return JSON `null` to
allow or a nonempty string to block. Evaluation errors fail closed with stderr
reported by i-insist. Human `I insist` approval remains available.

This changes the checker protocol. Coordinate runner and provider upgrades, then
rerun `install-rules` to replace old registrations, including tracked repository
registrations. Old rule fields and boolean checker output fail closed.
Restart your copilot and review `/hooks` after installation.
