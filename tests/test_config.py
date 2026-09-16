from __future__ import annotations

from typing import TYPE_CHECKING

import pytest

from new_feature.config import LiteralEnvSpec, SlugEnvSpec, load_project_config
from new_feature.errors import NewFeatureError

if TYPE_CHECKING:
    from pathlib import Path


def test_load_project_config_defaults(tmp_path: Path):
    (tmp_path / "pyproject.toml").write_text('[project]\nname = "demo"\n', encoding="utf-8")

    config = load_project_config(tmp_path)

    assert config.target_branch == "main"
    assert config.default_agent is None
    assert config.agents == {"codex": ("codex",), "claude": ("claude",)}
    assert config.create_prompt is None
    assert config.setup_prompt is None
    assert config.pull_before_create is False
    assert config.push is False
    assert config.setup == []
    assert config.pre_merge == []
    assert config.post_merge == []
    assert config.teardown == []
    assert config.env == {}


def test_global_config_supplies_default_agent(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    config_home = tmp_path / "config"
    monkeypatch.setenv("XDG_CONFIG_HOME", str(config_home))
    global_config = config_home / "new-feature/config.toml"
    global_config.parent.mkdir(parents=True)
    global_config.write_text('default_agent = "codex"\n', encoding="utf-8")
    repo = tmp_path / "repo"
    repo.mkdir()

    config = load_project_config(repo)

    assert config.default_agent == "codex"


def test_global_config_defaults_to_home_config_directory(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.delenv("XDG_CONFIG_HOME")
    monkeypatch.setattr("new_feature.config.Path.home", lambda: tmp_path)
    global_config = tmp_path / ".config/new-feature/config.toml"
    global_config.parent.mkdir(parents=True)
    global_config.write_text('default_agent = "claude"\n', encoding="utf-8")

    assert load_project_config(tmp_path).default_agent == "claude"


def test_repository_configs_override_global_default_agent(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    config_home = tmp_path / "config"
    monkeypatch.setenv("XDG_CONFIG_HOME", str(config_home))
    global_config = config_home / "new-feature/config.toml"
    global_config.parent.mkdir(parents=True)
    global_config.write_text('default_agent = "codex"\n', encoding="utf-8")
    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / ".new-feature.toml").write_text('default_agent = "claude"\n', encoding="utf-8")

    assert load_project_config(repo).default_agent == "claude"

    (repo / ".new-feature.local.toml").write_text('default_agent = "custom-agent"\n', encoding="utf-8")
    assert load_project_config(repo).default_agent == "custom-agent"


@pytest.mark.parametrize(
    ("content", "message"),
    [
        ("not valid toml", "invalid config.toml"),
        ('default_agent = ""\n', "global config.default_agent must be a non-empty string"),
        ("push = true\n", "unsupported global config options: push"),
    ],
)
def test_global_config_rejects_invalid_content(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, content: str, message: str
):
    config_home = tmp_path / "config"
    monkeypatch.setenv("XDG_CONFIG_HOME", str(config_home))
    global_config = config_home / "new-feature/config.toml"
    global_config.parent.mkdir(parents=True)
    global_config.write_text(content, encoding="utf-8")

    with pytest.raises(NewFeatureError, match=message):
        load_project_config(tmp_path)


def test_local_config_overlays_shared_pyproject_config_by_setting_and_table_entry(tmp_path: Path):
    (tmp_path / "pyproject.toml").write_text(
        """
[project]
name = "demo"

[tool.new-feature] # temporal-ok
target_branch = "develop"
default_agent = "shared"
create_prompt = "shared prompt"
pull_before_create = false
push = false
setup = ["shared setup"]

[tool.new-feature.agents] # temporal-ok
codex = ["shared-codex"]
shared = ["shared-agent"]

[tool.new-feature.env] # temporal-ok
INHERITED = { value = "shared" }
REPLACED = { allocate = "port", min = 3000, max = 3001 } # temporal-ok
""",
        encoding="utf-8",
    )
    (tmp_path / ".new-feature.local.toml").write_text(
        """
default_agent = "local"
pull_before_create = true
push = true
setup = ["local setup"]

[agents]
codex = ["local-codex"]
local = ["local-agent"]

[env]
REPLACED = { value = "local" } # temporal-ok
LOCAL = { allocate = "slug", prefix = "dev" }
""",
        encoding="utf-8",
    )

    config = load_project_config(tmp_path)

    assert config.target_branch == "develop"
    assert config.default_agent == "local"
    assert config.create_prompt == "shared prompt"
    assert config.pull_before_create is True
    assert config.push is True
    assert config.setup == ["local setup"]
    assert config.agents == {
        "codex": ("local-codex",),
        "claude": ("claude",),
        "shared": ("shared-agent",),
        "local": ("local-agent",),
    }
    assert config.env["INHERITED"] == LiteralEnvSpec(value="shared")
    assert config.env["REPLACED"] == LiteralEnvSpec(value="local")
    assert config.env["LOCAL"] == SlugEnvSpec(prefix="dev")


def test_local_config_works_without_a_shared_config_file(tmp_path: Path):
    (tmp_path / ".new-feature.local.toml").write_text(
        """
target_branch = "develop"
push = true

[agents]
local = ["local-agent"]

[env]
LOCAL = { value = "enabled" }
""",
        encoding="utf-8",
    )

    config = load_project_config(tmp_path)

    assert config.target_branch == "develop"
    assert config.default_agent is None
    assert config.push is True
    assert config.agents == {
        "codex": ("codex",),
        "claude": ("claude",),
        "local": ("local-agent",),
    }
    assert config.env == {"LOCAL": LiteralEnvSpec(value="enabled")}


@pytest.mark.parametrize(
    ("content", "message"),
    [
        ("not valid toml", "invalid .new-feature.local.toml"),
        ("mystery = true\n", "unsupported .new-feature.local.toml options"),
    ],
)
def test_local_config_errors_identify_the_local_source(tmp_path: Path, content: str, message: str):
    (tmp_path / ".new-feature.local.toml").write_text(content, encoding="utf-8")

    with pytest.raises(NewFeatureError, match=message):
        load_project_config(tmp_path)


def test_local_config_cannot_mask_an_invalid_shared_setting(tmp_path: Path):
    (tmp_path / "pyproject.toml").write_text('[tool.new-feature]\npush = "not a boolean"\n', encoding="utf-8")
    (tmp_path / ".new-feature.local.toml").write_text("push = true\n", encoding="utf-8")

    with pytest.raises(NewFeatureError, match=r"tool\.new-feature\.push must be a boolean"):
        load_project_config(tmp_path)
