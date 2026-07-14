from __future__ import annotations

import socket
import subprocess
from pathlib import Path

import pytest
from new_feature.agent import build_initial_prompt, build_setup_prompt
from new_feature.allocator import allocate_env
from new_feature.cli import build_parser, main, parse_args
from new_feature.commands import run_commands
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
from new_feature.git import create_worktree, remove_worktree_and_branch
from new_feature.gitignore import ensure_generated_paths_ignored
from new_feature.manifest import FeatureRecord, Manifest, load_manifest, save_manifest
from new_feature.slug import feature_key, slugify


def test_bare_feature_name_is_create_command():
    args = parse_args(["my-feature", "--no-agent"])
    assert args.command == "create"
    assert args.name == "my-feature"
    assert args.no_agent is True


def test_parser_accepts_merge_command():
    args = parse_args(["merge", "my-feature"])
    assert args.command == "merge"
    assert args.name == "my-feature"


def test_parser_accepts_setup_command():
    args = parse_args(["setup"])
    assert args.command == "setup"


def test_parser_rejects_removed_merge_feature_command():
    with pytest.raises(SystemExit):
        parse_args(["merge-feature", "my-feature"])


def test_parser_accepts_teardown_force_command():
    args = parse_args(["teardown", "my-feature", "--force"])
    assert args.command == "teardown"
    assert args.name == "my-feature"
    assert args.force is True


def test_top_level_help_explains_agent_workflow():
    help_text = build_parser().format_help()

    assert "Workflow for an already-running coding agent:" in help_text
    assert "new-feature create NAME --no-agent" in help_text
    assert "new-feature COMMAND --help" in help_text
    assert ".new-feature.toml" in help_text
    assert ".new-feature.local.toml" in help_text
    assert "*.local.toml" in help_text
    assert "--version" in help_text
    assert "[tool.new-feature]" in help_text
    assert "create_prompt" in help_text
    assert "setup_prompt" in help_text
    assert 'WEB_PORT = { allocate = "port"' in help_text
    assert "Configured commands are shell strings run sequentially" in help_text
    assert "NEW_FEATURE_WORKTREE" in help_text
    assert "cannot be exported into the already-running caller" in help_text
    assert "Run lifecycle commands from the control checkout" in help_text
    assert "merge" in help_text
    assert "teardown" in help_text
    assert "setup" in help_text
    assert "install-codex-hook" in help_text


@pytest.mark.parametrize(
    ("command", "expected"),
    [
        ("create", 'agents = { custom = ["custom-agent", "--prompt"] }'),
        ("setup", "*.local.toml ignore rules"),
        ("merge", "Run this command from the control checkout"),
        ("teardown", "from the control checkout, not from the feature worktree"),
        ("list", "owns .new-feature/manifest.toml"),
        ("doctor", "owns .new-feature/manifest.toml"),
        ("install-codex-hook", "Unrelated repository hooks are"),
    ],
)
def test_subcommand_help_explains_effects_and_safety(command: str, expected: str, capsys):
    with pytest.raises(SystemExit) as exc_info:
        parse_args([command, "--help"])

    assert exc_info.value.code == 0
    assert expected in capsys.readouterr().out


def test_slugify_normalizes_descriptive_name():
    assert slugify("Add Billing Webhooks") == "add-billing-webhooks"


def test_setup_prompt_requires_inspection_approval_and_optional_hook_choice():
    prompt = build_setup_prompt()

    assert "Start by running `new-feature --help`" in prompt
    assert "existing `.new-feature.toml`, `.new-feature.local.toml`, or `[tool.new-feature]`" in prompt
    assert "Recommend the ignored `.new-feature.local.toml` sidecar" in prompt
    assert "Present a concise proposed plan" in prompt
    assert "do not make further edits or install the hook until the user approves" in prompt
    assert "optional repository-local Codex hook" in prompt
    assert "improving existing configuration when present" in prompt


def test_slugify_rejects_empty_name():
    with pytest.raises(NewFeatureError, match="feature name cannot be empty"):
        slugify("   ")


def test_feature_key_uses_underscores_for_toml_table_names():
    assert feature_key("add-billing-webhooks") == "add_billing_webhooks"


