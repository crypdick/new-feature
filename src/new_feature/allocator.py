from __future__ import annotations

from pathlib import Path
import hashlib
import re
import socket

from new_feature.config import EnvSpec, ProjectConfig
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
    if spec.value is not None:
        return spec.value
    reserved = {record.env[key] for record in manifest.features.values() if key in record.env}
    match spec.allocate:
        case "port":
            return _allocate_port(key, spec, reserved)
        case "integer":
            return _allocate_integer(key, spec, reserved)
        case "name":
            return _allocate_name(key, spec, slug, repo_root)
        case "slug":
            prefix = _safe_token(spec.prefix or key.lower(), separator="-")
            return f"{prefix}-{slug}" if prefix else slug
        case "path":
            base = spec.base or ".new-feature"
            return str(Path(base) / slug)
        case None:
            raise NewFeatureError(f"env spec {key} must set value or allocate")
        case other:
            raise NewFeatureError(f"unsupported allocator for {key}: {other}")


def _allocate_port(key: str, spec: EnvSpec, reserved: set[str]) -> str:
    minimum = spec.minimum if spec.minimum is not None else 1024
    maximum = spec.maximum if spec.maximum is not None else 65535
    for port in range(minimum, maximum + 1):
        if str(port) in reserved:
            continue
        if _port_available(port):
            return str(port)
    raise NewFeatureError(f"no available port for {key} in range {minimum}-{maximum}")


def _allocate_integer(key: str, spec: EnvSpec, reserved: set[str]) -> str:
    minimum = spec.minimum if spec.minimum is not None else 0
    maximum = spec.maximum if spec.maximum is not None else 65535
    for value in range(minimum, maximum + 1):
        if str(value) not in reserved:
            return str(value)
    raise NewFeatureError(f"no available integer for {key} in range {minimum}-{maximum}")


def _allocate_name(key: str, spec: EnvSpec, slug: str, repo_root: Path) -> str:
    prefix = _safe_token(spec.prefix or key.lower(), separator="_")
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
