"""Wrap Git operations used by the managed feature lifecycle."""

from __future__ import annotations

import os
import subprocess
from dataclasses import dataclass
from pathlib import Path

from new_feature.errors import NewFeatureError


@dataclass(frozen=True)
class SubmoduleState:
    """An initialized submodule checkout, separate from its parent's index pin."""

    path: Path
    head: str
    branch: str | None
    status: str


@dataclass(frozen=True)
class CheckoutState:
    """Git state whose identity bounds a managed merge's ownership."""

    branch: str | None
    head: str
    merge_heads: tuple[str, ...]
    tree: str
    unstaged: str
    untracked: str
    submodules: tuple[SubmoduleState, ...]


def checkout_state(root: Path) -> CheckoutState:
    """Read exact commit, index, merge, and nonignored working-tree state."""
    merge_head = Path(run_git(root, "rev-parse", "--git-path", "MERGE_HEAD", capture=True).stdout.strip())
    merge_head = root / merge_head
    return CheckoutState(
        branch=worktree_branch(root),
        head=resolve_revision(root, "HEAD"),
        merge_heads=tuple(merge_head.read_text().splitlines()) if merge_head.exists() else (),
        tree=run_git(root, "write-tree", capture=True).stdout.strip(),
        # NOTE: docs/ARCHITECTURE.md's merge ownership separates gitlinks from checkouts.
        unstaged=run_git(
            root, "diff", "--no-ext-diff", "--binary", "--ignore-submodules=all", capture=True
        ).stdout,
        untracked=run_git(root, "ls-files", "--others", "--exclude-standard", "-z", capture=True).stdout,
        submodules=tuple(
            SubmoduleState(
                path=path,
                head=resolve_revision(root / path, "HEAD"),
                branch=worktree_branch(root / path),
                status=run_git(
                    root / path, "status", "--porcelain", "--untracked-files=all", capture=True
                ).stdout,
            )
            for path in initialized_submodules(root)
        ),
    )


def indexed_gitlink(root: Path, path: Path) -> str:
    """Read the exact gitlink commit recorded in the parent index."""
    return run_git(root, "rev-parse", f":{path.as_posix()}", capture=True).stdout.strip()


def commit_parents(root: Path, revision: str) -> tuple[str, ...]:
    """Return a commit's ordered parent identities."""
    return tuple(run_git(root, "show", "-s", "--format=%P", revision, capture=True).stdout.split())


def repo_root(cwd: Path) -> Path:
    """Return the root directory of the Git repository containing ``cwd``."""
    result = run_git(cwd, "rev-parse", "--show-toplevel", capture=True)
    return Path(result.stdout.strip())


def worktree_inventory(root: Path) -> dict[Path, str | None]:
    """Return registered worktree paths and their checked-out local branches."""
    result = run_git(root, "worktree", "list", "--porcelain", "-z", capture=True)
    inventory: dict[Path, str | None] = {}
    for entry in result.stdout.strip("\0").split("\0\0"):
        fields = entry.split("\0")
        path = Path(fields[0].removeprefix("worktree ")).resolve()
        branch = next(
            (field.removeprefix("branch refs/heads/") for field in fields if field.startswith("branch ")),
            None,
        )
        inventory[path] = branch
    return inventory


def local_exclude_path(root: Path) -> Path:
    """Resolve the local exclude file shared by the repository's worktrees."""
    result = run_git(root, "rev-parse", "--path-format=absolute", "--git-path", "info/exclude", capture=True)
    return Path(result.stdout.strip())


def ensure_repo_has_commits(root: Path) -> None:
    """Raise when the repository has no commit that can seed a worktree."""
    result = subprocess.run(
        ["git", "rev-parse", "--verify", "HEAD"],
        cwd=root,
        capture_output=True,
        text=True,
        check=False,
        env=git_environment(),
    )
    if result.returncode != 0:
        raise NewFeatureError("repository has no commits; make an initial commit before creating worktrees")


def create_worktree(root: Path, *, branch: str, worktree: Path, target_branch: str) -> None:
    """Create a feature branch and worktree from the configured target branch."""
    ensure_repo_has_commits(root)
    worktree.parent.mkdir(parents=True, exist_ok=True)
    run_git(root, "worktree", "add", "-b", branch, str(worktree), target_branch)


