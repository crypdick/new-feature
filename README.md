# new-feature

`new-feature` creates isolated Git worktrees, allocates runtime values, runs project-defined setup and teardown commands (such as creating and deleting a feature database), and optionally launches a configured coding agent in the new worktree.

## Install

Requires Python 3.13 or newer and Git. Install your chosen coding agent separately
and make its executable available on `PATH`.

```bash
uv tool install new-feature
new-feature setup --agent codex
```

Run `new-feature setup` inside the Git repository you want to configure. It adds local
ignore rules and launches the selected coding agent. Without a configured default agent,
pass `--agent codex` or `--agent claude`. The built-in prompt asks the agent to inspect the
project, propose configuration, and obtain approval before further edits or installing
the optional Codex or Claude Code hook. Run it again to review an existing integration.

## Usage

Run lifecycle commands from the original checkout that owns `.new-feature/manifest.toml`.
Use the feature worktree for edits and commits, then return to the original checkout
to merge or tear down. Create an initial Git commit before creating feature worktrees.

```bash
# Ask an agent to configure or improve new-feature for this repository.
new-feature setup --agent codex
# Create a feature worktree. It launches no agent unless you configure a local default.
new-feature my-feature
# Create a feature worktree and explicitly launch an agent.
new-feature my-feature --agent claude
# Create a feature worktree without launching an agent, even when a default is configured.
new-feature my-feature --no-agent
# Merge committed feature work into the configured target branch.
new-feature merge my-feature
# Run configured teardown and remove the feature worktree.
new-feature teardown my-feature
# Teardown a worktree even if it has uncommitted work.
new-feature teardown my-feature --force
# Inspect managed features and diagnose stale state.
new-feature list
new-feature doctor
new-feature doctor --repair
```

`new-feature NAME` is shorthand for `new-feature create NAME`. Names are normalized
into branch and directory slugs. Use the explicit `create` form when a name matches
a subcommand, such as `new-feature create setup`.

Use `new-feature create NAME --dry-run` to print proposed environment values without
creating a worktree or reserving values. Run `new-feature COMMAND --help` for command help.

## Project Config

Put shared repository policy in the target repo's `.new-feature.toml`:

```toml
target_branch = "main"
setup = ["uv sync"]
pre_merge = ["uv run pytest"]
post_merge = ["uv run pytest"]
teardown = []

[env]
WEB_PORT = { allocate = "port", min = 3000, max = 3999 }
API_PORT = { allocate = "port", min = 4000, max = 4999 }
DATABASE_NAME = { allocate = "name", prefix = "myapp", max_length = 63 }
CACHE_DIR = { allocate = "path", base = ".new-feature/cache" }
```

Keep personal preferences in the ignored `.new-feature.local.toml` sidecar:

```toml
default_agent = "codex"
pull_before_create = true
push = true
agents = { custom = ["custom-agent", "--prompt"] }
```

To choose one built-in agent by default across repositories, set it in the global config:

```toml
# ~/.config/new-feature/config.toml
default_agent = "codex"
```

`$XDG_CONFIG_HOME/new-feature/config.toml` is used when `XDG_CONFIG_HOME` is set. Only
`default_agent` is accepted globally. Repository shared config overrides the global value, and
the repository's `.new-feature.local.toml` overrides both.

`new-feature setup` and feature creation add `*.local.toml` to Git’s local `info/exclude`. Generated ignore rules are shared by linked worktrees and leave tracked `.gitignore` files unchanged.
This makes local agent commands, automatic pull/push preferences, and machine-specific values
safe to customize without changing versioned repository policy.

All settings remain optional. `new-feature` first loads the optional global default agent, then
resolves shared repository configuration from
`.new-feature.toml` when present, otherwise from `[tool.new-feature]` in `pyproject.toml`.
It then overlays `.new-feature.local.toml`, which uses the standalone-file syntax above and
can also be used on its own. A local value replaces a shared scalar or command list; entries
in `agents` and `env` overlay by name. For projects that prefer the shared `pyproject.toml`
form, use `[tool.new-feature.env]` there and `[env]` in the local sidecar.

