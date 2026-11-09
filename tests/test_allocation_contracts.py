from __future__ import annotations

import json

import pytest

from new_feature.allocator import allocate_env, feature_environment
from new_feature.cli import main
from new_feature.config import PortEnvSpec, ProjectConfig, config_fingerprint, config_fingerprint_changed
from new_feature.errors import NewFeatureError
from new_feature.manifest import FeatureRecord, Manifest, load_manifest, save_manifest
from tests.conftest import init_git_repo


def record(*, ports):
    return FeatureRecord(
        name="one",
        slug="one",
        branch="one",
        worktree=".worktrees/one",
        target_branch="main",
        status="active",
        created_at="now",
        env={"OLD_PORT": "42000", "INTEGER": "42001"},
        allocated_ports=ports,
    )


def allocation(root, existing, minimum=42000, maximum=42001):
    return allocate_env(
        config=ProjectConfig(env={"NEW_PORT": PortEnvSpec(minimum, maximum)}),
        manifest=Manifest(features={"one": existing}),
        name="two",
        slug="two",
        branch="two",
        worktree=root / ".worktrees/two",
        repo_root=root,
    )


def test_port_provenance_survives_config_key_removal(tmp_path, monkeypatch):
    monkeypatch.setattr("new_feature.allocator._port_available", lambda _port: True)
    existing = record(ports=["42000"])
    save_manifest(tmp_path, Manifest(features={"one": existing}))
    existing = load_manifest(tmp_path).features["one"]
    assert allocation(tmp_path, existing)["NEW_PORT"] == "42001"


def test_known_non_port_values_do_not_reserve_ports(tmp_path, monkeypatch):
    monkeypatch.setattr("new_feature.allocator._port_available", lambda _port: True)
    assert allocation(tmp_path, record(ports=[]))["NEW_PORT"] == "42000"


def test_legacy_allocations_reserve_values_and_explain_exhaustion(tmp_path, monkeypatch):
    monkeypatch.setattr("new_feature.allocator._port_available", lambda _port: True)
    with pytest.raises(NewFeatureError, match="recreate legacy features"):
        allocation(tmp_path, record(ports=None))


def test_known_reservations_report_plain_exhaustion(tmp_path):
    with pytest.raises(NewFeatureError, match="no available port") as error:
        allocation(tmp_path, record(ports=["42000"]), maximum=42000)
    assert "legacy" not in str(error.value)


def test_child_environment_derives_identity_from_record(tmp_path):
    existing = record(ports=[])
    existing.env.update(NEW_FEATURE_WORKTREE="/wrong", NEW_FEATURE_BRANCH="wrong")
    env = feature_environment(tmp_path, existing)
    assert env["NEW_FEATURE_WORKTREE"] == str(tmp_path / ".worktrees/one")
    assert env["NEW_FEATURE_BRANCH"] == "one"
    assert env["OLD_PORT"] == "42000"
    assert existing.env["NEW_FEATURE_WORKTREE"] == "/wrong"


def test_preferences_do_not_report_resource_drift(tmp_path, monkeypatch, capsys):
    init_git_repo(tmp_path)
    monkeypatch.chdir(tmp_path)
    assert main(["create", "one", "--no-agent"]) == 0
    (tmp_path / ".new-feature.local.toml").write_text('default_agent="codex"\npush=true\n')
    capsys.readouterr()
    assert main(["doctor", "--json"]) == 0
    feature = json.loads(capsys.readouterr().out)["features"][0]
    assert feature["config_drift"] is False
    assert feature["issues"] == []


def test_resource_fingerprint_scope_and_legacy_compatibility():
    baseline = config_fingerprint(ProjectConfig())
    assert config_fingerprint_changed(baseline, config_fingerprint(ProjectConfig(setup=["true"])))
    assert config_fingerprint_changed(baseline, config_fingerprint(ProjectConfig(target_branch="develop")))
    assert not config_fingerprint_changed("legacy-digest", baseline)
    assert not config_fingerprint_changed("", baseline)


def test_created_port_reservation_survives_configuration_rename(tmp_path, monkeypatch):
    init_git_repo(tmp_path)
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr("new_feature.allocator._port_available", lambda _port: True)
    config = tmp_path / ".new-feature.local.toml"
    config.write_text('[env]\nOLD_PORT={allocate="port", min=42000, max=42001}\n')
    assert main(["create", "one", "--no-agent"]) == 0
    first = load_manifest(tmp_path).features["one"]
    assert first.allocated_ports == ["42000"]
    config.write_text('[env]\nNEW_PORT={allocate="port", min=42000, max=42001}\n')
    assert main(["create", "two", "--no-agent"]) == 0
    assert load_manifest(tmp_path).features["two"].env["NEW_PORT"] == "42001"
    assert main(["create", "one", "--no-agent"]) == 0
    assert load_manifest(tmp_path).features["one"].env == first.env
