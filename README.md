# new-feature

`new-feature` aims to eliminate friction for creating new features. In a single command, it creates isolated git worktrees, allocates conflict-free runtime values, runs project-defined setup and teardown commands (such as creating and deleting a feature database), and optionally launches a configured coding agent in the new worktree.

## Install

```bash
uv tool install new-feature
new-feature setup --agent codex
```

`new-feature setup` launches the configured coding agent in the current repository. With
no local default agent yet, pass `--agent codex` or `--agent claude`. The agent inspects the
project, proposes a repository-specific configuration, asks about unresolved choices such
as the optional Codex hook, and waits for approval before further edits. Run it again to
review and improve an existing integration.

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
new-feature setup --agent codex
# Create a feature worktree. It launches no agent unless you configure a local default.
new-feature my-feature
# Create a feature worktree and explicitly launch an agent.
new-feature my-feature --agent claude
# Create a feature worktree without launching an agent, even when a default is configured.
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
push = true
agents = { custom = ["custom-agent", "--prompt"] }
```

`new-feature setup` and feature creation ensure that `*.local.toml` is in `.gitignore`.
This makes local agent commands, automatic-push preferences, and machine-specific values
safe to customize without changing versioned repository policy.

All settings remain optional. `new-feature` resolves a shared configuration from
`.new-feature.toml` when present, otherwise from `[tool.new-feature]` in `pyproject.toml`.
It then overlays `.new-feature.local.toml`, which uses the standalone-file syntax above and
can also be used on its own. A local value replaces a shared scalar or command list; entries
in `agents` and `env` overlay by name. For projects that prefer the shared `pyproject.toml`
form, use `[tool.new-feature.env]` there and `[env]` in the local sidecar.

`default_agent` and `push` remain supported in shared config when a repository deliberately
wants to enforce them, but local placement is the recommended default. `default_agent` is
optional: without it, feature creation does not launch an interactive agent. Codex and Claude
are built in and always work with `--agent`; `agents` adds or overrides named commands and fixed
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

`setup` runs after worktree creation; `teardown` runs before worktree removal.

Supported env entries:

- `{ value = "literal" }`
- `{ allocate = "port", min = 3000, max = 3999 }`
- `{ allocate = "integer", min = 1, max = 15 }`
- `{ allocate = "name", prefix = "myapp", max_length = 63 }`
- `{ allocate = "slug", prefix = "myapp" }`
- `{ allocate = "path", base = ".new-feature/cache" }`

## Lifecycle

`new-feature my-feature` creates branch `my-feature` and worktree `.worktrees/my-feature`, reserves env values in `.new-feature/manifest.toml`, runs setup, and launches an agent only when `default_agent` or `--agent` selects one. It automatically adds `.new-feature/`, `.worktrees/`, and `*.local.toml` to `.gitignore`. If setup fails, it runs a forced teardown so the partial worktree, branch, and manifest entry do not linger.

After a successful create that does not launch an agent (for example, with `--no-agent` or no selected agent), `new-feature` prints the absolute worktree path and a copy-pasteable command such as:

```text
Worktree ready: /path/to/repository/.worktrees/my-feature
Next: cd -- /path/to/repository/.worktrees/my-feature
```

A CLI process cannot change its parent shell's or an already-running coding agent's working directory. In an interactive shell, run the printed `cd` command; an existing coding agent should use the printed absolute path as the working directory for its subsequent tools. Paths on the `Next:` line are shell-quoted when necessary.

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

Both installers accept `--global` to install the guard in the user-level configuration
(`~/.codex/hooks.json` or `~/.claude/settings.json`) so it covers every repository on the
machine; outside a `new-feature`-managed repository the guard allows everything. The Claude
Code installer also accepts `--local` to write the guard to `.claude/settings.local.json`,
the personal gitignored settings file, instead of the shared `settings.json`.
