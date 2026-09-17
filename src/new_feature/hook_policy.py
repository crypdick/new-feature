"""Evaluate provider-neutral managed-worktree hook requests."""

from __future__ import annotations

import re
import shlex
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import NewType

from new_feature.config import load_project_config
from new_feature.errors import NewFeatureError
from new_feature.git import git_environment

BranchName = NewType("BranchName", str)
WorktreeAction = NewType("WorktreeAction", str)

_WORKTREE_ACTIONS = {"add", "remove"}
_SHELL_SEPARATORS = {";", "&&", "||", "|", "&", "(", ")", ""}
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


@dataclass(frozen=True)
class EditRequest:
    """Describe paths an agent intends to edit."""

    targets: tuple[Path, ...]


@dataclass(frozen=True)
class WorktreeRequest:
    """Describe a direct Git worktree lifecycle operation."""

    action: WorktreeAction


type HookRequest = EditRequest | WorktreeRequest


@dataclass(frozen=True)
class PolicyDenial:
    """Describe a request the managed-worktree policy disallows."""

    reason: str


@dataclass(frozen=True)
class GitContext:
    """Describe the repository and branch that own a target path."""

    root: Path
    branch: BranchName
    target_branch: BranchName


def evaluate_worktree_policy(request: HookRequest, *, cwd: Path) -> PolicyDenial | None:
    """Return a denial when a normalized request bypasses managed worktrees."""
    if isinstance(request, WorktreeRequest):
        return PolicyDenial(_worktree_denial_reason(request.action))
    for target in request.targets:
        try:
            context = _git_context_for(target, cwd=cwd)
        except (NewFeatureError, OSError):
            continue
        if context is not None and context.branch == context.target_branch:
            if _is_ignored_root_sidecar(target, cwd=cwd, root=context.root):
                continue
            return PolicyDenial(_edit_denial_reason(context))
    return None


def parse_worktree_action(command: str) -> WorktreeAction | None:
    """Return the direct managed-worktree action invoked by a shell command."""
    for shell_command in _parse_shell_commands(command):
        git_arguments = _git_arguments(shell_command)
        if git_arguments is None:
            continue
        action = _git_worktree_action(git_arguments, 0)
        if action is not None:
            return action
    return None


def evaluate_merge_policy(command: str, *, cwd: Path) -> PolicyDenial | None:
    """Reject starting a direct merge on the configured target branch."""
    for shell_command in _parse_shell_commands(command):
        if shell_command[0] == "cd" and len(shell_command) in {2, 3}:
            cwd = cwd / Path(shell_command[-1]).expanduser()
            continue
        arguments = _git_arguments(shell_command)
        if arguments is None:
            continue
        index = _skip_options(arguments, 0, options_with_values=_GIT_OPTIONS_WITH_VALUES)
        if arguments[index : index + 1] != ["merge"]:
            continue
        # NOTE: docs/ARCHITECTURE.md's Agent guards permit recovery on the target branch.
        if arguments[index + 1 :] in (["--continue"], ["--abort"], ["--quit"], ["--help"], ["-h"]):
            continue
        try:
            context = _git_context_for(cwd, cwd=cwd, git_options=tuple(arguments[:index]))
        except (NewFeatureError, OSError):
            continue
        if context is not None and context.branch == context.target_branch:
            return PolicyDenial(
                f"Direct git merge on target branch '{context.target_branch}' is disabled. "
                "Use `new-feature merge <feature-name>`. To finish or cancel an existing merge, "
                "use `git merge --continue`, `git merge --abort`, or `git merge --quit`."
            )
    return None


def _parse_shell_commands(command: str) -> list[list[str]]:
    try:
        lexer = shlex.shlex(command, posix=True, punctuation_chars=";&|()\n")
        lexer.whitespace = " \t\r"
        lexer.whitespace_split = True
        return _shell_commands(list(lexer))
    except ValueError:
        return []


def _shell_commands(tokens: list[str]) -> list[list[str]]:
    commands: list[list[str]] = []
    start = 0
    for index, token in enumerate(tokens):
        if not token or token.strip("\n") not in _SHELL_SEPARATORS:
            continue
        if start < index:
            commands.append(tokens[start:index])
        start = index + 1
    if start < len(tokens):
        commands.append(tokens[start:])
    return commands


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


def _git_context_for(path: Path, *, cwd: Path, git_options: tuple[str, ...] = ()) -> GitContext | None:
    probe = _existing_probe_path(path, cwd=cwd)
    root = _git_output(probe, *git_options, "rev-parse", "--show-toplevel")
    if root is None:
        return None
    root_path = Path(root).resolve()
    # NOTE: docs/ARCHITECTURE.md permits bootstrap only before the first commit.
    history = _git_output(probe, *git_options, "rev-list", "--all", "--max-count=1")
    if history is not None and not history:
        return None
    branch = _git_output(probe, *git_options, "branch", "--show-current")
    if not branch:
        return None
    # NOTE: docs/ARCHITECTURE.md documents protection of the configured target branch.
    target_branch = load_project_config(root_path).target_branch
    return GitContext(
        root=root_path,
        branch=BranchName(branch),
        target_branch=BranchName(target_branch),
    )


def _is_ignored_root_sidecar(path: Path, *, cwd: Path, root: Path) -> bool:
    # NOTE: docs/ARCHITECTURE.md permits only the ignored, untracked root configuration file.
    target = path.expanduser()
    if not target.is_absolute():
        target = cwd / target
    name = ".new-feature.local.toml"
    return target.resolve() == root / name and _git_output(root, "check-ignore", "--", name) == name


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
        env=git_environment(),
    )
    if result.returncode != 0:
        return None
    return result.stdout.strip()


def _edit_denial_reason(context: GitContext) -> str:
    return (
        "BLOCKED [new-feature-target-branch]: Direct agent edits are disabled on "
        f"target branch '{context.target_branch}' at {context.root}. Run "
        "`new-feature <feature-name> --no-agent`, then continue the work from "
        "`.worktrees/<feature-name>`."
    )


def _worktree_denial_reason(action: WorktreeAction) -> str:
    replacement = (
        "`new-feature <feature-name> --no-agent`"
        if action == "add"
        else "`new-feature teardown <feature-name>`"
    )
    return (
        f"BLOCKED [new-feature-worktree-{action}]: Direct `git worktree {action}` is disabled. "
        f"Use {replacement} instead. Only with human approval, prefix this command with `HUMAN_PERMISSION_GRANTED=1`."
    )
