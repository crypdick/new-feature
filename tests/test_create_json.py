from __future__ import annotations

import json
import sys
from typing import TYPE_CHECKING

import pytest

from new_feature.cli import main
from tests.conftest import init_git_repo

if TYPE_CHECKING:
    from pathlib import Path


@pytest.mark.parametrize("explicit", [False, True])
def test_create_json_created_and_reused(tmp_path: Path, monkeypatch, capfd, explicit):
    init_git_repo(
        tmp_path,
        '[tool.new-feature]\nsetup = ["echo bootstrap"]\n[tool.new-feature.env]\nSECRET = {value="private-value"}\n',
    )
    monkeypatch.chdir(tmp_path)
    capfd.readouterr()
    arguments = ["create", "demo"] if explicit else ["demo"]
    for status in ("created", "reused"):
        assert main([*arguments, "--no-agent", "--json"]) == 0
        output = capfd.readouterr()
        result = json.loads(output.out)
        assert result["schema_version"] == 1
        assert result["command"] == "create"
        assert result["ok"] is True
        assert result["status"] == status
        assert result["feature"] == {
            "name": "demo",
            "slug": "demo",
            "branch": "demo",
            "target_branch": "main",
            "worktree": str(tmp_path / ".worktrees/demo"),
            "status": "active",
        }
        assert "private-value" not in output.out
        if status == "created":
            assert "bootstrap" in output.err
            assert "HEAD is now" in output.err
        else:
            assert "bootstrap" not in output.err


@pytest.mark.parametrize(
    "agent",
    [
        "missing-executable-create-json",
        f"{sys.executable} -c \"import sys; print('agent output'); sys.exit(7)\"",
    ],
)
def test_create_json_preserves_identity_after_agent_failure(tmp_path: Path, monkeypatch, capfd, agent):
    init_git_repo(tmp_path)
    monkeypatch.chdir(tmp_path)
    capfd.readouterr()
    assert main(["demo", "--agent", agent, "--json"]) != 0
    output = capfd.readouterr()
    result = json.loads(output.out)
    assert result["ok"] is False
    assert result["status"] == "created"
    assert result["feature"]["worktree"] == str(tmp_path / ".worktrees/demo")
    assert result["agent_error"]["code"] == "agent-failed"
    assert (tmp_path / ".worktrees/demo/.git").exists()


def test_create_json_successful_agent_output_stays_on_stderr(tmp_path: Path, monkeypatch, capfd):
    init_git_repo(tmp_path)
    monkeypatch.chdir(tmp_path)
    capfd.readouterr()
    agent = f"{sys.executable} -c \"print('agent output')\""
    assert main(["demo", "--agent", agent, "--json"]) == 0
    output = capfd.readouterr()
    result = json.loads(output.out)
    assert result["agent_exit_code"] == 0
    assert result["agent_error"] is None
    assert "agent output" in output.err


def test_create_json_setup_failure_is_single_error(tmp_path: Path, monkeypatch, capfd):
    init_git_repo(tmp_path, '[tool.new-feature]\nsetup = ["echo failed-setup; exit 3"]\n')
    monkeypatch.chdir(tmp_path)
    capfd.readouterr()
    assert main(["demo", "--no-agent", "--json"]) == 1
    output = capfd.readouterr()
    assert json.loads(output.out)["error"]["code"] == "command-failed"
    assert "failed-setup" in output.err
    assert not (tmp_path / ".worktrees/demo").exists()


@pytest.mark.parametrize(
    "arguments", [["create", "--json"], ["demo", "--json", "--unknown"], ["demo", "--json", "--dry-run"]]
)
def test_create_json_invalid_arguments(arguments, capsys):
    assert main(arguments) == 2
    assert json.loads(capsys.readouterr().out)["error"]["code"] == "invalid-arguments"


def test_human_create_reports_agent_launch_failure(tmp_path: Path, monkeypatch, capfd):
    init_git_repo(tmp_path)
    monkeypatch.chdir(tmp_path)
    capfd.readouterr()
    assert main(["demo", "--agent", "missing-executable-create-json"]) == 1
    output = capfd.readouterr()
    assert "agent command failed" in output.err
    assert (tmp_path / ".worktrees/demo/.git").exists()