def import_worktree(root: Path, *, branch: str, worktree: Path, source: str) -> bool:
    """Check out an existing branch without hooks, filters, or filesystem monitors."""
    ref = run_git(
        root, "rev-parse", "--symbolic-full-name", "--verify", "--end-of-options", source, capture=True
    ).stdout.strip()
    if not ref.startswith(("refs/heads/", "refs/remotes/")) or ref.endswith("/HEAD"):
        raise NewFeatureError("--from requires an existing local or remote branch")
    owns_branch = ref != f"refs/heads/{branch}"
    options = inert_git_options(root)
    worktree.parent.mkdir(parents=True, exist_ok=True)
    arguments = ["-b", branch, str(worktree), ref] if owns_branch else [str(worktree), branch]
    run_git(root, *options, "worktree", "add", *arguments)
    return owns_branch


def inert_git_options(root: Path) -> list[str]:
    """Disable Git callbacks when checking out or inspecting unreviewed code."""
    # NOTE: README.md documents inert import and inspection without Git callbacks.
    options = ["-c", "core.hooksPath=/dev/null", "-c", "core.fsmonitor=false"]
    for entry in run_git(root, "config", "--null", "--list", capture=True).stdout.split("\0"):
        key = entry.split("\n", 1)[0]
        if key.startswith("filter.") and key.endswith((".clean", ".smudge", ".process", ".required")):
            options.extend(["-c", f"{key}={'false' if key.endswith('.required') else ''}"])
    return options


def pull_target(root: Path, *, target_branch: str, ignore_dirty: bool = False) -> None:
    """Fast-forward the checked-out target branch from its upstream.

    With ignore_dirty, uncommitted changes stay in place; `git pull --ff-only`
    still refuses to overwrite any of them.
    """
    current_branch = run_git(root, "branch", "--show-current", capture=True).stdout.strip()
    if current_branch != target_branch:
        raise NewFeatureError(f"target branch '{target_branch}' is not checked out")
    if not ignore_dirty and not worktree_is_clean(root):
        raise NewFeatureError(
            "target checkout has uncommitted changes; commit or stash them before creating a feature, "
            "or pass --ignore-dirty to keep them in place"
        )
    run_git(root, "pull", "--ff-only", capture=True)


def worktree_is_clean(worktree: Path, *, allow_untracked: bool = False, inert: bool = False) -> bool:
    """Return whether a worktree has no staged, unstaged, or untracked changes."""
    args = ("--untracked-files=no",) if allow_untracked else ()
    options = inert_git_options(worktree) if inert else []
    result = run_git(worktree, *options, "status", "--porcelain", *args, capture=True)
    return not result.stdout.strip()


def untracked_paths(worktree: Path, *, excludes: list[str]) -> tuple[Path, ...]:
    """List untracked files, including ignored files, except explicit ignore patterns."""
    arguments = [f"--exclude={pattern}" for pattern in excludes]
    result = run_git(worktree, "ls-files", "--others", "-z", *arguments, capture=True)
    return tuple(Path(name) for name in result.stdout.split("\0") if name)


def initialized_submodules(worktree: Path) -> tuple[Path, ...]:
    """List initialized submodule directories from the worktree index."""
    result = run_git(worktree, "ls-files", "--stage", "-z", capture=True)
    paths = []
    for entry in result.stdout.split("\0"):
        if entry.startswith("160000 "):
            path = Path(entry.partition("\t")[2])
            if (worktree / path / ".git").exists():
                paths.append(path)
    return tuple(paths)


def branch_paths(root: Path, branch: str) -> set[Path]:
    """Return tracked paths at a branch tip, including submodule roots."""
    result = run_git(root, "ls-tree", "-r", "--name-only", "-z", branch, capture=True)
    return {Path(name) for name in result.stdout.split("\0") if name}


def worktree_branch(worktree: Path) -> str | None:
    """Return the checked-out branch, or None for a detached worktree."""
    branch = run_git(worktree, "branch", "--show-current", capture=True).stdout.strip()
    return branch or None


def branch_exists(root: Path, branch: str) -> bool:
    """Return whether a local branch exists."""
    result = subprocess.run(
        ["git", "show-ref", "--verify", "--quiet", f"refs/heads/{branch}"],
        cwd=root,
        check=False,
        env=git_environment(),
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
        env=git_environment(),
    )
    if result.returncode not in {0, 1}:
        raise NewFeatureError(f"git command failed while comparing {branch} with {target_branch}")
    return result.returncode == 0


def branch_has_unique_patches(root: Path, *, branch: str, target_branch: str) -> bool:
    """Return whether ``branch`` has a non-merge patch absent from the target history."""
    result = run_git(root, "cherry", target_branch, branch, capture=True)
    return any(line.startswith("+ ") for line in result.stdout.splitlines())


