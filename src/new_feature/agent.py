"""Build and launch coding-agent prompts for feature worktrees."""

from __future__ import annotations

import os
import shlex
import subprocess
from pathlib import Path

from new_feature.config import AgentCommand, ProjectConfig
from new_feature.errors import NewFeatureError


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
        "existing `new-feature.toml` or `[tool.new-feature]` configuration. Infer the "
        "appropriate target branch, agent command, setup and teardown commands, pre-merge "
        "and post-merge checks, and isolated environment allocations. Present a concise "
        "proposed plan and interview the user about only the material choices that cannot "
        "be inferred safely, including default_agent and any named agents. "
        "Explicitly ask whether they want to install the optional "
        "repository-local Codex hook. Do not edit files or install the hook until the user "
        "approves the plan. After approval, implement and verify the configuration, "
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


def resolve_agent(config: ProjectConfig, override: str | None) -> AgentCommand:
    """Resolve a named or shell-form agent selection into an executable command."""
    selection = config.default_agent if override is None else override
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
