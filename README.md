# new-feature

`new-feature` creates isolated git worktree environments for feature work, allocates conflict-free runtime values, and launches an interactive Codex session in the new worktree.

## Usage

```bash
uvx new-feature my-feature
uvx new-feature merge-feature my-feature
uvx new-feature teardown my-feature
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

## Generated State

The generated manifest is a single ignored TOML file in the main checkout:

```text
.new-feature/manifest.toml
.new-feature/manifest.lock
```

The manifest stores all active feature env allocations, so ports, names, paths, and namespaces can be reserved without scanning generated worktrees.
