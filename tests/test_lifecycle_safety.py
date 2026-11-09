from __future__ import annotations

import json
import subprocess
from dataclasses import replace

import pytest

from new_feature import creation
from new_feature.cli import main
from new_feature.errors import NewFeatureError
from new_feature.git import remove_worktree_and_branch
from new_feature.manifest import FeatureRecord, Manifest, load_manifest, save_manifest
from tests.conftest import init_git_repo


def test_teardown_preserves_commits_created_by_cleanup(tmp_path, monkeypatch, capsys):
    init_git_repo(
        tmp_path,
        '[tool.new-feature]\nteardown = ["echo valuable > cleanup.txt; git add cleanup.txt; git commit -m cleanup"]\n',
    )
    monkeypatch.chdir(tmp_path)
    assert main(["create", "demo", "--no-agent"]) == 0
    assert main(["teardown", "demo"]) == 1
    assert "unmerged commits" in capsys.readouterr().err
    assert (tmp_path / ".worktrees/demo/cleanup.txt").read_text() == "valuable\n"
    assert "demo" in load_manifest(tmp_path).features
    subprocess.run(["git", "show-ref", "--verify", "refs/heads/demo"], cwd=tmp_path, check=True)


@pytest.mark.parametrize("force", [False, True])
def test_teardown_rejects_branch_switch_by_cleanup(tmp_path, monkeypatch, force):
    init_git_repo(tmp_path, '[tool.new-feature]\nteardown = ["git switch -c unrelated"]\n')
    monkeypatch.chdir(tmp_path)
    assert main(["create", "demo", "--no-agent"]) == 0
    assert main(["teardown", "demo", *(["--force"] if force else [])]) == 1
    assert (tmp_path / ".worktrees/demo").is_dir()
    assert "demo" in load_manifest(tmp_path).features


def test_setup_cannot_mark_mismatched_checkout_active(tmp_path, monkeypatch):
    init_git_repo(tmp_path, '[tool.new-feature]\nsetup = ["git switch -c unrelated"]\n')
    monkeypatch.chdir(tmp_path)
    assert main(["create", "demo", "--no-agent"]) == 1
    assert load_manifest(tmp_path).features["demo"].status == "initializing"
    assert (tmp_path / ".worktrees/demo").is_dir()


def test_worktree_force_does_not_authorize_discarding_branch_commits(tmp_path, monkeypatch):
    init_git_repo(tmp_path)
    monkeypatch.chdir(tmp_path)
    assert main(["create", "demo", "--no-agent"]) == 0
    worktree = tmp_path / ".worktrees/demo"
    (worktree / "README.md").write_text("unmerged work\n")
    subprocess.run(["git", "add", "README.md"], cwd=worktree, check=True)
    subprocess.run(["git", "commit", "-m", "unmerged"], cwd=worktree, check=True)
    with pytest.raises(NewFeatureError, match="not fully merged"):
        remove_worktree_and_branch(tmp_path, branch="demo", worktree=worktree, force=True)
    subprocess.run(["git", "show-ref", "--verify", "refs/heads/demo"], cwd=tmp_path, check=True)


@pytest.mark.parametrize(
    "command",
    [
        ["create", "demo", "--no-agent"],
        ["merge", "demo"],
        ["teardown", "demo"],
        ["teardown", "demo", "--force"],
        ["path", "demo"],
        ["exec", "demo", "--", "true"],
        ["changes", "demo"],
        ["prune", "--merged"],
    ],
)
def test_commands_share_managed_checkout_identity(tmp_path, monkeypatch, command):
    init_git_repo(tmp_path)
    monkeypatch.chdir(tmp_path)
    assert main(["create", "demo", "--no-agent"]) == 0
    worktree = tmp_path / ".worktrees/demo"
    subprocess.run(["git", "switch", "-c", "unrelated"], cwd=worktree, check=True)
    assert main(command) == 1
    assert worktree.is_dir()
    assert "demo" in load_manifest(tmp_path).features


