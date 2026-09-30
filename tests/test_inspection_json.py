from __future__ import annotations

import json
import shutil
import subprocess
from typing import TYPE_CHECKING

import pytest

from new_feature.cli import main
from tests.conftest import init_git_repo

if TYPE_CHECKING:
    from pathlib import Path


@pytest.mark.parametrize("command", ["list", "status", "doctor"])
def test_json_inspection_exposes_machine_fields(tmp_path: Path, monkeypatch, capsys, command):
    init_git_repo(tmp_path)
    monkeypatch.chdir(tmp_path)
    assert main(["feature", "--no-agent"]) == 0
    capsys.readouterr()
    assert main([command, "--json"]) == 0
    result = json.loads(capsys.readouterr().out)
    assert result["schema_version"] == 1
    assert result["ok"] is True
    feature = result["features"][0]
    assert feature["slug"] == "feature"
    assert feature["worktree"] == str(tmp_path / ".worktrees" / "feature")
    assert feature["status"] == "active"
    assert feature["integration"] == "merged"
    assert feature["clean"] is True
    assert feature["issues"] == []
    assert feature["state"] == "ok"
    assert "env" not in feature


def test_json_doctor_reports_issues_and_post_repair_state(tmp_path: Path, monkeypatch, capfd):
    init_git_repo(tmp_path)
    monkeypatch.chdir(tmp_path)
    assert main(["feature", "--no-agent"]) == 0
    shutil.rmtree(tmp_path / ".worktrees" / "feature")
    capfd.readouterr()
    assert main(["doctor", "--json"]) == 1
    report = json.loads(capfd.readouterr().out)
    assert report["ok"] is False
    assert report["features"][0]["issues"] == ["missing-worktree"]
    assert main(["doctor", "--repair", "--json"]) == 0
    report = json.loads(capfd.readouterr().out)
    assert report["ok"] is True
    assert report["features"] == []
    assert report["repairs"] == [
        {"slug": "feature", "message": "removed missing worktree and merged branch feature"}
    ]
    assert "feature" not in subprocess.check_output(["git", "branch"], cwd=tmp_path, text=True)


@pytest.mark.parametrize("command", ["list", "doctor"])
def test_json_empty_and_expected_error(tmp_path: Path, monkeypatch, capsys, command):
    init_git_repo(tmp_path)
    monkeypatch.chdir(tmp_path)
    assert main([command, "--json"]) == 0
    assert json.loads(capsys.readouterr().out)["features"] == []
    (tmp_path / ".new-feature").mkdir()
    (tmp_path / ".new-feature" / "manifest.toml").write_text("invalid[", encoding="utf-8")
    assert main([command, "--json"]) == 1
    output = capsys.readouterr()
    assert json.loads(output.out)["error"]["code"] == "command-failed"
    assert "invalid feature manifest" in output.err


def test_json_invalid_arguments_preserve_exit_and_error(capsys):
    assert main(["doctor", "--json", "--bad-option"]) == 2
    output = capsys.readouterr()
    assert json.loads(output.out)["error"]["code"] == "invalid-arguments"
    assert "unrecognized arguments" in output.err


def test_json_repair_failure_preserves_single_error_envelope(tmp_path: Path, monkeypatch, capfd):
    from new_feature.manifest import feature_operation_lock, load_manifest

    init_git_repo(tmp_path)
    monkeypatch.chdir(tmp_path)
    assert main(["feature", "--no-agent"]) == 0
    capfd.readouterr()
    with feature_operation_lock(tmp_path, "feature"):
        assert main(["doctor", "--json", "--repair"]) == 1
    output = capfd.readouterr()
    error = json.loads(output.out)["error"]
    assert error["code"] == "command-failed"
    assert "feature operation already in progress" in error["message"]
    assert load_manifest(tmp_path).features


@pytest.mark.parametrize("command", ["list", "doctor"])
def test_json_unreadable_worktree_reports_error_without_mixing_stdout(
    tmp_path: Path, monkeypatch, capfd, command
):
    init_git_repo(tmp_path)
    monkeypatch.chdir(tmp_path)
    assert main(["feature", "--no-agent"]) == 0
    (tmp_path / ".worktrees" / "feature" / ".git").write_text("invalid", encoding="utf-8")
    capfd.readouterr()
    assert main([command, "--json"]) == (1 if command == "doctor" else 0)
    output = capfd.readouterr()
    feature = json.loads(output.out)["features"][0]
    assert feature["issues"] == ["worktree-error"]
    assert feature["clean"] is None
    assert "git command failed" in feature["worktree_error"]
    assert "git command failed" in output.err


def test_json_literal_on_unsupported_command_preserves_argparse_behavior(capsys):
    with pytest.raises(SystemExit) as exc_info:
        main(["create", "feature", "--json"])
    assert exc_info.value.code == 2
    output = capsys.readouterr()
    assert not output.out
    assert "unrecognized arguments: --json" in output.err


def test_json_help_preserves_human_help(capsys):
    with pytest.raises(SystemExit) as exc_info:
        main(["doctor", "--json", "--help"])
    assert exc_info.value.code == 0
    assert "usage: new-feature doctor" in capsys.readouterr().out


def test_json_doctor_sorts_features_by_slug(tmp_path: Path, monkeypatch, capsys):
    init_git_repo(tmp_path)
    monkeypatch.chdir(tmp_path)
    assert main(["a0", "--no-agent"]) == 0
    assert main(["a-1", "--no-agent"]) == 0
    capsys.readouterr()
    assert main(["doctor", "--json"]) == 0
    report = json.loads(capsys.readouterr().out)
    assert [feature["slug"] for feature in report["features"]] == ["a-1", "a0"]
