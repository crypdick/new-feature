from __future__ import annotations

import json
import subprocess
from typing import TYPE_CHECKING

import pytest

from new_feature.cli import main
from new_feature.cli_parser import command_names, parse_args, wants_json
from new_feature.manifest import load_manifest
from tests.conftest import init_git_repo

if TYPE_CHECKING:
    from pathlib import Path


def test_command_capabilities_drive_json_intent_and_shorthand():
    assert set(command_names(feature_names=True)) == {
        "create",
        "merge",
        "exec",
        "teardown",
        "path",
        "changes",
    }
    assert set(command_names(json_output=True)) == {"create", "list", "status", "doctor", "prune", "changes"}
    for command in command_names():
        assert wants_json([command, "--json"]) == (command in command_names(json_output=True))
    assert wants_json(["new-task", "--json"])
    assert not wants_json(["--bad-option", "--json"])
    assert not wants_json(["codex-hook", "--json"])
    with pytest.raises(SystemExit):
        parse_args(["codex-hook"])


@pytest.mark.parametrize("switch_in_hook", [False, True])
def test_merge_rejects_wrong_feature_branch_before_target_mutation(
    tmp_path: Path, monkeypatch, capsys, switch_in_hook
):
    pre_merge = 'pre_merge=["git switch -c unrelated"]' if switch_in_hook else ""
    init_git_repo(tmp_path, f"[tool.new-feature]\n{pre_merge}\n")
    monkeypatch.chdir(tmp_path)
    assert main(["demo", "--no-agent"]) == 0
    worktree = tmp_path / ".worktrees/demo"
    (worktree / "change").write_text("feature work\n")
    subprocess.run(["git", "add", "change"], cwd=worktree, check=True)
    subprocess.run(["git", "commit", "-m", "Feature work"], cwd=worktree, check=True)
    if not switch_in_hook:
        subprocess.run(["git", "switch", "-c", "unrelated"], cwd=worktree, check=True)
    before = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=tmp_path)
    capsys.readouterr()
    assert main(["merge", "demo"]) == 1
    assert "missing or mismatched" in capsys.readouterr().err
    assert subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=tmp_path) == before
    assert not (tmp_path / "change").exists()
    assert load_manifest(tmp_path).features["demo"].status == "active"


def test_exec_derives_feature_identity_from_record(tmp_path: Path, monkeypatch, capfd):
    from new_feature.manifest import save_manifest

    init_git_repo(tmp_path)
    monkeypatch.chdir(tmp_path)
    assert main(["demo", "--no-agent"]) == 0
    manifest = load_manifest(tmp_path)
    manifest.features["demo"].env.update(NEW_FEATURE_WORKTREE="/wrong", NEW_FEATURE_REPO_ROOT="/wrong")
    save_manifest(tmp_path, manifest)
    capfd.readouterr()
    assert (
        main([
            "exec",
            "demo",
            "sh",
            "-c",
            'printf \'["%s","%s"]\' "$NEW_FEATURE_WORKTREE" "$NEW_FEATURE_REPO_ROOT"',
        ])
        == 0
    )
    assert json.loads(capfd.readouterr().out) == [str(tmp_path / ".worktrees/demo"), str(tmp_path)]
