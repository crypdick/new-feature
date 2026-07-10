from __future__ import annotations

from pathlib import Path
import subprocess

from new_feature.errors import NewFeatureError


def repo_root(cwd: Path) -> Path:
    result = _git(cwd, "rev-parse", "--show-toplevel", capture=True)
    return Path(result.stdout.strip())


def ensure_repo_has_commits(root: Path) -> None:
    result = subprocess.run(["git", "rev-parse", "--verify", "HEAD"], cwd=root, capture_output=True, text=True)
    if result.returncode != 0:
        raise NewFeatureError("repository has no commits; make an initial commit before creating worktrees")


def create_worktree(root: Path, *, branch: str, worktree: Path, target_branch: str) -> None:
    ensure_repo_has_commits(root)
    worktree.parent.mkdir(parents=True, exist_ok=True)
    _git(root, "worktree", "add", "-b", branch, str(worktree), target_branch)


def worktree_is_clean(worktree: Path) -> bool:
    result = _git(worktree, "status", "--porcelain", capture=True)
    return result.stdout.strip() == ""


def is_branch_merged(root: Path, *, branch: str, target_branch: str) -> bool:
    result = subprocess.run(["git", "merge-base", "--is-ancestor", branch, target_branch], cwd=root)
    return result.returncode == 0


def begin_merge_without_commit(root: Path, *, branch: str, target_branch: str) -> None:
    _git(root, "checkout", target_branch)
    _git(root, "merge", "--no-commit", "--no-ff", branch)


def commit_merge(root: Path, *, name: str) -> None:
    _git(root, "commit", "-m", f"Merge feature {name}")


def abort_merge(root: Path) -> None:
    subprocess.run(["git", "merge", "--abort"], cwd=root)


def push_target(root: Path, *, target_branch: str) -> None:
    _git(root, "push", "origin", target_branch)


def remove_worktree_and_branch(root: Path, *, branch: str, worktree: Path, force: bool) -> None:
    args = ["worktree", "remove"]
    if force:
        args.append("--force")
    args.append(str(worktree))
    _git(root, *args)
    _git(root, "branch", "-D" if force else "-d", branch)


def _git(cwd: Path, *args: str, capture: bool = False) -> subprocess.CompletedProcess[str]:
    result = subprocess.run(["git", *args], cwd=cwd, text=True, capture_output=capture)
    if result.returncode != 0:
        detail = result.stderr.strip() if capture and result.stderr else " ".join(args)
        raise NewFeatureError(f"git command failed: {detail}")
    return result
