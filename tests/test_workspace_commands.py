from __future__ import annotations

import json

import pytest

from new_feature.cli import main
from new_feature.cli_parser import parse_args
from tests.conftest import init_git_repo


def test_workspace_commands_through_cli(tmp_path, monkeypatch, capsys):
    init_git_repo(tmp_path)
    monkeypatch.chdir(tmp_path)
    assert main(["completion", "bash"]) == 0
    assert "complete -F _new_feature new-feature" in capsys.readouterr().out
    assert main(["demo", "--no-agent"]) == 0
    capsys.readouterr()
    assert main(["path", "demo"]) == 0
    assert capsys.readouterr().out == f"{tmp_path}/.worktrees/demo\n"
    assert main(["completion", "--features"]) == 0
    assert capsys.readouterr().out == "demo\n"
    assert main(["changes", "demo", "--json"]) == 0
    report = json.loads(capsys.readouterr().out)
    assert report["changes"]["state"] == "clean"
    assert len(report["generation"]) == 32


@pytest.mark.parametrize(
    "arguments",
    [
        ["completion"],
        ["completion", "bash", "--features"],
        ["create", "demo", "--from", "main", "--agent", "codex"],
        ["create", "demo", "--from", "main", "--bootstrap"],
        ["create", "demo", "--from", "main", "--prompt", "review"],
        ["create", "demo", "--bootstrap", "--dry-run"],
        ["prune"],
        ["prune", "--merged", "--force"],
    ],
)
def test_workspace_argument_conflicts(arguments):
    with pytest.raises(SystemExit) as error:
        parse_args(arguments)
    assert error.value.code == 2


def test_inert_feature_inspection(tmp_path, monkeypatch, capsys):
    init_git_repo(tmp_path)
    monkeypatch.chdir(tmp_path)
    assert main(["demo", "--from", "main", "--json"]) == 0
    result = json.loads(capsys.readouterr().out)
    assert result["feature"]["status"] == "inert"
    assert result["agent_exit_code"] is None
    assert main(["list", "--json"]) == 0
    assert json.loads(capsys.readouterr().out)["features"][0]["issues"] == ["inert"]


@pytest.mark.parametrize(
    "arguments",
    [
        ["list", "--json"],
        ["doctor", "--json"],
        ["teardown", "demo", "--dry-run"],
        ["prune", "--merged", "--dry-run", "--json"],
    ],
)
def test_inert_inspection_never_executes_clean_filter(tmp_path, monkeypatch, arguments):
    import subprocess

    init_git_repo(tmp_path)
    (tmp_path / ".gitattributes").write_text("README.md filter=review\n")
    subprocess.run(["git", "add", ".gitattributes"], cwd=tmp_path, check=True)
    subprocess.run(["git", "commit", "-m", "attributes"], cwd=tmp_path, check=True)
    marker = tmp_path / "filter-executed"
    subprocess.run(
        ["git", "config", "filter.review.clean", f'touch "{marker}"; cat'], cwd=tmp_path, check=True
    )
    monkeypatch.chdir(tmp_path)
    assert main(["demo", "--from", "main"]) == 0
    worktree = tmp_path / ".worktrees/demo"
    original = (worktree / "README.md").read_text()
    (worktree / "README.md").write_text(original.replace("demo", "test"))
    assert main(arguments) in (0, 1)
    assert not marker.exists()