def test_load_project_config_from_dotfile(tmp_path: Path):
    (tmp_path / ".new-feature.toml").write_text(
        """
target_branch = "develop"
create_prompt = "Start with the data model."
setup_prompt = "Configure only the test suite."
setup = ["uv sync"]
pre_merge = ["uv run pytest"]
post_merge = ["uv run pytest"]
teardown = ["dropdb --if-exists $DATABASE_NAME"]

[env]
WEB_PORT = { allocate = "port", min = 3000, max = 3999 }
STATIC_ENV = { value = "development" }
""",
        encoding="utf-8",
    )
    config = load_project_config(tmp_path)
    assert config.target_branch == "develop"
    assert config.create_prompt == "Start with the data model."
    assert config.setup_prompt == "Configure only the test suite."
    assert config.setup == ["uv sync"]
    assert isinstance(config.env["WEB_PORT"], PortEnvSpec)
    assert config.env["WEB_PORT"].minimum == 3000
    assert isinstance(config.env["STATIC_ENV"], LiteralEnvSpec)
    assert config.env["STATIC_ENV"].value == "development"


def test_dotfile_takes_precedence_over_pyproject(tmp_path: Path):
    (tmp_path / "pyproject.toml").write_text("not valid toml", encoding="utf-8")
    (tmp_path / ".new-feature.toml").write_text('target_branch = "develop"\n', encoding="utf-8")
    (tmp_path / ".new-feature.local.toml").write_text("push = true\n", encoding="utf-8")

    config = load_project_config(tmp_path)

    assert config.target_branch == "develop"
    assert config.push is True


def test_legacy_standalone_config_is_ignored(tmp_path: Path):
    (tmp_path / "new-feature.toml").write_text('target_branch = "develop"\n', encoding="utf-8")

    assert load_project_config(tmp_path) == ProjectConfig()


def test_load_project_config_env_allocators(tmp_path: Path):
    (tmp_path / "pyproject.toml").write_text(
        """
[project]
name = "demo"

[tool.new-feature] # temporal-ok
target_branch = "develop"
setup = ["uv sync"]
pre_merge = ["uv run pytest"]
post_merge = ["uv run pytest"]
teardown = ["dropdb --if-exists $DATABASE_NAME"]

[tool.new-feature.env] # temporal-ok
WEB_PORT = { allocate = "port", min = 3000, max = 3999 }
DATABASE_NAME = { allocate = "name", prefix = "demo", max_length = 63 }
STATIC_ENV = { value = "development" }
WORKER_ID = { allocate = "integer" }
NAMESPACE = { allocate = "slug" }
CACHE_DIR = { allocate = "path" }
""",
        encoding="utf-8",
    )
    config = load_project_config(tmp_path)
    assert config.target_branch == "develop"
    assert config.setup == ["uv sync"]
    assert isinstance(config.env["WEB_PORT"], PortEnvSpec)
    assert config.env["WEB_PORT"].minimum == 3000
    assert isinstance(config.env["DATABASE_NAME"], NameEnvSpec)
    assert config.env["DATABASE_NAME"].prefix == "demo"
    assert isinstance(config.env["STATIC_ENV"], LiteralEnvSpec)
    assert config.env["STATIC_ENV"].value == "development"
    assert config.env["WORKER_ID"] == IntegerEnvSpec()
    assert config.env["NAMESPACE"] == SlugEnvSpec(prefix="namespace")
    assert config.env["CACHE_DIR"] == PathEnvSpec()


def test_ensure_generated_paths_ignored_creates_gitignore(tmp_path: Path):
    ensure_generated_paths_ignored(tmp_path)
    assert (tmp_path / ".gitignore").read_text(
        encoding="utf-8"
    ) == ".new-feature/\n.worktrees/\n*.local.toml\n"


def test_ensure_generated_paths_ignored_is_idempotent(tmp_path: Path):
    (tmp_path / ".gitignore").write_text(".venv\n.new-feature/\n", encoding="utf-8")
    ensure_generated_paths_ignored(tmp_path)
    assert (tmp_path / ".gitignore").read_text(
        encoding="utf-8"
    ) == ".venv\n.new-feature/\n.worktrees/\n*.local.toml\n"


def test_manifest_round_trip(tmp_path: Path):
    manifest = Manifest(
        features={
            "my_feature": FeatureRecord(
                name="my-feature",
                slug="my-feature",
                branch="feature/my-feature",
                worktree=".worktrees/my-feature",
                target_branch="main",
                status="active",
                created_at="2026-07-10T12:00:00Z",
                merged_at="",
                env={"WEB_PORT": "3123"},
            )
        }
    )
    save_manifest(tmp_path, manifest)
    loaded = load_manifest(tmp_path)
    assert loaded.features["my_feature"].env["WEB_PORT"] == "3123"
    assert loaded.features["my_feature"].branch == "feature/my-feature"


