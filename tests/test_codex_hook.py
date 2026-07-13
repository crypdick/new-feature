from __future__ import annotations

import io
import json
import subprocess
from pathlib import Path

import pytest

from new_feature import cli
from new_feature import atomic_file as atomic_file_module
from new_feature import codex_hook as codex_hook_module
from new_feature.codex_hook import run_codex_hook
from new_feature.codex_install import install_codex_hook
from new_feature.errors import NewFeatureError


def _payload(path: Path, *, tool_name: str = "apply_patch") -> io.StringIO:
    return io.StringIO(
        json.dumps({
            "tool_name": tool_name,
            "tool_input": {"command": f"*** Begin Patch\n*** Update File: {path}\n*** End Patch"},
        })
    )


def _run(path: Path, *, cwd: Path, tool_name: str = "apply_patch") -> dict[str, object] | None:
    output = io.StringIO()
    assert run_codex_hook(_payload(path, tool_name=tool_name), output, cwd=cwd) == 0
    return json.loads(output.getvalue()) if output.getvalue() else None


def _run_bash(command: object, *, cwd: Path, field: str = "command") -> dict[str, object] | None:
    output = io.StringIO()
    payload = io.StringIO(json.dumps({"tool_name": "Bash", "tool_input": {field: command}}))
    assert run_codex_hook(payload, output, cwd=cwd) == 0
    return json.loads(output.getvalue()) if output.getvalue() else None


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
    assert run_codex_hook(payload, output, cwd=tmp_path) == 0
    assert "target branch 'develop'" in output.getvalue()


def test_hook_supports_legacy_edit_payload_and_ignores_unrelated_input(tmp_path: Path) -> None:
    from tests.conftest import init_git_repo

    init_git_repo(tmp_path)
    output = io.StringIO()
    edit = io.StringIO(
        json.dumps({"tool_name": "Edit", "tool_input": {"file_path": str(tmp_path / "README.md")}})
    )
    assert run_codex_hook(edit, output, cwd=tmp_path) == 0
    assert "permissionDecision" in output.getvalue()

    for raw in ("not json", "[]", json.dumps({"tool_name": "mcp__filesystem__read_file"})):
        output = io.StringIO()
        assert run_codex_hook(io.StringIO(raw), output, cwd=tmp_path) == 0
        assert output.getvalue() == ""

    malformed_edit = io.StringIO(json.dumps({"tool_name": "Write", "tool_input": []}))
    assert run_codex_hook(malformed_edit, io.StringIO(), cwd=tmp_path) == 0


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
    assert run_codex_hook(payload, output, cwd=tmp_path) == 0
    assert output.getvalue() == ""


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
    assert run_codex_hook(nested_input, output, cwd=tmp_path) == 0
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
        codex_hook_module.subprocess,
        "run",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(OSError("missing git")),
    )
    assert _run(tmp_path / "file.py", cwd=tmp_path) is None


def test_installer_creates_hook_file_and_is_idempotent(tmp_path: Path) -> None:
    hooks_path = install_codex_hook(tmp_path)
    install_codex_hook(tmp_path)

    document = json.loads(hooks_path.read_text(encoding="utf-8"))
    groups = document["hooks"]["PreToolUse"]
    assert len(groups) == 1
    assert groups[0]["matcher"] == "Bash|Edit|Write|apply_patch"
    assert groups[0]["hooks"][0]["command"] == "new-feature codex-hook"
    assert hooks_path == tmp_path / ".codex" / "hooks.json"
    assert hooks_path.stat().st_mode & 0o777 == 0o600


