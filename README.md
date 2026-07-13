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

## Releases

Changing `[project].version` in `pyproject.toml` and merging that change to `main`
publishes the distributions to PyPI, tags the merged commit as `v<VERSION>`, and creates
a GitHub Release. Keep the project version in `uv.lock` synchronized with `pyproject.toml`.
The release workflow can also be run manually to recover from a partial release.

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

## Codex hook

Install the Codex hook in the current repository:

```bash
new-feature install-codex-hook
```

This writes `.codex/hooks.json`; Codex loads the guard only for this trusted repository.

## Project Config

Add config to the target repo's `pyproject.toml`:

```toml
[tool.new-feature]
target_branch = "main"
branch_prefix = "feature/"
agent = ["codex"]
push = false
setup = ["uv sync"]
pre_merge = ["uv run pytest"]
post_merge = ["uv run pytest"]
teardown = []

[tool.new-feature.env]
WEB_PORT = { allocate = "port", min = 3000, max = 3999 }
API_PORT = { allocate = "port", min = 4000, max = 4999 }
DATABASE_NAME = { allocate = "name", prefix = "myapp", max_length = 63 }
CACHE_DIR = { allocate = "path", base = ".new-feature/cache" }
```

`agent` is the command and arguments used to launch the coding agent. `new-feature` appends its
generated feature prompt as the final argument, so agents that require a prompt flag can be configured
directly:

```toml
[tool.new-feature]
agent = ["copilot", "--prompt"]
```

`setup` runs after worktree creation; `teardown` runs before worktree removal.

Supported env entries:

- `{ value = "literal" }`
- `{ allocate = "port", min = 3000, max = 3999 }`
- `{ allocate = "integer", min = 1, max = 15 }`
- `{ allocate = "name", prefix = "myapp", max_length = 63 }`
- `{ allocate = "slug", prefix = "myapp" }`
- `{ allocate = "path", base = ".new-feature/cache" }`

## Lifecycle

`new-feature my-feature` creates `.worktrees/my-feature`, reserves env values in `.new-feature/manifest.toml`, runs setup, and launches the configured agent in the worktree. It automatically adds `.new-feature/` and `.worktrees/` to `.gitignore`. If setup fails, it runs a forced teardown so the partial worktree, branch, and manifest entry do not linger.

`new-feature list` shows each managed feature and its current Git/worktree state. `new-feature doctor` reports stale manifest entries, dirty worktrees, unmerged branches, and configuration drift. `doctor --repair` removes only manifest entries whose worktree and branch are both already gone.

`new-feature merge my-feature` runs pre-merge checks in the feature worktree, starts a no-commit merge into the target branch, runs post-merge checks on the merged target checkout, commits the merge only if those checks pass, and pushes only when `push = true`.

`new-feature teardown my-feature` runs the configured teardown commands before removing the worktree, deleting the branch, and removing the manifest entry. If the worktree has uncommitted changes or the branch has commits that are not in the target branch, pass `--force` to abandon them deliberately.
