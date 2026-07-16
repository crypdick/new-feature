# new-feature

`new-feature` aims to eliminate friction for creating new features. In a single command, it creates isolated git worktrees, allocates conflict-free runtime values, runs project-defined setup and teardown commands (such as creating and deleting a feature database), and launches the configured coding agent in the new worktree.

## Install

```bash
uv tool install new-feature
new-feature setup
```

`new-feature setup` launches the configured coding agent (Codex by default) in the
current repository. The agent inspects the project, proposes a repository-specific
configuration, asks about unresolved choices such as the optional Codex hook, and waits
for approval before editing. Run it again to review and improve an existing integration.

## Documentation

The documentation site uses this README as its homepage and generates its API reference
from package docstrings. Build it before committing documentation changes:

```bash
uv run mkdocs build --strict
```

To preview the site locally with live reload, run `uv run mkdocs serve`. Pushing to
`main` builds and deploys the site through GitHub Pages.

## Usage

```bash
# Ask an agent to configure or improve new-feature for this repository.
new-feature setup
# Create a feature worktree and launch the configured agent.
new-feature my-feature
# Create a feature worktree without launching another agent.
new-feature my-feature --no-agent
# Merges the worktree into the main branch
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

## Project Config

Add config to the target repo's `.new-feature.toml`:

```toml
target_branch = "main"
default_agent = "codex"
agents = { codex = ["codex"], claude = ["claude"] }
push = false
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

All settings remain optional. If both `.new-feature.toml` and `pyproject.toml` exist,
`.new-feature.toml` takes precedence. For projects that prefer to keep tool configuration in
`pyproject.toml`, place the same settings under `[tool.new-feature]` and use
`[tool.new-feature.env]` instead of `[env]`.

`default_agent` is the configured agent name used when `--agent` is omitted. Codex and Claude are
built in; `agents` adds or overrides named commands and fixed arguments. `new-feature` appends its
generated feature prompt as the final argument, so agents that require a prompt flag can be configured
directly:

```toml
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

`setup` runs after worktree creation; `teardown` runs before worktree removal.

Supported env entries:

- `{ value = "literal" }`
- `{ allocate = "port", min = 3000, max = 3999 }`
- `{ allocate = "integer", min = 1, max = 15 }`
- `{ allocate = "name", prefix = "myapp", max_length = 63 }`
- `{ allocate = "slug", prefix = "myapp" }`
- `{ allocate = "path", base = ".new-feature/cache" }`

## Lifecycle

`new-feature my-feature` creates branch `my-feature` and worktree `.worktrees/my-feature`, reserves env values in `.new-feature/manifest.toml`, runs setup, and launches the configured agent in the worktree. It automatically adds `.new-feature/` and `.worktrees/` to `.gitignore`. If setup fails, it runs a forced teardown so the partial worktree, branch, and manifest entry do not linger.

`new-feature list` shows each managed feature and its current Git/worktree state. `new-feature doctor` reports stale manifest entries, dirty worktrees, unmerged branches, and configuration drift. `doctor --repair` removes stale manifest entries whose worktree and branch are both already gone, and recovers a missing worktree only when its branch is already merged.

`new-feature merge my-feature` runs pre-merge checks in the feature worktree and rejects a conflicting merge before changing the target checkout. It then starts a no-commit merge into the target branch, runs post-merge checks on the merged target checkout, commits the merge only if those checks pass, and pushes only when `push = true`. Any failure after the merge starts is aborted.

`new-feature teardown my-feature` runs the configured teardown commands before removing the worktree, deleting the branch, and removing the manifest entry. If the worktree has uncommitted changes or the branch has commits that are not in the target branch, pass `--force` to abandon them deliberately.

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
