"""Evaluate provider-neutral managed-worktree hook requests."""

from __future__ import annotations

import hashlib
import itertools
import json
import re
import subprocess
import time
from contextlib import suppress
from dataclasses import dataclass
from pathlib import Path
from typing import NewType, TypedDict

from new_feature.config import load_project_config
from new_feature.git import git_environment
from new_feature.manifest import target_merge_lock_held
from new_feature.shell_commands import commands_with_cwd, parse_shell_commands

BranchName = NewType("BranchName", str)
WorktreeAction = NewType("WorktreeAction", str)

_WORKTREE_ACTIONS = {"add", "remove"}
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


class _Snapshot(TypedDict):
    """Tracked target changes plus the merge state that explains staged ones."""

    changes: dict[str, str]
    unstaged: list[str]
    # HEAD, MERGE_HEAD, and whether the target merge lock is held.
    merge: list[str | bool]


@dataclass(frozen=True)
class GitContext:
    """Describe the repository and branch that own a target path."""

    root: Path
    branch: BranchName
    target_branch: BranchName


@dataclass(frozen=True)
class WriteTarget:
    """Distinguish content writes from changes to a directory entry itself."""

    path: Path
    follow_symlinks: bool = True


def blocks_target_edit(targets: tuple[Path | WriteTarget, ...], *, cwd: Path) -> bool:
    """Protect both the named entry and any content destination it follows."""
    for target in targets:
        write = target if isinstance(target, WriteTarget) else WriteTarget(target)
        path = cwd / write.path.expanduser()
        entry = path.parent.resolve() / path.name
        destinations = {entry, entry.resolve()} if write.follow_symlinks else {entry}
        for destination in destinations:
            probe = destination.parent if destination.is_symlink() else destination
            context = _git_context_for(probe)
            if context is not None and context.branch == context.target_branch:
                ignored_target = destination.resolve() if write.follow_symlinks else destination
                if _is_ignored_untracked_path(ignored_target, root=context.root):
                    continue
                return True
    return False


def record_target_changes(command: str, *, cwd: Path, call_id: str | None) -> None:
    """Remember tracked changes on the target branch before a shell command runs."""
    for git_dir, directory in _reached_checkouts(command, cwd=cwd).items():
        snapshot = _target_snapshot(directory)
        if snapshot is None:
            continue
        path = _record_path(git_dir, call_id)
        if call_id is not None:
            path.parent.mkdir(exist_ok=True)
            # Another rule can block a call after this record, so its post check never runs.
            cutoff = time.time() - _STALE_RECORD_SECONDS
            for record in path.parent.iterdir():
                # Post checks and other cleanup calls can delete records concurrently.
                with suppress(FileNotFoundError):
                    if record.stat().st_mtime < cutoff:
                        record.unlink(missing_ok=True)
        path.write_text(json.dumps(snapshot), encoding="utf-8")


def target_changed_since_record(command: str, *, cwd: Path, call_id: str | None) -> bool:
    """Check whether tracked target-branch files changed since this call's record."""
    # NOTE: docs/ARCHITECTURE.md's Agent guards describe this post-command check.
    changed = False
    for git_dir, directory in _reached_checkouts(command, cwd=cwd).items():
        path = _record_path(git_dir, call_id)
        try:
            recorded = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            recorded = None
        if call_id is not None:
            path.unlink(missing_ok=True)
        snapshot = _target_snapshot(directory)
        if snapshot is None:
            continue
        if call_id is None:
            path.write_text(json.dumps(snapshot), encoding="utf-8")
        changed |= _changed_since(recorded, snapshot)
    return changed


def _changed_since(recorded: object, snapshot: _Snapshot) -> bool:
    previous = recorded if isinstance(recorded, dict) else {}
    before = previous.get("changes", {})
    changes, merge_state = snapshot["changes"], snapshot["merge"]
    if previous.get("merge") != merge_state or merge_state[2]:
        # NOTE: docs/ARCHITECTURE.md's Agent guards describe this merge-window trade-off.
        # Merges and commits stage what they change, so edits outside the index still stand out.
        changes = {name: changes[name] for name in snapshot["unstaged"] if name in changes}
    return any(name not in before or before[name] != signature for name, signature in changes.items())


def _reached_checkouts(command: str, *, cwd: Path) -> dict[Path, Path]:
    """Map the git dir of each checkout the command can reach to a directory inside it."""
    checkouts: dict[Path, Path] = {}
    directories = [cwd, *(directory for directory, _ in commands_with_cwd(command, cwd=cwd))]
    for directory in directories:
        probe = _existing_probe_path(directory)
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


