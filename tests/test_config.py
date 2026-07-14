from __future__ import annotations

from pathlib import Path

import pytest

from new_feature.config import LiteralEnvSpec, SlugEnvSpec, load_project_config
from new_feature.errors import NewFeatureError


def test_load_project_config_defaults(tmp_path: Path):
    (tmp_path / "pyproject.toml").write_text('[project]\nname = "demo"\n', encoding="utf-8")

    config = load_project_config(tmp_path)

    assert config.target_branch == "main"
    assert config.default_agent is None
    assert config.agents == {"codex": ("codex",), "claude": ("claude",)}
    assert config.create_prompt is None
    assert config.setup_prompt is None
    assert config.push is False
    assert config.setup == []
    assert config.pre_merge == []
    assert config.post_merge == []
    assert config.teardown == []
    assert config.env == {}


def test_local_config_overlays_shared_pyproject_config_by_setting_and_table_entry(tmp_path: Path):
    (tmp_path / "pyproject.toml").write_text(
        """
[project]
name = "demo"

[tool.new-feature] # temporal-ok
target_branch = "develop"
default_agent = "shared"
create_prompt = "shared prompt"
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

    with pytest.raises(NewFeatureError, match="tool.new-feature.push must be a boolean"):
        load_project_config(tmp_path)
