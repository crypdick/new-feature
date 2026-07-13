"""Persist and parse the lifecycle state of managed features."""

from __future__ import annotations

import tomllib
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass, field
from pathlib import Path
from typing import Literal, cast

import tomli_w
from filelock import FileLock

from new_feature.atomic_file import atomic_text_write
from new_feature.errors import NewFeatureError

MANIFEST_DIR = ".new-feature"
MANIFEST_FILE = "manifest.toml"
LOCK_FILE = "manifest.lock"
MANIFEST_VERSION = 2
type FeatureStatus = Literal["active", "merged"]
type RawTable = dict[str, object]

_FEATURE_FIELDS = {
    "name",
    "slug",
    "branch",
    "worktree",
    "target_branch",
    "status",
    "created_at",
    "merged_at",
    "config_fingerprint",
    "env",
}


@dataclass
class FeatureRecord:
    """Store the allocated state and lifecycle status of one managed feature."""

    name: str
    slug: str
    branch: str
    worktree: str
    target_branch: str
    status: FeatureStatus
    created_at: str
    merged_at: str = ""
    config_fingerprint: str = ""
    env: dict[str, str] = field(default_factory=dict)


@dataclass
class Manifest:
    """Store all managed feature records for one control checkout."""

    version: int = MANIFEST_VERSION
    features: dict[str, FeatureRecord] = field(default_factory=dict)


def manifest_path(repo_root: Path) -> Path:
    """Return the path of a repository's managed-feature manifest."""
    return repo_root / MANIFEST_DIR / MANIFEST_FILE


@contextmanager
def manifest_lock(repo_root: Path) -> Iterator[None]:
    """Serialize manifest reads and writes for a repository."""
    lock_path = repo_root / MANIFEST_DIR / LOCK_FILE
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    with FileLock(str(lock_path)):
        yield


def load_manifest(repo_root: Path) -> Manifest:
    """Load a repository manifest, returning an empty one when none exists."""
    path = manifest_path(repo_root)
    if not path.exists():
        return Manifest()
    try:
        data = tomllib.loads(path.read_text(encoding="utf-8"))
    except (OSError, tomllib.TOMLDecodeError) as exc:
        raise NewFeatureError(f"invalid feature manifest: {exc}") from exc
    version = _parse_version(data.get("version", 1))
    features = _parse_features(data.get("features", {}))
    return Manifest(version=MANIFEST_VERSION if version == 1 else version, features=features)


def _parse_version(value: object) -> int:
    if not isinstance(value, int) or isinstance(value, bool):
        raise NewFeatureError("feature manifest version must be an integer")
    if value not in {1, MANIFEST_VERSION}:
        raise NewFeatureError(f"unsupported manifest version: {value}")
    return value


def _parse_features(value: object) -> dict[str, FeatureRecord]:
    table = _table(value, location="features")
    return {key: _parse_feature(key, raw) for key, raw in table.items()}


def _parse_feature(key: str, value: object) -> FeatureRecord:
    raw = _table(value, location=f"features.{key}")
    unexpected = set(raw) - _FEATURE_FIELDS
    if unexpected:
        names = ", ".join(sorted(unexpected))
        raise NewFeatureError(f"feature manifest entry {key} has unsupported fields: {names}")
    return FeatureRecord(
        name=_required_string(raw, "name", entry=key),
        slug=_required_string(raw, "slug", entry=key),
        branch=_required_string(raw, "branch", entry=key),
        worktree=_required_string(raw, "worktree", entry=key),
        target_branch=_required_string(raw, "target_branch", entry=key),
        status=_feature_status(raw.get("status"), entry=key),
        created_at=_optional_string(raw, "created_at", entry=key),
        merged_at=_optional_string(raw, "merged_at", entry=key),
        config_fingerprint=_optional_string(raw, "config_fingerprint", entry=key),
        env=_string_map(raw.get("env", {}), location=f"features.{key}.env"),
    )


def _table(value: object, *, location: str) -> RawTable:
    if not isinstance(value, dict):
        raise NewFeatureError(f"feature manifest {location} must be a TOML table")
    return cast("RawTable", value)


def _required_string(raw: RawTable, field_name: str, *, entry: str) -> str:
    value = raw.get(field_name)
    if not isinstance(value, str) or not value:
        raise NewFeatureError(f"feature manifest entry {entry}.{field_name} must be a non-empty string")
    return value


def _optional_string(raw: RawTable, field_name: str, *, entry: str) -> str:
    value = raw.get(field_name, "")
    if not isinstance(value, str):
        raise NewFeatureError(f"feature manifest entry {entry}.{field_name} must be a string")
    return value


def _feature_status(value: object, *, entry: str) -> FeatureStatus:
    if value not in {"active", "merged"}:
        raise NewFeatureError(f"feature manifest entry {entry}.status must be active or merged")
    return value


def _string_map(value: object, *, location: str) -> dict[str, str]:
    table = _table(value, location=location)
    parsed: dict[str, str] = {}
    for key, item in table.items():
        if not isinstance(item, str):
            raise NewFeatureError(f"feature manifest {location} values must be strings")
        parsed[key] = item
    return parsed


def save_manifest(repo_root: Path, manifest: Manifest) -> None:
    """Atomically persist a managed-feature manifest to disk."""
    path = manifest_path(repo_root)
    data = {
        "version": manifest.version,
        "features": {
            key: {
                "name": record.name,
                "slug": record.slug,
                "branch": record.branch,
                "worktree": record.worktree,
                "target_branch": record.target_branch,
                "status": record.status,
                "created_at": record.created_at,
                "merged_at": record.merged_at,
                "config_fingerprint": record.config_fingerprint,
                "env": record.env,
            }
            for key, record in sorted(manifest.features.items())
        },
    }
    try:
        atomic_text_write(path, tomli_w.dumps(data), default_mode=0o600)
    except OSError as exc:
        raise NewFeatureError(f"cannot write feature manifest {path}: {exc}") from exc
