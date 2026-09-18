from __future__ import annotations

import subprocess
from typing import TYPE_CHECKING

import pytest

from new_feature.agent import launch_interactive_agent
from new_feature.commands import run_commands
from new_feature.errors import NewFeatureError
from new_feature.git import ensure_repo_has_commits, local_exclude_path
from new_feature.rule_checker import should_block
from tests.conftest import init_git_repo

if TYPE_CHECKING:
    from pathlib import Path


@pytest.mark.parametrize("variable", ["GIT_DIR", "GIT_COMMON_DIR"])
@pytest.mark.parametrize("operation", ["exclude", "commits", "policy", "command", "agent"])
def test_operations_use_the_requested_repository(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, variable: str, operation: str
) -> None:
    caller = tmp_path / "caller"
    target = tmp_path / "target"
    caller.mkdir()
    target.mkdir()
    init_git_repo(caller)
    subprocess.run(["git", "checkout", "-b", "feature"], cwd=caller, check=True)
    if operation == "commits":
        subprocess.run(["git", "init", "-b", "main"], cwd=target, check=True)
    else:
        init_git_repo(target)
    caller_config = (caller / ".git/config").read_bytes()

    with monkeypatch.context() as context:
        context.setenv(variable, str(caller / ".git"))
        if operation == "exclude":
            assert local_exclude_path(target) == target / ".git/info/exclude"
        elif operation == "commits":
            with pytest.raises(NewFeatureError, match="repository has no commits"):
                ensure_repo_has_commits(target)
        elif operation == "policy":
            assert should_block(
                "target-branch",
                {
                    "kind": "file_edit",
                    "cwd": str(target),
                    "paths": [str(target / "README.md")],
                },
            )
        elif operation == "command":
            run_commands(["git config isolation.target yes"], cwd=target, env={})
        else:
            assert launch_interactive_agent(("git", "config", "isolation.target"), target, {}, "yes") == 0

    assert (caller / ".git/config").read_bytes() == caller_config
    if operation in {"command", "agent"}:
        result = subprocess.run(
            ["git", "config", "--get", "isolation.target"],
            cwd=target,
            capture_output=True,
            text=True,
            check=True,
        )
        assert result.stdout == "yes\n"


def test_commands_preserve_explicit_git_settings(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    init_git_repo(tmp_path)
    monkeypatch.setenv("GIT_CONFIG_COUNT", "1")
    monkeypatch.setenv("GIT_CONFIG_KEY_0", "user.name")
    monkeypatch.setenv("GIT_CONFIG_VALUE_0", "Inherited identity")
    monkeypatch.setenv("VALUE", "inherited")

    run_commands(
        ['git config user.name > identity; printf "$VALUE" > allocated'],
        cwd=tmp_path,
        env={"VALUE": "allocated"},
    )

    assert (tmp_path / "identity").read_text(encoding="utf-8") == "Inherited identity\n"
    assert (tmp_path / "allocated").read_text(encoding="utf-8") == "allocated"
