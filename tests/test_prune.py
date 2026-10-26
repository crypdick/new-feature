from __future__ import annotations

import json
import subprocess
from typing import TYPE_CHECKING

from new_feature.cli import main
from new_feature.manifest import feature_operation_lock, load_manifest
from new_feature.prune import prune_features
from tests.conftest import init_git_repo

if TYPE_CHECKING:
    from pathlib import Path


def create_feature(root: Path, monkeypatch, name: str) -> Path:
    monkeypatch.chdir(root)
    assert main([name, "--no-agent"]) == 0
    return root / ".worktrees" / name


def test_prune_removes_integrated_features_and_preserves_unmerged(tmp_path: Path, monkeypatch, capsys):
    init_git_repo(tmp_path)
    integrated = create_feature(tmp_path, monkeypatch, "integrated")
    unmerged = create_feature(tmp_path, monkeypatch, "unmerged")
    (unmerged / "README.md").write_text("unique work\n")
    subprocess.run(["git", "commit", "-am", "unique"], cwd=unmerged, check=True)
    capsys.readouterr()
    assert prune_features(tmp_path, dry_run=False, json_output=True) == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["schema_version"] == 1
    assert payload["command"] == "prune"
    assert payload["ok"] is True
    assert [(entry["slug"], entry["outcome"]) for entry in payload["features"]] == [
        ("integrated", "removed"),
        ("unmerged", "skipped"),
    ]
    assert not integrated.exists()
    assert unmerged.exists()
    assert set(load_manifest(tmp_path).features) == {"unmerged"}


def test_prune_preview_preserves_state_and_reports_refusals(tmp_path: Path, monkeypatch, capsys):
    init_git_repo(tmp_path, '[tool.new-feature]\nteardown=["touch cleaned"]\n')
    ready = create_feature(tmp_path, monkeypatch, "ready")
    dirty = create_feature(tmp_path, monkeypatch, "dirty")
    (dirty / "valuable").write_text("preserve")
    before = {path: path.read_bytes() for path in (tmp_path / ".new-feature").rglob("*") if path.is_file()}
    capsys.readouterr()
    assert prune_features(tmp_path, dry_run=True, json_output=True) == 1
    payload = json.loads(capsys.readouterr().out)
    assert payload["dry_run"] is True
    assert payload["features"][0]["outcome"] == "refused"
    assert "unpreserved" in payload["features"][0]["reasons"][0]
    assert payload["features"][1]["outcome"] == "would-remove"
    assert all(path.read_bytes() == contents for path, contents in before.items())
    assert set(before) == {path for path in (tmp_path / ".new-feature").rglob("*") if path.is_file()}
    assert ready.exists()
    assert dirty.exists()
    assert not (ready / "cleaned").exists()


def test_prune_continues_after_cleanup_failure_without_stdout_noise(tmp_path: Path, monkeypatch, capfd):
    init_git_repo(
        tmp_path, "[tool.new-feature]\nteardown=['echo cleanup-output; test \"$NEW_FEATURE_SLUG\" != fail']\n"
    )
    failed = create_feature(tmp_path, monkeypatch, "fail")
    ready = create_feature(tmp_path, monkeypatch, "ready")
    capfd.readouterr()
    assert prune_features(tmp_path, dry_run=False, json_output=True) == 1
    output = capfd.readouterr()
    payload = json.loads(output.out)
    assert payload["ok"] is False
    assert payload["features"][0]["outcome"] == "refused"
    assert payload["features"][1]["outcome"] == "removed"
    assert "cleanup-output" in output.err
    assert failed.exists()
    assert not ready.exists()


def test_prune_reports_locked_and_missing_worktrees(tmp_path: Path, monkeypatch, capsys):
    init_git_repo(tmp_path)
    create_feature(tmp_path, monkeypatch, "locked")
    missing = create_feature(tmp_path, monkeypatch, "missing")
    subprocess.run(["git", "worktree", "remove", str(missing)], cwd=tmp_path, check=True)
    capsys.readouterr()
    with feature_operation_lock(tmp_path, "locked"):
        assert prune_features(tmp_path, dry_run=False, json_output=True) == 1
    payload = json.loads(capsys.readouterr().out)
    assert all(entry["outcome"] == "refused" for entry in payload["features"])
    assert "already in progress" in payload["features"][0]["reasons"][0]
    assert "missing" in payload["features"][1]["reasons"][0]


