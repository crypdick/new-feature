"""Inspect managed feature worktrees and summarize their lifecycle state."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path

from new_feature.git import (
    branch_exists,
    branch_has_unique_patches,
    branch_has_unmerged_merge_commits,
    is_branch_merged,
    worktree_is_clean,
)
from new_feature.manifest import FeatureRecord


class IntegrationState(StrEnum):
    """Describe how a feature branch's commits relate to its target branch."""

    MERGED = "merged"
    PATCH_EQUIVALENT = "patch-equivalent"
    UNMERGED = "unmerged"


@dataclass(frozen=True)
class FeatureState:
    """Describe a managed feature's branch, worktree, and configuration health."""

    worktree_exists: bool
    branch_exists: bool
    clean: bool | None
    integration: IntegrationState | None
    config_drift: bool

    @property
    def stale(self) -> bool:
        """Return whether the feature record points to missing Git resources."""
        return not self.worktree_exists and not self.branch_exists

    def issues(self) -> tuple[str, ...]:
        """Return the detected consistency problems for this feature."""
        issues: list[str] = []
        if not self.worktree_exists:
            issues.append("missing-worktree")
        if not self.branch_exists:
            issues.append("missing-branch")
        if self.clean is False:
            issues.append("dirty")
        if self.integration is IntegrationState.UNMERGED:
            issues.append("unmerged")
        if self.config_drift:
            issues.append("config-drift")
        return tuple(issues)

    def describe(self) -> str:
        """Return a compact human-readable summary of the feature state."""
        labels = list(self.issues())
        if self.integration is IntegrationState.PATCH_EQUIVALENT:
            position = labels.index("config-drift") if "config-drift" in labels else len(labels)
            labels.insert(position, IntegrationState.PATCH_EQUIVALENT.value)
        return ",".join(labels) if labels else "ok"


def inspect_integration(root: Path, *, branch: str, target_branch: str) -> IntegrationState:
    """Classify whether a feature is merged, patch-equivalent, or still unmerged."""
    if is_branch_merged(root, branch=branch, target_branch=target_branch):
        return IntegrationState.MERGED
    # git cherry ignores merge commits, whose conflict resolutions can contain unique changes.
    if branch_has_unmerged_merge_commits(root, branch=branch, target_branch=target_branch):
        return IntegrationState.UNMERGED
    if branch_has_unique_patches(root, branch=branch, target_branch=target_branch):
        return IntegrationState.UNMERGED
    return IntegrationState.PATCH_EQUIVALENT


def inspect_feature(root: Path, record: FeatureRecord, current_fingerprint: str) -> FeatureState:
    """Inspect a feature record against the current repository and configuration."""
    worktree = root / record.worktree
    worktree_exists = worktree.is_dir()
    local_branch_exists = branch_exists(root, record.branch)
    clean = worktree_is_clean(worktree) if worktree_exists else None
    integration = (
        inspect_integration(root, branch=record.branch, target_branch=record.target_branch)
        if local_branch_exists
        else None
    )
    return FeatureState(
        worktree_exists=worktree_exists,
        branch_exists=local_branch_exists,
        clean=clean,
        integration=integration,
        config_drift=bool(record.config_fingerprint) and record.config_fingerprint != current_fingerprint,
    )
