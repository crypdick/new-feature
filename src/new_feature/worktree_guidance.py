"""Format worktree navigation guidance for agentless feature creation."""

from __future__ import annotations

import shlex
from pathlib import Path  # noqa: TC003 - package-wide beartype needs annotation types at runtime


def build_worktree_ready_message(worktree: Path) -> str:
    """Return guidance for an agentless caller to enter its worktree."""
    # NOTE: README.md's Lifecycle section documents this agentless-create guidance.
    return f"Worktree ready: {worktree}\nNext: cd -- {shlex.quote(str(worktree))}"


def build_teardown_reminder(slug: str) -> str:
    """Return the successful-merge reminder to clean up a feature worktree."""
    # NOTE: README.md's Lifecycle section documents teardown after a successful merge.
    return f"Feature merged. Remember to `new-feature teardown {slug}` when you are done with the worktree."
