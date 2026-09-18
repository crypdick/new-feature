from __future__ import annotations

import tomllib

import pytest

from new_feature import cli
from new_feature.hook_install import install_rules


def test_upgrade_replaces_owned_registration(tmp_path):
    path = tmp_path / ".i-insist/new-feature.toml"
    path.parent.mkdir()
    original = '# Keep this comment\n[[rules]]\nid = "target-branch"\nenabled = false\nmessage = "Custom"\n'
    path.write_text(original)
    path.chmod(0o640)
    install_rules(tmp_path)
    assert "Custom" not in path.read_text()
    assert "enabled" not in path.read_text()
    rules = tomllib.loads(path.read_text())["rules"]
    assert {rule["id"] for rule in rules} == {
        "target-branch",
        "target-merge",
        "worktree-add",
        "worktree-remove",
    }
    assert all(set(rule) == {"id", "checker"} for rule in rules)
    assert path.stat().st_mode & 0o777 == 0o640
    upgraded = path.read_bytes()
    install_rules(tmp_path)
    assert path.read_bytes() == upgraded


@pytest.mark.parametrize("original", ["invalid toml", "rules = 3", '[[rules]]\nmessage = "no id"'])
def test_upgrade_replaces_invalid_owned_registration(tmp_path, original):
    path = tmp_path / ".i-insist/new-feature.toml"
    path.parent.mkdir()
    path.write_text(original)
    other = path.with_name("other.toml")
    other.write_text("# other provider")
    install_rules(tmp_path)
    assert len(tomllib.loads(path.read_text())["rules"]) == 4
    assert other.read_text() == "# other provider"


def test_global_install_does_not_require_repository(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("HOME", str(tmp_path))
    assert cli.main(["install-rules", "--global"]) == 0
    assert (tmp_path / ".i-insist/new-feature.toml").exists()
    assert not (tmp_path / ".codex/hooks.json").exists()


@pytest.fixture(autouse=True)
def isolated_runner(monkeypatch):
    from new_feature import hook_install

    monkeypatch.setattr(hook_install, "ensure_runner", lambda: None)


def test_install_rules_does_not_interpret_native_hook_settings(tmp_path):
    path = tmp_path / ".codex/hooks.json"
    path.parent.mkdir()
    path.write_text("not provider-owned JSON")
    install_rules(tmp_path)
    assert path.read_text() == "not provider-owned JSON"
    assert (tmp_path / ".i-insist/new-feature.toml").exists()
