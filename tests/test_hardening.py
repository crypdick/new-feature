from __future__ import annotations

import subprocess
from contextlib import nullcontext
from pathlib import Path

import pytest

from new_feature import agent, atomic_file, cli, git
from new_feature.config import (
    IntegerEnvSpec,
    LiteralEnvSpec,
    NameEnvSpec,
    PathEnvSpec,
    PortEnvSpec,
    ProjectConfig,
    SlugEnvSpec,
    config_fingerprint,
    load_project_config,
)
from new_feature.errors import NewFeatureError
from new_feature.feature_state import FeatureState
from new_feature.manifest import FeatureRecord, Manifest, load_manifest, save_manifest


def test_dry_run_has_no_filesystem_side_effects(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from tests.conftest import init_git_repo

    init_git_repo(tmp_path, '[project]\nname = "demo"\n')
    monkeypatch.chdir(tmp_path)

    assert cli.main(["preview", "--dry-run"]) == 0
    assert not (tmp_path / ".gitignore").exists()
    assert not (tmp_path / ".new-feature").exists()
    assert not (tmp_path / ".worktrees").exists()


def test_dry_run_rejects_existing_feature(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from tests.conftest import init_git_repo

    init_git_repo(tmp_path, '[project]\nname = "demo"\n')
    monkeypatch.chdir(tmp_path)
    assert cli.main(["preview", "--no-agent"]) == 0

    assert cli.main(["preview", "--dry-run"]) == 1


def test_setup_failure_forces_teardown(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from tests.conftest import init_git_repo

    init_git_repo(
        tmp_path,
        '[project]\nname = "demo"\n\n[tool.new-feature]\nsetup = ["false"]\n',
    )
    monkeypatch.chdir(tmp_path)

    assert cli.main(["broken", "--no-agent"]) == 1
    assert not (tmp_path / ".worktrees" / "broken").exists()
    assert (
        subprocess.check_output(["git", "branch", "--list", "broken"], cwd=tmp_path, text=True).strip() == ""
    )
    assert load_manifest(tmp_path).features == {}


def test_setup_failure_reports_failed_forced_teardown(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    from tests.conftest import init_git_repo

    init_git_repo(
        tmp_path,
        '[project]\nname = "demo"\n\n[tool.new-feature]\nsetup = ["false"]\nteardown = ["false"]\n',
    )
    monkeypatch.chdir(tmp_path)

    assert cli.main(["broken", "--no-agent"]) == 1
    assert "forced teardown failed" in capsys.readouterr().err
    assert (tmp_path / ".worktrees" / "broken").exists()


def test_merge_start_failure_aborts_transaction(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    record = FeatureRecord(
        name="demo",
        slug="demo",
        branch="feature/demo",
        worktree=".worktrees/demo",
        target_branch="main",
        status="active",
        created_at="now",
    )
    aborted: list[Path] = []
    monkeypatch.setattr(cli, "load_project_config", lambda _root: ProjectConfig())
    monkeypatch.setattr(cli, "manifest_lock", lambda _root: nullcontext())
    monkeypatch.setattr(cli, "load_manifest", lambda _root: Manifest(features={"demo": record}))
    monkeypatch.setattr(cli, "run_commands", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(cli, "worktree_is_clean", lambda _path: True)
    monkeypatch.setattr(
        cli,
        "begin_merge_without_commit",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(NewFeatureError("conflict")),
    )
    monkeypatch.setattr(cli, "abort_merge", aborted.append)

    with pytest.raises(NewFeatureError, match="conflict"):
        cli._merge(tmp_path, "demo")
    assert aborted == [tmp_path]


def test_missing_agent_is_reported_as_domain_error(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        agent.subprocess,
        "call",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(FileNotFoundError("missing")),
    )

    with pytest.raises(NewFeatureError, match="agent command failed"):
        agent.launch_interactive_agent(("missing-agent",), tmp_path, {}, "prompt")


def test_list_and_doctor_report_config_drift(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    from tests.conftest import init_git_repo

    init_git_repo(tmp_path, '[project]\nname = "demo"\n')
    monkeypatch.chdir(tmp_path)
    assert cli.main(["alpha", "--no-agent"]) == 0
    assert cli.main(["list"]) == 0
    assert "alpha\tok" in capsys.readouterr().out

    (tmp_path / "pyproject.toml").write_text(
        '[project]\nname = "demo"\n\n[tool.new-feature]\npush = true\n', encoding="utf-8"
    )
    assert cli.main(["doctor"]) == 1
    assert "config-drift" in capsys.readouterr().out
    assert cli.main(["doctor", "--repair"]) == 1


def test_doctor_repairs_only_fully_stale_records(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    from tests.conftest import init_git_repo

    init_git_repo(tmp_path, '[project]\nname = "demo"\n')
    monkeypatch.chdir(tmp_path)
    assert cli.main(["stale", "--no-agent"]) == 0
    worktree = tmp_path / ".worktrees" / "stale"
    subprocess.run(["git", "worktree", "remove", "--force", str(worktree)], cwd=tmp_path, check=True)
    subprocess.run(["git", "branch", "-D", "stale"], cwd=tmp_path, check=True)

    assert cli.main(["doctor", "--repair"]) == 0
    assert "removed stale manifest entry stale" in capsys.readouterr().out
    assert load_manifest(tmp_path).features == {}
    assert cli.main(["doctor"]) == 0
    assert "doctor: ok" in capsys.readouterr().out


def test_feature_state_describes_all_issues() -> None:
    unhealthy = FeatureState(
        worktree_exists=False,
        branch_exists=False,
        clean=False,
        merged=False,
        config_drift=True,
    )
    assert unhealthy.stale is True
    assert unhealthy.describe() == "missing-worktree,missing-branch,dirty,unmerged,config-drift"

    healthy = FeatureState(
        worktree_exists=True,
        branch_exists=True,
        clean=True,
        merged=True,
        config_drift=False,
    )
    assert healthy.stale is False
    assert healthy.describe() == "ok"


@pytest.mark.parametrize(
    ("config", "message"),
    [
        ("[tool.new-feature]\ntarget_branch = 1\n", "target_branch must be a non-empty string"),
        ('[tool.new-feature]\npush = "false"\n', "push must be a boolean"),
        ('[tool.new-feature]\nsetup = [""]\n', "setup must be a list of non-empty strings"),
        ("[tool.new-feature]\nmystery = true\n", "unsupported tool.new-feature options"),
        ('[tool.new-feature.env]\n"BAD-NAME" = { value = "x" }\n', "valid environment variable"),
        ("[tool.new-feature.env]\nBAD = {}\n", "exactly one of value or allocate"),
        (
            '[tool.new-feature.env]\nBAD = { value = "x", allocate = "slug" }\n',
            "exactly one of value or allocate",
        ),
        (
            '[tool.new-feature.env]\nBAD = { value = "x", prefix = "y" }\n',
            "cannot set allocator options",
        ),
        ('[tool.new-feature.env]\nBAD = { value = "" }\n', "value must be a non-empty string"),
        ('[tool.new-feature.env]\nBAD = { allocate = "" }\n', "allocate must be a non-empty string"),
        ('[tool.new-feature.env]\nBAD = { allocate = "mystery" }\n', "unsupported allocator"),
        (
            '[tool.new-feature.env]\nBAD = { allocate = "port", prefix = "x" }\n',
            "unsupported options",
        ),
        ('[tool.new-feature.env]\nBAD = { allocate = "integer", min = true }\n', "must be an integer"),
        (
            '[tool.new-feature.env]\nBAD = { allocate = "integer", min = 2, max = 1 }\n',
            "min must not exceed max",
        ),
        ('[tool.new-feature.env]\nBAD = { allocate = "port", min = 0 }\n', "between 1 and 65535"),
        ('[tool.new-feature.env]\nBAD = { allocate = "port", max = 70000 }\n', "between 1 and 65535"),
        (
            '[tool.new-feature.env]\nBAD = { allocate = "name", max_length = 8 }\n',
            "max_length must be at least 9",
        ),
        (
            '[tool.new-feature.env]\nBAD = { allocate = "name", prefix = 1 }\n',
            "prefix must be a non-empty string",
        ),
    ],
)
def test_strict_config_errors(tmp_path: Path, config: str, message: str) -> None:
    (tmp_path / "pyproject.toml").write_text(config, encoding="utf-8")
    with pytest.raises(NewFeatureError, match=message):
        load_project_config(tmp_path)


@pytest.mark.parametrize(
    ("config", "message"),
    [
        ("tool = 1\n", "tool.*must be a TOML table"),
        ("not valid toml", "invalid pyproject.toml"),
    ],
)
def test_config_document_errors(tmp_path: Path, config: str, message: str) -> None:
    (tmp_path / "pyproject.toml").write_text(config, encoding="utf-8")
    with pytest.raises(NewFeatureError, match=message):
        load_project_config(tmp_path)


@pytest.mark.parametrize(
    ("config", "message"),
    [
        ("not valid toml", "invalid new-feature.toml"),
        ("target_branch = 1\n", "new-feature.toml.target_branch must be a non-empty string"),
        ('env = "bad"\n', r"\[env\] must be a TOML table"),
        ("mystery = true\n", "unsupported new-feature.toml options"),
    ],
)
def test_standalone_config_errors(tmp_path: Path, config: str, message: str) -> None:
    (tmp_path / "new-feature.toml").write_text(config, encoding="utf-8")
    with pytest.raises(NewFeatureError, match=message):
        load_project_config(tmp_path)


def test_config_fingerprint_is_stable_and_sensitive() -> None:
    baseline = config_fingerprint(ProjectConfig())
    assert baseline == config_fingerprint(ProjectConfig())
    assert baseline != config_fingerprint(ProjectConfig(push=True))
    assert config_fingerprint(ProjectConfig(env={"VALUE": PortEnvSpec()})) != config_fingerprint(
        ProjectConfig(env={"VALUE": IntegerEnvSpec()})
    )
    all_allocators = ProjectConfig(
        env={
            "LITERAL": LiteralEnvSpec("value"),
            "PORT": PortEnvSpec(),
            "INTEGER": IntegerEnvSpec(),
            "NAME": NameEnvSpec(prefix="name"),
            "SLUG": SlugEnvSpec(prefix="slug"),
            "PATH": PathEnvSpec(),
        }
    )
    assert config_fingerprint(all_allocators) == config_fingerprint(all_allocators)


def test_lifecycle_warns_when_config_changed(
    capsys: pytest.CaptureFixture[str],
) -> None:
    record = FeatureRecord(
        name="demo",
        slug="demo",
        branch="feature/demo",
        worktree=".worktrees/demo",
        target_branch="main",
        status="active",
        created_at="now",
        config_fingerprint=config_fingerprint(ProjectConfig()),
    )

    cli._warn_if_config_changed(ProjectConfig(push=True), record)
    assert "configuration changed" in capsys.readouterr().err


def test_git_branch_checks_report_command_errors(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    result = subprocess.CompletedProcess(["git"], 2)
    monkeypatch.setattr(git.subprocess, "run", lambda *_args, **_kwargs: result)

    with pytest.raises(NewFeatureError, match="checking branch"):
        git.branch_exists(tmp_path, "feature")
    with pytest.raises(NewFeatureError, match="comparing feature"):
        git.is_branch_merged(tmp_path, branch="feature", target_branch="main")


def test_manifest_rejects_unknown_version(tmp_path: Path) -> None:
    manifest_path = tmp_path / ".new-feature" / "manifest.toml"
    manifest_path.parent.mkdir(parents=True)
    manifest_path.write_text("version = 99\n", encoding="utf-8")

    with pytest.raises(NewFeatureError, match="unsupported manifest version"):
        load_manifest(tmp_path)


def test_manifest_reports_invalid_toml(tmp_path: Path) -> None:
    manifest_path = tmp_path / ".new-feature" / "manifest.toml"
    manifest_path.parent.mkdir(parents=True)
    manifest_path.write_text("not valid toml", encoding="utf-8")

    with pytest.raises(NewFeatureError, match="invalid feature manifest"):
        load_manifest(tmp_path)


@pytest.mark.parametrize(
    ("document", "message"),
    [
        ('version = "two"\n', "version must be an integer"),
        ("features = []\n", "features must be a TOML table"),
        (
            '[features.demo]\nname = 1\nslug = "demo"\nbranch = "demo"\n'
            'worktree = ".worktrees/demo"\ntarget_branch = "main"\nstatus = "active"\n',
            "demo.name must be a non-empty string",
        ),
        (
            '[features.demo]\nname = "demo"\nslug = "demo"\nbranch = "demo"\n'
            'worktree = ".worktrees/demo"\ntarget_branch = "main"\nstatus = "paused"\n',
            "demo.status must be active or merged",
        ),
        (
            '[features.demo]\nname = "demo"\nslug = "demo"\nbranch = "demo"\n'
            'worktree = ".worktrees/demo"\ntarget_branch = "main"\nstatus = "active"\n'
            "env = { PORT = 3000 }\n",
            "env values must be strings",
        ),
        (
            '[features.demo]\nname = "demo"\nslug = "demo"\nbranch = "demo"\n'
            'worktree = ".worktrees/demo"\ntarget_branch = "main"\nstatus = "active"\n'
            "created_at = 1\n",
            "created_at must be a string",
        ),
        (
            '[features.demo]\nname = "demo"\nslug = "demo"\nbranch = "demo"\n'
            'worktree = ".worktrees/demo"\ntarget_branch = "main"\nstatus = "active"\n'
            'mystery = "value"\n',
            "unsupported fields: mystery",
        ),
    ],
)
def test_manifest_rejects_malformed_typed_values(tmp_path: Path, document: str, message: str) -> None:
    manifest_path = tmp_path / ".new-feature" / "manifest.toml"
    manifest_path.parent.mkdir(parents=True)
    manifest_path.write_text(document, encoding="utf-8")

    with pytest.raises(NewFeatureError, match=message):
        load_manifest(tmp_path)


def test_manifest_atomic_write_preserves_previous_state_on_failure(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    save_manifest(tmp_path, Manifest())
    path = tmp_path / ".new-feature" / "manifest.toml"
    previous = path.read_text(encoding="utf-8")
    monkeypatch.setattr(
        atomic_file.os,
        "fsync",
        lambda *_args: (_ for _ in ()).throw(OSError("disk failure")),
    )

    with pytest.raises(NewFeatureError, match="cannot write feature manifest"):
        save_manifest(
            tmp_path,
            Manifest(
                features={
                    "demo": FeatureRecord(
                        name="demo",
                        slug="demo",
                        branch="demo",
                        worktree=".worktrees/demo",
                        target_branch="main",
                        status="active",
                        created_at="now",
                    )
                }
            ),
        )

    assert path.read_text(encoding="utf-8") == previous
    assert sorted(item.name for item in path.parent.iterdir()) == ["manifest.toml"]


def test_manifest_migrates_version_one(tmp_path: Path) -> None:
    save_manifest(tmp_path, Manifest(version=1))
    assert load_manifest(tmp_path).version == 2


def test_release_workflow_requires_quality_gate_before_build() -> None:
    workflow = Path(".github/workflows/publish.yml").read_text(encoding="utf-8")

    assert "quality:" in workflow
    assert "uv run pre-commit run --all-files" in workflow
    assert "needs: [prepare, quality]" in workflow
