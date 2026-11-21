"""Format worktree navigation guidance for agentless feature creation."""

from __future__ import annotations

import shlex
from pathlib import Path  # noqa: TC003 - package-wide beartype needs annotation types at runtime


def build_worktree_ready_message(worktree: Path, slug: str, *, inert: bool) -> str:
    """Tell an agentless caller how to use the checkout without changing sessions."""
    # NOTE: README.md's Lifecycle section documents this agentless-create guidance.
    if inert:
        return (
            f"Worktree imported (inert): {worktree}\n"
            f"After review, activate it: new-feature create {slug} --bootstrap --no-agent"
        )
    return (
        f"Worktree ready: {worktree}\n"
        f"Next: cd -- {shlex.quote(str(worktree))}\n"
        "In an existing agent session, set each tool call's workdir to the path above.\n"
        f"Run commands with the feature's saved environment: new-feature exec {slug} -- COMMAND ...\n"
        "Avoid reusing the target checkout's editable installs; they can load target code."
    )


def build_teardown_reminder(slug: str) -> str:
    """Return the successful-merge reminder to clean up a feature worktree."""
    # NOTE: README.md's Lifecycle section documents teardown after a successful merge.
    return (
        "Feature merged. @agents: do not orphan managed worktrees, teardown now if worktree "
        f"no longer needed: `new-feature teardown {slug}`."
    )
