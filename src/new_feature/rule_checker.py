"""Evaluate i-insist's neutral event; approval is owned by the runner."""

from __future__ import annotations

import json
import sys
from pathlib import Path

from new_feature.hook_policy import EditRequest, evaluate_worktree_policy, parse_worktree_action


def should_block(name: str, event: object) -> bool:
    """Check one provider rule without interpreting harness names or approvals."""
    if name not in {"worktree-add", "worktree-remove", "target-branch"}:
        raise ValueError(f"unknown rule: {name}")
    if not isinstance(event, dict):
        raise TypeError("event must be an object")
    kind, cwd = event.get("kind"), event.get("cwd")
    if kind not in {"shell", "file_write", "file_edit", "other"} or not isinstance(cwd, str) or not cwd:
        raise ValueError("event needs kind and cwd")
    if kind == "shell":
        command = event.get("command")
        if not isinstance(command, str):
            raise ValueError("shell event needs command")
        return name == f"worktree-{parse_worktree_action(command)}"
    if kind in {"file_write", "file_edit"}:
        paths = event.get("paths")
        if not isinstance(paths, list) or any(not isinstance(path, str) or not path for path in paths):
            raise ValueError("file event needs paths")
        if name == "target-branch":
            request = EditRequest(tuple(Path(path) for path in paths))
            return evaluate_worktree_policy(request, cwd=Path(cwd)) is not None
    return False


def main(name: str) -> int:
    """Read one neutral event and print exactly one JSON boolean."""
    try:
        result = should_block(name, json.load(sys.stdin))
    except (ValueError, TypeError, OSError) as exc:
        sys.stderr.write(f"new-feature checker: {exc}\n")
        return 2
    sys.stdout.write(json.dumps(result) + "\n")
    return 0
