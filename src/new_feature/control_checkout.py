"""Find the checkout owning a managed feature's lifecycle state."""

from __future__ import annotations

from pathlib import Path  # noqa: TC003 - beartype requires annotation types at runtime

from new_feature.errors import NewFeatureError
from new_feature.git import repo_root, worktree_inventory
from new_feature.manifest import load_manifest


def control_root(cwd: Path) -> Path:
    """Resolve manifest ownership through Git's registered worktrees."""
    current = repo_root(cwd).resolve()
    inventory = worktree_inventory(current)
    # NOTE: docs/ARCHITECTURE.md requires manifest ownership, not common-Git-directory guesses.
    owners: set[Path] = set()
    for candidate in inventory:
        for branch in _ownership_claims(candidate, current):
            if branch != inventory[current]:
                raise NewFeatureError(
                    f"managed worktree branch does not match its owning manifest: {current}"
                )
            owners.add(candidate)
    if len(owners) > 1:
        raise NewFeatureError(f"ambiguous managed worktree ownership: {current}")
    return next(iter(owners), current)


def require_managed_worktree(root: Path, worktree: Path, branch: str) -> Path:
    """Require a recorded path and branch to match a registered Git checkout."""
    path = worktree.resolve()
    if not path.is_dir() or worktree_inventory(root).get(path) != branch:
        raise NewFeatureError(f"feature worktree or branch is missing or mismatched: {worktree}")
    return path


def _ownership_claims(candidate: Path, current: Path) -> set[str]:
    """Inspect matching paths without letting broken unrelated sibling state interfere."""
    try:
        manifest = load_manifest(candidate)
    except NewFeatureError:
        # NOTE: docs/ARCHITECTURE.md limits unreadable-manifest failures to plausible owners.
        if candidate == current or current.is_relative_to(candidate / ".worktrees"):
            raise
        return set()
    return {
        record.branch
        for record in manifest.features.values()
        if (candidate / record.worktree).resolve() == current
    }
