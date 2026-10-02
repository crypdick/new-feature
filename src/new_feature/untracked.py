"""Copy local work between checkouts without committing or overwriting it."""

from __future__ import annotations

import hashlib
import os
import shutil
import stat
import tempfile
from pathlib import Path

from new_feature.errors import NewFeatureError
from new_feature.git import initialized_submodules, untracked_paths

# NOTE: README.md's Local file transfer section lists these additive exclusions.
TEMPORARY_PATTERNS = [
    ".new-feature/",
    ".worktrees/",
    "__pycache__/",
    "*.pyc",
    "*.pyo",
    ".venv/",
    "venv/",
    "node_modules/",
    ".pytest_cache/",
    ".mypy_cache/",
    ".ruff_cache/",
    ".cache/",
    "build/",
    "dist/",
    "site/",
    "*.egg-info/",
    ".coverage",
    ".coverage.*",
    "htmlcov/",
    "*.tmp",
    "*.swp",
    "*~",
]


def local_paths(worktree: Path, excludes: list[str]) -> tuple[Path, ...]:
    """Find transferable local files with Git's native ignore-pattern matching."""
    # Built-in disposable patterns always apply alongside custom patterns.
    paths = list(untracked_paths(worktree, excludes=[*excludes, *TEMPORARY_PATTERNS]))
    # Check initialized submodules too: Git status omits their ignored files.
    for submodule in initialized_submodules(worktree):
        paths.extend(submodule / path for path in local_paths(worktree / submodule, excludes))
    return tuple(paths)


def same_local_file(source: Path, destination: Path) -> bool:
    """Compare regular-file contents and permission bits, rejecting symlinks."""
    if source.is_symlink() or destination.is_symlink() or not source.is_file() or not destination.is_file():
        return False
    if stat.S_IMODE(source.stat().st_mode) != stat.S_IMODE(destination.stat().st_mode):
        return False
    with source.open("rb") as original, destination.open("rb") as copied:
        return (
            hashlib.file_digest(original, "sha256").digest() == hashlib.file_digest(copied, "sha256").digest()
        )


def validate_local_paths(root: Path, worktree: Path, paths: tuple[Path, ...], tracked: set[Path]) -> None:
    """Refuse unsafe sources, destination aliases, tracked paths, or different files."""
    for relative in paths:
        source = worktree / relative
        destination = root / relative
        # NOTE: symlinks and nested repositories are refused; support needs explicit ownership semantics.
        if source.is_symlink() or not source.is_file():
            raise NewFeatureError(f"untracked transfer requires a regular file: {relative}")
        if any(parent in tracked for parent in (relative, *relative.parents)):
            raise NewFeatureError(f"untracked transfer conflicts with a tracked path: {relative}")
        for component in (relative, *relative.parents[:-1]):
            parent = root / component
            if parent.is_symlink():
                raise NewFeatureError(f"untracked transfer refuses a destination symlink: {relative}")
            if parent != destination and parent.exists() and not parent.is_dir():
                raise NewFeatureError(f"untracked transfer conflicts with a destination parent: {relative}")
        if destination.exists() and not same_local_file(source, destination):
            raise NewFeatureError(f"untracked transfer would overwrite a different file: {relative}")


def copy_local_files(root: Path, worktree: Path, paths: tuple[Path, ...], tracked: set[Path]) -> None:
    """Copy without replacing existing files; retain all originals on success or failure."""
    try:
        validate_local_paths(root, worktree, paths, tracked)
        for relative in paths:
            _copy_local_file(worktree / relative, root / relative)
    except OSError as exc:
        raise NewFeatureError(
            f"untracked file transfer failed; originals retained in {worktree}: {exc}"
        ) from exc


def require_local_files_preserved(root: Path, worktree: Path, excludes: list[str]) -> None:
    """Protect local work unless an identical regular file exists outside the worktree."""
    paths = local_paths(worktree, excludes)
    validate_local_paths(root, worktree, paths, set())
    missing = [str(path) for path in paths if not same_local_file(worktree / path, root / path)]
    if missing:
        raise NewFeatureError(
            f"feature worktree has unpreserved untracked or ignored files: {missing!r}; "
            "run merge --include-untracked or move them before teardown; "
            "pass --force only to discard them deliberately"
        )


def _copy_local_file(source: Path, destination: Path) -> None:
    if same_local_file(source, destination):
        return
    destination.parent.mkdir(parents=True, exist_ok=True)
    descriptor, name = tempfile.mkstemp(prefix=".new-feature-copy-", dir=destination.parent)
    temporary = Path(name)
    try:
        with os.fdopen(descriptor, "wb") as output, source.open("rb") as original:
            shutil.copyfileobj(original, output)
            output.flush()
            os.fsync(output.fileno())
        shutil.copystat(source, temporary)
        # link creates the destination atomically and refuses concurrent replacements.
        destination.hardlink_to(temporary)
    finally:
        temporary.unlink()
