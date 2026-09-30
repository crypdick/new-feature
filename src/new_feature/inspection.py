"""Report human and machine-readable managed-feature state."""

from __future__ import annotations

import json
import sys
from pathlib import Path  # noqa: TC003 - beartype needs annotation types at runtime

from new_feature.config import ProjectConfig, config_fingerprint, load_project_config
from new_feature.feature_state import FeatureState, inspect_feature
from new_feature.manifest import (
    FeatureRecord,
    Manifest,
    feature_operation_lock,
    load_manifest,
    manifest_lock,
    save_manifest,
    target_merge_lock,
)
from new_feature.recovery import repair_feature


def write_json(payload: dict[str, object]) -> None:
    """Write one versioned JSON response to standard output."""
    # NOTE: README.md documents the inspection schema and stable error codes.
    sys.stdout.write(json.dumps({"schema_version": 1, **payload}, sort_keys=True) + "\n")


def feature_json(root: Path, record: FeatureRecord, state: FeatureState) -> dict[str, object]:
    """Represent feature identity and observed state without allocated environment secrets."""
    return {
        "name": record.name,
        "slug": record.slug,
        "branch": record.branch,
        "target_branch": record.target_branch,
        "worktree": str((root / record.worktree).resolve()),
        "status": record.status,
        "state": state.describe(),
        "issues": list(state.issues()),
        "worktree_exists": state.worktree_exists,
        "branch_exists": state.branch_exists,
        "clean": state.clean,
        "integration": state.integration,
        "config_drift": state.config_drift,
        "setup_incomplete": state.setup_incomplete,
        "worktree_error": state.worktree_error,
    }


def list_features(root: Path, *, json_output: bool) -> int:
    """Show managed feature states, optionally as one JSON document."""
    fingerprint = config_fingerprint(load_project_config(root))
    manifest = load_manifest(root)
    features: list[dict[str, object]] = []
    if not json_output:
        sys.stdout.write("NAME\tSTATE\tBRANCH\tWORKTREE\n")
    for record in sorted(manifest.features.values(), key=lambda item: item.slug):
        state = inspect_feature(root, record, fingerprint)
        features.append(feature_json(root, record, state))
        if not json_output:
            sys.stdout.write(f"{record.slug}\t{state.describe()}\t{record.branch}\t{record.worktree}\n")
        _worktree_warning(record, state)
    if json_output:
        write_json({"command": "list", "ok": True, "features": features})
    return 0


def doctor(root: Path, *, repair: bool, json_output: bool) -> int:
    """Report consistency problems and optionally remove recoverable stale state."""
    fingerprint = config_fingerprint(load_project_config(root))
    manifest = load_manifest(root)
    states = {key: inspect_feature(root, record, fingerprint) for key, record in manifest.features.items()}
    if not json_output:
        for key, state in sorted(states.items()):
            sys.stdout.write(f"{manifest.features[key].slug}: {state.describe()}\n")
            _worktree_warning(manifest.features[key], state)
    repairs = _repair_records(root, manifest, fingerprint, json_output=json_output) if repair else []
    if repair:
        # NOTE: README.md specifies that JSON repair reports remaining, current records.
        manifest = load_manifest(root)
        states = {
            key: inspect_feature(root, record, fingerprint) for key, record in manifest.features.items()
        }
    ok = not any(state.issues() for state in states.values())
    if json_output:
        for key, state in states.items():
            _worktree_warning(manifest.features[key], state)
        features = [
            feature_json(root, manifest.features[key], state)
            for key, state in sorted(states.items(), key=lambda item: manifest.features[item[0]].slug)
        ]
        write_json({"command": "doctor", "ok": ok, "features": features, "repairs": repairs})
    elif not states:
        sys.stdout.write("doctor: ok\n")
    return 0 if ok else 1


def _repair_records(
    root: Path, manifest: Manifest, fingerprint: str, *, json_output: bool
) -> list[dict[str, str]]:
    repairs: list[dict[str, str]] = []
    for key, observed in manifest.features.items():
        with (
            feature_operation_lock(root, observed.slug),
            target_merge_lock(root),
            manifest_lock(root),
        ):
            current = load_manifest(root)
            record = current.features.get(key)
            if record is None:
                continue
            state = inspect_feature(root, record, fingerprint)
            message = repair_feature(root, record, state)
            if message:
                del current.features[key]
                save_manifest(root, current)
                repairs.append({"slug": record.slug, "message": message})
                if not json_output:
                    sys.stdout.write(f"repaired: {message}\n")
    return repairs


def _worktree_warning(record: FeatureRecord, state: FeatureState) -> None:
    if state.worktree_error is not None:
        sys.stderr.write(f"new-feature: {record.slug}: {state.worktree_error}\n")


def warn_if_config_changed(config: ProjectConfig, record: FeatureRecord) -> None:
    """Warn when a feature retains allocations from an earlier project configuration."""
    if record.config_fingerprint and record.config_fingerprint != config_fingerprint(config):
        sys.stderr.write(
            f"new-feature: warning: project configuration changed since {record.slug} was created\n"
        )
