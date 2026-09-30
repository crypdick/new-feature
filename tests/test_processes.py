from __future__ import annotations

import os
from typing import TYPE_CHECKING

from new_feature.processes import worktree_processes

if TYPE_CHECKING:
    from pathlib import Path


def test_process_scan_ignores_unrelated_and_unreadable_entries(tmp_path: Path):
    worktree = tmp_path / "feature"
    nested = worktree / "nested"
    nested.mkdir(parents=True)
    other = tmp_path / "feature-other"
    other.mkdir()
    proc = tmp_path / "proc"
    proc.mkdir()
    for name, cwd in [("30", nested), ("2", worktree), ("3", other), ("4", None), ("self", worktree)]:
        entry = proc / name
        entry.mkdir()
        if cwd is not None:
            (entry / "cwd").symlink_to(cwd)
    assert worktree_processes(worktree, proc_root=proc) == [2, 30]


def test_process_scan_ignores_other_users(tmp_path: Path, monkeypatch):
    proc = tmp_path / "proc"
    entry = proc / "2"
    entry.mkdir(parents=True)
    (entry / "cwd").symlink_to(tmp_path)
    monkeypatch.setattr(os, "getuid", lambda: entry.stat().st_uid + 1)
    assert worktree_processes(tmp_path, proc_root=proc) == []
