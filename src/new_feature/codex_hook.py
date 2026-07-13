"""Adapt Codex PreToolUse payloads to the managed-worktree policy."""

from __future__ import annotations

import json
import sys
from io import StringIO, TextIOWrapper
from pathlib import Path
from typing import NewType, cast

from new_feature.hook_policy import (
    EditRequest,
    HookRequest,
    WorktreeRequest,
    evaluate_worktree_policy,
    parse_worktree_action,
)

type TextStream = StringIO | TextIOWrapper

CodexToolName = NewType("CodexToolName", str)

_DIRECT_EDIT_TOOLS = {"Write", "Edit", "apply_patch"}
_PATCH_FILE_PREFIXES = (
    "*** Add File: ",
    "*** Update File: ",
    "*** Delete File: ",
)


def run_codex_hook(stdin: TextStream, stdout: TextStream, *, cwd: Path) -> int:
    """Process one Codex PreToolUse payload and return its exit status."""
    try:
        payload = json.load(stdin)
    except (json.JSONDecodeError, OSError):
        return 0
    if not isinstance(payload, dict):
        return 0

    request = _request_from_payload(payload, cwd=cwd)
    if request is None:
        return 0
    denial = evaluate_worktree_policy(request, cwd=cwd)
    if denial is not None:
        _deny(stdout, denial.reason)
    return 0


def _request_from_payload(payload: dict[object, object], *, cwd: Path) -> HookRequest | None:
    raw_tool_name = payload.get("tool_name", "")
    tool_input = payload.get("tool_input", {})
    if raw_tool_name == "Bash":
        return _bash_request(tool_input)
    if raw_tool_name not in _DIRECT_EDIT_TOOLS:
        return None
    return _edit_request(CodexToolName(raw_tool_name), tool_input, cwd=cwd)


def _bash_request(tool_input: object) -> WorktreeRequest | None:
    if not isinstance(tool_input, dict):
        return None
    raw_command = tool_input.get("command", tool_input.get("cmd"))
    if not isinstance(raw_command, str):
        return None
    action = parse_worktree_action(raw_command)
    return WorktreeRequest(action) if action is not None else None


def _edit_request(tool_name: CodexToolName, tool_input: object, *, cwd: Path) -> EditRequest | None:
    targets = _direct_edit_targets(tool_name, tool_input, cwd=cwd)
    return EditRequest(tuple(targets)) if targets else None


def _direct_edit_targets(tool_name: CodexToolName, tool_input: object, *, cwd: Path) -> list[Path]:
    if tool_name in {"Write", "Edit"} and isinstance(tool_input, dict):
        file_path = tool_input.get("file_path")
        return [Path(file_path)] if isinstance(file_path, str) and file_path else [cwd]
    if tool_name == "apply_patch":
        return _apply_patch_targets(tool_input) or [cwd]
    return []


def _apply_patch_targets(tool_input: object) -> list[Path]:
    targets: list[Path] = []
    for text in _flatten_strings(tool_input):
        for line in text.splitlines():
            for prefix in _PATCH_FILE_PREFIXES:
                if line.startswith(prefix):
                    raw_path = line.removeprefix(prefix).strip()
                    if raw_path:
                        targets.append(Path(raw_path))
    return targets


def _flatten_strings(value: object) -> list[str]:
    if isinstance(value, str):
        return [value]
    if isinstance(value, dict):
        return [text for item in value.values() for text in _flatten_strings(item)]
    if isinstance(value, list):
        return [text for item in value for text in _flatten_strings(item)]
    return []


def _deny(stdout: TextStream, reason: str) -> None:
    json.dump(
        {
            "hookSpecificOutput": {
                "hookEventName": "PreToolUse",
                "permissionDecision": "deny",
                "permissionDecisionReason": reason,
            }
        },
        stdout,
    )


def main() -> int:
    """Run the Codex hook with the process standard streams."""
    return run_codex_hook(cast("TextStream", sys.stdin), cast("TextStream", sys.stdout), cwd=Path.cwd())


if __name__ == "__main__":
    raise SystemExit(main())
