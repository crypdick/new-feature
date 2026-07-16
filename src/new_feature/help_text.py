"""Define reusable help text for the command-line interface."""

from __future__ import annotations

_CONFIGURATION_GUIDE = """\
Configuration (.new-feature.toml, or [tool.new-feature] in pyproject.toml):
  target_branch = "main"           # branch each feature starts from and merges into
  default_agent = "codex"            # configured name or executable command
  agents = { codex = ["codex"], claude = ["claude"] }
  push = false                      # push target_branch after a successful merge
  setup = ["uv sync"]               # run in the feature worktree after creation
  pre_merge = ["uv run pytest"]     # run in the feature worktree before merging
  post_merge = ["uv run pytest"]    # run in the control checkout after merging
  teardown = []                     # run in the feature worktree before removal

  [env]
  WEB_PORT = { allocate = "port", min = 3000, max = 3999 }
  WORKER_ID = { allocate = "integer", min = 1, max = 20 }
  DATABASE_NAME = { allocate = "name", prefix = "myapp", max_length = 63 }
  CACHE_NAMESPACE = { allocate = "slug", prefix = "myapp" }
  CACHE_DIR = { allocate = "path", base = ".new-feature/cache" }
  APP_ENV = { value = "development" }

All settings are optional. The defaults are target_branch = "main", default_agent = "codex",
agents = { codex = ["codex"], claude = ["claude"] }, push = false, and empty command and
environment lists. Built-in create and setup prompts can be overridden with create_prompt and
setup_prompt in TOML, or for one invocation with --prompt TEXT.

If both .new-feature.toml and pyproject.toml exist, .new-feature.toml takes precedence.
For pyproject.toml, place these settings under [tool.new-feature] and use
[tool.new-feature.env] instead of [env].

Configured commands are shell strings run sequentially. They receive the allocated
environment plus NEW_FEATURE_NAME, NEW_FEATURE_SLUG, NEW_FEATURE_BRANCH,
NEW_FEATURE_WORKTREE, and NEW_FEATURE_REPO_ROOT. A nonzero command stops the operation.

Allocator forms:
  { value = "TEXT" }                            fixed string
  { allocate = "port", min = N, max = N }      available, unreserved TCP port
  { allocate = "integer", min = N, max = N }   unreserved integer
  { allocate = "name", prefix = "P", max_length = N }
                                                   deterministic identifier with hash
  { allocate = "slug", prefix = "P" }          prefix-feature-slug
  { allocate = "path", base = "PATH" }         PATH/feature-slug

port defaults to 1024..65535; integer defaults to 0..65535. Allocated values are
reserved per managed feature in .new-feature/manifest.toml.
"""

_AGENT_WORKFLOW = """\
Workflow for an already-running coding agent:
  1. Inspect .new-feature.toml or pyproject.toml and add configuration if the project
     needs setup, checks, cleanup, a different target branch, or isolated runtime values.
  2. From the control checkout, run: new-feature create NAME --no-agent
  3. Run `new-feature list` to confirm the normalized slug and worktree path, then do
     all implementation and commits inside .worktrees/SLUG.
  4. Return to the control checkout and run: new-feature merge SLUG
  5. After a successful merge, run: new-feature teardown SLUG

--no-agent prevents a nested coding-agent subprocess. Setup still receives allocated
environment variables, but they cannot be exported into the already-running caller.
Read .new-feature/manifest.toml and export any values needed by later manual commands.

Run lifecycle commands from the control checkout: its .new-feature/manifest.toml owns
the managed-feature records. The feature worktree is for implementation work.
"""

_STATE_GUIDE = """\
Managed state and safety:
  - setup launches an agent in the current checkout to configure new-feature itself.
  - install-codex-hook and install-claude-hook enforce the managed worktree workflow.
  - Worktrees live at .worktrees/SLUG and branches are named SLUG.
  - .new-feature/ and .worktrees/ are automatically added to .gitignore.
  - Setup failure triggers forced cleanup of the partial feature.
  - merge requires clean feature and target checkouts, rejects predicted conflicts, and aborts failed merges.
  - teardown refuses to discard dirty or unmerged work unless --force is supplied.
  - list shows paths and state; doctor diagnoses stale state and configuration drift.
"""

TOP_LEVEL_EPILOG = f"""\
{_AGENT_WORKFLOW}

The short form `new-feature NAME` is equivalent to `new-feature create NAME`.
Run `new-feature COMMAND --help` for command-specific effects and examples.

{_CONFIGURATION_GUIDE}

{_STATE_GUIDE}"""

