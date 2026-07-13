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


def begin_merge_without_commit(root: Path, *, branch: str, target_branch: str) -> None:
    """Start a no-commit merge after confirming the expected target branch."""
    _git(root, "checkout", target_branch)
    _git(root, "merge", "--no-commit", "--no-ff", branch)


def commit_merge(root: Path, *, name: str) -> None:
    """Commit the currently prepared merge using the feature name."""
    _git(root, "commit", "-m", f"Merge feature {name}")


def abort_merge(root: Path) -> None:
    """Abort a merge that was started but not committed."""
    subprocess.run(["git", "merge", "--abort"], cwd=root, check=False, env=_git_env())


def push_target(root: Path, *, target_branch: str) -> None:
    """Push the updated target branch to its configured upstream."""
    _git(root, "push", "origin", target_branch)


def remove_worktree_and_branch(root: Path, *, branch: str, worktree: Path, force: bool) -> None:
    """Remove a feature worktree and delete its local branch."""
    args = ["worktree", "remove"]
    if force:
        args.append("--force")
    args.append(str(worktree))
    _git(root, *args)
    _git(root, "branch", "-D" if force else "-d", branch)


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