def test_inspection_reports_managed_checkout_mismatch(tmp_path, monkeypatch, capsys):
    init_git_repo(tmp_path)
    monkeypatch.chdir(tmp_path)
    assert main(["create", "demo", "--no-agent"]) == 0
    subprocess.run(["git", "switch", "-c", "unrelated"], cwd=tmp_path / ".worktrees/demo", check=True)
    capsys.readouterr()
    assert main(["list", "--json"]) == 0
    record = json.loads(capsys.readouterr().out)["features"][0]
    assert record["issues"] == ["worktree-error"]
    assert record["clean"] is None
    assert main(["doctor"]) == 1


def test_unmanaged_teardown_rejects_plain_directory(tmp_path, monkeypatch):
    init_git_repo(tmp_path)
    (tmp_path / ".worktrees/demo").mkdir(parents=True)
    monkeypatch.chdir(tmp_path)
    assert main(["teardown", "demo", "--force"]) == 1
    assert (tmp_path / ".worktrees/demo").is_dir()


def test_creation_records_intent_before_git_mutation(tmp_path, monkeypatch):
    init_git_repo(tmp_path)
    monkeypatch.chdir(tmp_path)

    def fail_save(*_args):
        raise NewFeatureError("simulated write failure")

    with monkeypatch.context() as context:
        context.setattr(creation, "save_manifest", fail_save)
        assert main(["create", "demo", "--no-agent"]) == 1
    assert not (tmp_path / ".worktrees/demo").exists()
    assert load_manifest(tmp_path).features == {}
    assert main(["create", "demo", "--no-agent"]) == 0


def test_creation_preview_derives_current_checkout_environment(tmp_path, monkeypatch, capsys):
    init_git_repo(tmp_path)
    monkeypatch.chdir(tmp_path)
    assert main(["create", "demo", "--no-agent"]) == 0
    manifest = load_manifest(tmp_path)
    manifest.features["demo"].env["NEW_FEATURE_WORKTREE"] = "/outdated/checkout"
    save_manifest(tmp_path, manifest)
    capsys.readouterr()
    assert main(["create", "demo", "--dry-run", "--no-agent"]) == 0
    output = capsys.readouterr().out
    assert f"NEW_FEATURE_WORKTREE={tmp_path / '.worktrees/demo'}\n" in output
    assert "/outdated/checkout" not in output


def test_doctor_recovers_creation_intent_without_resources(tmp_path, monkeypatch):
    init_git_repo(tmp_path)
    monkeypatch.chdir(tmp_path)

    def fail_create(*_args, **_kwargs):
        raise NewFeatureError("simulated Git failure")

    with monkeypatch.context() as context:
        context.setattr(creation, "create_worktree", fail_create)
        assert main(["create", "demo", "--no-agent"]) == 1
    assert load_manifest(tmp_path).features["demo"].status == "initializing"
    assert main(["doctor", "--repair"]) == 0
    assert load_manifest(tmp_path).features == {}
    assert main(["create", "demo", "--no-agent"]) == 0


def test_doctor_clears_failed_import_without_deleting_existing_unmerged_branch(tmp_path, monkeypatch):
    init_git_repo(tmp_path)
    occupied = tmp_path / "occupied"
    subprocess.run(["git", "worktree", "add", "-b", "review", str(occupied)], cwd=tmp_path, check=True)
    (occupied / "README.md").write_text("unmerged work\n")
    subprocess.run(["git", "add", "README.md"], cwd=occupied, check=True)
    subprocess.run(["git", "commit", "-m", "unmerged"], cwd=occupied, check=True)
    monkeypatch.chdir(tmp_path)
    assert main(["create", "review", "--from", "review"]) == 1
    intent = load_manifest(tmp_path).features["review"]
    assert intent.status == "inert"
    assert intent.owns_branch is False
    assert not (tmp_path / ".worktrees/review").exists()
    assert main(["doctor", "--repair"]) == 0
    assert load_manifest(tmp_path).features == {}
    assert (occupied / "README.md").read_text() == "unmerged work\n"
    subprocess.run(["git", "show-ref", "--verify", "refs/heads/review"], cwd=tmp_path, check=True)


