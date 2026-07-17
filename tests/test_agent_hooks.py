from __future__ import annotations

import io
import json
import subprocess
from typing import TYPE_CHECKING

import pytest

from new_feature import cli
from new_feature import hook_policy as hook_policy_module
from new_feature.agent_hook import run_agent_hook

if TYPE_CHECKING:
    from pathlib import Path


def _payload(path: Path, *, tool_name: str = "apply_patch") -> io.StringIO:
    return io.StringIO(
        json.dumps({
            "tool_name": tool_name,
            "tool_input": {"command": f"*** Begin Patch\n*** Update File: {path}\n*** End Patch"},
        })
    )


def _run(path: Path, *, cwd: Path, tool_name: str = "apply_patch") -> dict[str, object] | None:
    output = io.StringIO()
    assert run_agent_hook(_payload(path, tool_name=tool_name), output, cwd=cwd) == 0
    return json.loads(output.getvalue()) if output.getvalue() else None


def _run_tool(tool_name: str, tool_input: object, *, cwd: Path) -> dict[str, object] | None:
    output = io.StringIO()
    payload = io.StringIO(json.dumps({"tool_name": tool_name, "tool_input": tool_input}))
    assert run_agent_hook(payload, output, cwd=cwd) == 0
    return json.loads(output.getvalue()) if output.getvalue() else None


def _run_bash(command: object, *, cwd: Path, field: str = "command") -> dict[str, object] | None:
    return _run_tool("Bash", {field: command}, cwd=cwd)


def test_hook_denies_apply_patch_on_default_target_branch(tmp_path: Path) -> None:
    from tests.conftest import init_git_repo

    init_git_repo(tmp_path)
    result = _run(tmp_path / "README.md", cwd=tmp_path)

    assert result is not None
    hook_output = result["hookSpecificOutput"]
    assert isinstance(hook_output, dict)
    assert hook_output["permissionDecision"] == "deny"
    reason = hook_output["permissionDecisionReason"]
    assert "target branch 'main'" in reason
    assert "new-feature <feature-name> --no-agent" in reason


def test_hook_allows_edits_from_feature_branch(tmp_path: Path) -> None:
    from tests.conftest import init_git_repo

    init_git_repo(tmp_path)
    subprocess.run(["git", "switch", "-c", "feature/demo"], cwd=tmp_path, check=True)

    assert _run(tmp_path / "README.md", cwd=tmp_path) is None


def test_hook_uses_configured_target_branch_and_new_file_parent(tmp_path: Path) -> None:
    from tests.conftest import init_git_repo

    init_git_repo(
        tmp_path,
        '[project]\nname = "demo"\n\n[tool.new-feature]\ntarget_branch = "develop"\n',
    )
    subprocess.run(["git", "switch", "-c", "develop"], cwd=tmp_path, check=True)

    payload = io.StringIO(
        json.dumps({
            "tool_name": "apply_patch",
            "tool_input": {"command": "*** Begin Patch\n*** Add File: nested/new.py\n*** End Patch"},
        })
    )
    output = io.StringIO()
    assert run_agent_hook(payload, output, cwd=tmp_path) == 0
    assert "target branch 'develop'" in output.getvalue()


def test_hook_supports_legacy_edit_payload_and_ignores_unrelated_input(tmp_path: Path) -> None:
    from tests.conftest import init_git_repo

    init_git_repo(tmp_path)
    output = io.StringIO()
    edit = io.StringIO(
        json.dumps({"tool_name": "Edit", "tool_input": {"file_path": str(tmp_path / "README.md")}})
    )
    assert run_agent_hook(edit, output, cwd=tmp_path) == 0
    assert "permissionDecision" in output.getvalue()

    for raw in ("not json", "[]", json.dumps({"tool_name": "mcp__filesystem__read_file"})):
        output = io.StringIO()
        assert run_agent_hook(io.StringIO(raw), output, cwd=tmp_path) == 0
        assert not output.getvalue()

    malformed_edit = io.StringIO(json.dumps({"tool_name": "Write", "tool_input": []}))
    assert run_agent_hook(malformed_edit, io.StringIO(), cwd=tmp_path) == 0


def test_hook_denies_claude_multi_edit_on_target_branch(tmp_path: Path) -> None:
    from tests.conftest import init_git_repo

    init_git_repo(tmp_path)
    result = _run_tool("MultiEdit", {"file_path": str(tmp_path / "README.md")}, cwd=tmp_path)

    assert result is not None
    hook_output = result["hookSpecificOutput"]
    assert isinstance(hook_output, dict)
    assert hook_output["permissionDecision"] == "deny"


def test_hook_denies_claude_notebook_edit_on_target_branch(tmp_path: Path) -> None:
    from tests.conftest import init_git_repo

    init_git_repo(tmp_path)
    result = _run_tool("NotebookEdit", {"notebook_path": str(tmp_path / "analysis.ipynb")}, cwd=tmp_path)

    assert result is not None
    hook_output = result["hookSpecificOutput"]
    assert isinstance(hook_output, dict)
    assert hook_output["permissionDecision"] == "deny"


