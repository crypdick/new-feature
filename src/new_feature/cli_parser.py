"""Define the command-line argument parser for every lifecycle command."""

from __future__ import annotations

import argparse
from importlib.metadata import version

from new_feature.help_text import (
    CREATE_DESCRIPTION,
    CREATE_EPILOG,
    DOCTOR_DESCRIPTION,
    EXEC_DESCRIPTION,
    LIST_DESCRIPTION,
    MERGE_DESCRIPTION,
    SETUP_DESCRIPTION,
    TEARDOWN_DESCRIPTION,
    TOP_LEVEL_EPILOG,
)

# Retired command names remain unavailable as shorthand feature names.
_RETIRED_COMMANDS = frozenset({"codex-hook", "claude-hook", "install-codex-hook", "install-claude-hook"})


def build_parser() -> argparse.ArgumentParser:
    """Build the command-line parser for every supported lifecycle command."""
    return _build_parser()[0]


def _build_parser() -> tuple[argparse.ArgumentParser, dict[str, argparse.ArgumentParser]]:
    parser = argparse.ArgumentParser(
        prog="new-feature",
        description="Create, merge, and clean up isolated feature worktrees.",
        epilog=TOP_LEVEL_EPILOG,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("--version", action="version", version=f"%(prog)s {version('new-feature')}")
    subparsers = parser.add_subparsers(dest="command", metavar="COMMAND")

    create = subparsers.add_parser(
        "create",
        help="create a worktree and optionally launch its coding agent",
        description=CREATE_DESCRIPTION,
        epilog=CREATE_EPILOG,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    create.set_defaults(accepts_feature_name=True)
    create.add_argument("name", metavar="NAME", help="descriptive feature name; normalized to a slug")
    agent_selection = create.add_mutually_exclusive_group()
    agent_selection.add_argument(
        "--no-agent",
        action="store_true",
        help="skip launching an agent",
    )
    agent_selection.add_argument(
        "--agent",
        metavar="COMMAND",
        help="agent name or executable command",
    )
    create.add_argument(
        "--dry-run",
        action="store_true",
        help="print environment values without creating or reserving anything",
    )
    create.add_argument(
        "--prompt",
        metavar="TEXT",
        type=_prompt,
        help="override the agent prompt",
    )
    create.add_argument(
        "--json", dest="json_output", action="store_true", help="emit a versioned creation result"
    )
    create.add_argument(
        "--from",
        dest="from_ref",
        metavar="BRANCH",
        help="import an existing local or remote branch without setup or agent launch",
    )
    create.add_argument(
        "--bootstrap",
        action="store_true",
        help="explicitly run setup for a previously imported inert feature",
    )
    create.add_argument(
        "--ignore-dirty",
        action="store_true",
        help="pull before creating even if the target checkout has uncommitted changes",
    )
    create.set_defaults(command="create")

    setup = subparsers.add_parser(
        "setup",
        help="launch an agent to configure new-feature for this repository",
        description=SETUP_DESCRIPTION,
        epilog="Example:\n  new-feature setup --agent codex",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    setup.add_argument(
        "--agent",
        metavar="COMMAND",
        help="agent name or executable command",
    )
    setup.add_argument(
        "--prompt",
        metavar="TEXT",
        type=_prompt,
        help="override the agent prompt",
    )
    setup.set_defaults(command="setup")

    merge = subparsers.add_parser(
        "merge",
        help="check and merge a managed feature",
        description=MERGE_DESCRIPTION,
        epilog="Example:\n  new-feature merge billing-webhooks",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    merge.add_argument(
        "--include-untracked",
        action="store_true",
        help="copy local files, including ignored files, into target checkout",
    )
    merge.add_argument(
        "--ignore-dirty",
        action="store_true",
        help="stash uncommitted target changes during the merge and restore them afterwards",
    )
    merge.set_defaults(accepts_feature_name=True)
    merge.add_argument("name", metavar="NAME", help="feature name or slug shown by `new-feature list`")
    merge.add_argument(
        "git_args",
        nargs=argparse.REMAINDER,
        metavar="GIT_ARGS",
        help="arguments passed through to `git merge`",
    )
    merge.set_defaults(command="merge")

    execution = subparsers.add_parser(
        "exec",
        help="run a command in a feature's recorded environment",
        description=EXEC_DESCRIPTION,
        epilog="Example:\n  new-feature exec billing-webhooks -- uv run pytest",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    execution.set_defaults(accepts_feature_name=True)
    execution.add_argument("name", metavar="NAME", help="exact feature name or normalized slug")
    execution.add_argument(
        "argv", nargs=argparse.REMAINDER, metavar="COMMAND", help="executable and arguments"
    )
    execution.set_defaults(command="exec")

    teardown = subparsers.add_parser(
        "teardown",
        help="clean up and remove a feature worktree",
        description=TEARDOWN_DESCRIPTION,
        epilog=(
            "Examples:\n"
            "  new-feature teardown billing-webhooks\n"
            "  new-feature teardown billing-webhooks --force"
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    teardown.set_defaults(accepts_feature_name=True)
    teardown.add_argument(
        "name",
        metavar="NAME",
        help="feature name or worktree slug",
    )
    teardown.add_argument(
        "--force",
        action="store_true",
        help="discard uncommitted changes and unmerged feature commits; bypass process guards",
    )
    teardown.add_argument(
        "--dry-run",
        action="store_true",
        help="preview cleanup, removal, and refusal conditions without changing resources",
    )
    teardown.set_defaults(command="teardown")

    feature_list = subparsers.add_parser(
        "list",
        aliases=["status"],
        help="show managed features and their current state",
        description=LIST_DESCRIPTION,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    feature_list.add_argument(
        "--json", dest="json_output", action="store_true", help="emit versioned machine-readable state"
    )
    feature_list.set_defaults(command="list")

    doctor = subparsers.add_parser(
        "doctor",
        help="find stale state and configuration drift",
        description=DOCTOR_DESCRIPTION,
        epilog="Example:\n  new-feature doctor\n  new-feature doctor --repair",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    doctor.add_argument(
        "--repair",
        action="store_true",
        help="remove stale records and integrated branches with missing worktrees",
    )
    doctor.add_argument(
        "--json",
        dest="json_output",
        action="store_true",
        help="emit versioned machine-readable state and repairs",
    )
    doctor.set_defaults(command="doctor")

    _add_workspace_commands(subparsers)

    rules = subparsers.add_parser("install-rules", help="install harness-neutral i-insist rules")
    rules.add_argument(
        "--global",
        dest="global_scope",
        action="store_true",
        help="install in ~/.i-insist for every repository",
    )
    rules.set_defaults(command="install-rules")

    return parser, subparsers.choices


def command_names(*, feature_names: bool = False, json_output: bool = False) -> tuple[str, ...]:
    """Derive command capabilities from the actual argument definitions."""
    _, commands = _build_parser()
    return tuple(
        name
        for name, parser in commands.items()
        if (not feature_names or parser.get_default("accepts_feature_name"))
        and (not json_output or parser.get_default("json_output") is False)
    )


def parse_args(argv: list[str]) -> argparse.Namespace:
    """Parse a command-line argument list into a lifecycle command request."""
    parser, commands = _build_parser()
    if argv and argv[0] not in commands and argv[0] not in _RETIRED_COMMANDS and not argv[0].startswith("-"):
        argv = ["create", *argv]
    args = parser.parse_args(argv)
    if args.command is None:
        parser.error("feature name or subcommand is required")
    if args.command == "merge":
        boundary = args.git_args.index("--") if "--" in args.git_args else len(args.git_args)
        own_arguments = args.git_args[:boundary]
        # NOTE: README.md's Lifecycle section reserves help for the wrapper,
        # even after NAME; argparse.REMAINDER otherwise forwards it to Git.
        if {"--help", "-h"}.intersection(own_arguments):
            parser.parse_args(["merge", "--help"])
        args.include_untracked |= "--include-untracked" in own_arguments
        args.ignore_dirty |= "--ignore-dirty" in own_arguments
        wrapper_options = {"--include-untracked", "--ignore-dirty"}
        args.git_args = [value for value in own_arguments if value not in wrapper_options] + args.git_args[
            boundary:
        ]
    if args.command == "completion" and (bool(args.shell) == args.features):
        parser.error("completion requires a shell or --features")
    if args.command == "create":
        _check_creation_arguments(parser, args)
    if args.command == "create" and args.no_agent and args.prompt is not None:
        parser.error("--prompt cannot be used with --no-agent")
    if args.command == "exec" and not args.argv:
        parser.error("exec requires a command after NAME --")
    return args


def _prompt(value: str) -> str:
    if not value:
        raise argparse.ArgumentTypeError("prompt must be a non-empty string")
    return value


def wants_json(argv: list[str]) -> bool:
    """Recognize JSON intent for supported commands, including shorthand creation."""
    if "--json" not in argv:
        return False
    command = argv[0]
    return command in command_names(json_output=True) or (
        command not in command_names() and command not in _RETIRED_COMMANDS and not command.startswith("-")
    )


def _add_workspace_commands(subparsers: argparse._SubParsersAction[argparse.ArgumentParser]) -> None:
    path = subparsers.add_parser("path", help="print the absolute path of an exact managed feature")
    path.set_defaults(accepts_feature_name=True)
    path.add_argument("name", metavar="NAME")

    completion = subparsers.add_parser("completion", help="print shell completion integration")
    completion.add_argument("shell", nargs="?", choices=("bash", "zsh", "fish"))
    completion.add_argument("--features", action="store_true", help=argparse.SUPPRESS)

    prune = subparsers.add_parser(
        "prune", help="remove integrated features using normal teardown safety checks"
    )
    prune.add_argument(
        "--merged", action="store_true", required=True, help="select merged and patch-equivalent features"
    )
    prune.add_argument("--dry-run", action="store_true", help="preview candidates without changing resources")
    prune.add_argument(
        "--json", dest="json_output", action="store_true", help="emit versioned per-feature outcomes"
    )

    changes = subparsers.add_parser("changes", help="inspect staged, working-tree, and untracked changes")
    changes.set_defaults(accepts_feature_name=True)
    changes.add_argument("name", metavar="NAME")
    changes.add_argument("--json", dest="json_output", action="store_true")
    changes.add_argument("--expected-generation", metavar="TOKEN", help="refuse a replaced feature")


def _check_creation_arguments(parser: argparse.ArgumentParser, args: argparse.Namespace) -> None:
    if args.json_output and args.dry_run:
        parser.error("--json cannot be used with --dry-run")
    if args.from_ref and (args.bootstrap or args.agent or args.prompt):
        parser.error("--from cannot be used with --bootstrap, --agent, or --prompt")
    if args.bootstrap and args.dry_run:
        parser.error("--bootstrap cannot be used with --dry-run")
