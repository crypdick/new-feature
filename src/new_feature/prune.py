"""Remove integrated managed features using normal teardown safeguards."""

from __future__ import annotations

import sys
from contextlib import nullcontext
from pathlib import Path  # noqa: TC003 - runtime annotation checking

from new_feature.control_checkout import require_managed_worktree
from new_feature.errors import NewFeatureError
from new_feature.feature_state import IntegrationState, inspect_integration
from new_feature.inspection import write_json
from new_feature.manifest import FeatureRecord, feature_operation_lock, load_manifest
from new_feature.output import command_output
from new_feature.slug import feature_key
from new_feature.teardown import preview_teardown, teardown


def prune_features(root: Path, *, dry_run: bool, json_output: bool) -> int:
    """Process managed features in slug order and report each cleanup outcome."""
    # NOTE: README.md documents explicit merged policy, preview, and normal teardown checks.
    records = sorted(load_manifest(root).features.values(), key=lambda record: record.slug)
    results: list[dict[str, object]] = []
    for record in records:
        with command_output(json_output=json_output):
            outcome, reasons = _prune_feature(root, record, dry_run=dry_run)
        results.append({
            "slug": record.slug,
            "branch": record.branch,
            "worktree": str((root / record.worktree).resolve()),
            "outcome": outcome,
            "reasons": reasons,
        })
        if not json_output:
            detail = f": {'; '.join(reasons)}" if reasons else ""
            sys.stdout.write(f"{record.slug}\t{outcome}{detail}\n")
    ok = all(result["outcome"] != "refused" for result in results)
    if json_output:
        write_json({"command": "prune", "ok": ok, "dry_run": dry_run, "features": results})
    elif not results:
        sys.stdout.write("No managed features.\n")
    return 0 if ok else 1


def _prune_feature(root: Path, record: FeatureRecord, *, dry_run: bool) -> tuple[str, list[str]]:
    try:
        with nullcontext() if dry_run else feature_operation_lock(root, record.slug):
            return _prune_current(root, record, dry_run=dry_run)
    except NewFeatureError as exc:
        return "refused", [str(exc)]


def _prune_current(root: Path, record: FeatureRecord, *, dry_run: bool) -> tuple[str, list[str]]:
    current = load_manifest(root).features.get(feature_key(record.slug))
    if current != record:
        raise NewFeatureError("feature changed since inventory; refresh before pruning")
    require_managed_worktree(root, root / record.worktree, record.branch)
    integration = inspect_integration(root, branch=record.branch, target_branch=record.target_branch)
    if integration is IntegrationState.UNMERGED:
        return "skipped", ["unmerged"]
    if dry_run:
        preview = preview_teardown(root, record.slug)
        return ("refused", preview.refusals) if preview.refusals else ("would-remove", [])
    teardown(root, record.slug, force=False)
    return "removed", []
