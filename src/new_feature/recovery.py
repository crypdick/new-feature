"""Repair managed-feature records that cannot retain unmerged work."""

from __future__ import annotations

from typing import TYPE_CHECKING

from new_feature.git import remove_worktree_and_branch

if TYPE_CHECKING:
    import pathlib

    import new_feature.feature_state
    import new_feature.manifest


def repair_feature(
    root: pathlib.Path,
    record: new_feature.manifest.FeatureRecord,
    state: new_feature.feature_state.FeatureState,
) -> str | None:
    """Repair a stale feature record and return a description of the repair."""
    if state.stale:
        return f"removed stale manifest entry {record.slug}"
    if not state.worktree_exists and state.branch_exists and state.merged:
        remove_worktree_and_branch(
            root,
            branch=record.branch,
            worktree=root / record.worktree,
            force=False,
        )
        return f"removed missing worktree and merged branch {record.slug}"
    return None
