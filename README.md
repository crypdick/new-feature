# new-feature

`new-feature` aims to eliminate friction for creating new features. In a single comamnd, it creates isolated git worktree environments, allocates conflict-free runtime values, and launches an interactive Codex session in the new worktree.

## Usage

```bash
# Create a new worktree and set it up with isolated db, .env, or anything else you want.
uvx new-feature my-feature
# Merges the worktree into the main branch
uvx new-feature merge-feature my-feature
# Runs your teardown commands to delete dev databases and the git worktree.
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
agent = "codex"
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

`new-feature teardown my-feature` runs teardown commands, removes the worktree, deletes the branch, and removes the manifest entry. If the feature has not gone through `merge-feature`, pass `--force` to abandon it deliberately.
