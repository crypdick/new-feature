from __future__ import annotations

import subprocess

import pytest

from new_feature.errors import NewFeatureError
from new_feature.rule_checker import should_block
from tests.conftest import init_git_repo


def blocked(root, command):
    return should_block("target-merge", {"kind": "shell", "cwd": str(root), "command": command})


@pytest.mark.parametrize(
    "command",
    [
        "git merge",
        "git merge feature",
        "git merge --ff-only feature",
        "git merge --no-ff feature",
        "env X=1 command git --no-pager merge feature",
        "echo ready && git merge feature",
        "echo ready\ngit merge feature",
        "echo ready &&\ngit merge feature",
        "echo ready\n\ngit merge feature",
        "git -C '' merge feature",
    ],
)
def test_blocks_starting_target_merge(tmp_path, command):
    init_git_repo(tmp_path)
    assert blocked(tmp_path, command)


@pytest.mark.parametrize(
    "command",
    [
        "git merge --continue",
        "git merge --abort",
        "git merge --quit",
        "git merge --help",
        "git status",
        "git commit",
        "new-feature merge demo",
        "echo 'git merge demo'",
        "git pull --ff-only",
        "git merge '",
    ],
)
def test_allows_recovery_and_other_commands(tmp_path, command):
    init_git_repo(tmp_path)
    assert not blocked(tmp_path, command)


def test_allows_feature_merges_and_uses_configured_target(tmp_path):
    init_git_repo(tmp_path)
    subprocess.run(["git", "switch", "-c", "develop"], cwd=tmp_path, check=True)
    assert not blocked(tmp_path, "git merge main")
    (tmp_path / ".new-feature.toml").write_text('target_branch = "develop"\n')
    assert blocked(tmp_path, "git merge feature")


def test_directory_overrides_select_actual_checkout(tmp_path):
    target = tmp_path / "target"
    feature = tmp_path / "feature"
    target.mkdir()
    feature.mkdir()
    init_git_repo(target)
    init_git_repo(feature)
    subprocess.run(["git", "switch", "-c", "feature"], cwd=feature, check=True)
    assert blocked(feature, f"git -C {target} merge feature")
    assert not blocked(target, f"git -C {feature} merge main")
    assert blocked(feature, f"git -C {target} -C . merge feature")
    assert blocked(feature, f"cd {target} && git merge feature")
    assert not blocked(target, f"cd -- {feature} && git merge main")
    assert blocked(feature, f"git --git-dir={target / '.git'} --work-tree={target} merge feature")


def test_recovery_does_not_exempt_later_merge(tmp_path):
    init_git_repo(tmp_path)
    assert blocked(tmp_path, "git merge --abort && git merge feature")


def test_allows_non_repository_and_non_shell_event(tmp_path):
    assert not blocked(tmp_path, "git merge feature")
    assert not should_block("target-merge", {"kind": "other", "cwd": str(tmp_path)})


def test_bad_project_config_reports_failure(tmp_path):
    init_git_repo(tmp_path)
    (tmp_path / ".new-feature.toml").write_text("invalid toml")
    with pytest.raises(NewFeatureError, match="invalid"):
        blocked(tmp_path, "git merge feature")


def test_git_probe_failure_propagates(tmp_path, monkeypatch):
    from new_feature import hook_policy

    def unavailable(*args, **kwargs):
        raise OSError("git unavailable")

    monkeypatch.setattr(hook_policy.subprocess, "run", unavailable)
    with pytest.raises(OSError, match="git unavailable"):
        blocked(tmp_path, "git merge feature")
