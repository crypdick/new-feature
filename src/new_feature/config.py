from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any
import tomllib

from new_feature.errors import NewFeatureError


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
    branch_prefix: str = "feature/"
    agent: str = "codex"
    push: bool = False
    setup: list[str] = field(default_factory=list)
    pre_merge: list[str] = field(default_factory=list)
    post_merge: list[str] = field(default_factory=list)
    teardown: list[str] = field(default_factory=list)
    env: dict[str, EnvSpec] = field(default_factory=dict)


def _string_list(raw: dict[str, Any], name: str) -> list[str]:
    value = raw.get(name, [])
    if not isinstance(value, list) or not all(isinstance(item, str) for item in value):
        raise NewFeatureError(f"tool.new-feature.{name} must be a list of strings")
    return list(value)


def load_project_config(repo_root: Path) -> ProjectConfig:
    pyproject = repo_root / "pyproject.toml"
    if not pyproject.exists():
        return ProjectConfig()
    data = tomllib.loads(pyproject.read_text(encoding="utf-8"))
    raw = data.get("tool", {}).get("new-feature", {})
    if not isinstance(raw, dict):
        raise NewFeatureError("[tool.new-feature] must be a TOML table")

    env_raw = raw.get("env", {})
    if not isinstance(env_raw, dict):
        raise NewFeatureError("[tool.new-feature.env] must be a TOML table")

    env: dict[str, EnvSpec] = {}
    for key, value in env_raw.items():
        if not isinstance(value, dict):
            raise NewFeatureError(f"env spec {key} must be a TOML inline table")
        env[key] = EnvSpec(
            allocate=value.get("allocate"),
            value=value.get("value"),
            minimum=value.get("min"),
            maximum=value.get("max"),
            prefix=value.get("prefix"),
            max_length=value.get("max_length"),
            base=value.get("base"),
        )

    return ProjectConfig(
        target_branch=str(raw.get("target_branch", "main")),
        branch_prefix=str(raw.get("branch_prefix", "feature/")),
        agent=str(raw.get("agent", "codex")),
        push=bool(raw.get("push", False)),
        setup=_string_list(raw, "setup"),
        pre_merge=_string_list(raw, "pre_merge"),
        post_merge=_string_list(raw, "post_merge"),
        teardown=_string_list(raw, "teardown"),
        env=env,
    )
