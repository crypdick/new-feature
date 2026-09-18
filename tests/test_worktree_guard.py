from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from new_feature import hook_policy
from new_feature.rule_checker import should_block
from tests.conftest import init_git_repo


def blocked(path: Path, *, cwd: Path) -> bool:
    return should_block(
        "target-branch",
        {
            "kind": "file_edit",
            "cwd": str(cwd),
            "paths": [str(path)],
        },
    )


@pytest.mark.parametrize("kind", ["file_write", "file_edit"])
def test_blocks_target_edits_and_allows_feature_branch(tmp_path: Path, kind: str) -> None:
    init_git_repo(tmp_path)
    event = {"kind": kind, "cwd": str(tmp_path), "paths": ["README.md"]}
    assert should_block("target-branch", event)
    subprocess.run(["git", "switch", "-c", "feature/demo"], cwd=tmp_path, check=True)
    assert not should_block("target-branch", event)
    subprocess.run(["git", "checkout", "--detach"], cwd=tmp_path, check=True)
    assert not should_block("target-branch", event)


def test_uses_configured_target_branch_and_new_file_parent(tmp_path: Path) -> None:
    init_git_repo(
        tmp_path,
        '[project]\nname = "demo"\n\n[tool.new-feature]\ntarget_branch = "develop"\n',
    )
    subprocess.run(["git", "switch", "-c", "develop"], cwd=tmp_path, check=True)
    assert blocked(Path("nested/new.py"), cwd=tmp_path)


def test_allows_non_repository_and_invalid_project_config(tmp_path: Path) -> None:
    assert not blocked(tmp_path / "missing.py", cwd=tmp_path)
    init_git_repo(tmp_path, "not valid toml")
    assert not blocked(tmp_path / "pyproject.toml", cwd=tmp_path)


def test_git_probe_failure_does_not_crash_edit_guard(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    def unavailable(*args, **kwargs):
        raise OSError("git unavailable")

    monkeypatch.setattr(hook_policy.subprocess, "run", unavailable)
    assert not blocked(tmp_path / "file.py", cwd=tmp_path)


@pytest.mark.parametrize(
    ("command", "action"),
    [
        ("git worktree add .worktrees/demo -b feature/demo", "add"),
        ("/usr/bin/git worktree remove --force .worktrees/demo", "remove"),
        (
            "echo ready && git -C /repo -c advice.detachedHead=false worktree add /tmp/demo",
            "add",
        ),
        ("git --no-pager worktree remove /tmp/demo", "remove"),
        ("FEATURE=x git worktree add /tmp/demo", "add"),
        ("env FEATURE=x git worktree remove /tmp/demo", "remove"),
        ("/usr/bin/env -i git worktree add /tmp/demo", "add"),
        ("env -- git worktree add /tmp/demo", "add"),
        ("env -u FEATURE git worktree remove /tmp/demo", "remove"),
        ("env --unset=FEATURE git worktree add /tmp/demo", "add"),
        ("command git worktree remove /tmp/demo", "remove"),
        ("exec git worktree add /tmp/demo", "add"),
        ("sudo -n git worktree remove /tmp/demo", "remove"),
    ],
)
def test_blocks_direct_worktree_add_and_remove(tmp_path: Path, command: str, action: str) -> None:
    assert should_block(
        f"worktree-{action}",
        {
            "kind": "shell",
            "cwd": str(tmp_path),
            "command": command,
        },
    )


@pytest.mark.parametrize(
    "command",
    [
        "git worktree list",
        "git worktree prune",
        "git worktree repair",
        "git worktree move old new",
        "git help worktree add",
        "new-feature demo --no-agent",
        "new-feature teardown demo",
        "echo 'git worktree add /tmp/demo'",
        "echo git worktree add /tmp/demo",
        "git worktree 'unterminated",
        "git",
        "git && echo done",
        ";",
        "FEATURE=x",
        "env",
        "env -u",
    ],
)
def test_allows_other_worktree_and_new_feature_commands(tmp_path: Path, command: str) -> None:
    for name in ("worktree-add", "worktree-remove"):
        assert not should_block(name, {"kind": "shell", "cwd": str(tmp_path), "command": command})
