from __future__ import annotations

import json
import re
import shlex
import subprocess
import sys
from dataclasses import dataclass
from io import StringIO, TextIOWrapper
from pathlib import Path
from typing import TYPE_CHECKING, NewType, cast

if TYPE_CHECKING:
    from collections.abc import Iterator

from new_feature.config import load_project_config
from new_feature.errors import NewFeatureError

BranchName = NewType("BranchName", str)
WorktreeAction = NewType("WorktreeAction", str)
type TextStream = StringIO | TextIOWrapper

_DIRECT_EDIT_TOOLS = {"Write", "Edit", "apply_patch"}
_WORKTREE_ACTIONS = {"add", "remove"}
_SHELL_SEPARATORS = {";", "&&", "||", "|", "&", "(", ")"}
_ASSIGNMENT = re.compile(r"[A-Za-z_][A-Za-z0-9_]*=.*\Z")
_COMMAND_WRAPPERS = {"command", "exec"}
_ENV_OPTIONS_WITH_VALUES = {"-C", "--chdir", "-S", "--split-string", "-u", "--unset"}
_SUDO_OPTIONS_WITH_VALUES = {
    "-C",
    "--chdir",
    "-D",
    "--chroot",
    "-g",
    "--group",
    "-h",
    "--host",
    "-p",
    "--prompt",
    "-R",
    "--role",
    "-r",
    "--type",
    "-T",
    "--command-timeout",
    "-u",
    "--user",
}
_GIT_OPTIONS_WITH_VALUES = {
    "-C",
    "-c",
    "--config-env",
    "--git-dir",
    "--namespace",
    "--super-prefix",
    "--work-tree",
}
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
    tool_input = payload.get("tool_input", {})
    if tool_name == "Bash":
        action = _worktree_action(tool_input)
        if action is not None:
            _deny(stdout, _worktree_denial_reason(action))
        return 0
    if tool_name not in _DIRECT_EDIT_TOOLS:
        return 0

    for target in _direct_edit_targets(cast("str", tool_name), tool_input, cwd=cwd):
        try:
            context = _git_context_for(target, cwd=cwd)
        except (NewFeatureError, OSError):
            continue
        if context is not None and context.branch == context.target_branch:
            _deny(stdout, _denial_reason(context))
            return 0
    return 0


def _worktree_action(tool_input: object) -> WorktreeAction | None:
    if not isinstance(tool_input, dict):
        return None
    raw_command = tool_input.get("command", tool_input.get("cmd"))
    if not isinstance(raw_command, str):
        return None
    try:
        lexer = shlex.shlex(raw_command, posix=True, punctuation_chars=";&|()")
        lexer.whitespace_split = True
        tokens = list(lexer)
    except ValueError:
        return None
    for command in _shell_commands(tokens):
        git_arguments = _git_arguments(command)
        if git_arguments is None:
            continue
        action = _git_worktree_action(git_arguments, 0)
        if action is not None:
            return action
    return None


def _shell_commands(tokens: list[str]) -> Iterator[list[str]]:
    start = 0
    for index, token in enumerate(tokens):
        if token not in _SHELL_SEPARATORS:
            continue
        if start < index:
            yield tokens[start:index]
        start = index + 1
    if start < len(tokens):
        yield tokens[start:]


def _git_arguments(command: list[str]) -> list[str] | None:
    index = _executable_index(command)
    if index is None or Path(command[index]).name != "git":
        return None
    return command[index + 1 :]


def _executable_index(command: list[str]) -> int | None:
    index = 0
    while index < len(command):
        while index < len(command) and _ASSIGNMENT.fullmatch(command[index]):
            index += 1
        if index >= len(command):
            return None

        executable = Path(command[index]).name
        if executable in _COMMAND_WRAPPERS:
            index = _skip_options(command, index + 1, options_with_values=set())
            continue
        if executable == "env":
            index = _skip_options(command, index + 1, options_with_values=_ENV_OPTIONS_WITH_VALUES)
            continue
        if executable == "sudo":
            index = _skip_options(command, index + 1, options_with_values=_SUDO_OPTIONS_WITH_VALUES)
            continue
        return index
    return None


def _skip_options(command: list[str], index: int, *, options_with_values: set[str]) -> int:
    while index < len(command):
        word = command[index]
        if word == "--":
            return index + 1
        option = word.split("=", 1)[0]
        if option in options_with_values and "=" not in word:
            index += 2
            continue
        if word.startswith("-"):
            index += 1
            continue
        return index
    return index


def _git_worktree_action(tokens: list[str], index: int) -> WorktreeAction | None:
    while index < len(tokens):
        word = tokens[index]
        if word == "worktree":
            return _worktree_subcommand(tokens, index + 1)
        if word in _GIT_OPTIONS_WITH_VALUES:
            index += 2
            continue
        if word.startswith("-"):
            index += 1
            continue
        return None
    return None


def _worktree_subcommand(tokens: list[str], index: int) -> WorktreeAction | None:
    if index < len(tokens) and tokens[index] in _WORKTREE_ACTIONS:
        return WorktreeAction(tokens[index])
    return None


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


def _worktree_denial_reason(action: WorktreeAction) -> str:
    # NOTE: README.md documents that Codex must manage feature worktrees through this CLI.
    replacement = (
        "`new-feature <feature-name> --no-agent`"
        if action == "add"
        else "`new-feature teardown <feature-name>`"
    )
    return (
        f"BLOCKED [new-feature-worktree-{action}]: Direct `git worktree {action}` is disabled. "
        f"Use {replacement} instead."
    )


def main() -> int:
    return run_codex_hook(cast("TextStream", sys.stdin), cast("TextStream", sys.stdout), cwd=Path.cwd())


if __name__ == "__main__":
    raise SystemExit(main())
