from __future__ import annotations

import tomllib
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass, field
from pathlib import Path

import tomli_w
from filelock import FileLock

MANIFEST_DIR = ".new-feature"
MANIFEST_FILE = "manifest.toml"
LOCK_FILE = "manifest.lock"


@dataclass
class FeatureRecord:
    name: str
    slug: str
    branch: str
    worktree: str
    target_branch: str
    status: str
    created_at: str
    merged_at: str = ""
    env: dict[str, str] = field(default_factory=dict)


@dataclass
class Manifest:
    version: int = 1
    features: dict[str, FeatureRecord] = field(default_factory=dict)


def manifest_path(repo_root: Path) -> Path:
    return repo_root / MANIFEST_DIR / MANIFEST_FILE


@contextmanager
def manifest_lock(repo_root: Path) -> Iterator[None]:
    lock_path = repo_root / MANIFEST_DIR / LOCK_FILE
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    with FileLock(str(lock_path)):
        yield


def load_manifest(repo_root: Path) -> Manifest:
    path = manifest_path(repo_root)
    if not path.exists():
        return Manifest()
    data = tomllib.loads(path.read_text(encoding="utf-8"))
    features: dict[str, FeatureRecord] = {}
    for key, raw in data.get("features", {}).items():
        features[key] = FeatureRecord(
            name=str(raw["name"]),
            slug=str(raw["slug"]),
            branch=str(raw["branch"]),
            worktree=str(raw["worktree"]),
            target_branch=str(raw["target_branch"]),
            status=str(raw["status"]),
            created_at=str(raw.get("created_at", "")),
            merged_at=str(raw.get("merged_at", "")),
            env={str(env_key): str(env_value) for env_key, env_value in raw.get("env", {}).items()},
        )
    return Manifest(version=int(data.get("version", 1)), features=features)


def save_manifest(repo_root: Path, manifest: Manifest) -> None:
    path = manifest_path(repo_root)
    path.parent.mkdir(parents=True, exist_ok=True)
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
                "env": record.env,
            }
            for key, record in sorted(manifest.features.items())
        },
    }
    path.write_text(tomli_w.dumps(data), encoding="utf-8")
