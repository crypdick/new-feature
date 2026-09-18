"""Evaluate i-insist's neutral event; approval is owned by the runner."""

from __future__ import annotations

import json
import sys
from pathlib import Path

from new_feature.errors import NewFeatureError
from new_feature.hook_policy import (
    blocks_target_edit,
    blocks_target_merge,
    parse_worktree_action,
)

MESSAGES = {
    "worktree-add": "Direct git worktree add is disabled. Use new-feature <feature-name> --no-agent, then work in .worktrees/<feature-name>. Only the human can authorize an override with I insist.",
    "worktree-remove": "Direct git worktree remove is disabled. Use new-feature teardown <feature-name>. Only the human can authorize an override with I insist.",
    "target-branch": "Direct edits on the repository's target branch are disabled. Run new-feature <feature-name> --no-agent, then continue in .worktrees/<feature-name>. Only the human can authorize an override with I insist.",
    "target-merge": "Direct git merge on the target branch is disabled. Use new-feature merge <feature-name>. Recovery remains allowed: git merge --continue, --abort, or --quit. Only the human can authorize an override with I insist.",
}


def should_block(name: str, event: object) -> bool:
    """Check one provider rule without interpreting harness names or approvals."""
    if name not in MESSAGES:
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
        if name == "target-merge":
            return blocks_target_merge(command, cwd=Path(cwd))
        return name == f"worktree-{parse_worktree_action(command)}"
    if kind in {"file_write", "file_edit"}:
        paths = event.get("paths")
        if not isinstance(paths, list) or any(not isinstance(path, str) or not path for path in paths):
            raise ValueError("file event needs paths")
        if name == "target-branch":
            return blocks_target_edit(tuple(Path(path) for path in paths), cwd=Path(cwd))
    return False


def main(name: str) -> int:
    """Read one neutral event and print a JSON denial message or null."""
    try:
        result = should_block(name, json.load(sys.stdin))
    except (NewFeatureError, ValueError, TypeError, OSError) as exc:
        sys.stderr.write(f"new-feature checker: {exc}\n")
        return 2
    sys.stdout.write(json.dumps(MESSAGES[name] if result else None) + "\n")
    return 0
