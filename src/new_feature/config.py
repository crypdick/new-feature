from __future__ import annotations

import hashlib
import json
import re
import tomllib
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import cast

from new_feature.errors import NewFeatureError

type AgentCommand = tuple[str, ...]
type RawTable = dict[str, object]

_CONFIG_KEYS = {
    "target_branch",
    "agent",
    "push",
    "setup",
    "pre_merge",
    "post_merge",
    "teardown",
    "env",
}
_ALLOCATOR_KEYS = {
    "port": {"allocate", "min", "max"},
    "integer": {"allocate", "min", "max"},
    "name": {"allocate", "prefix", "max_length"},
    "slug": {"allocate", "prefix"},
    "path": {"allocate", "base"},
}
_ENV_NAME = re.compile(r"[A-Za-z_][A-Za-z0-9_]*\Z")


@dataclass(frozen=True)
class EnvSpec:
    allocate: str | None = None
    value: str | None = None
    minimum: int | None = None
    maximum: int | None = None
    prefix: str | None = None
    max_length: int | None = None
    base: str | None = None


@dataclass(frozen=True)
class ProjectConfig:
    target_branch: str = "main"
    agent: AgentCommand = ("codex",)
    push: bool = False
    setup: list[str] = field(default_factory=list)
    pre_merge: list[str] = field(default_factory=list)
    post_merge: list[str] = field(default_factory=list)
    teardown: list[str] = field(default_factory=list)
    env: dict[str, EnvSpec] = field(default_factory=dict)


def _string_list(raw: RawTable, name: str) -> list[str]:
    value = raw.get(name, [])
    if not isinstance(value, list) or not all(isinstance(item, str) and item for item in value):
        raise NewFeatureError(f"tool.new-feature.{name} must be a list of non-empty strings")
    return list(value)


def _agent_command(raw: RawTable) -> AgentCommand:
    # NOTE: README.md documents this value as an argv prefix.
    value = raw.get("agent", ["codex"])
    if not isinstance(value, list) or not value:
        raise NewFeatureError("tool.new-feature.agent must be a non-empty list of non-empty strings")
    if not all(isinstance(item, str) for item in value) or not all(value):
        raise NewFeatureError("tool.new-feature.agent must be a non-empty list of non-empty strings")
    return tuple(value)


def _string(raw: RawTable, name: str, default: str) -> str:
    value = raw.get(name, default)
    if not isinstance(value, str) or not value:
        raise NewFeatureError(f"tool.new-feature.{name} must be a non-empty string")
    return value


def _boolean(raw: RawTable, name: str, *, default: bool) -> bool:
    value = raw.get(name, default)
    if not isinstance(value, bool):
        raise NewFeatureError(f"tool.new-feature.{name} must be a boolean")
    return value


def _optional_string(raw: RawTable, name: str, *, env_key: str) -> str | None:
    value = raw.get(name)
    if value is not None and (not isinstance(value, str) or not value):
        raise NewFeatureError(f"env spec {env_key}.{name} must be a non-empty string")
    return value


def _required_string_option(raw: RawTable, name: str, *, env_key: str) -> str:
    value = raw[name]
    if not isinstance(value, str) or not value:
        raise NewFeatureError(f"env spec {env_key}.{name} must be a non-empty string")
    return value


def _optional_int(raw: RawTable, name: str, *, env_key: str) -> int | None:
    value = raw.get(name)
    if value is not None and (not isinstance(value, int) or isinstance(value, bool)):
        raise NewFeatureError(f"env spec {env_key}.{name} must be an integer")
    return value


def _env_spec(key: str, raw: object) -> EnvSpec:
    if not _ENV_NAME.fullmatch(key):
        raise NewFeatureError(f"env name must be a valid environment variable: {key}")
    if not isinstance(raw, dict):
        raise NewFeatureError(f"env spec {key} must be a TOML inline table")
    table = cast("RawTable", raw)
    has_value = "value" in table
    has_allocator = "allocate" in table
    if has_value == has_allocator:
        raise NewFeatureError(f"env spec {key} must set exactly one of value or allocate")
    if has_value:
        return _literal_env_spec(key, table)
    return _allocated_env_spec(key, table)


