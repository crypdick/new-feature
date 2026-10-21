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
    shell_write_targets,
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
        return _blocks_shell(name, command, cwd=Path(cwd))
    if kind in {"file_write", "file_edit"}:
        paths = event.get("paths")
        if not isinstance(paths, list) or any(not isinstance(path, str) or not path for path in paths):
            raise ValueError("file event needs paths")
        if name == "target-branch":
            return blocks_target_edit(tuple(Path(path) for path in paths), cwd=Path(cwd))
    if name == "worktree-add":
        return _creates_harness_worktree(event.get("tool_name"), event.get("tool_input"))
    return False


def _blocks_shell(name: str, command: str, *, cwd: Path) -> bool:
    if name == "target-merge":
        return blocks_target_merge(command, cwd=cwd)
    if name == "target-branch":
        return blocks_target_edit(shell_write_targets(command, cwd=cwd), cwd=cwd)
    return name == f"worktree-{parse_worktree_action(command)}"


def _creates_harness_worktree(tool_name: object, tool_input: object) -> bool:
    # NOTE: docs/ARCHITECTURE.md's Agent guards cover Claude Code's native worktree tools.
    arguments = tool_input if isinstance(tool_input, dict) else {}
    if tool_name == "EnterWorktree":
        return "path" not in arguments
    return tool_name == "Agent" and arguments.get("isolation") == "worktree"


def main(name: str) -> int:
    """Read one neutral event and print a JSON denial message or null."""
    try:
        result = should_block(name, json.load(sys.stdin))
    except (NewFeatureError, ValueError, TypeError, OSError) as exc:
        sys.stderr.write(f"new-feature checker: {exc}\n")
        return 2
    sys.stdout.write(json.dumps(MESSAGES[name] if result else None) + "\n")
    return 0