def test_hook_allows_claude_edit_tools_from_feature_branch(tmp_path: Path) -> None:
    from tests.conftest import init_git_repo

    init_git_repo(tmp_path)
    subprocess.run(["git", "switch", "-c", "feature/demo"], cwd=tmp_path, check=True)

    assert _run_tool("MultiEdit", {"file_path": str(tmp_path / "README.md")}, cwd=tmp_path) is None
    assert (
        _run_tool("NotebookEdit", {"notebook_path": str(tmp_path / "analysis.ipynb")}, cwd=tmp_path) is None
    )


def test_hook_uses_cwd_when_notebook_path_is_missing(tmp_path: Path) -> None:
    from tests.conftest import init_git_repo

    init_git_repo(tmp_path)
    result = _run_tool("NotebookEdit", {"notebook_path": ""}, cwd=tmp_path)

    assert result is not None
    assert "permissionDecision" in json.dumps(result)


@pytest.mark.parametrize(
    ("command", "action", "replacement"),
    [
        ("git worktree add .worktrees/demo -b feature/demo", "add", "new-feature <feature-name>"),
        ("/usr/bin/git worktree remove --force .worktrees/demo", "remove", "new-feature teardown"),
        (
            "echo ready && git -C /repo -c advice.detachedHead=false worktree add /tmp/demo",
            "add",
            "new-feature <feature-name>",
        ),
        ("git --no-pager worktree remove /tmp/demo", "remove", "new-feature teardown"),
        ("FEATURE=x git worktree add /tmp/demo", "add", "new-feature <feature-name>"),
        ("env FEATURE=x git worktree remove /tmp/demo", "remove", "new-feature teardown"),
        ("/usr/bin/env -i git worktree add /tmp/demo", "add", "new-feature <feature-name>"),
        ("env -- git worktree add /tmp/demo", "add", "new-feature <feature-name>"),
        ("env -u FEATURE git worktree remove /tmp/demo", "remove", "new-feature teardown"),
        ("env --unset=FEATURE git worktree add /tmp/demo", "add", "new-feature <feature-name>"),
        ("command git worktree remove /tmp/demo", "remove", "new-feature teardown"),
        ("exec git worktree add /tmp/demo", "add", "new-feature <feature-name>"),
        ("sudo -n git worktree remove /tmp/demo", "remove", "new-feature teardown"),
    ],
)
def test_hook_denies_direct_worktree_add_and_remove(
    tmp_path: Path, command: str, action: str, replacement: str
) -> None:
    result = _run_bash(command, cwd=tmp_path)

    assert result is not None
    hook_output = result["hookSpecificOutput"]
    assert isinstance(hook_output, dict)
    assert f"git worktree {action}" in hook_output["permissionDecisionReason"]
    assert replacement in hook_output["permissionDecisionReason"]


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
def test_hook_allows_other_worktree_and_new_feature_commands(tmp_path: Path, command: str) -> None:
    assert _run_bash(command, cwd=tmp_path) is None


def test_hook_accepts_cmd_alias_and_ignores_malformed_bash_input(tmp_path: Path) -> None:
    assert _run_bash("git worktree add /tmp/demo", cwd=tmp_path, field="cmd") is not None
    assert _run_bash(None, cwd=tmp_path) is None

    output = io.StringIO()
    payload = io.StringIO(json.dumps({"tool_name": "Bash", "tool_input": []}))
    assert run_agent_hook(payload, output, cwd=tmp_path) == 0
    assert not output.getvalue()


def test_hook_handles_nested_patch_input_empty_targets_and_detached_head(tmp_path: Path) -> None:
    from tests.conftest import init_git_repo

    init_git_repo(tmp_path)
    nested_input = io.StringIO(
        json.dumps({
            "tool_name": "apply_patch",
            "tool_input": [None, {"command": "*** Add File: \n*** Update File: README.md"}],
        })
    )
    output = io.StringIO()
    assert run_agent_hook(nested_input, output, cwd=tmp_path) == 0
    assert "permissionDecision" in output.getvalue()

    subprocess.run(["git", "checkout", "--detach"], cwd=tmp_path, check=True)
    assert _run(tmp_path / "README.md", cwd=tmp_path) is None


def test_hook_fails_open_outside_git_and_for_invalid_project_config(tmp_path: Path) -> None:
    assert _run(tmp_path / "missing.py", cwd=tmp_path) is None

    from tests.conftest import init_git_repo

    init_git_repo(tmp_path, "not valid toml")
    assert _run(tmp_path / "pyproject.toml", cwd=tmp_path) is None


def test_hook_fails_open_when_git_cannot_start(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        hook_policy_module.subprocess,
        "run",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(OSError("missing git")),
    )
    assert _run(tmp_path / "file.py", cwd=tmp_path) is None


@pytest.mark.parametrize("command", ["codex-hook", "claude-hook"])
def test_internal_hook_commands_run_without_repository(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, command: str
) -> None:
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(cli.sys, "stdin", io.StringIO(json.dumps({"tool_name": "Bash"})))
    output = io.StringIO()
    monkeypatch.setattr(cli.sys, "stdout", output)

    assert cli.main([command]) == 0
    assert not output.getvalue()
