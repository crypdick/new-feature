"""Define the command-line argument parser for every lifecycle command."""

from __future__ import annotations

import argparse
from importlib.metadata import version

from new_feature.help_text import (
    CREATE_DESCRIPTION,
    CREATE_EPILOG,
    DOCTOR_DESCRIPTION,
    INSTALL_CLAUDE_HOOK_DESCRIPTION,
    INSTALL_CODEX_HOOK_DESCRIPTION,
    LIST_DESCRIPTION,
    MERGE_DESCRIPTION,
    SETUP_DESCRIPTION,
    TEARDOWN_DESCRIPTION,
    TOP_LEVEL_EPILOG,
)

_COMMANDS = frozenset({
    "create",
    "setup",
    "merge",
    "teardown",
    "list",
    "status",
    "doctor",
    "install-codex-hook",
    "install-claude-hook",
})


def build_parser() -> argparse.ArgumentParser:
    """Build the command-line parser for every supported lifecycle command."""
    parser = argparse.ArgumentParser(
        prog="new-feature",
        description=("Manage the full lifecycle of isolated feature worktrees and their coding agents."),
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
    create.add_argument("name", metavar="NAME", help="descriptive feature name; normalized to a slug")
    agent_selection = create.add_mutually_exclusive_group()
    agent_selection.add_argument(
        "--no-agent",
        action="store_true",
        help="set up the feature without spawning the configured agent subprocess",
    )
    agent_selection.add_argument(
        "--agent",
        metavar="COMMAND",
        help="use a configured agent name or an executable command for this invocation",
    )
    create.add_argument(
        "--dry-run",
        action="store_true",
        help="print allocated environment values without modifying the repository",
    )
    create.add_argument(
        "--prompt",
        metavar="TEXT",
        type=_prompt,
        help="replace the configured or generated prompt passed to the agent",
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
        help="use a configured agent name or an executable command for this invocation",
    )
    setup.add_argument(
        "--prompt",
        metavar="TEXT",
        type=_prompt,
        help="replace the configured or generated prompt passed to the agent",
    )
    setup.set_defaults(command="setup")

    merge = subparsers.add_parser(
        "merge",
        help="check and merge a managed feature",
        description=MERGE_DESCRIPTION,
        epilog="Example:\n  new-feature merge billing-webhooks",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    merge.add_argument("name", metavar="NAME", help="feature name or slug shown by `new-feature list`")
    merge.set_defaults(command="merge")

    teardown = subparsers.add_parser(
        "teardown",
        help="clean up and remove a managed feature",
        description=TEARDOWN_DESCRIPTION,
        epilog=(
            "Examples:\n"
            "  new-feature teardown billing-webhooks\n"
            "  new-feature teardown billing-webhooks --force"
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    teardown.add_argument("name", metavar="NAME", help="feature name or slug shown by `new-feature list`")
    teardown.add_argument(
        "--force",
        action="store_true",
        help="discard uncommitted changes and unmerged feature commits",
    )
    teardown.set_defaults(command="teardown")

    feature_list = subparsers.add_parser(
        "list",
        aliases=["status"],
        help="show managed features and their current state",
        description=LIST_DESCRIPTION,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    feature_list.set_defaults(command="list")

    doctor = subparsers.add_parser(
        "doctor",
        help="diagnose manifest, worktree, and branch consistency",
        description=DOCTOR_DESCRIPTION,
        epilog="Example:\n  new-feature doctor\n  new-feature doctor --repair",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    doctor.add_argument(
        "--repair",
        action="store_true",
        help="remove manifest entries whose worktree and branch are both already gone",
    )
    doctor.set_defaults(command="doctor")

    install_codex = subparsers.add_parser(
        "install-codex-hook",
        help="install the repository-local Codex worktree guard",
        description=INSTALL_CODEX_HOOK_DESCRIPTION,
        epilog=(
            "Example:\n"
            "  new-feature install-codex-hook\n\n"
            "After installation, restart Codex and use `/hooks` to review and trust it."
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    install_codex.set_defaults(command="install-codex-hook")

    install_claude = subparsers.add_parser(
        "install-claude-hook",
        help="install the repository-local Claude Code worktree guard",
        description=INSTALL_CLAUDE_HOOK_DESCRIPTION,
        epilog=(
            "Example:\n"
            "  new-feature install-claude-hook\n\n"
            "After installation, restart Claude Code so the session reloads its hooks."
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    install_claude.set_defaults(command="install-claude-hook")

    return parser


def parse_args(argv: list[str]) -> argparse.Namespace:
    """Parse a command-line argument list into a lifecycle command request."""
    if argv and argv[0] not in _COMMANDS and not argv[0].startswith("-"):
        argv = ["create", *argv]
    parser = build_parser()
    args = parser.parse_args(argv)
    if args.command is None:
        parser.error("feature name or subcommand is required")
    if args.command == "create" and args.no_agent and args.prompt is not None:
        parser.error("--prompt cannot be used with --no-agent")
    return args


def _prompt(value: str) -> str:
    if not value:
        raise argparse.ArgumentTypeError("prompt must be a non-empty string")
    return value
