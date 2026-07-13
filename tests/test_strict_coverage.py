from __future__ import annotations

import runpy
import subprocess
import sys
from pathlib import Path

import pytest

from new_feature.allocator import allocate_env
from new_feature.cli import main, parse_args
from new_feature.config import (
    IntegerEnvSpec,
    LiteralEnvSpec,
    NameEnvSpec,
    PathEnvSpec,
    PortEnvSpec,
    ProjectConfig,
    SlugEnvSpec,
    load_project_config,
)
from new_feature.errors import NewFeatureError
from new_feature.git import (
    abort_merge,
    ensure_repo_has_commits,
    is_branch_merged,
    repo_root,
    worktree_is_clean,
)
from new_feature.gitignore import ensure_generated_paths_ignored
from new_feature.manifest import FeatureRecord, Manifest, load_manifest, manifest_lock
from new_feature.slug import slugify


def test_module_entrypoint_exits_with_cli_code(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(sys, "argv", ["new-feature", "my-feature", "--dry-run"])

    with pytest.raises(SystemExit) as exc_info:
        runpy.run_module("new_feature.__main__", run_name="__main__")

    assert exc_info.value.code == 1


def test_parse_args_rejects_missing_command() -> None:
    with pytest.raises(SystemExit):
        parse_args([])


def test_main_reports_non_git_directory(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.chdir(tmp_path)

    assert main(["my-feature", "--dry-run"]) == 1


def test_allocator_supports_literals_integer_slug_and_default_path(tmp_path: Path) -> None:
    config = ProjectConfig(
        env={
            "STATIC": LiteralEnvSpec(value="development"),
            "NUMBER": IntegerEnvSpec(minimum=2, maximum=3),
            "NAMESPACE": SlugEnvSpec(prefix="demo app"),
            "CACHE_DIR": PathEnvSpec(),
        }
    )
    manifest = Manifest(
        features={
            "other": FeatureRecord(
                name="other",
                slug="other",
                branch="feature/other",
                worktree=".worktrees/other",
                target_branch="main",
                status="active",
                created_at="2026-07-10T12:00:00Z",
                env={"NUMBER": "2"},
            )
        }
    )

    env = allocate_env(
        config=config,
        manifest=manifest,
        name="my-feature",
        slug="my-feature",
        branch="feature/my-feature",
        worktree=tmp_path / ".worktrees" / "my-feature",
        repo_root=tmp_path,
    )

    assert env["STATIC"] == "development"
    assert env["NUMBER"] == "3"
    assert env["NAMESPACE"] == "demo-app-my-feature"
    assert env["CACHE_DIR"] == ".new-feature/my-feature"


def test_allocator_supports_slug_without_prefix_and_custom_path(tmp_path: Path) -> None:
    config = ProjectConfig(
        env={
            "SLUG": SlugEnvSpec(prefix="!!!"),
            "CACHE_DIR": PathEnvSpec(base="tmp/cache"),
        }
    )

    env = allocate_env(
        config=config,
        manifest=Manifest(),
        name="my-feature",
        slug="my-feature",
        branch="feature/my-feature",
        worktree=tmp_path / ".worktrees" / "my-feature",
        repo_root=tmp_path,
    )

    assert env["SLUG"] == "my-feature"
    assert env["CACHE_DIR"] == "tmp/cache/my-feature"


def test_allocator_reports_exhausted_integer_and_port_ranges(tmp_path: Path) -> None:
    manifest = Manifest(
        features={
            "other": FeatureRecord(
                name="other",
                slug="other",
                branch="feature/other",
                worktree=".worktrees/other",
                target_branch="main",
                status="active",
                created_at="2026-07-10T12:00:00Z",
                env={"NUMBER": "1", "WEB_PORT": "3000"},
            )
        }
    )

    with pytest.raises(NewFeatureError, match="no available integer"):
        allocate_env(
            config=ProjectConfig(env={"NUMBER": IntegerEnvSpec(minimum=1, maximum=1)}),
            manifest=manifest,
            name="my-feature",
            slug="my-feature",
            branch="feature/my-feature",
            worktree=tmp_path / ".worktrees" / "my-feature",
            repo_root=tmp_path,
        )

    with pytest.raises(NewFeatureError, match="no available port"):
        allocate_env(
            config=ProjectConfig(env={"WEB_PORT": PortEnvSpec(minimum=3000, maximum=3000)}),
            manifest=manifest,
            name="my-feature",
            slug="my-feature",
            branch="feature/my-feature",
            worktree=tmp_path / ".worktrees" / "my-feature",
            repo_root=tmp_path,
        )


def test_allocator_truncates_long_names(tmp_path: Path) -> None:
    env = allocate_env(
        config=ProjectConfig(env={"DATABASE_NAME": NameEnvSpec(prefix="demo", max_length=16)}),
        manifest=Manifest(),
        name="my-feature",
        slug="my-very-long-feature-name",
        branch="feature/my-feature",
        worktree=tmp_path / ".worktrees" / "my-feature",
        repo_root=tmp_path,
    )

    assert len(env["DATABASE_NAME"]) == 16


def test_slugify_rejects_punctuation_only_name() -> None:
    with pytest.raises(NewFeatureError, match="letters or numbers"):
        slugify("--- !!!")


def test_config_validation_errors(tmp_path: Path) -> None:
    (tmp_path / "pyproject.toml").write_text('[tool]\nnew-feature = "bad"\n', encoding="utf-8")
    with pytest.raises(NewFeatureError, match="must be a TOML table"):
        load_project_config(tmp_path)

    (tmp_path / "pyproject.toml").write_text('[tool.new-feature]\nenv = "bad"\n', encoding="utf-8")
    with pytest.raises(NewFeatureError, match="env.*must be a TOML table"):
        load_project_config(tmp_path)

    (tmp_path / "pyproject.toml").write_text('[tool.new-feature]\nsetup = "uv sync"\n', encoding="utf-8")
    with pytest.raises(NewFeatureError, match="setup must be a list"):
        load_project_config(tmp_path)

    (tmp_path / "pyproject.toml").write_text('[tool.new-feature]\ndefault_agent = ""\n', encoding="utf-8")
    with pytest.raises(NewFeatureError, match="default_agent must be a non-empty string"):
        load_project_config(tmp_path)

    (tmp_path / "pyproject.toml").write_text('[tool.new-feature]\ncreate_prompt = ""\n', encoding="utf-8")
    with pytest.raises(NewFeatureError, match="create_prompt must be a non-empty string"):
        load_project_config(tmp_path)

    (tmp_path / "pyproject.toml").write_text("[tool.new-feature]\nsetup_prompt = 1\n", encoding="utf-8")
    with pytest.raises(NewFeatureError, match="setup_prompt must be a non-empty string"):
        load_project_config(tmp_path)

    (tmp_path / "pyproject.toml").write_text('[tool.new-feature]\nagents = "codex"\n', encoding="utf-8")
    with pytest.raises(NewFeatureError, match="agents must be a table"):
        load_project_config(tmp_path)

    (tmp_path / "pyproject.toml").write_text(
        "[tool.new-feature]\nagents = { codex = [] }\n", encoding="utf-8"
    )
    with pytest.raises(NewFeatureError, match="agents.codex must be a non-empty list"):
        load_project_config(tmp_path)

    (tmp_path / "pyproject.toml").write_text(
        "[tool.new-feature]\nagents = { codex = [1] }\n", encoding="utf-8"
    )
    with pytest.raises(NewFeatureError, match="agents.codex must be a non-empty list"):
        load_project_config(tmp_path)

    (tmp_path / "pyproject.toml").write_text(
        '[tool.new-feature]\nagents = { "" = ["codex"] }\n', encoding="utf-8"
    )
    with pytest.raises(NewFeatureError, match="agents names must be non-empty strings"):
        load_project_config(tmp_path)

    (tmp_path / "pyproject.toml").write_text('[tool.new-feature.env]\nBAD = "value"\n', encoding="utf-8")
    with pytest.raises(NewFeatureError, match="env spec BAD"):
        load_project_config(tmp_path)


def test_load_project_config_without_pyproject(tmp_path: Path) -> None:
    assert load_project_config(tmp_path) == ProjectConfig()


def test_git_reports_unborn_repositories_and_failed_commands(tmp_path: Path) -> None:
    subprocess.run(["git", "init", "-b", "main"], cwd=tmp_path, check=True)

    with pytest.raises(NewFeatureError, match="repository has no commits"):
        ensure_repo_has_commits(tmp_path)

    with pytest.raises(NewFeatureError, match="git command failed"):
        repo_root(tmp_path / "missing")


def test_git_cleanliness_branch_ancestry_and_abort(tmp_path: Path) -> None:
    from tests.conftest import init_git_repo

    init_git_repo(tmp_path)
    assert repo_root(tmp_path) == tmp_path
    assert worktree_is_clean(tmp_path) is True
    (tmp_path / "dirty.txt").write_text("dirty\n", encoding="utf-8")
    assert worktree_is_clean(tmp_path) is False
    subprocess.run(["git", "checkout", "-b", "feature"], cwd=tmp_path, check=True)
    subprocess.run(["git", "add", "dirty.txt"], cwd=tmp_path, check=True)
    subprocess.run(["git", "commit", "-m", "dirty"], cwd=tmp_path, check=True)
    assert is_branch_merged(tmp_path, branch="feature", target_branch="main") is False
    abort_merge(tmp_path)


def test_gitignore_existing_complete_file_stays_unchanged(tmp_path: Path) -> None:
    gitignore = tmp_path / ".gitignore"
    gitignore.write_text(".new-feature/\n.worktrees/\n", encoding="utf-8")

    ensure_generated_paths_ignored(tmp_path)

    assert gitignore.read_text(encoding="utf-8") == ".new-feature/\n.worktrees/\n"


def test_manifest_lock_creates_lock_directory(tmp_path: Path) -> None:
    with manifest_lock(tmp_path):
        assert (tmp_path / ".new-feature" / "manifest.lock").exists()


def test_main_reports_unknown_features(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from tests.conftest import init_git_repo

    init_git_repo(tmp_path, '[project]\nname = "demo"\n')
    monkeypatch.chdir(tmp_path)

    assert main(["merge", "missing"]) == 1
    assert main(["teardown", "missing", "--force"]) == 1


def test_create_dry_run_and_duplicate_detection(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    from tests.conftest import init_git_repo

    init_git_repo(tmp_path, '[project]\nname = "demo"\n')
    monkeypatch.chdir(tmp_path)

    assert main(["my-feature", "--dry-run"]) == 0
    assert "NEW_FEATURE_BRANCH=my-feature" in capsys.readouterr().out
    assert main(["my-feature", "--no-agent"]) == 0
    assert main(["my-feature", "--no-agent"]) == 1


def test_create_launches_configured_agent(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from tests.conftest import init_git_repo

    agent = tmp_path / "agent.py"
    agent.write_text(
        'from pathlib import Path\nimport os, sys\nPath("agent-ran.txt").write_text(os.environ["NEW_FEATURE_SLUG"] + "|" + "|".join(sys.argv[1:]))\n',
        encoding="utf-8",
    )
    wrapper = tmp_path / "agent"
    wrapper.write_text(f'#!/bin/sh\nexec {sys.executable} {agent} "$@"\n', encoding="utf-8")
    wrapper.chmod(0o755)
    init_git_repo(
        tmp_path,
        (
            f'[project]\nname = "demo"\n\n[tool.new-feature]\n'
            f'default_agent = "test"\nagents = {{ test = ["{wrapper}", "--prompt"] }}\n'
            'create_prompt = "configured create prompt"\n'
        ),
    )
    monkeypatch.chdir(tmp_path)

    assert main(["my-feature"]) == 0
    output = tmp_path / ".worktrees" / "my-feature" / "agent-ran.txt"
    assert output.read_text(encoding="utf-8") == "my-feature|--prompt|configured create prompt"


def test_create_launches_unconfigured_agent_command(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from tests.conftest import init_git_repo

    agent = tmp_path / "agent.py"
    agent.write_text(
        'from pathlib import Path\nimport sys\nPath("agent-ran.txt").write_text("|".join(sys.argv[1:]))\n',
        encoding="utf-8",
    )
    wrapper = tmp_path / "agent"
    wrapper.write_text(f'#!/bin/sh\nexec {sys.executable} {agent} "$@"\n', encoding="utf-8")
    wrapper.chmod(0o755)
    init_git_repo(tmp_path, '[project]\nname = "demo"\n')
    monkeypatch.chdir(tmp_path)

    assert main(["my-feature", "--agent", f"{wrapper} --baz-flag", "--prompt", "invocation prompt"]) == 0
    output = tmp_path / ".worktrees" / "my-feature" / "agent-ran.txt"
    assert output.read_text(encoding="utf-8") == "--baz-flag|invocation prompt"


def test_setup_launches_configured_agent_in_current_repo_without_lifecycle_writes(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from tests.conftest import init_git_repo

    agent = tmp_path / "setup-agent.py"
    agent.write_text(
        'from pathlib import Path\nimport sys\nPath("setup-agent-ran.txt").write_text("|".join(sys.argv[1:]))\n',
        encoding="utf-8",
    )
    wrapper = tmp_path / "setup-agent"
    wrapper.write_text(f'#!/bin/sh\nexec {sys.executable} {agent} "$@"\n', encoding="utf-8")
    wrapper.chmod(0o755)
    init_git_repo(
        tmp_path,
        (
            f'[project]\nname = "demo"\n\n[tool.new-feature]\n'
            f'default_agent = "test"\nagents = {{ test = ["{wrapper}", "--prompt"] }}\n'
            'setup_prompt = "configured setup prompt"\n'
        ),
    )
    monkeypatch.chdir(tmp_path)

    assert main(["setup", "--agent", "test"]) == 0
    output = (tmp_path / "setup-agent-ran.txt").read_text(encoding="utf-8")
    assert output == "--prompt|configured setup prompt"
    assert not (tmp_path / ".new-feature").exists()
    assert not (tmp_path / ".worktrees").exists()
    assert not (tmp_path / ".gitignore").exists()


def test_merge_rejects_dirty_worktree_and_aborts_failed_post_merge(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from tests.conftest import init_git_repo

    init_git_repo(tmp_path, '[project]\nname = "demo"\n\n[tool.new-feature]\npost_merge = ["false"]\n')
    monkeypatch.chdir(tmp_path)
    assert main(["my-feature", "--no-agent"]) == 0
    worktree = tmp_path / ".worktrees" / "my-feature"
    (worktree / "dirty.txt").write_text("dirty\n", encoding="utf-8")
    assert main(["merge", "my-feature"]) == 1
    subprocess.run(["git", "add", ".gitignore"], cwd=tmp_path, check=True)
    subprocess.run(["git", "commit", "-m", "ignore generated state"], cwd=tmp_path, check=True)
    subprocess.run(["git", "add", "dirty.txt"], cwd=worktree, check=True)
    subprocess.run(["git", "commit", "-m", "dirty"], cwd=worktree, check=True)

    assert main(["merge", "my-feature"]) == 1
    assert not (tmp_path / ".git" / "MERGE_HEAD").exists()


def test_teardown_after_merge_uses_non_force_branch_delete(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from tests.conftest import init_git_repo

    init_git_repo(tmp_path, '[project]\nname = "demo"\n')
    monkeypatch.chdir(tmp_path)
    assert main(["my-feature", "--no-agent"]) == 0
    subprocess.run(["git", "add", ".gitignore"], cwd=tmp_path, check=True)
    subprocess.run(["git", "commit", "-m", "ignore generated state"], cwd=tmp_path, check=True)
    worktree = tmp_path / ".worktrees" / "my-feature"
    (worktree / "feature.txt").write_text("done\n", encoding="utf-8")
    subprocess.run(["git", "add", "feature.txt"], cwd=worktree, check=True)
    subprocess.run(["git", "commit", "-m", "feature"], cwd=worktree, check=True)
    assert main(["merge", "my-feature"]) == 0

    assert main(["teardown", "my-feature"]) == 0
    assert load_manifest(tmp_path).features == {}


def test_merge_reports_missing_record_after_merge(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from tests.conftest import init_git_repo

    init_git_repo(
        tmp_path,
        '[project]\nname = "demo"\n\n[tool.new-feature]\npost_merge = ["rm .new-feature/manifest.toml"]\n',
    )
    monkeypatch.chdir(tmp_path)
    assert main(["my-feature", "--no-agent"]) == 0
    subprocess.run(["git", "add", ".gitignore"], cwd=tmp_path, check=True)
    subprocess.run(["git", "commit", "-m", "ignore generated state"], cwd=tmp_path, check=True)
    worktree = tmp_path / ".worktrees" / "my-feature"
    (worktree / "feature.txt").write_text("done\n", encoding="utf-8")
    subprocess.run(["git", "add", "feature.txt"], cwd=worktree, check=True)
    subprocess.run(["git", "commit", "-m", "feature"], cwd=worktree, check=True)

    assert main(["merge", "my-feature"]) == 1


def test_main_reports_unknown_internal_command(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from argparse import Namespace

    from new_feature import cli
    from tests.conftest import init_git_repo

    init_git_repo(tmp_path, '[project]\nname = "demo"\n')
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(cli, "parse_args", lambda _argv: Namespace(command="weird"))

    assert cli.main([]) == 1


def test_merge_pushes_when_configured_unit(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from contextlib import nullcontext

    from new_feature import cli

    record = FeatureRecord(
        name="my-feature",
        slug="my-feature",
        branch="feature/my-feature",
        worktree=".worktrees/my-feature",
        target_branch="main",
        status="active",
        created_at="2026-07-10T12:00:00Z",
        env={},
    )
    manifest = Manifest(features={"my_feature": record})
    pushed = []

    monkeypatch.setattr(cli, "load_project_config", lambda _root: ProjectConfig(push=True))
    monkeypatch.setattr(cli, "manifest_lock", lambda _root: nullcontext())
    monkeypatch.setattr(cli, "load_manifest", lambda _root: manifest)
    monkeypatch.setattr(cli, "run_commands", lambda _commands, *, cwd, env: None)
    monkeypatch.setattr(cli, "worktree_is_clean", lambda _worktree: True)
    monkeypatch.setattr(cli, "begin_merge_without_commit", lambda _root, *, branch, target_branch: None)
    monkeypatch.setattr(cli, "commit_merge", lambda _root, *, name: None)
    monkeypatch.setattr(cli, "push_target", lambda _root, *, target_branch: pushed.append(target_branch))
    monkeypatch.setattr(cli, "save_manifest", lambda _root, _manifest: None)

    assert cli._merge(tmp_path, "my-feature") == 0
    assert pushed == ["main"]
    assert record.status == "merged"