`default_agent`, `pull_before_create`, and `push` can supply shared defaults, but local
configuration can override them. Local placement is recommended for personal preferences.
`default_agent` is optional: without it or `--agent`, feature creation does not launch an
interactive agent. Codex and Claude have built-in command aliases; `agents` adds or overrides named commands and fixed
arguments. `new-feature` appends its generated feature prompt as the final argument, so a
personal agent that requires a prompt flag can be configured in the local sidecar:

```toml
# .new-feature.local.toml
default_agent = "custom"
agents = { custom = ["custom-agent", "--prompt"] }
```

Use a configured agent for one invocation, or pass an executable command directly:

```bash
new-feature my-feature --agent claude
new-feature my-feature --agent "fooagent --baz-flag"
new-feature setup --agent claude
```

When the value exactly matches a key in `agents`, that configured command is used. Otherwise,
`new-feature` parses the value as an executable command without invoking a shell.

The built-in create and setup prompts can be overridden with `create_prompt` and `setup_prompt` in
TOML, or for one invocation with `--prompt`.

Defaults are `target_branch = "main"`, `pull_before_create = false`, `push = false`,
no selected agent, and empty lifecycle command lists and environment allocations.
When enabled, pull uses the target branch's configured upstream; push sends the target
branch to `origin`.

Lifecycle commands are shell strings, run sequentially. `setup`, `pre_merge`, and
`teardown` run in the feature worktree; `post_merge` runs in the original checkout
after merging and before committing. A nonzero exit stops the operation.

Commands and launched feature agents receive allocated environment values plus
`NEW_FEATURE_NAME`, `NEW_FEATURE_SLUG`, `NEW_FEATURE_BRANCH`, `NEW_FEATURE_WORKTREE`,
and `NEW_FEATURE_REPO_ROOT`. These values are not exported into your existing shell
or coding-agent session; consult `.new-feature/manifest.toml` for manual commands.

Supported env entries:

- `{ value = "literal" }`
- `{ allocate = "port", min = 3000, max = 3999 }`
- `{ allocate = "integer", min = 1, max = 15 }`
- `{ allocate = "name", prefix = "myapp", max_length = 63 }`
- `{ allocate = "slug", prefix = "myapp" }`
- `{ allocate = "path", base = ".new-feature/cache" }`

Port reservations are shared across configured port variables in this repository's
manifest. Availability is checked on localhost during allocation; the tool does not
hold the port open or reserve it against other repositories or programs. Integer
reservations are per variable name. Path allocation returns `base/feature-slug` as
text without creating a directory; relative paths resolve from the consuming command's
working directory.

## Lifecycle

Git operations, hook policy probes, lifecycle commands, and launched agents discard
inherited repository-location, index, and object-directory overrides such as
`GIT_DIR` and `GIT_COMMON_DIR`. Their working directory selects the repository,
even when invoked from a Git hook. Transport and authentication settings remain
available; explicitly configured lifecycle environment values still take precedence.

Merge completion is determined from Git ancestry, including empty features and features merged outside this tool. Already-integrated branches update manifest bookkeeping without running checks or creating another commit. Repeat merges inspect the current branch and require a clean feature worktree. If commits were added after a successful merge, the command runs the full checks and merges those commits. A push-only retry applies only while the branch remains included in the target history.

`new-feature my-feature` creates branch `my-feature` and worktree `.worktrees/my-feature`, reserves env values in `.new-feature/manifest.toml`, runs setup, and launches an agent only when `default_agent` or `--agent` selects one. With `pull_before_create = true`, it first runs a fast-forward-only pull on the clean, checked-out target branch. It automatically adds `.new-feature/`, `.worktrees/`, and `*.local.toml` to Git’s local `info/exclude`, preserving existing exclude rules. If setup fails or receives a handled interruption, it stops the command's process group and attempts forced teardown. If teardown also fails, the command reports both failures; inspect the remaining worktree and use `doctor` to check its state.

Running create again for an active feature reuses its recorded worktree and environment, skips
pulling, allocation, and setup, and launches the selected agent again. Dry runs also skip pulling.
Without a selected agent, it prints
the existing worktree guidance. If the recorded worktree or branch is missing, create stops and
directs you to `new-feature doctor --repair` instead of silently replacing inconsistent state.

After a successful create that does not launch an agent (for example, with `--no-agent` or no selected agent), `new-feature` prints the absolute worktree path and a copy-pasteable command such as:

