"""Bounded shell parsing for advisory guards, without evaluating shell code."""

from __future__ import annotations

import itertools
import os
import re
import shlex
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Iterator

_CONTROL_WORDS = {
    "if",
    "then",
    "elif",
    "else",
    "fi",
    "for",
    "select",
    "while",
    "until",
    "do",
    "done",
    "case",
    "esac",
    "function",
    "{",
    "}",
}
type _ShellPart = list[str] | str  # Command words or an unquoted shell operator.

# Preserve quoting here so a literal '<<' cannot start a heredoc. shlex removes it.
_HEREDOC_TOKENS = re.compile(
    r"\#[^\n]*|"
    r"""(?:[^\s;&|()<>'"\\]+|\\[\s\S]|'[^']*'|"(?:\\[\s\S]|[^"\\])*")+|"""
    r"<<-|[;&|()<>\n]+"
)


class _UnsupportedShellSyntaxError(Exception):
    """Mark shell syntax outside the advisory parser, not a checker failure."""


def parse_shell_commands(command: str) -> list[list[str]]:
    try:
        parts = _parse_shell_parts(command)
    except _UnsupportedShellSyntaxError:
        return []
    return [part if isinstance(part, list) else [part] for part in parts]


def _parse_shell_parts(command: str) -> list[_ShellPart]:
    tokens: list[tuple[str, bool]] = []
    heredocs: list[tuple[str, bool]] = []
    header = ""
    for line in command.splitlines(keepends=True):
        if heredocs:
            delimiter, strip_tabs = heredocs[0]
            candidate = line.lstrip("\t") if strip_tabs else line
            if candidate.removesuffix("\n") == delimiter:
                heredocs.pop(0)
            continue
        header += line
        if header.endswith("\\\n"):
            continue
        try:
            lexer = shlex.shlex(header, posix=True, punctuation_chars=";&|()<>\n")
            lexer.whitespace = " \t\r"
            lexer.whitespace_split = True
            list(lexer)
        except ValueError:
            # A quoted shell argument may span physical lines.
            continue
        # NOTE: docs/ARCHITECTURE.md excludes heredoc data from shell command checks.
        raw_words = _HEREDOC_TOKENS.findall(header)
        for raw in raw_words:
            if raw.startswith("#"):
                continue
            # Process substitution contains nested commands, not a literal redirect.
            if raw.startswith(("<(", ">(")):
                raise _UnsupportedShellSyntaxError("process substitution")
            if re.fullmatch(r"[;&|()\n]+", raw):
                tokens.extend((part, True) for part in re.findall(r"&&|\|\||[;&|()\n]", raw))
            else:
                tokens.extend((word, False) for word in shlex.split(raw, comments=False))
        heredocs.extend(
            (shlex.split(target, comments=False)[0], operator == "<<-")
            for operator, target in itertools.pairwise(raw_words)
            if operator in {"<<", "<<-"}
        )
        header = ""
    return [] if header else _shell_commands(tokens)


def _shell_commands(tokens: list[tuple[str, bool]]) -> list[_ShellPart]:
    commands: list[_ShellPart] = []
    words: list[str] = []
    for word, separator in tokens:
        if separator:
            if words:
                commands.append(words)
                words = []
            if word == "\n" and commands and commands[-1] == "|":
                continue
            commands.append(word.removesuffix("\n"))
        else:
            words.append(word)
    if words:
        commands.append(words)
    return commands


@dataclass
class _DirectoryState:
    """Possible directories after successful and failed commands in an AND/OR list."""

    success: set[Path]
    failure: set[Path]
    operator: str = ";"

    def incoming(self) -> set[Path]:
        if self.operator == "&&":
            return self.success
        if self.operator == "||":
            return self.failure
        return self.success | self.failure

    def update(self, success: set[Path], failure: set[Path], *, before_pipe: bool) -> None:
        # All stages start in the same directories. Only the whole pipeline has
        # a status for the surrounding AND/OR list.
        if before_pipe:
            return
        if self.operator == "&&":
            failure = failure | self.failure
        elif self.operator == "||":
            success = success | self.success
        self.success, self.failure = success, failure


