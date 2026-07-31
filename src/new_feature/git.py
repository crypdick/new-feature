"""Wrap Git operations used by the managed feature lifecycle."""

from __future__ import annotations

import os
import subprocess
from pathlib import Path

from new_feature.errors import NewFeatureError


def repo_root(cwd: Path) -> Path:
    """Return the root directory of the Git repository containing ``cwd``."""
    result = _git(cwd, "rev-parse", "--show-toplevel", capture=True)
    return Path(result.stdout.strip())


def ensure_repo_has_commits(root: Path) -> None:
    """Raise when the repository has no commit that can seed a worktree."""
    result = subprocess.run(
        ["git", "rev-parse", "--verify", "HEAD"], cwd=root, capture_output=True, text=True, check=False
    )
    if result.returncode != 0:
        raise NewFeatureError("repository has no commits; make an initial commit before creating worktrees")


def create_worktree(root: Path, *, branch: str, worktree: Path, target_branch: str) -> None:
    """Create a feature branch and worktree from the configured target branch."""
    ensure_repo_has_commits(root)
    worktree.parent.mkdir(parents=True, exist_ok=True)
    _git(root, "worktree", "add", "-b", branch, str(worktree), target_branch)


def pull_target(root: Path, *, target_branch: str) -> None:
    """Fast-forward the clean, checked-out target branch from its upstream."""
    current_branch = _git(root, "branch", "--show-current", capture=True).stdout.strip()
    if current_branch != target_branch:
        raise NewFeatureError(f"target branch '{target_branch}' is not checked out")
    if not worktree_is_clean(root):
        raise NewFeatureError(
            "target checkout has uncommitted changes; commit or stash them before creating a feature"
        )
    _git(root, "pull", "--ff-only", capture=True)


def worktree_is_clean(worktree: Path) -> bool:
    """Return whether a worktree has no staged, unstaged, or untracked changes."""
    result = _git(worktree, "status", "--porcelain", capture=True)
    return not result.stdout.strip()


def branch_exists(root: Path, branch: str) -> bool:
    """Return whether a local branch exists."""
    result = subprocess.run(
        ["git", "show-ref", "--verify", "--quiet", f"refs/heads/{branch}"],
        cwd=root,
        check=False,
        env=_git_env(),
    )
    if result.returncode not in {0, 1}:
        raise NewFeatureError(f"git command failed while checking branch: {branch}")
    return result.returncode == 0


def is_branch_merged(root: Path, *, branch: str, target_branch: str) -> bool:
    """Return whether a branch is fully merged into the target branch."""
    result = subprocess.run(
        ["git", "merge-base", "--is-ancestor", branch, target_branch],
        cwd=root,
        check=False,
        env=_git_env(),
    )
    if result.returncode not in {0, 1}:
        raise NewFeatureError(f"git command failed while comparing {branch} with {target_branch}")
    return result.returncode == 0


def branch_has_unique_patches(root: Path, *, branch: str, target_branch: str) -> bool:
    """Return whether ``branch`` has a non-merge patch absent from the target history."""
    result = _git(root, "cherry", target_branch, branch, capture=True)
    return any(line.startswith("+ ") for line in result.stdout.splitlines())


def branch_has_unmerged_merge_commits(root: Path, *, branch: str, target_branch: str) -> bool:
    """Return whether the branch range contains a merge commit Git cherry would ignore."""
    result = _git(
        root,
        "rev-list",
        "--merges",
        "--max-count=1",
        f"{target_branch}..{branch}",
        capture=True,
    )
    return bool(result.stdout.strip())


def merge_is_clean(root: Path, *, branch: str, target_branch: str) -> bool:
    """Return whether merging a feature branch into its target would avoid conflicts."""
    result = subprocess.run(
        ["git", "merge-tree", "--write-tree", target_branch, branch],
        cwd=root,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        check=False,
        env=_git_env(),
    )
    if result.returncode not in {0, 1}:
        raise NewFeatureError(f"git command failed while checking merge of {branch} into {target_branch}")
    return result.returncode == 0


def ensure_merge_is_clean(root: Path, *, branch: str, target_branch: str) -> None:
    """Raise when merging a feature branch into its target would conflict."""
    if not merge_is_clean(root, branch=branch, target_branch=target_branch):
        raise NewFeatureError(
            "feature branch conflicts with the target branch; resolve the conflicts in the feature worktree before merging"
        )


def begin_merge_without_commit(root: Path, *, branch: str, target_branch: str) -> None:
    """Start a conflict-free no-commit merge into the expected target branch."""
    # NOTE: README.md's Lifecycle section documents this preflight safety guarantee.
    ensure_merge_is_clean(root, branch=branch, target_branch=target_branch)
    _git(root, "checkout", target_branch)
    _git(root, "merge", "--no-commit", "--no-ff", branch)


def commit_merge(root: Path, *, name: str) -> None:
    """Commit the currently prepared merge using the feature name."""
    _git(root, "commit", "-m", f"Merge feature {name}")


def resolve_revision(root: Path, ref: str) -> str:
    """Resolve a Git ref to its commit object ID."""
    return _git(root, "rev-parse", "--verify", ref, capture=True).stdout.strip()


def merge_in_progress(root: Path) -> bool:
    """Return whether the checkout has an active merge."""
    merge_head = _git(root, "rev-parse", "--git-path", "MERGE_HEAD", capture=True).stdout.strip()
    return (root / merge_head).exists()


def rollback_merge(root: Path, *, revision: str) -> None:
    """Restore a checkout that was clean before a managed merge."""
    _git(root, "reset", "--hard", revision)
    _git(root, "clean", "-fd")
    rollback_failed = [
        resolve_revision(root, "HEAD") != revision,
        merge_in_progress(root),
        not worktree_is_clean(root),
    ]
    if any(rollback_failed):
        raise NewFeatureError("managed merge rollback did not restore a clean target checkout")


def push_target(root: Path, *, target_branch: str) -> None:
    """Push the updated target branch to its configured upstream."""
    _git(root, "push", "origin", target_branch)


def remove_worktree_and_branch(
    root: Path, *, branch: str, worktree: Path, force: bool, force_branch: bool = False
) -> None:
    """Remove a feature worktree and delete its local branch."""
    args = ["worktree", "remove"]
    if force:
        args.append("--force")
    args.append(str(worktree))
    try:
        _git(root, *args)
    except NewFeatureError:
        if worktree.exists():
            raise
        _git(root, "worktree", "prune")
    _git(root, "branch", "-D" if force or force_branch else "-d", branch)


def _git(cwd: Path, *args: str, capture: bool = False) -> subprocess.CompletedProcess[str]:
    try:
        result = subprocess.run(
            ["git", *args], cwd=cwd, text=True, capture_output=capture, check=False, env=_git_env()
        )
    except OSError as exc:
        raise NewFeatureError(f"git command failed: {exc}") from exc
    if result.returncode != 0:
        detail = result.stderr.strip() if capture and result.stderr else " ".join(args)
        raise NewFeatureError(f"git command failed: {detail}")
    return result


def _git_env() -> dict[str, str]:
    env = os.environ.copy()
    for key in ("GIT_DIR", "GIT_WORK_TREE", "GIT_INDEX_FILE"):
        env.pop(key, None)
    return env
