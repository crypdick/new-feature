from __future__ import annotations

from pathlib import Path

import pytest

from new_feature.agent import resolve_agent
from new_feature.cli import parse_args
from new_feature.config import ProjectConfig, load_project_config
from new_feature.errors import NewFeatureError


def test_parser_accepts_agent_overrides() -> None:
    create = parse_args(["my-feature", "--agent", "claude"])
    setup = parse_args(["setup", "--agent", "fooagent --baz-flag"])

    assert create.agent == "claude"
    assert setup.agent == "fooagent --baz-flag"


def test_parser_rejects_agent_override_with_no_agent() -> None:
    with pytest.raises(SystemExit):
        parse_args(["my-feature", "--no-agent", "--agent", "claude"])


def test_load_project_config_includes_built_in_and_custom_agents(tmp_path: Path) -> None:
    (tmp_path / "new-feature.toml").write_text(
        """
default_agent = "claude"
agents = { claude = ["claude", "--permission-mode", "acceptEdits"], custom = ["custom-agent"] }
""",
        encoding="utf-8",
    )

    config = load_project_config(tmp_path)

    assert config.default_agent == "claude"
    assert config.agents == {
        "codex": ("codex",),
        "claude": ("claude", "--permission-mode", "acceptEdits"),
        "custom": ("custom-agent",),
    }


def test_resolve_agent_prefers_configured_names_and_parses_commands() -> None:
    config = ProjectConfig(
        default_agent="claude",
        agents={"claude": ("claude", "--permission-mode", "acceptEdits")},
    )

    assert resolve_agent(config, None) == ("claude", "--permission-mode", "acceptEdits")
    assert resolve_agent(config, "claude") == ("claude", "--permission-mode", "acceptEdits")
    assert resolve_agent(ProjectConfig(default_agent="fooagent --baz-flag"), None) == (
        "fooagent",
        "--baz-flag",
    )
    assert resolve_agent(config, 'fooagent --baz-flag "a value"') == (
        "fooagent",
        "--baz-flag",
        "a value",
    )


@pytest.mark.parametrize("selection", ["", 'fooagent "unterminated'])
def test_resolve_agent_rejects_invalid_command(selection: str) -> None:
    with pytest.raises(NewFeatureError, match="agent command"):
        resolve_agent(ProjectConfig(), selection)