```text
Worktree ready: /path/to/repository/.worktrees/my-feature
Next: cd -- /path/to/repository/.worktrees/my-feature
```

A CLI process cannot change its parent shell's or an already-running coding agent's working directory. In an interactive shell, run the printed `cd` command; an existing coding agent should use the printed absolute path as the working directory for its subsequent tools. Paths on the `Next:` line are shell-quoted when necessary.

Create, merge, teardown, and doctor repair cannot concurrently change the same feature.
If interrupted creation leaves a feature marked `setup-incomplete`, inspect and preserve
any work, then tear down and recreate the feature. After a successful merge, tear down
the feature before creating another feature with the same name.

`new-feature list` shows each managed feature and its current Git/worktree state, including `patch-equivalent` when every patch already exists in the target history despite different commit ancestry and there are no unmerged merge commits. `new-feature doctor` reports stale manifest entries, dirty worktrees, unmerged branches, and configuration drift, returning a nonzero status while issues remain. `doctor --repair` removes stale manifest entries whose worktree and branch are both already gone. When a worktree is missing but its branch is merged or patch-equivalent, repair removes the branch, stale worktree registration, and manifest entry. It does not recreate worktrees or delete unmerged branches.

If Git cannot inspect an existing worktree, `list` and `doctor` report `worktree-error`, print the Git error to stderr, and continue inspecting other features. `list` still succeeds; `doctor` returns a failing status. `doctor --repair` leaves unreadable worktrees and their manifest entries intact so you can recover their contents.

`new-feature merge my-feature` requires a clean feature worktree and rejects predicted conflicts before running pre-merge checks. Different features can run those checks in parallel. Updates to the target checkout run one at a time and require a clean target checkout. The command rechecks for conflicts, merges without committing, runs post-merge checks, then commits and records the merge. It pushes only when `push = true`.

If the merge, post-merge checks, commit, or bookkeeping fails, the command attempts to restore the target's original clean revision and removes non-ignored untracked files created there. It reports a rollback failure if restoration fails. This does not undo external effects such as database changes made by lifecycle commands. A push failure leaves the successful local merge recorded; rerun the same merge command to retry the push while the feature remains integrated. Failed pre- and post-merge commands retain their combined output under `.new-feature/diagnostics/merge-failures/<feature>/`; the error prints the exact log path. A successful merge prints a reminder to run teardown; it does not remove the feature worktree.

`new-feature teardown my-feature` runs the configured teardown commands before removing the worktree, deleting the branch, and removing the manifest entry. If a teardown command fails, removal stops, including with `--force`. If the manifest does not know the feature, teardown still recognizes the conventional `.worktrees/my-feature` path, derives its actual branch, and applies the same Git safety checks. It skips configured teardown commands for that fallback because their recorded environment is unavailable. Merged and patch-equivalent branches are safe to remove normally. If the worktree has uncommitted changes, the branch has patches absent from the target history, or an unmanaged worktree is detached, pass `--force` to abandon it deliberately. Branch ranges containing unmerged merge commits remain `unmerged` because patch comparison cannot account for novel conflict resolutions.

## Agent hooks

Install the Codex or Claude Code hook in the current repository:

```bash
new-feature install-codex-hook
new-feature install-claude-hook
```

The Codex hook is written to `.codex/hooks.json`; Codex loads the guard only for this trusted
repository. The Claude Code hook is written to the `hooks` section of `.claude/settings.json`,
which Claude Code loads at session start. Both guards protect the configured target branch from
direct agent edits and require Git worktree creation and removal to go through the managed
`new-feature` lifecycle.

Direct edits are allowed before the repository has any commits, so its first commit can
be created. Once history exists, protection also applies to orphan target branches.
The root `.new-feature.local.toml` remains editable only while Git ignores it and it is
untracked; nested files and symlinks to other files receive no exception. Every path in
a multi-file edit is checked independently.

Both installers accept `--global` to install the guard in the user-level configuration
(`~/.codex/hooks.json` or `~/.claude/settings.json`) so it covers every repository on the
machine; outside a `new-feature`-managed repository the guard allows everything. The Claude
Code installer also accepts `--local` to write the guard to `.claude/settings.local.json`,
the personal gitignored settings file, instead of the shared `settings.json`.