def _literal_env_spec(key: str, raw: RawTable) -> EnvSpec:
    if set(raw) != {"value"}:
        raise NewFeatureError(f"env spec {key} with value cannot set allocator options")
    return EnvSpec(value=_required_string_option(raw, "value", env_key=key))


def _allocated_env_spec(key: str, raw: RawTable) -> EnvSpec:
    allocator = _required_string_option(raw, "allocate", env_key=key)
    allowed = _ALLOCATOR_KEYS.get(allocator)
    if allowed is None:
        raise NewFeatureError(f"unsupported allocator for {key}: {allocator}")
    unexpected = set(raw) - allowed
    if unexpected:
        names = ", ".join(sorted(unexpected))
        raise NewFeatureError(f"unsupported options for {key} {allocator} allocator: {names}")

    minimum = _optional_int(raw, "min", env_key=key)
    maximum = _optional_int(raw, "max", env_key=key)
    if minimum is not None and maximum is not None and minimum > maximum:
        raise NewFeatureError(f"env spec {key}.min must not exceed max")
    if allocator == "port":
        for field_name, field_value in (("min", minimum), ("max", maximum)):
            if field_value is not None and not 1 <= field_value <= 65535:
                raise NewFeatureError(f"env spec {key}.{field_name} must be between 1 and 65535")

    max_length = _optional_int(raw, "max_length", env_key=key)
    if max_length is not None and max_length < 9:
        raise NewFeatureError(f"env spec {key}.max_length must be at least 9")
    return EnvSpec(
        allocate=allocator,
        minimum=minimum,
        maximum=maximum,
        prefix=_optional_string(raw, "prefix", env_key=key),
        max_length=max_length,
        base=_optional_string(raw, "base", env_key=key),
    )


def config_fingerprint(config: ProjectConfig) -> str:
    payload = {
        "target_branch": config.target_branch,
        "agent": config.agent,
        "push": config.push,
        "setup": config.setup,
        "pre_merge": config.pre_merge,
        "post_merge": config.post_merge,
        "teardown": config.teardown,
        "env": {key: asdict(value) for key, value in sorted(config.env.items())},
    }
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
    return hashlib.sha256(encoded).hexdigest()


def load_project_config(repo_root: Path) -> ProjectConfig:
    pyproject = repo_root / "pyproject.toml"
    if not pyproject.exists():
        return ProjectConfig()
    try:
        data = tomllib.loads(pyproject.read_text(encoding="utf-8"))
    except tomllib.TOMLDecodeError as exc:
        raise NewFeatureError(f"invalid pyproject.toml: {exc}") from exc
    tool_data = data.get("tool", {})
    if not isinstance(tool_data, dict):
        raise NewFeatureError("[tool] must be a TOML table")
    raw_data = tool_data.get("new-feature", {})
    if not isinstance(raw_data, dict):
        raise NewFeatureError("[tool.new-feature] must be a TOML table")
    raw = cast("RawTable", raw_data)
    unexpected = set(raw) - _CONFIG_KEYS
    if unexpected:
        names = ", ".join(sorted(unexpected))
        raise NewFeatureError(f"unsupported tool.new-feature options: {names}")

    env_data = raw.get("env", {})
    if not isinstance(env_data, dict):
        raise NewFeatureError("[tool.new-feature.env] must be a TOML table")
    env_raw = cast("RawTable", env_data)

    env = {key: _env_spec(key, value) for key, value in env_raw.items()}

    return ProjectConfig(
        target_branch=_string(raw, "target_branch", "main"),
        agent=_agent_command(raw),
        push=_boolean(raw, "push", default=False),
        setup=_string_list(raw, "setup"),
        pre_merge=_string_list(raw, "pre_merge"),
        post_merge=_string_list(raw, "post_merge"),
        teardown=_string_list(raw, "teardown"),
        env=env,
    )
