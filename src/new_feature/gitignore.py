"""Maintain ignore rules for managed runtime state."""

from __future__ import annotations

from pathlib import Path

from filelock import FileLock

from new_feature.atomic_file import atomic_text_write
from new_feature.git import local_exclude_path

# NOTE: README.md documents the generated ignore rules for managed state and local preferences.
GENERATED_PATTERNS = [".new-feature/", ".worktrees/", "*.local.toml"]


def ensure_generated_paths_ignored(repo_root: Path) -> None:
    """Ignore managed state locally without modifying tracked files."""
    exclude = local_exclude_path(repo_root)
    exclude.parent.mkdir(parents=True, exist_ok=True)
    with FileLock(str(exclude) + ".new-feature.lock"):
        existing = exclude.read_text(encoding="utf-8") if exclude.exists() else ""
        missing = [pattern for pattern in GENERATED_PATTERNS if pattern not in existing.splitlines()]
        if missing:
            separator = "\n" if existing and not existing.endswith("\n") else ""
            atomic_text_write(exclude, existing + separator + "\n".join(missing) + "\n", default_mode=0o644)