@pytest.mark.parametrize("resource", ["branch", "worktree", "symlink"])
def test_creation_does_not_claim_existing_resources(tmp_path, monkeypatch, resource):
    init_git_repo(tmp_path)
    monkeypatch.chdir(tmp_path)
    if resource == "branch":
        subprocess.run(["git", "branch", "demo"], cwd=tmp_path, check=True)
    else:
        (tmp_path / ".worktrees").mkdir()
        if resource == "worktree":
            (tmp_path / ".worktrees/demo").mkdir()
        else:
            (tmp_path / ".worktrees/demo").symlink_to(tmp_path / "missing")
    assert main(["create", "demo", "--no-agent"]) == 1
    assert load_manifest(tmp_path).features == {}


def record():
    return FeatureRecord(
        name="demo",
        slug="demo",
        branch="demo",
        worktree=".worktrees/demo",
        target_branch="main",
        status="active",
        created_at="now",
    )


@pytest.mark.parametrize(
    ("key", "changes", "message"),
    [
        ("wrong", {}, "inconsistent slug or key"),
        ("demo", {"slug": "Demo"}, "inconsistent slug or key"),
        ("demo", {"branch": "main"}, "must differ"),
        ("demo", {"worktree": "/outside/demo"}, "contained relative path"),
        ("demo", {"worktree": "../demo"}, "contained relative path"),
        ("demo", {"worktree": "."}, "contained relative path"),
    ],
)
def test_manifest_enforces_relational_invariants(tmp_path, key, changes, message):
    save_manifest(tmp_path, Manifest(features={key: replace(record(), **changes)}))
    with pytest.raises(NewFeatureError, match=message):
        load_manifest(tmp_path)


@pytest.mark.parametrize("duplicate", ["branch", "worktree"])
def test_manifest_rejects_duplicate_resources(tmp_path, duplicate):
    other = replace(record(), name="other", slug="other", branch="other", worktree=".worktrees/other")
    setattr(other, duplicate, getattr(record(), duplicate))
    save_manifest(tmp_path, Manifest(features={"demo": record(), "other": other}))
    with pytest.raises(NewFeatureError, match="duplicate worktrees or branches"):
        load_manifest(tmp_path)


@pytest.mark.parametrize("escape", ["parent", "root"])
def test_manifest_rejects_escaping_symlink(tmp_path, escape):
    (tmp_path / ".worktrees").mkdir()
    (tmp_path / ".worktrees/demo").symlink_to(tmp_path.parent if escape == "parent" else tmp_path)
    save_manifest(tmp_path, Manifest(features={"demo": record()}))
    with pytest.raises(NewFeatureError, match="outside its control checkout"):
        load_manifest(tmp_path)


def test_manifest_rejects_symlink_aliases_of_same_checkout(tmp_path):
    (tmp_path / ".worktrees/other").mkdir(parents=True)
    (tmp_path / ".worktrees/demo").symlink_to(tmp_path / ".worktrees/other")
    other = replace(record(), name="other", slug="other", branch="other", worktree=".worktrees/other")
    save_manifest(tmp_path, Manifest(features={"demo": record(), "other": other}))
    with pytest.raises(NewFeatureError, match="duplicate resolved worktrees"):
        load_manifest(tmp_path)


@pytest.mark.parametrize(
    "ports", [["0"], ["65536"], ["\u0661"], ["no"], ["9" * 5000], ["01"], ["1", "1"], [1], "bad"]
)
def test_manifest_rejects_invalid_port_provenance(tmp_path, ports):
    save_manifest(tmp_path, Manifest(features={"demo": record()}))
    path = tmp_path / ".new-feature/manifest.toml"
    path.write_text(
        path.read_text().replace(
            'status = "active"', f'status = "active"\nallocated_ports = {json.dumps(ports)}'
        )
    )
    with pytest.raises(NewFeatureError, match="allocated_ports"):
        load_manifest(tmp_path)