def commands_with_cwd(command: str, *, cwd: Path) -> list[tuple[Path, list[str]]]:
    """Return commands with inferred directories, or no candidates for unsupported syntax."""
    try:
        # Validate the entire command before exposing any inferred directories.
        return list(_commands_with_cwd(command, cwd=cwd))
    except _UnsupportedShellSyntaxError:
        return []


def _commands_with_cwd(command: str, *, cwd: Path) -> Iterator[tuple[Path, list[str]]]:
    parts = [
        _current_shell_words(part) if isinstance(part, list) else part for part in _parse_shell_parts(command)
    ]
    _require_supported_cwd_commands(parts)
    state = _DirectoryState({cwd}, {cwd})
    scopes: list[_DirectoryState] = []
    for part, following in itertools.pairwise([*parts, ""]):
        before_pipe = following == "|"
        if part == "(":
            scopes.append(state)
            incoming = state.incoming()
            state = _DirectoryState(set(incoming), set(incoming))
        elif part == ")":
            if not scopes:
                raise _UnsupportedShellSyntaxError("unmatched closing subshell")
            state = scopes.pop()
            incoming = state.incoming()
            state.update(incoming, incoming, before_pipe=before_pipe)
        elif part == "|":
            continue
        elif isinstance(part, str):
            state.operator = part
        else:
            incoming = state.incoming()
            if part[0] == "cd":
                success = _cd_directories(part, incoming)
            else:
                for directory in sorted(incoming):
                    yield directory, part
                success = incoming
            state.update(success, incoming, before_pipe=before_pipe)
            state.operator = state.operator if before_pipe else ";"
    if scopes:
        raise _UnsupportedShellSyntaxError("unclosed subshell")


def _current_shell_words(words: list[str]) -> list[str]:
    """Unwrap only prefixes that execute builtins in the current shell."""
    index = 0
    while index < len(words) and re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*=.*", words[index]):
        index += 1
    while index < len(words) and words[index] in {"command", "builtin"}:
        index += 1
        while index < len(words) and words[index] in {"--", "-p"}:
            index += 1
    if words[index : index + 1] != ["cd"]:
        return words
    if any(word.startswith(("CDPATH=", "PWD=")) for word in words[:index]):
        raise _UnsupportedShellSyntaxError("cd with CDPATH or PWD overrides")
    return words[index:]


def _require_supported_cwd_commands(parts: list[_ShellPart]) -> None:
    names = {part[0] for part in parts if isinstance(part, list)}
    if "cd" in names and "&" in parts:
        raise _UnsupportedShellSyntaxError("cd with background commands")
    if "cd" in names and "|" in parts:
        _require_supported_pipeline(parts)
    if names & _CONTROL_WORDS:
        raise _UnsupportedShellSyntaxError("shell control flow")


def _require_supported_pipeline(parts: list[_ShellPart]) -> None:
    for index, part in enumerate(parts):
        if not isinstance(part, list) or part[0] != "cd":
            continue
        if parts[index - 1 : index] == ["|"] or parts[index + 1 : index + 2] == ["|"]:
            raise _UnsupportedShellSyntaxError("cd as a pipeline stage")
    # The lexer can retain escaped line breaks in words, changing command names
    # or arguments. Don't infer a checkout from those words.
    if any("\n" in word for part in parts if isinstance(part, list) for word in part):
        raise _UnsupportedShellSyntaxError("cd with a pipeline and multiline words")


def _cd_directories(words: list[str], directories: set[Path]) -> set[Path]:
    arguments = words[1:]
    if arguments[:1] == ["--"]:
        arguments = arguments[1:]
    if (
        len(arguments) != 1
        or arguments[0].startswith("-")
        or any(character in arguments[0] for character in "$`*?[")
    ):
        raise _UnsupportedShellSyntaxError("nonliteral cd")
    target = Path(arguments[0]).expanduser()
    if os.environ.get("CDPATH") and not target.is_absolute() and not arguments[0].startswith(("./", "../")):
        raise _UnsupportedShellSyntaxError("relative cd with CDPATH")
    # Shell cd uses logical parent paths; resolve() would follow symlinks before removing `..`
    candidates = {Path(os.path.abspath(directory / target)) for directory in directories}  # noqa: PTH100
    return {candidate for candidate in candidates if candidate.is_dir()}
