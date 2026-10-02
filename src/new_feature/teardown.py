"""Preview and perform guarded feature teardown."""

from __future__ import annotations

import sys
from dataclasses import dataclass
from pathlib import Path  # noqa: TC003 - beartype needs annotation types at runtime

from new_feature.commands import run_commands
from new_feature.config import ProjectConfig, load_project_config
from new_feature.errors import NewFeatureError
from new_feature.feature_state import IntegrationState, inspect_integration
from new_feature.git import remove_worktree_and_branch, worktree_branch, worktree_is_clean
from new_feature.inspection import warn_if_config_changed
from new_feature.manifest import FeatureRecord, load_manifest, manifest_lock, save_manifest
from new_feature.processes import require_no_worktree_processes
from new_feature.slug import feature_key, slugify
from new_feature.untracked import require_local_files_preserved


@dataclass(frozen=True)
class TeardownTarget:
    """Resolve resources to remove and cleanup environment available for them."""

    key: str
    worktree: Path
    branch: str | None
    target_branch: str
    record: FeatureRecord | None


def teardown(root: Path, name: str, *, force: bool, dry_run: bool = False) -> int:
    """Preview or remove a feature, retaining resources when cleanup fails."""
    config = load_project_config(root)
    target = _resolve_target(root, name, config)
    refusals = [] if force else _refusals(root, target, config)
    if dry_run:
        # NOTE: README.md documents lock-free preview, refusal exits, and cleanup uncertainty.
        _preview(target, config, refusals, force=force)
        return 1 if refusals else 0
    if refusals:
        raise NewFeatureError("; ".join(refusals))
    if target.record is None:
        sys.stderr.write("new-feature: unmanaged worktree; skipping configured teardown commands\n")
    else:
        warn_if_config_changed(config, target.record)
        run_commands(config.teardown, cwd=target.worktree, env=target.record.env)
    if not force:
        # NOTE: README.md documents process checks before cleanup and immediately before removal.
        require_no_worktree_processes(target.worktree)
        if not worktree_is_clean(target.worktree, allow_untracked=True):
            raise NewFeatureError(
                "feature worktree has uncommitted tracked changes; pass --force to abandon them"
            )
        require_local_files_preserved(root, target.worktree, config.safe_to_delete)
    remove_worktree_and_branch(
        root,
        branch=target.branch,
        worktree=target.worktree,
        # Git refuses ordinary untracked files even after their copies are verified.
        # NOTE: README.md documents safe deletion of preserved local files and excluded artifacts.
        force=True,
        force_branch=not force,
    )
    if target.record is not None:
        with manifest_lock(root):
            manifest = load_manifest(root)
            del manifest.features[target.key]
            save_manifest(root, manifest)
    return 0


def _resolve_target(root: Path, name: str, config: ProjectConfig) -> TeardownTarget:
    slug = slugify(name)
    key = feature_key(slug)
    record = load_manifest(root).features.get(key)
    if record is None:
        # NOTE: README.md documents teardown without a manifest entry.
        worktree = root / ".worktrees" / slug
        if not worktree.is_dir():
            raise NewFeatureError(f"unknown feature: {name}")
        branch = worktree_branch(worktree)
        target_branch = config.target_branch
    else:
        worktree = root / record.worktree
        branch = record.branch
        target_branch = record.target_branch
    if not worktree.is_dir():
        raise NewFeatureError(
            "feature worktree is missing; run `new-feature doctor --repair` to recover an integrated branch"
        )
    return TeardownTarget(key, worktree, branch, target_branch, record)


def _refusals(root: Path, target: TeardownTarget, config: ProjectConfig) -> list[str]:
    refusals: list[str] = []
    if not worktree_is_clean(target.worktree, allow_untracked=True):
        refusals.append("feature worktree has uncommitted changes; pass --force to abandon them")
    if target.branch is None:
        refusals.append("unmanaged worktree is detached; pass --force to abandon it")
    elif (
        inspect_integration(root, branch=target.branch, target_branch=target.target_branch)
        is IntegrationState.UNMERGED
    ):
        refusals.append("feature branch has unmerged commits; pass --force to abandon them")
    try:
        require_local_files_preserved(root, target.worktree, config.safe_to_delete)
    except NewFeatureError as exc:
        refusals.append(str(exc))
    try:
        require_no_worktree_processes(target.worktree)
    except NewFeatureError as exc:
        refusals.append(str(exc))
    return refusals


def _preview(target: TeardownTarget, config: ProjectConfig, refusals: list[str], *, force: bool) -> None:
    lines = [
        f"Worktree: {target.worktree.resolve()}",
        f"Branch: {target.branch or '(detached)'}",
        f"Target: {target.target_branch}",
        f"Force: {str(force).lower()}",
    ]
    if target.record is None:
        lines.append("Cleanup: skip configured cleanup (unmanaged worktree)")
    elif config.teardown:
        lines.extend(f"Cleanup: {command}" for command in config.teardown)
        lines.append("Cleanup failure would stop removal even with --force.")
    else:
        lines.append("Cleanup: no configured commands")
    lines.append("Action: remove worktree")
    if target.branch is not None:
        lines.append(f"Action: delete branch {target.branch}")
    if target.record is not None:
        lines.append(f"Action: remove manifest entry {target.key}")
    lines.extend(f"Refused: {reason}" for reason in refusals)
    if not refusals:
        lines.append("Ready: preflight passed; preview reserves nothing.")
    sys.stdout.write("\n".join(lines) + "\n")
