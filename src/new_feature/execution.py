"""Run commands with a managed feature's saved runtime environment."""

from __future__ import annotations

from pathlib import Path  # noqa: TC003 - beartype requires annotation types at runtime

from new_feature import commands
from new_feature.control_checkout import require_managed_worktree
from new_feature.errors import NewFeatureError
from new_feature.feature_state import require_setup_complete
from new_feature.manifest import feature_execution_lock, load_manifest, manifest_lock
from new_feature.slug import feature_key, slugify


def execute_feature(root: Path, name: str, argv: list[str]) -> int:
    """Select an exact normalized feature and execute a literal command there."""
    slug = slugify(name)
    with feature_execution_lock(root, slug):
        with manifest_lock(root):
            record = load_manifest(root).features.get(feature_key(slug))
        if record is None:
            raise NewFeatureError(f"unknown feature: {name}")
        require_setup_complete(record)
        worktree = require_managed_worktree(root, root / record.worktree, record.branch)
        return commands.run_argv(argv, cwd=worktree, env=record.env)
