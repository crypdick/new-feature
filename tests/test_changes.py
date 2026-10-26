from __future__ import annotations

import json
import subprocess
from typing import TYPE_CHECKING

import pytest

from new_feature.changes import inspect_changes
from new_feature.cli import main
from new_feature.errors import NewFeatureError
from new_feature.manifest import load_manifest, save_manifest
from tests.conftest import init_git_repo

if TYPE_CHECKING:
    from pathlib import Path


@pytest.fixture
def changes_root(tmp_path: Path, monkeypatch) -> Path:
    init_git_repo(tmp_path)
    monkeypatch.chdir(tmp_path)
    assert main(["feature", "--no-agent"]) == 0
    return tmp_path


def test_changes_reports_clean_checkout(changes_root: Path, capsys):
    capsys.readouterr()
    assert inspect_changes(changes_root, "Feature", json_output=True) == 0
    report = json.loads(capsys.readouterr().out)
    assert report["schema_version"] == 1
    assert report["command"] == "changes"
    assert report["worktree"] == str(changes_root / ".worktrees/feature")
    assert report["generation"] == load_manifest(changes_root).features["feature"].generation
    assert report["changes"] == {
        "state": "clean",
        "summary": {
            "modified": 0,
            "added": 0,
            "deleted": 0,
            "renamed": 0,
            "untracked": 0,
            "staged": 0,
            "conflicts": 0,
        },
        "files": [],
    }


def test_changes_separates_index_worktree_renames_and_untracked(changes_root: Path, capsys):
    worktree = changes_root / ".worktrees/feature"
    subprocess.run(["git", "mv", "README.md", "renamed\nfile.md"], cwd=worktree, check=True)
    (worktree / "renamed\nfile.md").write_text("# changed\n")
    (worktree / "untracked file").write_text("local")
    capsys.readouterr()
    assert inspect_changes(changes_root, "feature", json_output=True) == 0
    changes = json.loads(capsys.readouterr().out)["changes"]
    assert changes["files"] == [
        {
            "path": "renamed\nfile.md",
            "original_path": "README.md",
            "index": "renamed",
            "worktree": "modified",
        },
        {"path": "untracked file", "worktree": "untracked"},
    ]
    assert changes["summary"] == {
        "modified": 0,
        "added": 0,
        "deleted": 0,
        "renamed": 1,
        "untracked": 1,
        "staged": 1,
        "conflicts": 0,
    }


def test_changes_rejects_stale_expected_generation(changes_root: Path):
    with pytest.raises(NewFeatureError, match="generation changed"):
        inspect_changes(changes_root, "feature", json_output=True, expected_generation="old")


def test_changes_rejects_unknown_feature(changes_root: Path):
    with pytest.raises(NewFeatureError, match="unknown feature: feat"):
        inspect_changes(changes_root, "feat", json_output=True)


def test_changes_rejects_manifest_replacement_during_status(changes_root: Path, monkeypatch, capsys):
    from new_feature import changes

    original = changes.subprocess.run

    def replace_after_status(argv, **kwargs):
        result = original(argv, **kwargs)
        if "status" in argv:
            manifest = load_manifest(changes_root)
            manifest.features["feature"].generation = "replacement"
            save_manifest(changes_root, manifest)
        return result

    monkeypatch.setattr(changes.subprocess, "run", replace_after_status)
    capsys.readouterr()
    with pytest.raises(NewFeatureError, match="changed during inspection"):
        inspect_changes(changes_root, "feature", json_output=True)
    assert not capsys.readouterr().out


def test_changes_human_output_quotes_filenames(changes_root: Path, capsys):
    (changes_root / ".worktrees/feature/line\nbreak").write_text("local")
    capsys.readouterr()
    assert inspect_changes(changes_root, "feature", json_output=False) == 0
    assert '"line\\nbreak"' in capsys.readouterr().out


@pytest.mark.parametrize(
    ("status_output", "expected_files", "category"),
    [
        (b"A  added\0", [{"path": "added", "index": "added"}], "added"),
        (b" D deleted\0", [{"path": "deleted", "worktree": "deleted"}], "deleted"),
        (b"UU conflict\0", [{"path": "conflict", "index": "unmerged", "worktree": "unmerged"}], "conflicts"),
        (b" M file\0", [{"path": "file", "worktree": "modified"}], "modified"),
        (
            b"C  copied\0source\0",
            [{"path": "copied", "original_path": "source", "index": "copied"}],
            "modified",
        ),
    ],
)
def test_changes_reports_git_status_states(
    changes_root: Path, monkeypatch, capsys, status_output, expected_files, category
):
    from new_feature import changes

    original = changes.subprocess.run

    def status(argv, **kwargs):
        if "status" in argv:
            return subprocess.CompletedProcess(argv, 0, status_output, b"")
        return original(argv, **kwargs)

    monkeypatch.setattr(changes.subprocess, "run", status)
    capsys.readouterr()
    assert inspect_changes(changes_root, "feature", json_output=True) == 0
    report = json.loads(capsys.readouterr().out)["changes"]
    assert report["files"] == expected_files
    assert report["summary"][category] == 1


