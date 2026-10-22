"""Evaluate provider-neutral managed-worktree hook requests."""

from __future__ import annotations

import hashlib
import itertools
import json
import re
import shlex
import subprocess
import time
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, NewType

from new_feature.config import load_project_config
from new_feature.git import git_environment

if TYPE_CHECKING:
    from collections.abc import Iterator

BranchName = NewType("BranchName", str)
WorktreeAction = NewType("WorktreeAction", str)

_WORKTREE_ACTIONS = {"add", "remove"}
_SHELL_SEPARATORS = {";", "&&", "||", "|", "&", "(", ")", ""}
_ASSIGNMENT = re.compile(r"[A-Za-z_][A-Za-z0-9_]*=.*\Z")
# Preserve quoting here so a literal '<<' cannot start a heredoc. shlex removes it.
_HEREDOC_TOKENS = re.compile(
    r"\#[^\n]*|"
    r"""(?:[^\s;&|()<>'"\\]+|\\[\s\S]|'[^']*'|"(?:\\[\s\S]|[^"\\])*")+|"""
    r"<<-|[;&|()<>]+"
)
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
_STALE_RECORD_SECONDS = 24 * 60 * 60
_REDIRECT_WRITES = {">", ">>", ">|", "&>", "&>>", "<>"}
_REDIRECT_OPERATORS = _REDIRECT_WRITES | {"<", "<<", "<<<", ">&", "<&"}
_FD_DUPLICATION = re.compile(r"\d+-?|-\Z")
_IN_PLACE_EDITORS = {"sed", "perl"}
_IN_PLACE_SCRIPT_OPTIONS = {"-e", "-f", "--expression", "--file"}
_LAST_ARGUMENT_WRITERS = {"cp", "install", "ln"}
_ALL_ARGUMENT_WRITERS = {"tee", "mv", "rm", "touch", "truncate"}
_WRITER_OPTIONS_WITH_VALUES = {"-s", "--size", "-r", "--reference", "-m", "--mode", "-S", "--suffix"}
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
class GitContext:
    """Describe the repository and branch that own a target path."""

    root: Path
    branch: BranchName
    target_branch: BranchName


def blocks_target_edit(targets: tuple[Path, ...], *, cwd: Path) -> bool:
    """Check whether any target belongs to the protected branch."""
    for target in targets:
        context = _git_context_for(target, cwd=cwd)
        if context is not None and context.branch == context.target_branch:
            if _is_ignored_untracked_path(target, cwd=cwd, root=context.root):
                continue
            return True
    return False


def record_target_changes(command: str, *, cwd: Path, call_id: str | None) -> None:
    """Remember tracked changes on the target branch before a shell command runs."""
    for git_dir, directory in _reached_checkouts(command, cwd=cwd).items():
        changes = _target_changes(directory)
        if changes is None:
            continue
        path = _record_path(git_dir, call_id)
        if call_id is not None:
            path.parent.mkdir(exist_ok=True)
            # Another rule can block a call after this record, so its post check never runs.
            cutoff = time.time() - _STALE_RECORD_SECONDS
            for record in path.parent.iterdir():
                if record.stat().st_mtime < cutoff:
                    record.unlink(missing_ok=True)
        path.write_text(json.dumps(changes), encoding="utf-8")


def target_changed_since_record(command: str, *, cwd: Path, call_id: str | None) -> bool:
    """Check whether tracked target-branch files changed since this call's record."""
    # NOTE: docs/ARCHITECTURE.md's Agent guards describe this post-command check.
    changed = False
    for git_dir, directory in _reached_checkouts(command, cwd=cwd).items():
        path = _record_path(git_dir, call_id)
        try:
            recorded = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            recorded = {}
        if call_id is not None:
            path.unlink(missing_ok=True)
        changes = _target_changes(directory)
        if changes is None:
            continue
        if call_id is None:
            path.write_text(json.dumps(changes), encoding="utf-8")
        changed |= any(
            name not in recorded or recorded[name] != signature for name, signature in changes.items()
        )
    return changed


def _reached_checkouts(command: str, *, cwd: Path) -> dict[Path, Path]:
    """Map the git dir of each checkout the command can reach to a directory inside it."""
    checkouts: dict[Path, Path] = {}
    directories = [cwd, *(directory for directory, _ in _commands_with_cwd(command, cwd=cwd))]
    for directory in directories:
        probe = _existing_probe_path(directory, cwd=cwd)
        git_dir = _git_output(probe, "rev-parse", "--absolute-git-dir")
        if git_dir is not None:
            checkouts.setdefault(Path(git_dir), probe)
    return checkouts


def _record_path(git_dir: Path, call_id: str | None) -> Path:
    if call_id is None:
        # NOTE: without a harness call ID, concurrent shell calls share one record.
        return git_dir / "new-feature-shell-changes.json"
    name = hashlib.sha256(call_id.encode()).hexdigest()
    return git_dir / "new-feature-shell-changes" / f"{name}.json"


def _target_changes(directory: Path) -> dict[str, list[int] | None] | None:
    context = _git_context_for(directory, cwd=directory)
    if context is None or context.branch != context.target_branch:
        return None
    names = _git_output(context.root, "diff", "HEAD", "--name-only", "--no-renames", "-z")
    if names is None:  # pragma: no cover - context proved a repository with history
        return None
    changes: dict[str, list[int] | None] = {}
    for name in filter(None, names.split("\0")):
        try:
            status = (context.root / name).lstat()
        except FileNotFoundError:
            changes[name] = None
        else:
            changes[name] = [status.st_mtime_ns, status.st_size]
    return changes


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