def _target_snapshot(directory: Path) -> _Snapshot | None:
    context = _git_context_for(directory)
    if context is None or context.branch != context.target_branch:
        return None
    root = context.root
    names = _git_output(root, "diff", "HEAD", "--name-only", "--no-renames", "-z")
    unstaged = _git_output(root, "diff", "--name-only", "--no-renames", "--diff-filter=u", "-z")
    head = _git_output(root, "rev-parse", "HEAD")
    if names is None or unstaged is None or head is None:  # pragma: no cover - context proved history
        return None
    merge_head = _git_output(root, "rev-parse", "--quiet", "--verify", "MERGE_HEAD") or ""
    return {
        "changes": _signatures(root, names),
        "unstaged": list(filter(None, unstaged.split("\0"))),
        "merge": [head, merge_head, target_merge_lock_held(root)],
    }


def _signatures(root: Path, names: str) -> dict[str, str]:
    changes: dict[str, str] = {}
    for name in filter(None, names.split("\0")):
        diff = _git_output(
            root,
            "diff",
            "HEAD",
            "--binary",
            "--no-ext-diff",
            "--no-textconv",
            "--no-renames",
            "--",
            name,
            strip=False,
        )
        if diff is None:
            raise OSError(f"cannot fingerprint tracked changes: {root / name}")
        changes[name] = hashlib.sha256(diff.encode()).hexdigest()
    return changes


def parse_worktree_action(command: str) -> WorktreeAction | None:
    """Return the direct managed-worktree action invoked by a shell command."""
    for shell_command in parse_shell_commands(command):
        git_arguments = _git_arguments(shell_command)
        if git_arguments is None:
            continue
        action = _git_worktree_action(git_arguments, 0)
        if action is not None:
            return action
    return None


def blocks_target_merge(command: str, *, cwd: Path) -> bool:
    """Reject starting a direct merge on the configured target branch."""
    for directory, shell_command in commands_with_cwd(command, cwd=cwd):
        arguments = _git_arguments(shell_command)
        if arguments is None:
            continue
        index = _skip_options(arguments, 0, options_with_values=_GIT_OPTIONS_WITH_VALUES)
        if arguments[index : index + 1] != ["merge"]:
            continue
        # NOTE: docs/ARCHITECTURE.md's Agent guards permit recovery on the target branch.
        if arguments[index + 1 :] in (["--continue"], ["--abort"], ["--quit"], ["--help"], ["-h"]):
            continue
        context = _git_context_for(directory, git_options=tuple(arguments[:index]))
        if context is not None and context.branch == context.target_branch:
            return True
    return False


def shell_write_targets(command: str, *, cwd: Path) -> tuple[WriteTarget, ...]:
    """Return files that common shell redirections and file utilities would write."""
    # NOTE: docs/ARCHITECTURE.md's Agent guards list the recognized shell writes.
    targets: list[WriteTarget] = []
    for directory, shell_command in commands_with_cwd(command, cwd=cwd):
        targets.extend(
            WriteTarget(directory / Path(word).expanduser()) for word in _redirect_targets(shell_command)
        )
        index = _executable_index(shell_command)
        executable = Path(shell_command[index]).name if index is not None else ""
        operands = _utility_targets(shell_command)
        for index, word in enumerate(operands):
            path = directory / Path(word).expanduser()
            follows = _utility_follows_symlinks(
                executable, shell_command, path, destination=index == len(operands) - 1
            )
            targets.append(WriteTarget(path, follow_symlinks=follows))
    # NOTE: docs/ARCHITECTURE.md defers variable paths to the post-command check;
    # shlex removes quoting, so even quoted dollar signs cannot be resolved here.
    return tuple(target for target in targets if "$" not in str(target.path))


def _utility_follows_symlinks(executable: str, command: list[str], path: Path, *, destination: bool) -> bool:
    if executable == "sed":
        return "--follow-symlinks" in command
    if executable in {"mv", "ln", "install"}:
        options = list(itertools.takewhile(lambda word: word != "--", command))
        short_flags = "".join(
            word[1:] for word in options if word.startswith("-") and not word.startswith("--")
        )
        entry_only = "T" in short_flags or "--no-target-directory" in options
        if executable == "ln":
            entry_only |= "n" in short_flags or "--no-dereference" in options
        return destination and path.is_dir() and not entry_only
    return executable not in {"rm", "perl"}


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


def _git_context_for(path: Path, *, git_options: tuple[str, ...] = ()) -> GitContext | None:
    probe = _existing_probe_path(path)
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


def _is_ignored_untracked_path(path: Path, *, root: Path) -> bool:
    # NOTE: docs/ARCHITECTURE.md permits ignored, untracked paths on the target branch.
    try:
        relative = path.relative_to(root)
    except ValueError:
        return False
    return _git_output(root, "check-ignore", "--quiet", "--", str(relative)) is not None


def _existing_probe_path(path: Path) -> Path:
    probe = path.expanduser().absolute()
    if probe.exists():
        return probe if probe.is_dir() else probe.parent
    parent = probe.parent
    while not parent.exists():
        parent = parent.parent
    return parent


def _git_output(path: Path, *args: str, strip: bool = True) -> str | None:
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
    return result.stdout.strip() if strip else result.stdout