@pytest.mark.parametrize(
    ("status_output", "error"),
    [
        (b"bad\0", "invalid git status output"),
        (b"ZZ file\0", "invalid git status code"),
        (b"R  file\0", "invalid git rename output"),
        (b"?? invalid-\xff\0", "cannot inspect feature changes"),
    ],
)
def test_changes_rejects_invalid_status_output(changes_root: Path, monkeypatch, status_output, error):
    from new_feature import changes

    original = changes.subprocess.run

    def status(argv, **kwargs):
        if "status" in argv:
            return subprocess.CompletedProcess(argv, 0, status_output, b"")
        return original(argv, **kwargs)

    monkeypatch.setattr(changes.subprocess, "run", status)
    with pytest.raises(NewFeatureError, match=error):
        inspect_changes(changes_root, "feature", json_output=True)


@pytest.mark.parametrize(
    "failure", [OSError("unavailable"), subprocess.TimeoutExpired("git", 5), "git-failed"]
)
def test_changes_reports_command_failures(changes_root: Path, monkeypatch, failure):
    from new_feature import changes

    original = changes.subprocess.run

    def status(argv, **kwargs):
        if "status" in argv:
            if failure == "git-failed":
                return subprocess.CompletedProcess(argv, 1, b"", b"cannot inspect")
            raise failure
        return original(argv, **kwargs)

    monkeypatch.setattr(changes.subprocess, "run", status)
    with pytest.raises(NewFeatureError, match="cannot inspect"):
        inspect_changes(changes_root, "feature", json_output=True)


def test_changes_human_clean_and_rename_output(changes_root: Path, capsys):
    capsys.readouterr()
    assert inspect_changes(changes_root, "feature", json_output=False) == 0
    assert "No changed files" in capsys.readouterr().out
    subprocess.run(
        ["git", "mv", "README.md", "renamed.md"], cwd=changes_root / ".worktrees/feature", check=True
    )
    assert inspect_changes(changes_root, "feature", json_output=False) == 0
    assert '"README.md" -> "renamed.md"' in capsys.readouterr().out


def test_changes_rejects_checkout_replacement_during_status(changes_root: Path, monkeypatch, capsys):
    from new_feature import changes

    original = changes.subprocess.run
    marker = changes_root / ".worktrees/feature/.git"

    def replace_after_status(argv, **kwargs):
        result = original(argv, **kwargs)
        if "status" in argv:
            content = marker.read_bytes()
            marker.rename(marker.with_name(".git.previous"))
            marker.write_bytes(content)
        return result

    monkeypatch.setattr(changes.subprocess, "run", replace_after_status)
    capsys.readouterr()
    with pytest.raises(NewFeatureError, match="changed during inspection"):
        inspect_changes(changes_root, "feature", json_output=True)
    assert not capsys.readouterr().out


def test_changes_accepts_matching_generation(changes_root: Path, capsys):
    generation = load_manifest(changes_root).features["feature"].generation
    capsys.readouterr()
    assert inspect_changes(changes_root, "feature", json_output=True, expected_generation=generation) == 0
    assert json.loads(capsys.readouterr().out)["generation"] == generation


def test_changes_legacy_generation_is_null_and_cannot_satisfy_guard(changes_root: Path, capsys):
    manifest = load_manifest(changes_root)
    manifest.features["feature"].generation = ""
    save_manifest(changes_root, manifest)
    capsys.readouterr()
    assert inspect_changes(changes_root, "feature", json_output=True) == 0
    assert json.loads(capsys.readouterr().out)["generation"] is None
    with pytest.raises(NewFeatureError, match="generation changed"):
        inspect_changes(changes_root, "feature", json_output=True, expected_generation="")


def test_changes_does_not_execute_clean_filters_in_inert_import(changes_root: Path, capsys):
    source = changes_root / ".worktrees/feature"
    subprocess.run(
        ["git", "config", "filter.review.clean", 'sh -c "echo executed > filter-ran; cat"'],
        cwd=source,
        check=True,
    )
    subprocess.run(["git", "config", "filter.review.smudge", "cat"], cwd=source, check=True)
    subprocess.run(["git", "config", "filter.review.required", "true"], cwd=source, check=True)
    (source / ".gitattributes").write_text("payload filter=review\n")
    (source / "payload").write_text("before\n")
    subprocess.run(["git", "add", ".gitattributes", "payload"], cwd=source, check=True)
    subprocess.run(["git", "commit", "-m", "add filter attributes"], cwd=source, check=True)
    assert main(["create", "review", "--from", "feature", "--no-agent"]) == 0
    review = changes_root / ".worktrees/review"
    assert not (review / "filter-ran").exists()
    # Same byte length forces Git to hash through a clean filter instead of trusting size.
    (review / "payload").write_text("after!\n")
    capsys.readouterr()
    assert inspect_changes(changes_root, "review", json_output=True) == 0
    assert not (review / "filter-ran").exists()
    files = json.loads(capsys.readouterr().out)["changes"]["files"]
    assert files == [{"path": "payload", "worktree": "modified"}]