def blocks_target_merge(command: str, *, cwd: Path) -> bool:
    """Reject starting a direct merge on the configured target branch."""
    for directory, shell_command in _commands_with_cwd(command, cwd=cwd):
        arguments = _git_arguments(shell_command)
        if arguments is None:
            continue
        index = _skip_options(arguments, 0, options_with_values=_GIT_OPTIONS_WITH_VALUES)
        if arguments[index : index + 1] != ["merge"]:
            continue
        # NOTE: docs/ARCHITECTURE.md's Agent guards permit recovery on the target branch.
        if arguments[index + 1 :] in (["--continue"], ["--abort"], ["--quit"], ["--help"], ["-h"]):
            continue
        context = _git_context_for(directory, cwd=directory, git_options=tuple(arguments[:index]))
        if context is not None and context.branch == context.target_branch:
            return True
    return False


def shell_write_targets(command: str, *, cwd: Path) -> tuple[Path, ...]:
    """Return files that common shell redirections and file utilities would write."""
    # NOTE: docs/ARCHITECTURE.md's Agent guards list the recognized shell writes.
    targets: list[Path] = []
    for directory, shell_command in _commands_with_cwd(command, cwd=cwd):
        targets.extend(directory / Path(word).expanduser() for word in _redirect_targets(shell_command))
        targets.extend(directory / Path(word).expanduser() for word in _utility_targets(shell_command))
    return tuple(targets)


def _commands_with_cwd(command: str, *, cwd: Path) -> Iterator[tuple[Path, list[str]]]:
    """Yield each non-cd shell command with the directory literal cd commands left it in."""
    for shell_command in _parse_shell_commands(command):
        if shell_command[0] == "cd" and len(shell_command) in {2, 3}:
            cwd = cwd / Path(shell_command[-1]).expanduser()
            continue
        yield cwd, shell_command


def _redirect_targets(command: list[str]) -> list[str]:
    targets = []
    for operator, target in itertools.pairwise(command):
        if operator in _REDIRECT_WRITES or (operator == ">&" and not _FD_DUPLICATION.fullmatch(target)):
            targets.append(target)
    return targets


def _utility_targets(command: list[str]) -> list[str]:
    index = _executable_index(command)
    if index is None:
        return []
    executable = Path(command[index]).name
    arguments = _without_redirects(command[index + 1 :])
    if executable in _IN_PLACE_EDITORS:
        return _in_place_targets(arguments)
    if executable not in _LAST_ARGUMENT_WRITERS | _ALL_ARGUMENT_WRITERS:
        return []
    operands = _operands(arguments, options_with_values=_WRITER_OPTIONS_WITH_VALUES)
    return operands[-1:] if executable in _LAST_ARGUMENT_WRITERS else operands


def _in_place_targets(arguments: list[str]) -> list[str]:
    in_place = any(
        word.startswith("--in-place") or (re.fullmatch(r"-[A-Za-z]*i.*", word) is not None)
        for word in arguments
    )
    if not in_place:
        return []
    operands = _operands(arguments, options_with_values=_IN_PLACE_SCRIPT_OPTIONS)
    has_script_option = any(word.split("=", 1)[0] in _IN_PLACE_SCRIPT_OPTIONS for word in arguments)
    return operands if has_script_option else operands[1:]


def _without_redirects(arguments: list[str]) -> list[str]:
    result: list[str] = []
    index = 0
    while index < len(arguments):
        word = arguments[index]
        following = arguments[index + 1] if index + 1 < len(arguments) else ""
        if word in _REDIRECT_OPERATORS:
            index += 2
            continue
        # A file descriptor number such as the 2 in 2>/dev/null belongs to the redirect.
        if not (word.isdigit() and following in _REDIRECT_OPERATORS):
            result.append(word)
        index += 1
    return result


def _operands(arguments: list[str], *, options_with_values: set[str]) -> list[str]:
    operands: list[str] = []
    index = 0
    while index < len(arguments):
        word = arguments[index]
        if word == "--":
            operands.extend(arguments[index + 1 :])
            break
        if word.split("=", 1)[0] in options_with_values and "=" not in word:
            index += 2
            continue
        if not word.startswith("-"):
            operands.append(word)
        index += 1
    return operands


def _parse_shell_commands(command: str) -> list[list[str]]:
    tokens: list[str] = []
    heredocs: list[tuple[str, bool]] = []
    header = ""
    for line in command.splitlines(keepends=True):
        if heredocs:
            delimiter, strip_tabs = heredocs[0]
            candidate = line.lstrip("\t") if strip_tabs else line
            if candidate.removesuffix("\n") == delimiter:
                heredocs.pop(0)
            continue
        header += line
        if header.endswith("\\\n"):
            continue
        try:
            lexer = shlex.shlex(header, posix=True, punctuation_chars=";&|()<>\n")
            lexer.whitespace = " \t\r"
            lexer.whitespace_split = True
            words = list(lexer)
        except ValueError:
            # A quoted shell argument may span physical lines.
            continue
        tokens.extend(words)
        # NOTE: docs/ARCHITECTURE.md excludes heredoc data from shell command checks.
        raw_words = _HEREDOC_TOKENS.findall(header)
        heredocs.extend(
            (shlex.split(target, comments=False)[0], operator == "<<-")
            for operator, target in itertools.pairwise(raw_words)
            if operator in {"<<", "<<-"}
        )
        header = ""
    return [] if header else _shell_commands(tokens)


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


def _is_ignored_untracked_path(path: Path, *, cwd: Path, root: Path) -> bool:
    # NOTE: docs/ARCHITECTURE.md permits ignored, untracked paths on the target branch.
    target = path.expanduser()
    if not target.is_absolute():
        target = cwd / target
    try:
        relative = target.resolve().relative_to(root)
    except ValueError:
        return False
    return _git_output(root, "check-ignore", "--quiet", "--", str(relative)) is not None


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
