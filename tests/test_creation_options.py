from __future__ import annotations

import json
import shutil
import subprocess
from typing import TYPE_CHECKING

import pytest

from new_feature.cli import main
from new_feature.errors import NewFeatureError
from new_feature.manifest import load_manifest, manifest_path
from tests.conftest import init_git_repo

if TYPE_CHECKING:
    from pathlib import Path


@pytest.mark.parametrize(
    ("initial", "arguments", "message"),
    [
        (None, ["demo", "--bootstrap"], "--bootstrap requires an existing inert feature"),
        ("active", ["demo", "--from", "main"], "feature already exists; omit --from to reuse it"),
        ("active", ["demo", "--bootstrap"], "--bootstrap requires an inert feature"),
        ("inert", ["demo"], "feature is inert: demo"),
    ],
)
def test_creation_choices_refuse_incompatible_state(
    tmp_path: Path, monkeypatch, capfd, initial, arguments, message
):
    init_git_repo(tmp_path)
    monkeypatch.chdir(tmp_path)
    if initial is not None:
        creation = ["demo", "--no-agent"]
        if initial == "inert":
            creation.extend(["--from", "main"])
        assert main(creation) == 0
    capfd.readouterr()
    assert main([*arguments, "--no-agent", "--json"]) == 1
    report = json.loads(capfd.readouterr().out)
    assert message in report["error"]["message"]
    records = load_manifest(tmp_path).features
    if initial is None:
        assert records == {}
        assert not (tmp_path / ".worktrees/demo").exists()
    else:
        assert records["demo"].status == initial
        assert (tmp_path / ".worktrees/demo/.git").exists()


def test_failed_bootstrap_preserves_import_for_retry(tmp_path: Path, monkeypatch, capfd):
    init_git_repo(tmp_path, '[tool.new-feature]\nsetup = ["printf saved > setup-output; exit 3"]\n')
    monkeypatch.chdir(tmp_path)
    assert main(["demo", "--from", "main"]) == 0
    worktree = tmp_path / ".worktrees/demo"
    capfd.readouterr()
    assert main(["demo", "--bootstrap", "--no-agent", "--json"]) == 1
    report = json.loads(capfd.readouterr().out)
    assert report["error"]["code"] == "command-failed"
    assert load_manifest(tmp_path).features["demo"].status == "inert"
    assert (worktree / "setup-output").read_text() == "saved"
    assert (worktree / ".git").exists()
    (tmp_path / ".new-feature.local.toml").write_text("setup = []\n")
    assert main(["demo", "--bootstrap", "--no-agent", "--json"]) == 0
    assert json.loads(capfd.readouterr().out)["feature"]["status"] == "active"
    assert (worktree / "setup-output").read_text() == "saved"


@pytest.mark.parametrize("invalid", ['"true"', "1"])
def test_manifest_rejects_non_boolean_branch_ownership(tmp_path: Path, monkeypatch, invalid):
    init_git_repo(tmp_path)
    monkeypatch.chdir(tmp_path)
    assert main(["demo", "--no-agent"]) == 0
    path = manifest_path(tmp_path)
    path.write_text(path.read_text().replace("owns_branch = true", f"owns_branch = {invalid}"))
    with pytest.raises(NewFeatureError, match="owns_branch must be a boolean"):
        load_manifest(tmp_path)


def test_doctor_repairs_missing_import_without_deleting_existing_branch(tmp_path: Path, monkeypatch, capfd):
    init_git_repo(tmp_path)
    subprocess.run(["git", "branch", "demo"], cwd=tmp_path, check=True)
    monkeypatch.chdir(tmp_path)
    assert main(["demo", "--from", "demo"]) == 0
    shutil.rmtree(tmp_path / ".worktrees/demo")
    capfd.readouterr()
    assert main(["doctor", "--repair", "--json"]) == 0
    report = json.loads(capfd.readouterr().out)
    assert report["features"] == []
    assert report["repairs"] == [
        {"slug": "demo", "message": "removed missing worktree record demo; retained existing branch"}
    ]
    assert (
        subprocess.check_output(["git", "branch", "--list", "demo"], cwd=tmp_path, text=True).strip()
        == "demo"
    )
    assert load_manifest(tmp_path).features == {}
