from __future__ import annotations

from importlib.metadata import version
from pathlib import Path

import pytest

from new_feature import agent as agent_module
from new_feature.agent import resolve_agent, resolve_prompt
from new_feature.cli import main, parse_args
from new_feature.config import ProjectConfig, load_project_config
from new_feature.errors import NewFeatureError


def test_parser_accepts_agent_and_prompt_overrides() -> None:
    create = parse_args(["my-feature", "--agent", "claude", "--prompt", "create this feature"])
    setup = parse_args(["setup", "--agent", "fooagent --baz-flag", "--prompt", "set this up"])

    assert create.agent == "claude"
    assert create.prompt == "create this feature"
    assert setup.agent == "fooagent --baz-flag"
    assert setup.prompt == "set this up"


def test_parser_prints_installed_version(capsys) -> None:
    with pytest.raises(SystemExit) as exc_info:
        parse_args(["--version"])

    assert exc_info.value.code == 0
    assert capsys.readouterr().out == f"new-feature {version('new-feature')}\n"


def test_parser_rejects_agent_override_with_no_agent() -> None:
    with pytest.raises(SystemExit):
        parse_args(["my-feature", "--no-agent", "--agent", "claude"])


@pytest.mark.parametrize(
    "arguments", [["my-feature", "--no-agent", "--prompt", "do it"], ["setup", "--prompt", ""]]
)
def test_parser_rejects_invalid_prompt_overrides(arguments: list[str]) -> None:
    with pytest.raises(SystemExit):
        parse_args(arguments)


def test_load_project_config_includes_built_in_and_custom_agents(tmp_path: Path) -> None:
    (tmp_path / ".new-feature.toml").write_text(
        """
default_agent = "claude"
agents = { claude = ["claude", "--permission-mode", "acceptEdits"], custom = ["custom-agent"] }
create_prompt = "Create only the API."
setup_prompt = "Configure the Python tooling."
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
    assert config.create_prompt == "Create only the API."
    assert config.setup_prompt == "Configure the Python tooling."


def test_resolve_prompt_prefers_invocation_override_then_project_config() -> None:
    assert resolve_prompt("default", "configured", "override") == "override"
    assert resolve_prompt("default", "configured", None) == "configured"
    assert resolve_prompt("default", None, None) == "default"


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


def test_resolve_agent_returns_none_without_a_default_and_keeps_builtin_aliases() -> None:
    config = ProjectConfig()

    assert resolve_agent(config, None) is None
    assert resolve_agent(config, "codex") == ("codex",)
    assert resolve_agent(config, "claude") == ("claude",)


@pytest.mark.parametrize("selection", ["", 'fooagent "unterminated'])
def test_resolve_agent_rejects_invalid_command(selection: str) -> None:
    with pytest.raises(NewFeatureError, match="agent command"):
        resolve_agent(ProjectConfig(), selection)


def test_create_without_default_agent_does_not_launch_an_agent(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from tests.conftest import init_git_repo

    init_git_repo(tmp_path, '[project]\nname = "demo"\n')
    monkeypatch.chdir(tmp_path)

    assert main(["my-feature"]) == 0
    assert (tmp_path / ".worktrees" / "my-feature").is_dir()


def test_create_rejects_prompt_without_an_effective_agent(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    from tests.conftest import init_git_repo

    init_git_repo(tmp_path, '[project]\nname = "demo"\n')
    monkeypatch.chdir(tmp_path)

    assert main(["my-feature", "--prompt", "implement it"]) == 1

    assert "--prompt requires an agent" in capsys.readouterr().err
    assert not (tmp_path / ".worktrees" / "my-feature").exists()


def test_setup_without_default_agent_directs_user_to_builtin_agents(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    from tests.conftest import init_git_repo

    init_git_repo(tmp_path, '[project]\nname = "demo"\n')
    monkeypatch.chdir(tmp_path)

    assert main(["setup"]) == 1

    error = capsys.readouterr().err
    assert "setup requires an agent" in error
    assert "--agent codex" in error
    assert "--agent claude" in error
    assert (tmp_path / ".gitignore").read_text(
        encoding="utf-8"
    ) == ".new-feature/\n.worktrees/\n*.local.toml\n"


def test_setup_launches_builtin_codex_without_toml_configuration(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from tests.conftest import init_git_repo

    launches: list[tuple[object, ...]] = []
    monkeypatch.setattr(agent_module, "launch_interactive_agent", lambda *args: launches.append(args) or 0)
    init_git_repo(tmp_path, '[project]\nname = "demo"\n')
    monkeypatch.chdir(tmp_path)

    assert main(["setup", "--agent", "codex"]) == 0

    assert launches[0][0] == ("codex",)
