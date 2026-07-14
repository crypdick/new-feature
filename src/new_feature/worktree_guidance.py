"""Format worktree navigation guidance for agentless feature creation."""

from __future__ import annotations

import shlex
from pathlib import Path  # noqa: TC003 - package-wide beartype needs annotation types at runtime


def build_worktree_ready_message(worktree: Path) -> str:
    """Return guidance for an agentless caller to enter its worktree."""
    # NOTE: README.md's Lifecycle section documents this agentless-create guidance.
    return f"Worktree ready: {worktree}\nNext: cd -- {shlex.quote(str(worktree))}"
