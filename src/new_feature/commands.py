from __future__ import annotations

from pathlib import Path
import os
import subprocess

from new_feature.errors import NewFeatureError


def run_commands(commands: list[str], *, cwd: Path, env: dict[str, str]) -> None:
    process_env = {**os.environ, **env}
    for command in commands:
        print(f"+ {command}")
        result = subprocess.run(command, shell=True, cwd=cwd, env=process_env)
        if result.returncode != 0:
            raise NewFeatureError(f"command failed with exit code {result.returncode}: {command}")
