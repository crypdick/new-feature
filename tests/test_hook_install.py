from __future__ import annotations

import json
from pathlib import Path

import pytest

from new_feature import atomic_file as atomic_file_module
from new_feature import cli
from new_feature.errors import NewFeatureError
from new_feature.hook_install import install_claude_hook, install_codex_hook


def test_codex_installer_creates_hook_file_and_is_idempotent(tmp_path: Path) -> None:
    hooks_path = install_codex_hook(tmp_path)
    install_codex_hook(tmp_path)

    document = json.loads(hooks_path.read_text(encoding="utf-8"))
    groups = document["hooks"]["PreToolUse"]
    assert len(groups) == 1
    assert groups[0]["matcher"] == "Bash|Edit|Write|apply_patch"
    assert groups[0]["hooks"][0]["command"] == "new-feature codex-hook"
    assert hooks_path == tmp_path / ".codex" / "hooks.json"
    assert hooks_path.stat().st_mode & 0o777 == 0o600


def test_claude_installer_creates_settings_file_and_is_idempotent(tmp_path: Path) -> None:
    settings_path = install_claude_hook(tmp_path)
    install_claude_hook(tmp_path)

    document = json.loads(settings_path.read_text(encoding="utf-8"))
    groups = document["hooks"]["PreToolUse"]
    assert len(groups) == 1
    assert groups[0]["matcher"] == "Bash|Edit|Write|MultiEdit|NotebookEdit"
    assert groups[0]["hooks"][0]["command"] == "new-feature claude-hook"
    assert settings_path == tmp_path / ".claude" / "settings.json"
    assert settings_path.stat().st_mode & 0o777 == 0o600


def test_claude_installer_preserves_unrelated_settings_and_hooks(tmp_path: Path) -> None:
    settings_path = tmp_path / ".claude" / "settings.json"
    settings_path.parent.mkdir()
    settings_path.write_text(
        json.dumps({
            "permissions": {"allow": ["Bash(uv run pytest)"]},
            "hooks": {
                "PostToolUse": [{"hooks": []}],
                "PreToolUse": [
                    {
                        "matcher": "Bash",
                        "hooks": [
                            {"type": "command", "command": "new-feature claude-hook"},
                            {"type": "command", "command": "keep-me"},
                        ],
                    },
                ],
            },
        }),
        encoding="utf-8",
    )

    install_claude_hook(tmp_path)

    document = json.loads(settings_path.read_text(encoding="utf-8"))
    assert document["permissions"] == {"allow": ["Bash(uv run pytest)"]}
    assert document["hooks"]["PostToolUse"] == [{"hooks": []}]
    groups = document["hooks"]["PreToolUse"]
    commands = [handler["command"] for group in groups for handler in group["hooks"]]
    assert commands.count("new-feature claude-hook") == 1
    assert "keep-me" in commands


def test_codex_installer_preserves_hooks_and_migrates_prototype(tmp_path: Path) -> None:
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


def test_codex_installer_preserves_sibling_handlers_when_updating_guard(tmp_path: Path) -> None:
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


def test_installers_do_not_replace_each_other(tmp_path: Path) -> None:
    codex_path = install_codex_hook(tmp_path)
    claude_path = install_claude_hook(tmp_path)
    install_codex_hook(tmp_path)
    install_claude_hook(tmp_path)

    codex_groups = json.loads(codex_path.read_text(encoding="utf-8"))["hooks"]["PreToolUse"]
    claude_groups = json.loads(claude_path.read_text(encoding="utf-8"))["hooks"]["PreToolUse"]
    assert len(codex_groups) == 1
    assert len(claude_groups) == 1


@pytest.mark.parametrize("installer", [install_codex_hook, install_claude_hook])
@pytest.mark.parametrize(
    ("document", "message"),
    [
        ("not json", "cannot read hooks file"),
        ("[]", "must contain a JSON object"),
        ('{"hooks": []}', "field 'hooks' must be a JSON object"),
        ('{"hooks": {"PreToolUse": {}}}', "field 'hooks.PreToolUse' must be a JSON array"),
    ],
)
def test_installers_reject_invalid_hook_documents(
    tmp_path: Path, installer, document: str, message: str
) -> None:
    paths = {
        install_codex_hook: tmp_path / ".codex" / "hooks.json",
        install_claude_hook: tmp_path / ".claude" / "settings.json",
    }
    hooks_path = paths[installer]
    hooks_path.parent.mkdir()
    hooks_path.write_text(document, encoding="utf-8")

    with pytest.raises(NewFeatureError, match=message):
        installer(tmp_path)


def test_install_codex_hook_command_uses_current_repository(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys
) -> None:
    from tests.conftest import init_git_repo

    init_git_repo(tmp_path)
    monkeypatch.chdir(tmp_path)

    assert cli.main(["install-codex-hook"]) == 0
    assert (tmp_path / ".codex" / "hooks.json").exists()
    assert "review and trust" in capsys.readouterr().out


def test_install_claude_hook_command_uses_current_repository(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys
) -> None:
    from tests.conftest import init_git_repo

    init_git_repo(tmp_path)
    monkeypatch.chdir(tmp_path)

    assert cli.main(["install-claude-hook"]) == 0
    assert (tmp_path / ".claude" / "settings.json").exists()
    assert "Claude Code" in capsys.readouterr().out


def test_claude_installer_supports_personal_project_scope(tmp_path: Path) -> None:
    settings_path = install_claude_hook(tmp_path, local=True)
    install_claude_hook(tmp_path, local=True)

    assert settings_path == tmp_path / ".claude" / "settings.local.json"
    document = json.loads(settings_path.read_text(encoding="utf-8"))
    groups = document["hooks"]["PreToolUse"]
    assert len(groups) == 1
    assert groups[0]["hooks"][0]["command"] == "new-feature claude-hook"


def test_install_claude_hook_command_local_scope_writes_settings_local(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys
) -> None:
    from tests.conftest import init_git_repo

    init_git_repo(tmp_path)
    monkeypatch.chdir(tmp_path)

    assert cli.main(["install-claude-hook", "--local"]) == 0
    assert (tmp_path / ".claude" / "settings.local.json").exists()
    assert not (tmp_path / ".claude" / "settings.json").exists()
    assert "settings.local.json" in capsys.readouterr().out


@pytest.mark.parametrize(
    ("command", "settings_path"),
    [
        ("install-codex-hook", Path(".codex") / "hooks.json"),
        ("install-claude-hook", Path(".claude") / "settings.json"),
    ],
)
def test_install_hook_commands_global_scope_writes_user_settings_without_a_repository(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys, command: str, settings_path: Path
) -> None:
    home = tmp_path / "home"
    home.mkdir()
    outside_any_repo = tmp_path / "elsewhere"
    outside_any_repo.mkdir()
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.chdir(outside_any_repo)

    assert cli.main([command, "--global"]) == 0

    document = json.loads((home / settings_path).read_text(encoding="utf-8"))
    groups = document["hooks"]["PreToolUse"]
    assert len(groups) == 1
    assert "every repository" in capsys.readouterr().out


def test_install_claude_hook_command_rejects_global_with_local(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.chdir(tmp_path)

    with pytest.raises(SystemExit):
        cli.main(["install-claude-hook", "--global", "--local"])


def test_install_codex_hook_command_rejects_local_scope(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.chdir(tmp_path)

    with pytest.raises(SystemExit):
        cli.main(["install-codex-hook", "--local"])


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
