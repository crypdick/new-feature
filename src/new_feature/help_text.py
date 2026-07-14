"""Define reusable help text for the command-line interface."""

from __future__ import annotations

_CONFIGURATION_GUIDE = """\
Configuration: put shared repository policy in .new-feature.toml, or in
[tool.new-feature] in pyproject.toml:
  target_branch = "main"           # branch each feature starts from and merges into
  setup = ["uv sync"]              # run in the feature worktree after creation
  pre_merge = ["uv run pytest"]    # run in the feature worktree before merging
  post_merge = ["uv run pytest"]   # run in the control checkout after merging
  teardown = []                    # run in the feature worktree before removal

  [env]
  WEB_PORT = { allocate = "port", min = 3000, max = 3999 }
  WORKER_ID = { allocate = "integer", min = 1, max = 20 }
  DATABASE_NAME = { allocate = "name", prefix = "myapp", max_length = 63 }
  CACHE_NAMESPACE = { allocate = "slug", prefix = "myapp" }
  CACHE_DIR = { allocate = "path", base = ".new-feature/cache" }
  APP_ENV = { value = "development" }

Put personal preferences in the ignored .new-feature.local.toml sidecar:
  default_agent = "codex"          # selected when --agent is omitted
  push = true                       # push target_branch after a successful merge
  agents = { custom = ["custom-agent", "--prompt"] }

All settings are optional. The defaults are target_branch = "main", no default agent,
built-in codex and claude aliases, push = false, and empty command and environment lists.
Without default_agent, feature creation does not launch an interactive agent. Built-in create
and setup prompts can be overridden with create_prompt and setup_prompt in TOML, or for one
invocation with --prompt TEXT.

new-feature resolves .new-feature.toml over pyproject.toml, then overlays
.new-feature.local.toml. A local scalar or command list replaces its shared value; agents and
env entries overlay by name. The local sidecar uses the standalone syntax above, even when the
shared configuration is in pyproject.toml. For pyproject.toml, place shared env values under
[tool.new-feature.env] instead of [env].

default_agent and push are supported in shared config when a repository deliberately requires
them, but local placement is recommended. new-feature setup and feature creation add
*.local.toml to .gitignore.

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
  1. Inspect .new-feature.toml, .new-feature.local.toml, or pyproject.toml and add
     configuration if the project needs setup, checks, cleanup, a different target branch,
     isolated runtime values, or personal agent preferences.
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
  - setup adds generated-state and *.local.toml ignore rules, then launches an agent when selected.
  - Codex users can run install-codex-hook to enforce the managed worktree workflow.
  - Worktrees live at .worktrees/SLUG and branches are named SLUG.
  - .new-feature/, .worktrees/, and *.local.toml are automatically added to .gitignore.
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
run project setup commands, and optionally launch the selected interactive coding agent.

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

Without default_agent or --agent, creation stops after setup and does not launch an agent.
The selected agent command is an argv prefix. new-feature appends its generated feature prompt as
the final argument and launches the command in the worktree with the allocated environment.
Use --agent codex or --agent claude without configuration, a configured NAME, or an executable
command directly. For a personal agent requiring a prompt flag, use in .new-feature.local.toml:
  default_agent = "custom"
  agents = {{ custom = ["custom-agent", "--prompt"] }}

{_CONFIGURATION_GUIDE}"""

SETUP_DESCRIPTION = """\
Launch the configured coding agent in the current repository to set up or improve its
new-feature integration. With no default_agent, pass --agent codex or --agent claude.

The agent starts by reading `new-feature --help` and inspecting the repository and any
existing .new-feature.toml, .new-feature.local.toml, or [tool.new-feature] configuration. It proposes a
repository-specific plan, interviews you about unresolved choices, and asks whether to
install the optional Codex hook before making changes. The command ensures generated-state
and *.local.toml ignore rules, then only launches the agent; it does not create a worktree or
install the hook itself.
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

MERGE_DESCRIPTION = """\
Merge a managed feature into its configured target branch.

This runs pre-merge commands in the feature worktree, requires both the feature and
target checkouts to be clean, and rejects a conflicting merge before changing the target
checkout. It then starts a no-commit merge and runs post-merge commands in the target
checkout. The merge is committed only when all checks pass. It is pushed only when
push = true in the resolved configuration. A failed merge or check is aborted.

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
