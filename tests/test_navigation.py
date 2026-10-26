from __future__ import annotations

import shutil
import subprocess
from typing import TYPE_CHECKING

import pytest

from new_feature.cli import main
from new_feature.errors import NewFeatureError
from new_feature.navigation import (
    print_feature_completions,
    print_feature_path,
    print_shell_completion,
)
from tests.conftest import init_git_repo

if TYPE_CHECKING:
    from pathlib import Path


@pytest.fixture
def feature_root(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    init_git_repo(tmp_path)
    monkeypatch.chdir(tmp_path)
    assert main(["My Feature", "--no-agent"]) == 0
    return tmp_path


def test_path_prints_absolute_path_for_exact_normalized_feature(feature_root: Path, capsys):
    capsys.readouterr()
    assert print_feature_path(feature_root, "My Feature") == 0
    assert capsys.readouterr().out == f"{feature_root}/.worktrees/my-feature\n"


@pytest.mark.parametrize("name", ["my", "missing"])
def test_path_rejects_partial_and_unknown_names(feature_root: Path, name):
    with pytest.raises(NewFeatureError, match=f"unknown feature: {name}"):
        print_feature_path(feature_root, name)


def test_path_rejects_checkout_replaced_with_other_branch(feature_root: Path):
    subprocess.run(
        ["git", "checkout", "-b", "replacement"],
        cwd=feature_root / ".worktrees/my-feature",
        check=True,
    )
    with pytest.raises(NewFeatureError, match="missing or mismatched"):
        print_feature_path(feature_root, "my-feature")


def test_completion_prints_sorted_slugs(feature_root: Path, capsys):
    assert main(["Another Feature", "--no-agent"]) == 0
    capsys.readouterr()
    assert print_feature_completions(feature_root) == 0
    assert capsys.readouterr().out == "another-feature\nmy-feature\n"


def test_completion_without_features_does_not_create_state(tmp_path: Path, capsys):
    assert print_feature_completions(tmp_path) == 0
    assert not capsys.readouterr().out
    assert not (tmp_path / ".new-feature").exists()


@pytest.mark.parametrize("shell", ["bash", "zsh", "fish"])
def test_generated_completion_uses_live_managed_features(shell, capsys):
    assert print_shell_completion(shell) == 0
    script = capsys.readouterr().out
    assert "new-feature completion --features" in script
    assert "path" in script
    assert "teardown" in script
    executable = shutil.which(shell)
    if executable is not None:
        result = subprocess.run([executable, "-n"], input=script, text=True, capture_output=True, check=False)
        assert result.returncode == 0, result.stderr


def test_unsupported_completion_shell_is_rejected():
    with pytest.raises(NewFeatureError, match="unsupported completion shell: powershell"):
        print_shell_completion("powershell")


@pytest.mark.parametrize("status", ["initializing", "merged"])
def test_path_allows_inspecting_existing_checkout_in_any_lifecycle_state(feature_root: Path, capsys, status):
    from new_feature.manifest import load_manifest, save_manifest

    manifest = load_manifest(feature_root)
    manifest.features["my_feature"].status = status
    save_manifest(feature_root, manifest)
    capsys.readouterr()
    assert print_feature_path(feature_root, "my-feature") == 0
    assert capsys.readouterr().out == f"{feature_root}/.worktrees/my-feature\n"


@pytest.mark.parametrize(
    ("words", "index", "expected"),
    [
        ("new-feature pa", 1, "path\n"),
        ("new-feature path my", 2, "my-feature\n"),
        ("new-feature completion z", 2, "zsh\n"),
        ("new-feature doctor a", 2, ""),
        ("new-feature exec my-feature command", 3, ""),
    ],
)
def test_bash_completion_filters_commands_features_and_shells(words, index, expected, capsys):
    assert print_shell_completion("bash") == 0
    script = capsys.readouterr().out
    script += '\nnew-feature() { printf "another-feature\\nmy-feature\\n"; }\n'
    script += f"COMP_WORDS=({words}); COMP_CWORD={index}; _new_feature\n"
    script += 'if ((${#COMPREPLY[@]})); then printf "%s\\n" "${COMPREPLY[@]}"; fi\n'
    result = subprocess.run(["bash"], input=script, text=True, capture_output=True, check=True)
    assert result.stdout == expected
