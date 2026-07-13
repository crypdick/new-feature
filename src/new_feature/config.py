"""Parse and represent repository configuration for the feature lifecycle."""

from __future__ import annotations

import hashlib
import json
import re
import tomllib
from dataclasses import dataclass, field
from pathlib import Path
from typing import assert_never, cast

from new_feature.errors import NewFeatureError

type AgentCommand = tuple[str, ...]
type RawTable = dict[str, object]

_CONFIG_KEYS = {
    "target_branch",
    "default_agent",
    "agents",
    "create_prompt",
    "setup_prompt",
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
_NEW_FEATURE_TOML = ".new-feature.toml"
_PYPROJECT_TOML = "pyproject.toml"


def _default_agents() -> dict[str, AgentCommand]:
    # NOTE: README.md documents the built-in agent names.
    return {"codex": ("codex",), "claude": ("claude",)}


@dataclass(frozen=True)
class LiteralEnvSpec:
    """Configure an environment variable with one fixed value."""

    value: str


@dataclass(frozen=True)
class PortEnvSpec:
    """Configure an environment variable with an allocatable TCP port range."""

    minimum: int = 1024
    maximum: int = 65535


@dataclass(frozen=True)
class IntegerEnvSpec:
    """Configure an environment variable with an allocatable integer range."""

    minimum: int = 0
    maximum: int = 65535


@dataclass(frozen=True)
class NameEnvSpec:
    """Configure an environment variable with a deterministic name allocation."""

    prefix: str
    max_length: int | None = None


@dataclass(frozen=True)
class SlugEnvSpec:
    """Configure an environment variable with a feature-derived slug."""

    prefix: str


@dataclass(frozen=True)
class PathEnvSpec:
    """Configure an environment variable with a feature-specific filesystem path."""

    base: str = ".new-feature"


type EnvSpec = LiteralEnvSpec | PortEnvSpec | IntegerEnvSpec | NameEnvSpec | SlugEnvSpec | PathEnvSpec


@dataclass(frozen=True)
class ProjectConfig:
    """Hold the normalized lifecycle configuration for one repository."""

    target_branch: str = "main"
    default_agent: str = "codex"
    agents: dict[str, AgentCommand] = field(default_factory=_default_agents)
    create_prompt: str | None = None
    setup_prompt: str | None = None
    push: bool = False
    setup: list[str] = field(default_factory=list)
    pre_merge: list[str] = field(default_factory=list)
    post_merge: list[str] = field(default_factory=list)
    teardown: list[str] = field(default_factory=list)
    env: dict[str, EnvSpec] = field(default_factory=dict)

    def __post_init__(self) -> None:
        object.__setattr__(self, "agents", {**_default_agents(), **self.agents})


@dataclass(frozen=True)
class _Parser:
    # Binds a raw table to its config path so field readers produce accurate error prefixes.
    raw: RawTable
    config_path: str

    def string(self, name: str, default: str) -> str:
        value = self.raw.get(name, default)
        if not isinstance(value, str) or not value:
            raise NewFeatureError(f"{self.config_path}.{name} must be a non-empty string")
        return value

    def boolean(self, name: str, *, default: bool) -> bool:
        value = self.raw.get(name, default)
        if not isinstance(value, bool):
            raise NewFeatureError(f"{self.config_path}.{name} must be a boolean")
        return value

    def string_list(self, name: str) -> list[str]:
        value = self.raw.get(name, [])
        if not isinstance(value, list) or not all(isinstance(item, str) and item for item in value):
            raise NewFeatureError(f"{self.config_path}.{name} must be a list of non-empty strings")
        return list(value)

    def optional_prompt(self, name: str) -> str | None:
        value = self.raw.get(name)
        if value is None:
            return None
        if not isinstance(value, str) or not value:
            raise NewFeatureError(f"{self.config_path}.{name} must be a non-empty string")
        return value

    def agents(self) -> dict[str, AgentCommand]:
        # Built-in agents are merged in by ProjectConfig.__post_init__; parse only what is declared.
        value = self.raw.get("agents", {})
        if not isinstance(value, dict):
            raise NewFeatureError(f"{self.config_path}.agents must be a table of agent commands")
        agents: dict[str, AgentCommand] = {}
        for name, command in cast("RawTable", value).items():
            if not name:
                raise NewFeatureError(f"{self.config_path}.agents names must be non-empty strings")
            agents[name] = self._agent_command(command, name)
        return agents

    def _agent_command(self, value: object, name: str) -> AgentCommand:
        # NOTE: README.md documents agent commands as argv prefixes.
        if (
            not isinstance(value, list)
            or not value
            or not all(isinstance(item, str) and item for item in value)
        ):
            raise NewFeatureError(
                f"{self.config_path}.agents.{name} must be a non-empty list of non-empty strings"
            )
        return tuple(value)


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
    return LiteralEnvSpec(value=_required_string_option(raw, "value", env_key=key))


def _allocated_env_spec(key: str, raw: RawTable) -> EnvSpec:
    allocator = _required_string_option(raw, "allocate", env_key=key)
    allowed = _ALLOCATOR_KEYS.get(allocator)
    if allowed is None:
        raise NewFeatureError(f"unsupported allocator for {key}: {allocator}")
    unexpected = set(raw) - allowed
    if unexpected:
        names = ", ".join(sorted(unexpected))
        raise NewFeatureError(f"unsupported options for {key} {allocator} allocator: {names}")
    return _parse_allocator(key, allocator, raw)


def _parse_allocator(key: str, allocator: str, raw: RawTable) -> EnvSpec:
    match allocator:
        case "port":
            minimum, maximum = _bounds(key, raw, default_minimum=1024, default_maximum=65535)
            for field_name, field_value in (("min", minimum), ("max", maximum)):
                if not 1 <= field_value <= 65535:
                    raise NewFeatureError(f"env spec {key}.{field_name} must be between 1 and 65535")
            return PortEnvSpec(minimum=minimum, maximum=maximum)
        case "integer":
            minimum, maximum = _bounds(key, raw, default_minimum=0, default_maximum=65535)
            return IntegerEnvSpec(minimum=minimum, maximum=maximum)
        case "name":
            max_length = _optional_int(raw, "max_length", env_key=key)
            if max_length is not None and max_length < 9:
                raise NewFeatureError(f"env spec {key}.max_length must be at least 9")
            return NameEnvSpec(
                prefix=_optional_string(raw, "prefix", env_key=key) or key.lower(),
                max_length=max_length,
            )
        case "slug":
            return SlugEnvSpec(prefix=_optional_string(raw, "prefix", env_key=key) or key.lower())
        case "path":
            return PathEnvSpec(base=_optional_string(raw, "base", env_key=key) or ".new-feature")
        case _:  # pragma: no cover - allocator was checked against _ALLOCATOR_KEYS above
            raise AssertionError(allocator)


def _bounds(
    key: str,
    raw: RawTable,
    *,
    default_minimum: int,
    default_maximum: int,
) -> tuple[int, int]:
    minimum = _optional_int(raw, "min", env_key=key)
    maximum = _optional_int(raw, "max", env_key=key)
    if minimum is not None and maximum is not None and minimum > maximum:
        raise NewFeatureError(f"env spec {key}.min must not exceed max")
    return (
        default_minimum if minimum is None else minimum,
        default_maximum if maximum is None else maximum,
    )


def config_fingerprint(config: ProjectConfig) -> str:
    """Return a stable digest representing a normalized project configuration."""
    payload = {
        "target_branch": config.target_branch,
        "default_agent": config.default_agent,
        "agents": config.agents,
        "create_prompt": config.create_prompt,
        "setup_prompt": config.setup_prompt,
        "push": config.push,
        "setup": config.setup,
        "pre_merge": config.pre_merge,
        "post_merge": config.post_merge,
        "teardown": config.teardown,
        "env": {key: _env_fingerprint(value) for key, value in sorted(config.env.items())},
    }
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
    return hashlib.sha256(encoded).hexdigest()


def _env_fingerprint(spec: EnvSpec) -> dict[str, object]:
    match spec:
        case LiteralEnvSpec(value=value):
            return {"value": value}
        case PortEnvSpec(minimum=minimum, maximum=maximum):
            return {"allocate": "port", "minimum": minimum, "maximum": maximum}
        case IntegerEnvSpec(minimum=minimum, maximum=maximum):
            return {"allocate": "integer", "minimum": minimum, "maximum": maximum}
        case NameEnvSpec(prefix=prefix, max_length=max_length):
            return {"allocate": "name", "prefix": prefix, "max_length": max_length}
        case SlugEnvSpec(prefix=prefix):
            return {"allocate": "slug", "prefix": prefix}
        case PathEnvSpec(base=base):
            return {"allocate": "path", "base": base}
        case _ as unreachable:  # pragma: no cover - EnvSpec is a closed union
            assert_never(unreachable)


def load_project_config(repo_root: Path) -> ProjectConfig:
    """Load configuration, prioritizing a standalone file over ``pyproject.toml``."""
    # NOTE: README.md documents standalone-file precedence over pyproject.toml.
    new_feature_toml = repo_root / _NEW_FEATURE_TOML
    if new_feature_toml.exists():
        return _parse_project_config(
            _load_toml_document(new_feature_toml),
            config_path=_NEW_FEATURE_TOML,
            env_table="[env]",
        )

    pyproject = repo_root / _PYPROJECT_TOML
    if not pyproject.exists():
        return ProjectConfig()
    data = _load_toml_document(pyproject)
    tool_data = data.get("tool", {})
    if not isinstance(tool_data, dict):
        raise NewFeatureError("[tool] must be a TOML table")
    raw_data = tool_data.get("new-feature", {})
    if not isinstance(raw_data, dict):
        raise NewFeatureError("[tool.new-feature] must be a TOML table")
    return _parse_project_config(
        cast("RawTable", raw_data),
        config_path="tool.new-feature",
        env_table="[tool.new-feature.env]",
    )


def _load_toml_document(path: Path) -> RawTable:
    try:
        return cast("RawTable", tomllib.loads(path.read_text(encoding="utf-8")))
    except tomllib.TOMLDecodeError as exc:
        raise NewFeatureError(f"invalid {path.name}: {exc}") from exc


def _parse_project_config(raw: RawTable, *, config_path: str, env_table: str) -> ProjectConfig:
    unexpected = set(raw) - _CONFIG_KEYS
    if unexpected:
        names = ", ".join(sorted(unexpected))
        raise NewFeatureError(f"unsupported {config_path} options: {names}")

    env_data = raw.get("env", {})
    if not isinstance(env_data, dict):
        raise NewFeatureError(f"{env_table} must be a TOML table")
    env_raw = cast("RawTable", env_data)

    env = {key: _env_spec(key, value) for key, value in env_raw.items()}

    parser = _Parser(raw, config_path)
    return ProjectConfig(
        target_branch=parser.string("target_branch", "main"),
        default_agent=parser.string("default_agent", "codex"),
        agents=parser.agents(),
        create_prompt=parser.optional_prompt("create_prompt"),
        setup_prompt=parser.optional_prompt("setup_prompt"),
        push=parser.boolean("push", default=False),
        setup=parser.string_list("setup"),
        pre_merge=parser.string_list("pre_merge"),
        post_merge=parser.string_list("post_merge"),
        teardown=parser.string_list("teardown"),
        env=env,
    )
