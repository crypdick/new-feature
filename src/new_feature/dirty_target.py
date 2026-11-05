"""Set aside an unrelated dirty target checkout during merge --ignore-dirty."""

from __future__ import annotations

import uuid
from contextlib import contextmanager
from pathlib import Path
from typing import TYPE_CHECKING

from new_feature.errors import NewFeatureError
from new_feature.git import git_succeeds, merge_result_tree, run_git, target_merge_base, worktree_is_clean

if TYPE_CHECKING:
    from collections.abc import Iterator


@contextmanager
def uncommitted_changes_set_aside(root: Path, *, purpose: str) -> Iterator[None]:
    """Stash uncommitted changes, including untracked files, and restore them afterwards.

    Restoring runs on success and failure. When the stash cannot be applied
    cleanly, it stays on the stash stack and the error names its commit.
    """
    # NOTE: README.md documents --ignore-dirty and its retained-stash recovery.
    stash = None
    if not worktree_is_clean(root):
        message = f"new-feature {purpose} {uuid.uuid4().hex[:12]}"
        run_git(root, "stash", "push", "--include-untracked", "--quiet", "--message", message, capture=True)
        # Git stashes nothing for changes such as dirty submodules; callers' clean checks still apply.
        stash = _stash_entry(root, field="%H", subject=message)
    if stash is None:
        yield
        return
    try:
        yield
    except BaseException as error:
        _restore_stash(root, stash, failure=error)
        raise
    _restore_stash(root, stash)


def _restore_stash(root: Path, stash: str, *, failure: BaseException | None = None) -> None:
    if not git_succeeds(root, "stash", "apply", "--index", "--quiet", stash):
        message = (
            f"uncommitted target changes did not restore cleanly and remain in stash {stash}; "
            f"inspect `git status`, then restore on a clean checkout with `git stash apply --index {stash}`"
        )
        if failure is None:
            raise NewFeatureError(message)
        raise NewFeatureError(f"{failure}; {message}") from failure
    # Locate the entry by commit at drop time; other processes may have pushed or dropped stashes.
    entry = _stash_entry(root, field="%gd", commit=stash)
    if entry is not None:
        run_git(root, "stash", "drop", "--quiet", entry, capture=True)


def _stash_entry(
    root: Path, *, field: str, subject: str | None = None, commit: str | None = None
) -> str | None:
    listing = run_git(root, "stash", "list", f"--format={field}%x00%H%x00%gs", capture=True).stdout
    for line in listing.splitlines():
        value, entry_commit, entry_subject = line.split("\0", 2)
        if entry_commit == commit or (subject is not None and entry_subject.endswith(subject)):
            return value
    return None


def ensure_changes_clear_of_merge(
    root: Path, *, branch: str, target_branch: str, fetch: bool, local_files: tuple[Path, ...]
) -> None:
    """Refuse when uncommitted changes touch paths the merge or local file copies would change.

    This mirrors `git merge` with a dirty checkout, so restoring stashed changes
    after the merge does not conflict.
    """
    # NOTE: README.md documents the --ignore-dirty overlap refusal.
    dirty = _dirty_paths(root)
    if not dirty:
        return
    base = target_merge_base(root, target_branch=target_branch, fetch=fetch)
    incoming = set(local_files)
    result_tree = merge_result_tree(root, branch=branch, target_branch=base)
    if result_tree is None:
        raise NewFeatureError(
            "feature branch conflicts with the target branch, so --ignore-dirty cannot predict which "
            "paths the merge changes; commit or stash target changes, or resolve the conflicts first"
        )
    diff = run_git(root, "diff", "--name-only", "--no-renames", "-z", "HEAD", result_tree, capture=True)
    incoming.update(Path(name) for name in diff.stdout.split("\0") if name)
    overlap = sorted(
        str(path)
        for path in dirty
        if any(path == other or other in path.parents or path in other.parents for other in incoming)
    )
    if overlap:
        raise NewFeatureError(
            "uncommitted target changes touch paths this merge changes: "
            f"{', '.join(overlap)}; commit or stash them before merging"
        )


def _dirty_paths(root: Path) -> tuple[Path, ...]:
    status = run_git(
        root, "status", "--porcelain=v1", "-z", "--untracked-files=all", "--no-renames", capture=True
    ).stdout
    return tuple(Path(entry[3:]) for entry in status.split("\0") if entry)
