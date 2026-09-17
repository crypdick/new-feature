from __future__ import annotations

import io
import json

import pytest

from new_feature import cli
from tests.conftest import init_git_repo


def check(monkeypatch, payload, name="worktree-add"):
    output = io.StringIO()
    monkeypatch.setattr(cli.sys, "stdin", io.StringIO(json.dumps(payload)))
    monkeypatch.setattr(cli.sys, "stdout", output)
    status = cli.main(["check-rule", name])
    return status, output.getvalue()


@pytest.mark.parametrize("harness", ["codex", "claude", "other-agent"])
def test_neutral_checker_ignores_harness_and_tool_name(tmp_path, monkeypatch, harness):
    event = {
        "kind": "shell",
        "command": "git worktree add /tmp/demo",
        "cwd": str(tmp_path),
        "paths": [],
        "harness": harness,
        "tool_name": "arbitrary",
    }
    assert check(monkeypatch, event) == (0, "true\n")
    assert check(monkeypatch, event, "worktree-remove") == (0, "false\n")


def test_neutral_file_checker_uses_event_cwd_and_all_paths(tmp_path, monkeypatch):
    init_git_repo(tmp_path)
    event = {"kind": "file_edit", "cwd": str(tmp_path), "paths": ["README.md"], "command": None}
    assert check(monkeypatch, event, "target-branch") == (0, "true\n")
    assert check(monkeypatch, event, "worktree-add") == (0, "false\n")
    event["kind"] = "other"
    assert check(monkeypatch, event, "target-branch") == (0, "false\n")


@pytest.mark.parametrize(
    "payload",
    [
        [],
        {},
        {"kind": "shell"},
        {"kind": "shell", "cwd": "/somewhere", "command": 3},
        {"kind": "file_edit", "cwd": "/somewhere", "paths": [3]},
    ],
)
def test_malformed_neutral_event_fails(monkeypatch, payload):
    status, output = check(monkeypatch, payload, "target-branch")
    assert status == 2
    assert not output


def test_install_rules_writes_provider_config_and_preserves_edits(tmp_path, monkeypatch):
    import tomllib

    init_git_repo(tmp_path)
    monkeypatch.chdir(tmp_path)
    assert cli.main(["install-rules"]) == 0
    path = tmp_path / ".i-insist/new-feature.toml"
    rules = tomllib.loads(path.read_text())["rules"]
    assert {r["id"] for r in rules} == {"worktree-add", "worktree-remove", "target-branch"}
    assert all(r["checker"][:2] == ["new-feature", "check-rule"] for r in rules)
    path.write_text(path.read_text().replace('id = "target-branch"', 'id = "target-branch"\nenabled = false'))
    original = path.read_bytes()
    assert cli.main(["install-rules"]) == 0
    assert path.read_bytes() == original


def test_unknown_rule_fails(monkeypatch):
    assert check(monkeypatch, {}, "unknown") == (2, "")


@pytest.fixture(autouse=True)
def isolated_runner(monkeypatch):
    from new_feature import hook_install

    monkeypatch.setattr(hook_install, "ensure_runner", lambda: None)