def test_allocate_env_avoids_manifest_ports(tmp_path: Path):
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
                merged_at="",
                env={"WEB_PORT": "3000"},
            )
        }
    )
    config = ProjectConfig(env={"WEB_PORT": PortEnvSpec(minimum=3000, maximum=3001)})
    env = allocate_env(
        config=config,
        manifest=manifest,
        name="my-feature",
        slug="my-feature",
        branch="feature/my-feature",
        worktree=tmp_path / ".worktrees" / "my-feature",
        repo_root=tmp_path,
    )
    assert env["WEB_PORT"] == "3001"


def test_allocate_env_avoids_live_port(tmp_path: Path):
    sock = socket.socket()
    sock.bind(("127.0.0.1", 0))
    occupied = sock.getsockname()[1]
    try:
        config = ProjectConfig(env={"WEB_PORT": PortEnvSpec(minimum=occupied, maximum=occupied + 1)})
        env = allocate_env(
            config=config,
            manifest=Manifest(),
            name="my-feature",
            slug="my-feature",
            branch="feature/my-feature",
            worktree=tmp_path / ".worktrees" / "my-feature",
            repo_root=tmp_path,
        )
        assert env["WEB_PORT"] == str(occupied + 1)
    finally:
        sock.close()


def test_allocate_env_includes_builtin_values(tmp_path: Path):
    config = ProjectConfig(env={"DATABASE_NAME": NameEnvSpec(prefix="demo", max_length=63)})
    worktree = tmp_path / ".worktrees" / "my-feature"
    env = allocate_env(
        config=config,
        manifest=Manifest(),
        name="my-feature",
        slug="my-feature",
        branch="feature/my-feature",
        worktree=worktree,
        repo_root=tmp_path,
    )
    assert env["NEW_FEATURE_NAME"] == "my-feature"
    assert env["NEW_FEATURE_BRANCH"] == "feature/my-feature"
    assert env["NEW_FEATURE_WORKTREE"] == str(worktree)
    assert env["DATABASE_NAME"].startswith("demo_my_feature_")


def test_run_commands_expands_env(tmp_path: Path):
    run_commands(['printf "$VALUE" > output.txt'], cwd=tmp_path, env={"VALUE": "ok"})
    assert (tmp_path / "output.txt").read_text(encoding="utf-8") == "ok"


def test_run_commands_reports_failed_command(tmp_path: Path):
    with pytest.raises(NewFeatureError, match="command failed"):
        run_commands(["exit 7"], cwd=tmp_path, env={})


def test_create_worktree_creates_branch_and_directory(tmp_path: Path):
    from tests.conftest import init_git_repo

    init_git_repo(tmp_path)
    worktree = tmp_path / ".worktrees" / "my-feature"
    create_worktree(tmp_path, branch="feature/my-feature", worktree=worktree, target_branch="main")
    assert worktree.exists()
    branch = subprocess.check_output(["git", "branch", "--show-current"], cwd=worktree, text=True).strip()
    assert branch == "feature/my-feature"


def test_remove_worktree_and_branch_deletes_both(tmp_path: Path):
    from tests.conftest import init_git_repo

    init_git_repo(tmp_path)
    worktree = tmp_path / ".worktrees" / "my-feature"
    create_worktree(tmp_path, branch="feature/my-feature", worktree=worktree, target_branch="main")
    remove_worktree_and_branch(tmp_path, branch="feature/my-feature", worktree=worktree, force=True)
    assert not worktree.exists()
    branches = subprocess.check_output(
        ["git", "branch", "--list", "feature/my-feature"], cwd=tmp_path, text=True
    )
    assert branches.strip() == ""


def test_initial_prompt_is_prd_interview_with_fast_path():
    prompt = build_initial_prompt("add-billing-webhooks")
    assert "Interview the user" in prompt
    assert "PRD" in prompt
    assert "add-billing-webhooks" in prompt
    assert "get right to work" in prompt


def test_create_lifecycle_creates_worktree_manifest_and_gitignore(tmp_path: Path, monkeypatch):
    from tests.conftest import init_git_repo

    init_git_repo(
        tmp_path,
        """
[project]
name = "demo"

[tool.new-feature] # temporal-ok
setup = ["printf $WEB_PORT > setup-port.txt"]

[tool.new-feature.env] # temporal-ok
WEB_PORT = { allocate = "port", min = 3200, max = 3201 }
""",
    )
    monkeypatch.chdir(tmp_path)
    assert main(["my-feature", "--no-agent"]) == 0
    assert (tmp_path / ".worktrees" / "my-feature").exists()
    assert (tmp_path / ".new-feature" / "manifest.toml").exists()
    assert load_manifest(tmp_path).features["my_feature"].branch == "my-feature"
    assert ".new-feature/" in (tmp_path / ".gitignore").read_text(encoding="utf-8")
    assert ".worktrees/" in (tmp_path / ".gitignore").read_text(encoding="utf-8")
    assert "*.local.toml" in (tmp_path / ".gitignore").read_text(encoding="utf-8")
    assert (tmp_path / ".worktrees" / "my-feature" / "setup-port.txt").read_text(encoding="utf-8") == "3200"