def test_installer_preserves_hooks_and_migrates_prototype(tmp_path: Path) -> None:
    hooks_path = tmp_path / ".codex" / "hooks.json"
    hooks_path.parent.mkdir()
    hooks_path.write_text(
        json.dumps({
            "custom": True,
            "hooks": {
                "PostToolUse": [{"hooks": []}],
                "PreToolUse": [
                    "unknown",
                    {"hooks": {}},
                    {"hooks": [None, {"command": "other-hook"}]},
                    {
                        "matcher": "apply_patch",
                        "hooks": [
                            {
                                "type": "command",
                                "command": "/usr/bin/python3 ~/.codex/hooks/require-worktree-edit.py",
                            }
                        ],
                    },
                ],
            },
        }),
        encoding="utf-8",
    )
    hooks_path.chmod(0o640)

    install_codex_hook(tmp_path)

    document = json.loads(hooks_path.read_text(encoding="utf-8"))
    assert document["custom"] is True
    assert document["hooks"]["PostToolUse"] == [{"hooks": []}]
    groups = document["hooks"]["PreToolUse"]
    assert len(groups) == 4
    assert groups[3]["hooks"][0]["command"] == "new-feature codex-hook"
    assert hooks_path.stat().st_mode & 0o777 == 0o640


def test_installer_preserves_sibling_handlers_when_updating_guard(tmp_path: Path) -> None:
    hooks_path = tmp_path / ".codex" / "hooks.json"
    hooks_path.parent.mkdir()
    hooks_path.write_text(
        json.dumps({
            "hooks": {
                "PreToolUse": [
                    {
                        "matcher": "Bash",
                        "hooks": [
                            {"type": "command", "command": "new-feature codex-hook"},
                            {"type": "command", "command": "keep-me"},
                        ],
                    },
                    {
                        "matcher": "Edit",
                        "hooks": [{"type": "command", "command": "new-feature codex-hook"}],
                    },
                ]
            }
        }),
        encoding="utf-8",
    )

    install_codex_hook(tmp_path)

    groups = json.loads(hooks_path.read_text(encoding="utf-8"))["hooks"]["PreToolUse"]
    commands = [handler["command"] for group in groups for handler in group["hooks"]]
    assert commands.count("new-feature codex-hook") == 1
    assert "keep-me" in commands
    sibling_group = next(group for group in groups if group["hooks"][0]["command"] == "keep-me")
    assert sibling_group["matcher"] == "Bash"


@pytest.mark.parametrize(
    ("document", "message"),
    [
        ("not json", "cannot read Codex hooks file"),
        ("[]", "must contain a JSON object"),
        ('{"hooks": []}', "field 'hooks' must be a JSON object"),
        ('{"hooks": {"PreToolUse": {}}}', "field 'hooks.PreToolUse' must be a JSON array"),
    ],
)
def test_installer_rejects_invalid_hook_documents(tmp_path: Path, document: str, message: str) -> None:
    hooks_path = tmp_path / ".codex" / "hooks.json"
    hooks_path.parent.mkdir()
    hooks_path.write_text(document, encoding="utf-8")

    with pytest.raises(NewFeatureError, match=message):
        install_codex_hook(tmp_path)


def test_install_command_uses_current_repository(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys
) -> None:
    from tests.conftest import init_git_repo

    init_git_repo(tmp_path)
    monkeypatch.chdir(tmp_path)

    assert cli.main(["install-codex-hook"]) == 0
    assert (tmp_path / ".codex" / "hooks.json").exists()
    assert "review and trust" in capsys.readouterr().out


def test_installer_removes_temporary_file_after_write_failure(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(
        atomic_file_module.os,
        "fsync",
        lambda *_args: (_ for _ in ()).throw(OSError("disk failure")),
    )

    with pytest.raises(OSError, match="disk failure"):
        install_codex_hook(tmp_path)
    assert list((tmp_path / ".codex").iterdir()) == []


def test_internal_codex_hook_command_runs_without_repository(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(cli.sys, "stdin", io.StringIO(json.dumps({"tool_name": "Bash"})))
    output = io.StringIO()
    monkeypatch.setattr(cli.sys, "stdout", output)

    assert cli.main(["codex-hook"]) == 0
    assert output.getvalue() == ""
