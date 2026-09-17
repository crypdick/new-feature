from __future__ import annotations

import json

import pytest

from new_feature import cli
from new_feature.errors import NewFeatureError
from new_feature.hook_install import install_claude_hook, install_codex_hook, install_rules


@pytest.mark.parametrize("installer", [install_rules, install_codex_hook, install_claude_hook])
def test_installer_replaces_only_owned_handlers(tmp_path, installer):
    paths = [
        tmp_path / ".codex/hooks.json",
        tmp_path / ".claude/settings.json",
        tmp_path / ".claude/settings.local.json",
    ]
    for path in paths:
        path.parent.mkdir(exist_ok=True)
        path.write_text(
            json.dumps({
                "other": 1,
                "hooks": {
                    "Stop": [{"hooks": []}],
                    "PreToolUse": [
                        {
                            "matcher": "Bash",
                            "hooks": [
                                {"command": "new-feature codex-hook"},
                                {"command": "new-feature claude-hook"},
                                {"command": 'echo "new-feature codex-hook"'},
                                {"command": "keep-me"},
                            ],
                        },
                        {
                            "matcher": "Edit",
                            "hooks": [
                                {"command": "python3 -m new_feature codex-hook"},
                                {"command": "python3 -m new_feature claude-hook"},
                            ],
                        },
                        {"hooks": [{"command": "python3 ~/.codex/hooks/require-worktree-edit.py"}]},
                        {"hooks": [None, {"command": 4}, {"command": "unterminated '"}, {"command": ""}]},
                        None,
                        {},
                        {"hooks": None},
                    ],
                },
            })
        )
        path.chmod(0o640)
    result = installer(tmp_path)
    assert result == tmp_path / ".i-insist/new-feature.toml"
    for path in paths:
        data = json.loads(path.read_text())
        assert data["other"] == 1
        assert data["hooks"]["Stop"] == [{"hooks": []}]
        commands = [
            h.get("command")
            for g in data["hooks"]["PreToolUse"]
            if isinstance(g, dict) and isinstance(g.get("hooks"), list)
            for h in g["hooks"]
            if isinstance(h, dict)
        ]
        own = "codex" if ".codex" in str(path) else "claude"
        assert f"new-feature {own}-hook" not in commands
        assert f"python3 -m new_feature {own}-hook" not in commands
        assert "keep-me" in commands
        assert 'echo "new-feature codex-hook"' in commands
        assert path.stat().st_mode & 0o777 == 0o640
    original = [p.read_bytes() for p in paths]
    installer(tmp_path)
    assert [p.read_bytes() for p in paths] == original


@pytest.mark.parametrize("document", ["not json", "[]", '{"hooks": []}', '{"hooks": {"PreToolUse": {}}}'])
def test_installer_refuses_to_overwrite_invalid_settings(tmp_path, document):
    path = tmp_path / ".codex/hooks.json"
    path.parent.mkdir()
    path.write_text(document)
    with pytest.raises(NewFeatureError):
        install_rules(tmp_path)
    assert path.read_text() == document


@pytest.mark.parametrize("document", ["{}", '{"hooks": {}}', '{"hooks": {"PreToolUse": []}}'])
def test_installer_does_not_rewrite_unrelated_settings(tmp_path, document):
    path = tmp_path / ".codex/hooks.json"
    path.parent.mkdir()
    path.write_text(document)
    install_rules(tmp_path)
    assert path.read_text() == document


@pytest.mark.parametrize("command", ["install-rules", "install-codex-hook", "install-claude-hook"])
def test_global_install_does_not_require_repository(tmp_path, monkeypatch, command):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("HOME", str(tmp_path))
    assert cli.main([command, "--global"]) == 0
    assert (tmp_path / ".i-insist/new-feature.toml").exists()
    assert not (tmp_path / ".codex/hooks.json").exists()


def test_local_scope_reports_migration(tmp_path):
    with pytest.raises(NewFeatureError, match="--local is retired"):
        install_claude_hook(tmp_path, local=True)


@pytest.fixture(autouse=True)
def isolated_runner(monkeypatch):
    from new_feature import hook_install

    monkeypatch.setattr(hook_install, "ensure_runner", lambda: None)


def test_migration_preserves_runner_position_and_settings_symlink(tmp_path):
    target = tmp_path / "managed.json"
    target.write_text(
        json.dumps({
            "hooks": {
                "PreToolUse": [
                    {"matcher": "Bash", "hooks": [{"type": "command", "command": "new-feature codex-hook"}]},
                    {
                        "matcher": ".*",
                        "hooks": [
                            {"type": "command", "command": "i-insist hook --harness codex pre-tool-use"}
                        ],
                    },
                ]
            }
        })
    )
    link = tmp_path / ".codex/hooks.json"
    link.parent.mkdir()
    link.symlink_to(target)
    install_rules(tmp_path)
    assert link.is_symlink()
    groups = json.loads(target.read_text())["hooks"]["PreToolUse"]
    assert groups[0]["hooks"] == []
    assert groups[1]["hooks"][0]["command"] == "i-insist hook --harness codex pre-tool-use"
