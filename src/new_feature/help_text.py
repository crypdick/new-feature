"""Define help text for the command-line interface."""

from __future__ import annotations

TOP_LEVEL_EPILOG = """\
Workflow:
  new-feature my-feature --no-agent
  cd .worktrees/my-feature          # edit and commit here
  cd ../..                         # return to the repository root
  new-feature merge my-feature
  new-feature teardown my-feature

Use --agent codex or --agent claude to launch an agent in the worktree.
Run lifecycle commands from the original checkout.
new-feature NAME is shorthand for new-feature create NAME.

Options: new-feature COMMAND --help
Configuration and docs: https://new-feature.ricardodecal.com/
"""

CREATE_DESCRIPTION = """\
Create a feature worktree, allocate its environment, and run setup.
Repeating an active name reuses the worktree without rerunning setup.
Tear down a merged feature before reusing its name.
An agent launches only with --agent or a configured default_agent.
"""

CREATE_EPILOG = """\
Examples:
  new-feature my-feature --agent codex
  new-feature my-feature --no-agent
  new-feature create my-feature --dry-run

Use --no-agent inside an existing agent session. Work in the printed path.
Run this command from the original checkout.
"""

SETUP_DESCRIPTION = """\
Launch an agent to configure this repository. Select one with --agent or default_agent.
Setup adds local ignore rules. The agent asks for approval before further edits
or installing optional hooks.
"""

INSTALL_CODEX_HOOK_DESCRIPTION = """\
Compatibility alias for install-rules: install .i-insist/new-feature.toml.
Block direct edits on the target branch and require worktree creation and removal
through new-feature.
Other hooks stay unchanged. Keep new-feature on PATH.
Restart Codex, then review and trust the guard with /hooks.
"""

INSTALL_CLAUDE_HOOK_DESCRIPTION = """\
Compatibility alias for install-rules: install .i-insist/new-feature.toml.
Block direct edits on the target branch and require worktree creation and removal
through new-feature.
Other settings and hooks stay unchanged. Keep new-feature on PATH.
Restart Claude Code, then review the guard with /hooks.
"""

MERGE_DESCRIPTION = """\
Check and merge a feature into its target branch. Requires clean feature and target checkouts.
Failed checks stop the merge. The command pushes only when push = true.
Run from the original checkout, then use teardown to remove the worktree.
"""

TEARDOWN_DESCRIPTION = """\
Run cleanup, then remove the worktree and branch. Refuse dirty or unmerged work
unless --force is supplied. Cleanup failure stops removal even with --force.
Without a manifest entry, .worktrees/NAME can still be removed, but configured
cleanup is skipped because its environment is unavailable.
Run from the original checkout.
"""

LIST_DESCRIPTION = """\
Show managed features, their state, branches, and worktree paths.
Run from the original checkout.
"""

DOCTOR_DESCRIPTION = """\
Find stale records, missing branches or worktrees, and configuration drift.
Exit nonzero while issues remain. Repair never deletes unmerged work.
Repair removes stale state; it does not recreate missing worktrees.
Run from the original checkout.
"""
