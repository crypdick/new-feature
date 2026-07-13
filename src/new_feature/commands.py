"""Run project-configured shell commands."""

from __future__ import annotations

import logging
import os
import subprocess
from pathlib import Path

from new_feature.errors import NewFeatureError

logger = logging.getLogger(__name__)


def run_commands(commands: list[str], *, cwd: Path, env: dict[str, str]) -> None:
    """Run commands sequentially and raise when any command fails."""
    process_env = {**os.environ, **env}
    for command in commands:
        logger.info("running configured command", extra={"command": command})
        result = subprocess.run(command, shell=True, cwd=cwd, env=process_env, check=False)
        if result.returncode != 0:
            raise NewFeatureError(f"command failed with exit code {result.returncode}: {command}")
