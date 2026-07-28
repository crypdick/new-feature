"""Run project-configured shell commands."""

from __future__ import annotations

import logging
import os
import subprocess
import sys
from pathlib import Path

from new_feature.errors import NewFeatureError

logger = logging.getLogger(__name__)


def run_commands(
    commands: list[str], *, cwd: Path, env: dict[str, str], failure_log: Path | None = None
) -> None:
    """Run commands sequentially and raise when any command fails."""
    process_env = {**os.environ, **env}
    if failure_log is None:
        for command in commands:
            logger.info("running configured command", extra={"command": command})
            result = subprocess.run(command, shell=True, cwd=cwd, env=process_env, check=False)
            if result.returncode != 0:
                raise NewFeatureError(f"command failed with exit code {result.returncode}: {command}")
        return

    failure_log.parent.mkdir(parents=True, exist_ok=True)
    with failure_log.open("w", encoding="utf-8") as log:
        for command in commands:
            logger.info("running configured command", extra={"command": command})
            process = subprocess.Popen(
                command,
                shell=True,
                cwd=cwd,
                env=process_env,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
            )
            for line in process.stdout or ():
                sys.stdout.write(line)
                sys.stdout.flush()
                log.write(line)
            if process.wait() != 0:
                raise NewFeatureError(
                    f"command failed with exit code {process.returncode}: {command}; "
                    f"failure log: {failure_log}"
                )
    failure_log.unlink()