def test_merge_runs_checks_and_commits_merge(tmp_path: Path, monkeypatch):
    from tests.conftest import init_git_repo

    init_git_repo(
        tmp_path,
        """
[project]
name = "demo"

[tool.new-feature] # temporal-ok
pre_merge = ["test -f feature.txt"]
post_merge = ["test -f feature.txt"]
push = false
""",
    )
    monkeypatch.chdir(tmp_path)
    assert main(["my-feature", "--no-agent"]) == 0
    subprocess.run(["git", "add", ".gitignore"], cwd=tmp_path, check=True)
    subprocess.run(["git", "commit", "-m", "ignore generated state"], cwd=tmp_path, check=True)
    worktree = tmp_path / ".worktrees" / "my-feature"
    (worktree / "feature.txt").write_text("done\n", encoding="utf-8")
    subprocess.run(["git", "add", "feature.txt"], cwd=worktree, check=True)
    subprocess.run(["git", "commit", "-m", "add feature"], cwd=worktree, check=True)
    assert main(["merge", "my-feature"]) == 0
    assert (tmp_path / "feature.txt").read_text(encoding="utf-8") == "done\n"
    manifest = load_manifest(tmp_path)
    assert manifest.features["my_feature"].status == "merged"


def test_merge_requires_clean_target_checkout(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    from tests.conftest import init_git_repo

    init_git_repo(tmp_path, '[project]\nname = "demo"\n')
    monkeypatch.chdir(tmp_path)

    assert main(["my-feature", "--no-agent"]) == 0

    assert main(["merge", "my-feature"]) == 1
    assert "target checkout has uncommitted changes" in capsys.readouterr().err


def test_teardown_allows_clean_feature_without_unique_commits(tmp_path: Path, monkeypatch):
    from tests.conftest import init_git_repo

    init_git_repo(tmp_path, '[project]\nname = "demo"\n')
    monkeypatch.chdir(tmp_path)
    assert main(["my-feature", "--no-agent"]) == 0
    assert main(["teardown", "my-feature"]) == 0
    assert not (tmp_path / ".worktrees" / "my-feature").exists()


def test_teardown_requires_force_for_unmerged_commits(tmp_path: Path, monkeypatch):
    from tests.conftest import init_git_repo

    init_git_repo(tmp_path, '[project]\nname = "demo"\n')
    monkeypatch.chdir(tmp_path)
    assert main(["my-feature", "--no-agent"]) == 0
    worktree = tmp_path / ".worktrees" / "my-feature"
    (worktree / "feature.txt").write_text("work\n", encoding="utf-8")
    subprocess.run(["git", "add", "feature.txt"], cwd=worktree, check=True)
    subprocess.run(["git", "commit", "-m", "feature work"], cwd=worktree, check=True)

    assert main(["teardown", "my-feature"]) == 1
    assert worktree.exists()


def test_teardown_requires_force_for_uncommitted_changes(tmp_path: Path, monkeypatch):
    from tests.conftest import init_git_repo

    init_git_repo(tmp_path, '[project]\nname = "demo"\n')
    monkeypatch.chdir(tmp_path)
    assert main(["my-feature", "--no-agent"]) == 0
    worktree = tmp_path / ".worktrees" / "my-feature"
    (worktree / "feature.txt").write_text("work\n", encoding="utf-8")

    assert main(["teardown", "my-feature"]) == 1
    assert worktree.exists()


def test_teardown_force_removes_worktree_branch_and_manifest_entry(tmp_path: Path, monkeypatch):
    from tests.conftest import init_git_repo

    init_git_repo(
        tmp_path,
        """
[project]
name = "demo"

[tool.new-feature] # temporal-ok
teardown = ["printf torn-down > teardown.txt"]
""",
    )
    monkeypatch.chdir(tmp_path)
    assert main(["my-feature", "--no-agent"]) == 0
    assert main(["teardown", "my-feature", "--force"]) == 0
    assert not (tmp_path / ".worktrees" / "my-feature").exists()
    manifest = load_manifest(tmp_path)
    assert "my_feature" not in manifest.features
    branches = subprocess.check_output(["git", "branch", "--list", "my-feature"], cwd=tmp_path, text=True)
    assert branches.strip() == ""
