"""Inspect Linux process working directories before removing a worktree."""

from __future__ import annotations

import os
from pathlib import Path

from new_feature.errors import NewFeatureError


def worktree_processes(worktree: Path, *, proc_root: Path = Path("/proc")) -> list[int]:
    """Find same-user processes with a working directory inside this worktree."""
    worktree = worktree.resolve()
    try:
        entries = list(proc_root.iterdir())
    except OSError as exc:
        raise NewFeatureError(
            f"cannot inspect process working directories: {exc}; pass --force to bypass"
        ) from exc
    processes: list[int] = []
    for entry in entries:
        if not entry.name.isdecimal():
            continue
        try:
            if entry.stat().st_uid != os.getuid():
                continue
            cwd = (entry / "cwd").readlink().resolve()
        except OSError:
            # NOTE: README.md documents vanished/unreadable process and scan-race limitations.
            continue
        if cwd.is_relative_to(worktree):
            processes.append(int(entry.name))
    return sorted(processes)


def require_no_worktree_processes(worktree: Path) -> None:
    """Refuse removal while a visible same-user process uses this working directory."""
    processes = worktree_processes(worktree)
    if processes:
        detail = ", ".join(f"PID {pid}" for pid in processes)
        raise NewFeatureError(
            f"processes have working directories inside feature worktree ({detail}); stop them or pass --force"
        )
