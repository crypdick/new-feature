from __future__ import annotations

import hashlib
import re
import socket
from pathlib import Path
from typing import assert_never

from new_feature.config import (
    EnvSpec,
    IntegerEnvSpec,
    LiteralEnvSpec,
    NameEnvSpec,
    PathEnvSpec,
    PortEnvSpec,
    ProjectConfig,
    SlugEnvSpec,
)
from new_feature.errors import NewFeatureError
from new_feature.manifest import Manifest


def allocate_env(
    *,
    config: ProjectConfig,
    manifest: Manifest,
    name: str,
    slug: str,
    branch: str,
    worktree: Path,
    repo_root: Path,
) -> dict[str, str]:
    env = {
        "NEW_FEATURE_NAME": name,
        "NEW_FEATURE_SLUG": slug,
        "NEW_FEATURE_BRANCH": branch,
        "NEW_FEATURE_WORKTREE": str(worktree),
        "NEW_FEATURE_REPO_ROOT": str(repo_root),
    }
    for key, spec in config.env.items():
        env[key] = _allocate_value(key, spec, manifest, slug, repo_root)
    return env


def _allocate_value(key: str, spec: EnvSpec, manifest: Manifest, slug: str, repo_root: Path) -> str:
    match spec:
        case LiteralEnvSpec(value=value):
            return value
        case PortEnvSpec():
            reserved = _reserved_values(key, manifest)
            return _allocate_port(key, spec, reserved)
        case IntegerEnvSpec():
            reserved = _reserved_values(key, manifest)
            return _allocate_integer(key, spec, reserved)
        case NameEnvSpec():
            return _allocate_name(key, spec, slug, repo_root)
        case SlugEnvSpec(prefix=raw_prefix):
            prefix = _safe_token(raw_prefix, separator="-")
            return f"{prefix}-{slug}" if prefix else slug
        case PathEnvSpec(base=base):
            return str(Path(base) / slug)
        case _ as unreachable:  # pragma: no cover - EnvSpec is a closed union
            assert_never(unreachable)


def _reserved_values(key: str, manifest: Manifest) -> set[str]:
    return {record.env[key] for record in manifest.features.values() if key in record.env}


def _allocate_port(key: str, spec: PortEnvSpec, reserved: set[str]) -> str:
    for port in range(spec.minimum, spec.maximum + 1):
        if str(port) in reserved:
            continue
        if _port_available(port):
            return str(port)
    raise NewFeatureError(f"no available port for {key} in range {spec.minimum}-{spec.maximum}")


def _allocate_integer(key: str, spec: IntegerEnvSpec, reserved: set[str]) -> str:
    for value in range(spec.minimum, spec.maximum + 1):
        if str(value) not in reserved:
            return str(value)
    raise NewFeatureError(f"no available integer for {key} in range {spec.minimum}-{spec.maximum}")


def _allocate_name(key: str, spec: NameEnvSpec, slug: str, repo_root: Path) -> str:
    prefix = _safe_token(spec.prefix, separator="_")
    body = _safe_token(slug, separator="_")
    digest = hashlib.sha256(f"{repo_root}:{slug}:{key}".encode()).hexdigest()[:8]
    value = f"{prefix}_{body}_{digest}" if prefix else f"{body}_{digest}"
    if spec.max_length and len(value) > spec.max_length:
        suffix = f"_{digest}"
        value = value[: spec.max_length - len(suffix)].rstrip("_") + suffix
    return value


def _safe_token(value: str, *, separator: str) -> str:
    token = re.sub(r"[^a-zA-Z0-9]+", separator, value).strip(separator).lower()
    return re.sub(rf"{re.escape(separator)}+", separator, token)


def _port_available(port: int) -> bool:
    with socket.socket() as sock:
        try:
            sock.bind(("127.0.0.1", port))
        except OSError:
            return False
    return True
