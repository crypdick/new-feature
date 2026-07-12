from __future__ import annotations

import os
import subprocess
from pathlib import Path

from new_feature.config import AgentCommand


def build_initial_prompt(name: str) -> str:
    return (
        f"Interview the user to turn `{name}` into a concise PRD for this repository. "
        "Inspect the local repo context first. If the feature name is descriptive enough "
        "and the repo context makes the likely implementation clear, summarize your "
        "inferred plan briefly and ask whether to get right to work."
    )


def launch_interactive_agent(agent: AgentCommand, worktree: Path, env: dict[str, str], prompt: str) -> int:
    return subprocess.call([*agent, prompt], cwd=worktree, env={**os.environ, **env})
