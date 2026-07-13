from __future__ import annotations

import json
import subprocess
import sys
from dataclasses import dataclass
from io import StringIO, TextIOWrapper
from pathlib import Path
from typing import NewType, cast

from new_feature.config import load_project_config
from new_feature.errors import NewFeatureError

BranchName = NewType("BranchName", str)
type TextStream = StringIO | TextIOWrapper

_DIRECT_EDIT_TOOLS = {"Write", "Edit", "apply_patch"}
_PATCH_FILE_PREFIXES = (
    "*** Add File: ",
    "*** Update File: ",
    "*** Delete File: ",
)


@dataclass(frozen=True)
class GitContext:
    root: Path
    branch: BranchName
    target_branch: BranchName


def run_codex_hook(stdin: TextStream, stdout: TextStream, *, cwd: Path) -> int:
    """Deny direct Codex edits to a managed repository's target branch."""
    try:
        payload = json.load(stdin)
    except (json.JSONDecodeError, OSError):
        return 0
    if not isinstance(payload, dict):
        return 0

    tool_name = payload.get("tool_name", "")
    if tool_name not in _DIRECT_EDIT_TOOLS:
        return 0

    tool_input = payload.get("tool_input", {})
    for target in _direct_edit_targets(cast("str", tool_name), tool_input, cwd=cwd):
        try:
            context = _git_context_for(target, cwd=cwd)
        except (NewFeatureError, OSError):
            continue
        if context is not None and context.branch == context.target_branch:
            _deny(stdout, _denial_reason(context))
            return 0
    return 0


def _direct_edit_targets(tool_name: str, tool_input: object, *, cwd: Path) -> list[Path]:
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


def _git_context_for(path: Path, *, cwd: Path) -> GitContext | None:
    probe = _existing_probe_path(path, cwd=cwd)
    root = _git_output(probe, "rev-parse", "--show-toplevel")
    if root is None:
        return None
    root_path = Path(root).resolve()
    branch = _git_output(root_path, "branch", "--show-current")
    if not branch:
        return None
    # NOTE: README.md documents that the configured target branch is protected.
    target_branch = load_project_config(root_path).target_branch
    return GitContext(
        root=root_path,
        branch=BranchName(branch),
        target_branch=BranchName(target_branch),
    )


def _existing_probe_path(path: Path, *, cwd: Path) -> Path:
    probe = path.expanduser()
    if not probe.is_absolute():
        probe = cwd / probe
    if probe.exists():
        return probe if probe.is_dir() else probe.parent
    parent = probe.parent
    while not parent.exists():
        parent = parent.parent
    return parent


def _git_output(path: Path, *args: str) -> str | None:
    result = subprocess.run(
        ("git", "-C", str(path), *args),
        stdout=subprocess.PIPE,
        stderr=subprocess.DEVNULL,
        text=True,
        check=False,
    )
    if result.returncode != 0:
        return None
    return result.stdout.strip()


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


def _denial_reason(context: GitContext) -> str:
    return (
        "BLOCKED [new-feature-target-branch]: Direct Codex edits are disabled on "
        f"target branch '{context.target_branch}' at {context.root}. Run "
        "`new-feature <feature-name> --no-agent`, then continue the work from "
        "`.worktrees/<feature-name>`."
    )


def main() -> int:
    return run_codex_hook(cast("TextStream", sys.stdin), cast("TextStream", sys.stdout), cwd=Path.cwd())


if __name__ == "__main__":
    raise SystemExit(main())