def test_prune_human_preview_and_empty_inventory(tmp_path: Path, monkeypatch, capsys):
    init_git_repo(tmp_path)
    monkeypatch.chdir(tmp_path)
    assert prune_features(tmp_path, dry_run=False, json_output=False) == 0
    assert "No managed features" in capsys.readouterr().out
    create_feature(tmp_path, monkeypatch, "feature")
    capsys.readouterr()
    assert prune_features(tmp_path, dry_run=True, json_output=False) == 0
    output = capsys.readouterr().out
    assert "would-remove" in output
    assert "feature" in output


def test_prune_refuses_feature_replaced_since_inventory(tmp_path: Path, monkeypatch, capsys):
    from dataclasses import replace

    from new_feature import prune as prune_module
    from new_feature.manifest import Manifest

    init_git_repo(tmp_path)
    worktree = create_feature(tmp_path, monkeypatch, "feature")
    original = load_manifest(tmp_path)
    replacement = Manifest(
        features={"feature": replace(original.features["feature"], generation="replacement")}
    )
    manifests = iter([original, replacement])
    monkeypatch.setattr(prune_module, "load_manifest", lambda _root: next(manifests))
    capsys.readouterr()
    assert prune_features(tmp_path, dry_run=False, json_output=True) == 1
    payload = json.loads(capsys.readouterr().out)
    assert payload["features"][0]["reasons"] == ["feature changed since inventory; refresh before pruning"]
    assert worktree.exists()


def test_prune_accepts_patch_equivalent_feature(tmp_path: Path, monkeypatch, capsys):
    init_git_repo(tmp_path)
    worktree = create_feature(tmp_path, monkeypatch, "feature")
    (worktree / "README.md").write_text("feature change\n")
    subprocess.run(["git", "commit", "-am", "feature"], cwd=worktree, check=True)
    subprocess.run(["git", "merge", "--squash", "feature"], cwd=tmp_path, check=True)
    subprocess.run(["git", "commit", "-m", "squashed"], cwd=tmp_path, check=True)
    capsys.readouterr()
    assert prune_features(tmp_path, dry_run=False, json_output=True) == 0
    assert json.loads(capsys.readouterr().out)["features"][0]["outcome"] == "removed"
    assert not worktree.exists()


def test_prune_preserves_unowned_branch_and_skips_inert_cleanup(tmp_path: Path, monkeypatch, capsys):
    from new_feature.manifest import save_manifest

    init_git_repo(tmp_path, '[tool.new-feature]\nteardown=["exit 99"]\n')
    worktree = create_feature(tmp_path, monkeypatch, "feature")
    manifest = load_manifest(tmp_path)
    manifest.features["feature"].owns_branch = False
    manifest.features["feature"].status = "inert"
    save_manifest(tmp_path, manifest)
    capsys.readouterr()
    assert main(["teardown", "feature", "--dry-run"]) == 0
    preview = capsys.readouterr().out
    assert "retain branch feature" in preview
    assert "skip configured cleanup" in preview
    assert prune_features(tmp_path, dry_run=False, json_output=True) == 0
    assert json.loads(capsys.readouterr().out)["features"][0]["outcome"] == "removed"
    assert not worktree.exists()
    subprocess.run(["git", "show-ref", "--verify", "refs/heads/feature"], cwd=tmp_path, check=True)


def test_prune_cli_requires_explicit_policy_and_rejects_force(tmp_path: Path, monkeypatch, capsys):
    init_git_repo(tmp_path)
    monkeypatch.chdir(tmp_path)
    assert main(["prune", "--json"]) == 2
    assert json.loads(capsys.readouterr().out)["error"]["code"] == "invalid-arguments"
    assert main(["prune", "--merged", "--force", "--json"]) == 2
    assert json.loads(capsys.readouterr().out)["error"]["code"] == "invalid-arguments"
    assert main(["prune", "--merged", "--dry-run", "--json"]) == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["features"] == []
    assert payload["dry_run"] is True
