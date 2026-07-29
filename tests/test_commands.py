from __future__ import annotations

import re
import subprocess
from typing import TYPE_CHECKING
from unittest.mock import Mock

import pytest

from new_feature import commands as commands_module
from new_feature.commands import run_commands
from new_feature.errors import NewFeatureError

if TYPE_CHECKING:
    from pathlib import Path


def test_run_commands_expands_env(tmp_path: Path):
    run_commands(['printf "$VALUE" > output.txt'], cwd=tmp_path, env={"VALUE": "ok"})
    assert (tmp_path / "output.txt").read_text(encoding="utf-8") == "ok"


def test_run_commands_reports_failed_command(tmp_path: Path):
    with pytest.raises(NewFeatureError, match="command failed"):
        run_commands(["exit 7"], cwd=tmp_path, env={})


def test_run_commands_reports_process_start_failure(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        commands_module.subprocess,
        "Popen",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(OSError("cannot execute")),
    )

    with pytest.raises(NewFeatureError, match="cannot start configured command"):
        run_commands(["missing"], cwd=tmp_path, env={})


def test_run_commands_retains_failed_command_output(tmp_path: Path):
    failure_log = tmp_path / "diagnostics" / "failure.log"

    with pytest.raises(NewFeatureError, match=re.escape(str(failure_log))):
        run_commands(
            ['printf "standard output"; printf "error output" >&2; exit 7'],
            cwd=tmp_path,
            env={},
            failure_log=failure_log,
        )

    assert failure_log.read_text(encoding="utf-8") == "standard outputerror output"


def test_run_commands_kills_the_process_group_when_interrupted(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    class InterruptingOutput:
        def __iter__(self):
            return self

        def __next__(self):
            raise KeyboardInterrupt

    popen_options: dict[str, object] = {}
    killed: list[tuple[int, int]] = []
    process = Mock(spec=subprocess.Popen)
    process.pid = 123
    process.stdout = InterruptingOutput()
    process.wait.return_value = 0

    def popen(*_args, **kwargs):
        popen_options.update(kwargs)
        return process

    monkeypatch.setattr(commands_module.subprocess, "Popen", popen)
    monkeypatch.setattr(
        commands_module.os,
        "killpg",
        lambda process_group, sig: killed.append((process_group, sig)),
    )

    with pytest.raises(KeyboardInterrupt):
        run_commands(["command"], cwd=tmp_path, env={}, failure_log=tmp_path / "failure.log")

    assert popen_options["start_new_session"] is True
    assert killed == [(123, commands_module.signal.SIGKILL)]