def branch_has_unmerged_merge_commits(root: Path, *, branch: str, target_branch: str) -> bool:
    """Return whether the branch range contains a merge commit Git cherry would ignore."""
    result = run_git(
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
    return merge_result_tree(root, branch=branch, target_branch=target_branch) is not None


def merge_result_tree(root: Path, *, branch: str, target_branch: str) -> str | None:
    """Return the tree a conflict-free merge would produce, or None when it would conflict."""
    result = subprocess.run(
        ["git", "merge-tree", "--write-tree", target_branch, branch],
        cwd=root,
        text=True,
        capture_output=True,
        check=False,
        env=git_environment(),
    )
    if result.returncode not in {0, 1}:
        raise NewFeatureError(f"git command failed while checking merge of {branch} into {target_branch}")
    return result.stdout.split("\n", 1)[0] if result.returncode == 0 else None


def target_merge_base(root: Path, *, target_branch: str, fetch: bool) -> str:
    """Return the ref a merge builds on: origin/<target> when the target can fast-forward to it.

    With fetch, refresh origin first and refuse a target that has diverged from it.
    """
    if not fetch:
        return target_branch
    run_git(root, "fetch", "--quiet", "origin", capture=True)
    # NOTE: relies on the default origin refspec; a missing ref means nothing is published yet.
    upstream = f"refs/remotes/origin/{target_branch}"
    if not git_succeeds(root, "show-ref", "--verify", "--quiet", upstream):
        return target_branch
    if git_succeeds(root, "merge-base", "--is-ancestor", target_branch, upstream):
        return upstream
    if not git_succeeds(root, "merge-base", "--is-ancestor", upstream, target_branch):
        raise NewFeatureError(
            f"target branch '{target_branch}' has diverged from origin/{target_branch}; "
            f"integrate origin/{target_branch} into it before merging"
        )
    return target_branch


def ensure_push_possible(root: Path, *, base: str, target_branch: str) -> None:
    """Refuse early when origin rejects a dry-run push of the merge base to the target branch.

    This catches unreachable remotes, missing credentials, and lost write access;
    server-side hooks and branch protection only run on the real push.
    """
    # NOTE: README.md documents the push preflight and its limits.
    result = subprocess.run(
        ["git", "push", "--dry-run", "--quiet", "origin", f"{base}:refs/heads/{target_branch}"],
        cwd=root,
        text=True,
        capture_output=True,
        check=False,
        env=git_environment(),
    )
    if result.returncode != 0:
        detail = result.stderr.strip().splitlines()[-1:] or ["no details from git"]
        raise NewFeatureError(
            f"cannot push {target_branch} to origin ({detail[0]}); fix access before merging"
        )


def ensure_merge_is_clean(root: Path, *, branch: str, target_branch: str) -> None:
    """Raise when merging a feature branch into its target would conflict."""
    if not merge_is_clean(root, branch=branch, target_branch=target_branch):
        raise NewFeatureError(
            "feature branch conflicts with the target branch; resolve the conflicts in the feature worktree before merging"
        )


def checkout_target(root: Path, *, target_branch: str) -> None:
    """Select the target before assuming ownership of its rollback state."""
    run_git(root, "checkout", target_branch)


def merge_feature_branch(
    root: Path,
    *,
    branch: str,
    target_branch: str,
    git_args: tuple[str, ...] = (),
) -> None:
    """Merge a feature branch into the expected target branch."""
    # NOTE: README.md documents that custom Git arguments bypass the default conflict preflight.
    if not git_args:
        ensure_merge_is_clean(root, branch=branch, target_branch=target_branch)
        git_args = ("--no-commit", "--no-ff")
    _ensure_incoming_paths_safe(root, branch=branch, target_branch=target_branch)
    run_git(root, "merge", *git_args, branch)


def commit_merge(root: Path, *, name: str, git_args: tuple[str, ...] = ()) -> None:
    """Finish a prepared merge with the appropriate message and editor behavior."""
    if not git_args:
        run_git(root, "commit", "-m", f"Merge feature {name}")
        return
    # Git has already prepared MERGE_MSG or SQUASH_MSG from the supplied options.
    commit_args = ("commit",) if {"--edit", "-e"}.intersection(git_args) else ("commit", "--no-edit")
    run_git(root, *commit_args)


def resolve_revision(root: Path, ref: str) -> str:
    """Resolve a Git ref to its commit object ID."""
    return run_git(root, "rev-parse", "--verify", ref, capture=True).stdout.strip()


def merge_in_progress(root: Path) -> bool:
    """Return whether the checkout has an active merge."""
    merge_head = run_git(root, "rev-parse", "--git-path", "MERGE_HEAD", capture=True).stdout.strip()
    return (root / merge_head).exists()


def rollback_merge(root: Path, *, revision: str) -> None:
    """Restore a checkout that was clean before a managed merge."""
    run_git(root, "reset", "--hard", revision)
    rollback_failed = [
        resolve_revision(root, "HEAD") != revision,
        merge_in_progress(root),
        not worktree_is_clean(root),
    ]
    if any(rollback_failed):
        raise NewFeatureError("managed merge rollback did not restore a clean target checkout")


def sync_target_with_origin(root: Path, *, target_branch: str) -> None:
    """Fast-forward the checked-out target to origin so a merge builds on published history."""
    base = target_merge_base(root, target_branch=target_branch, fetch=True)
    if base != target_branch:
        run_git(root, "merge", "--ff-only", "--quiet", base, capture=True)


def git_succeeds(root: Path, *args: str) -> bool:
    return subprocess.run(["git", *args], cwd=root, check=False, env=git_environment()).returncode == 0


def push_target(root: Path, *, target_branch: str) -> None:
    """Push the updated target branch to its configured upstream."""
    run_git(root, "push", "origin", target_branch)


def remove_worktree_and_branch(
    root: Path, *, branch: str | None, worktree: Path, force: bool, force_branch: bool = False
) -> None:
    """Remove a worktree and its local branch when it has one."""
    args = ["worktree", "remove"]
    if force:
        args.append("--force")
    args.append(str(worktree))
    # NOTE: README.md requires JSON repair stdout to contain only its report.
    try:
        run_git(root, *args, capture=True)
    except NewFeatureError:
        if not worktree.exists():
            run_git(root, "worktree", "prune", capture=True)
        elif not force and worktree_is_clean(worktree):
            # Git requires --force to remove a worktree containing a submodule,
            # even when both worktree and submodule are clean.
            run_git(root, "worktree", "remove", "--force", str(worktree), capture=True)
        else:
            raise
    if branch is not None:
        run_git(root, "branch", "-D" if force or force_branch else "-d", branch, capture=True)


def run_git(cwd: Path, *args: str, capture: bool = False) -> subprocess.CompletedProcess[str]:
    try:
        result = subprocess.run(
            ["git", *args], cwd=cwd, text=True, capture_output=capture, check=False, env=git_environment()
        )
    except OSError as exc:
        raise NewFeatureError(f"git command failed: {exc}") from exc
    if result.returncode != 0:
        detail = result.stderr.strip() if capture and result.stderr else " ".join(args)
        raise NewFeatureError(f"git command failed: {detail}")
    return result


def git_environment() -> dict[str, str]:
    """Keep transport settings but discard the caller's repository context."""
    # NOTE: docs/ARCHITECTURE.md documents isolation for Git, lifecycle commands, and agents.
    env = os.environ.copy()
    for key in (
        "GIT_DIR",
        "GIT_COMMON_DIR",
        "GIT_WORK_TREE",
        "GIT_IMPLICIT_WORK_TREE",
        "GIT_INDEX_FILE",
        "GIT_OBJECT_DIRECTORY",
        "GIT_ALTERNATE_OBJECT_DIRECTORIES",
        "GIT_GRAFT_FILE",
        "GIT_SHALLOW_FILE",
        "GIT_PREFIX",
    ):
        env.pop(key, None)
    return env


def _ensure_incoming_paths_safe(root: Path, *, branch: str, target_branch: str) -> None:
    # NOTE: README.md documents collision checks that protect ignored target files.
    tracked_target = branch_paths(root, target_branch)
    for relative in branch_paths(root, branch) - tracked_target:
        destination = root / relative
        if destination.is_dir() and not destination.is_symlink():
            collision = bool(
                run_git(
                    root,
                    "--literal-pathspecs",
                    "ls-files",
                    "--others",
                    "-z",
                    "--",
                    str(relative),
                    capture=True,
                ).stdout
            )
        else:
            collision = destination.exists()
        if collision or any(
            (root / part).is_symlink()
            or (part != relative and (root / part).exists() and not (root / part).is_dir())
            for part in (relative, *relative.parents[:-1])
            if part not in tracked_target
        ):
            raise NewFeatureError(f"git merge would overwrite an existing local path: {relative}")
