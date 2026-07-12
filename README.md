# new-feature

`new-feature` aims to eliminate friction for creating new features. In a single command, it creates isolated git worktrees, allocates conflict-free runtime values, runs project-defined setup and teardown commands (such as creating and deleting a feature database), and launches an interactive Codex session in the new worktree.

## Install

```bash
uv tool install new-feature
```

Or copy and paste this into your favorite coding agent:

> Run `curl -fsSL https://pypi.org/pypi/new-feature/json`, read `info.description`, and set up `new-feature` on this machine.

## Usage

```bash
# Create a feature worktree and launch the configured agent.
uvx new-feature my-feature
# Merges the worktree into the main branch
uvx new-feature merge-feature my-feature
# Run configured teardown and remove the feature worktree.
uvx new-feature teardown my-feature
# Teardown a worktree even if it has uncommitted work.
uvx new-feature teardown my-feature --force
```

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

`new-feature my-feature` creates `.worktrees/my-feature`, reserves env values in `.new-feature/manifest.toml`, runs setup, and launches interactive Codex in the worktree. It automatically adds `.new-feature/` and `.worktrees/` to `.gitignore`.

`new-feature merge-feature my-feature` runs pre-merge checks in the feature worktree, starts a no-commit merge into the target branch, runs post-merge checks on the merged target checkout, commits the merge only if those checks pass, and pushes only when `push = true`.

`new-feature teardown my-feature` runs the configured teardown commands before removing the worktree, deleting the branch, and removing the manifest entry. If the feature has not gone through `merge-feature`, pass `--force` to abandon it deliberately.
