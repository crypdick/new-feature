"""Run project-configured shell commands."""

from __future__ import annotations

import logging
import os
import signal
import subprocess
import sys
from contextlib import suppress
from pathlib import Path
from typing import TextIO

from new_feature.errors import NewFeatureError

logger = logging.getLogger(__name__)


def run_commands(
    commands: list[str], *, cwd: Path, env: dict[str, str], failure_log: Path | None = None
) -> None:
    """Run commands sequentially and raise when any command fails."""
    process_env = {**os.environ, **env}
    if failure_log is None:
        for command in commands:
            returncode = _run_command(command, cwd=cwd, env=process_env)
            if returncode != 0:
                raise NewFeatureError(f"command failed with exit code {returncode}: {command}")
        return

    failure_log.parent.mkdir(parents=True, exist_ok=True)
    with failure_log.open("w", encoding="utf-8") as log:
        for command in commands:
            returncode = _run_command(command, cwd=cwd, env=process_env, log=log)
            if returncode != 0:
                raise NewFeatureError(
                    f"command failed with exit code {returncode}: {command}; failure log: {failure_log}"
                )
    failure_log.unlink()


def _run_command(command: str, *, cwd: Path, env: dict[str, str], log: TextIO | None = None) -> int:
    """Run one command in an owned process group."""
    logger.info("running configured command", extra={"command": command})
    try:
        process = subprocess.Popen(
            command,
            shell=True,
            cwd=cwd,
            env=env,
            stdout=subprocess.PIPE if log is not None else None,
            stderr=subprocess.STDOUT if log is not None else None,
            text=True,
            start_new_session=True,
        )
    except OSError as exc:
        raise NewFeatureError(f"cannot start configured command: {command}: {exc}") from exc
    try:
        if log is not None:
            for line in process.stdout or ():
                sys.stdout.write(line)
                sys.stdout.flush()
                log.write(line)
        returncode = process.wait()
    except BaseException:
        _terminate_process_group(process)
        raise
    if returncode != 0:
        _terminate_process_group(process)
    return returncode


def _terminate_process_group(process: subprocess.Popen[str]) -> None:
    """Stop the shell and any descendants left by a failed or interrupted command."""
    with suppress(ProcessLookupError):
        os.killpg(process.pid, signal.SIGKILL)
    process.wait()