CREATE_DESCRIPTION = """\
Create an isolated feature branch and worktree, allocate its configured environment,
run project setup commands, and launch the configured interactive coding agent.

The worktree is created at .worktrees/SLUG from the configured target branch. Runtime
values are reserved in .new-feature/manifest.toml. If setup fails, new-feature attempts
a forced teardown so a partial feature does not linger.
"""

CREATE_EPILOG = f"""\
Examples:
  new-feature create "Add billing webhooks"
  new-feature "Add billing webhooks" --no-agent
  new-feature create billing-webhooks --dry-run

If you are already a coding agent, use --no-agent to prevent spawning another agent in
a subprocess. Setup still runs; then work inside .worktrees/SLUG yourself. --dry-run
only prints proposed environment values and does not create or reserve anything.

The selected agent command is an argv prefix. new-feature appends its generated feature prompt as
the final argument and launches the command in the worktree with the allocated environment.
Use --agent NAME to select a configured agent, or --agent "COMMAND --FLAG" to run an executable
command directly. For an agent requiring a prompt flag, use for example:
  default_agent = "custom"
  agents = {{ custom = ["custom-agent", "--prompt"] }}

{_CONFIGURATION_GUIDE}"""

SETUP_DESCRIPTION = """\
Launch the configured coding agent in the current repository to set up or improve its
new-feature integration.

The agent starts by reading `new-feature --help` and inspecting the repository and any
existing .new-feature.toml or [tool.new-feature] configuration. It proposes a
repository-specific plan, interviews you about unresolved choices, and asks whether to
install the optional Codex or Claude Code hook before making changes.
This command only launches the agent; it does not edit the repository, create a
worktree, or install the hooks itself.
"""

INSTALL_CODEX_HOOK_DESCRIPTION = """\
Install or update the repository-local Codex PreToolUse guard in .codex/hooks.json.

The guard denies Codex direct Write, Edit, and apply_patch operations on the configured
target branch. It also denies raw `git worktree add` and `git worktree remove` commands
so Codex uses the managed new-feature lifecycle. Unrelated repository hooks are
preserved, while an installed new-feature or legacy worktree guard is replaced.

The hook runs `new-feature codex-hook`, so new-feature must remain available on PATH.
Codex applies repository hooks only after the repository is trusted. Restart Codex after
installation, then use `/hooks` to review and trust the guard.
"""

INSTALL_CLAUDE_HOOK_DESCRIPTION = """\
Install or update the repository-local Claude Code PreToolUse guard in
.claude/settings.json.

The guard denies Claude Code direct Write, Edit, MultiEdit, and NotebookEdit operations
on the configured target branch. It also denies raw `git worktree add` and
`git worktree remove` commands so Claude Code uses the managed new-feature lifecycle.
Unrelated settings and hooks are preserved, while an installed new-feature guard is
replaced.

The hook runs `new-feature claude-hook`, so new-feature must remain available on PATH.
Claude Code loads hooks at session start, so restart Claude Code after installation and
review the loaded hooks with `/hooks`.
"""

MERGE_DESCRIPTION = """\
Merge a managed feature into its configured target branch.

This runs pre-merge commands in the feature worktree, requires both the feature and
target checkouts to be clean, and rejects a conflicting merge before changing the target
checkout. It then starts a no-commit merge and runs post-merge commands in the target
checkout. The merge is committed only when all checks pass. It is pushed only when
push = true in the project config. A failed merge or check is aborted.

Run this command from the control checkout, not from the feature worktree.
"""

TEARDOWN_DESCRIPTION = """\
Run configured teardown commands, then remove a managed worktree, its feature branch,
and its manifest entry.

By default, teardown refuses to discard uncommitted changes or commits not merged into
the target branch. --force deliberately bypasses both protections. Run this command
from the control checkout, not from the feature worktree.
"""

LIST_DESCRIPTION = """\
List every managed feature with its state, branch, and worktree path.

State includes lifecycle status and detected problems such as a missing worktree,
missing branch, dirty worktree, unmerged commits, or configuration drift. Run this
command from the control checkout that owns .new-feature/manifest.toml.
"""

DOCTOR_DESCRIPTION = """\
Diagnose manifest, Git branch, worktree, and project-configuration consistency.

The command exits nonzero while issues remain. --repair removes a stale manifest entry
when both its worktree and branch are already gone. It also removes a missing worktree's
branch only after confirming that the branch is merged; it does not discard work. Run
this command from the control checkout that owns .new-feature/manifest.toml.
"""
