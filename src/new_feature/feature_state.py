from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from new_feature.git import branch_exists, is_branch_merged, worktree_is_clean
from new_feature.manifest import FeatureRecord


@dataclass(frozen=True)
class FeatureState:
    worktree_exists: bool
    branch_exists: bool
    clean: bool | None
    merged: bool | None
    config_drift: bool

    @property
    def stale(self) -> bool:
        return not self.worktree_exists and not self.branch_exists

    def issues(self) -> tuple[str, ...]:
        issues: list[str] = []
        if not self.worktree_exists:
            issues.append("missing-worktree")
        if not self.branch_exists:
            issues.append("missing-branch")
        if self.clean is False:
            issues.append("dirty")
        if self.merged is False:
            issues.append("unmerged")
        if self.config_drift:
            issues.append("config-drift")
        return tuple(issues)

    def describe(self) -> str:
        issues = self.issues()
        return ",".join(issues) if issues else "ok"


def inspect_feature(root: Path, record: FeatureRecord, current_fingerprint: str) -> FeatureState:
    worktree = root / record.worktree
    worktree_exists = worktree.is_dir()
    local_branch_exists = branch_exists(root, record.branch)
    clean = worktree_is_clean(worktree) if worktree_exists else None
    merged = (
        is_branch_merged(root, branch=record.branch, target_branch=record.target_branch)
        if local_branch_exists
        else None
    )
    return FeatureState(
        worktree_exists=worktree_exists,
        branch_exists=local_branch_exists,
        clean=clean,
        merged=merged,
        config_drift=bool(record.config_fingerprint) and record.config_fingerprint != current_fingerprint,
    )
