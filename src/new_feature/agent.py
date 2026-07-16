"""Build and launch coding-agent prompts for feature worktrees."""

from __future__ import annotations

import os
import shlex
import subprocess
from dataclasses import dataclass
from pathlib import Path

from new_feature.config import AgentCommand, ProjectConfig
from new_feature.errors import NewFeatureError


@dataclass(frozen=True)
class AgentLaunchOptions:
    """Capture optional command-line agent and prompt selection."""

    agent_override: str | None
    prompt_override: str | None


def agent_required_error(*, prompt_requested: bool) -> NewFeatureError:
    """Explain how to select an agent when a launch was requested without one."""
    if prompt_requested:
        return NewFeatureError(
            "--prompt requires an agent; pass --agent codex or --agent claude, or configure default_agent"
        )
    return NewFeatureError(
        "setup requires an agent; pass --agent codex or --agent claude, or configure default_agent"
    )


def build_initial_prompt(name: str) -> str:
    """Return the implementation prompt for a newly created feature."""
    return (
        f"Interview the user to turn `{name}` into a concise PRD for this repository. "
        "Inspect the local repo context first. If the feature name is descriptive enough "
        "and the repo context makes the likely implementation clear, summarize your "
        "inferred plan briefly and ask whether to get right to work."
    )


def build_setup_prompt() -> str:
    """Return the repository-configuration prompt for a coding agent."""
    return (
        "Set up or improve this repository's integration with the `new-feature` tool. "
        "Start by running `new-feature --help`, then inspect the local repository and any "
        "existing `.new-feature.toml`, `.new-feature.local.toml`, or `[tool.new-feature]` "
        "configuration. Infer the appropriate shared target branch, setup and teardown "
        "commands, pre-merge and post-merge checks, and isolated environment allocations. "
        "Recommend the ignored `.new-feature.local.toml` sidecar for personal preferences "
        "such as default_agent, push, and local agent commands; shared configuration still "
        "supports them when repository policy requires it. Present a concise proposed plan "
        "and interview the user about only the material choices that cannot be inferred safely. "
        "Explicitly ask whether they want to install the optional "
        "repository-local Codex or Claude Code hook. The setup command has already initialized its ignore "
        "rules; do not make further edits or install the hook until the user approves the plan. "
        "After approval, implement and verify the configuration, "
        "improving existing configuration when present, and explain the resulting create, "
        "merge, and teardown workflow. Do not run `new-feature setup` again from this "
        "agent session."
    )


def resolve_prompt(default: str, configured: str | None, override: str | None) -> str:
    """Select an explicit prompt override, configured prompt, or default prompt."""
    # NOTE: README.md documents prompt override precedence.
    if override is not None:
        return override
    if configured is not None:
        return configured
    return default


def resolve_agent(config: ProjectConfig, override: str | None) -> AgentCommand | None:
    """Resolve an optional named or shell-form agent selection into a command."""
    selection = config.default_agent if override is None else override
    if selection is None:
        return None
    configured = config.agents.get(selection)
    if configured is not None:
        return configured
    try:
        command = tuple(shlex.split(selection))
    except ValueError as exc:
        raise NewFeatureError(f"invalid agent command: {exc}") from exc
    if not command:
        raise NewFeatureError("agent command cannot be empty")
    return command


def launch_interactive_agent(agent: AgentCommand, worktree: Path, env: dict[str, str], prompt: str) -> int:
    """Launch an agent in a worktree with its allocated environment and prompt."""
    try:
        return subprocess.call([*agent, prompt], cwd=worktree, env={**os.environ, **env})
    except OSError as exc:
        raise NewFeatureError(f"agent command failed: {exc}") from exc
