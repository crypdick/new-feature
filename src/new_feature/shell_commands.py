"""Bounded shell parsing for advisory guards, without evaluating shell code."""

from __future__ import annotations

import itertools
import os
import re
import shlex
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING

from new_feature.errors import NewFeatureError

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
_SHELL_SEPARATORS = {";", "&&", "||", "|", "&", "(", ")", ""}
# Preserve quoting here so a literal '<<' cannot start a heredoc. shlex removes it.
_HEREDOC_TOKENS = re.compile(
    r"\#[^\n]*|"
    r"""(?:[^\s;&|()<>'"\\]+|\\[\s\S]|'[^']*'|"(?:\\[\s\S]|[^"\\])*")+|"""
    r"<<-|[;&|()<>\n]+"
)


def parse_shell_commands(command: str) -> list[list[str]]:
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


def _shell_commands(tokens: list[tuple[str, bool]]) -> list[list[str]]:
    commands: list[list[str]] = []
    words: list[str] = []
    for token, separator in tokens:
        if separator:
            if words:
                commands.append(words)
                words = []
            commands.append([token.removesuffix("\n")])
        else:
            words.append(token)
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

    def update(self, success: set[Path], failure: set[Path]) -> None:
        if self.operator == "&&":
            failure |= self.failure
        elif self.operator == "||":
            success |= self.success
        self.success, self.failure = success, failure


def commands_with_cwd(command: str, *, cwd: Path) -> Iterator[tuple[Path, list[str]]]:
    """Track literal cd and subshell scopes; refuse directory inference beyond this grammar."""
    commands = [_current_shell_words(words) for words in parse_shell_commands(command)]
    _require_supported_cwd_commands(commands)
    state = _DirectoryState({cwd}, {cwd})
    scopes: list[_DirectoryState] = []
    for words in commands:
        operator = words[0]
        if words == ["("]:
            scopes.append(state)
            incoming = state.incoming()
            state = _DirectoryState(set(incoming), set(incoming))
        elif words == [")"]:
            if not scopes:
                raise NewFeatureError("cannot infer shell cwd: unmatched closing subshell")
            state = scopes.pop()
            incoming = state.incoming()
            state.update(set(incoming), set(incoming))
        elif len(words) == 1 and operator in _SHELL_SEPARATORS:
            state.operator = operator
        else:
            incoming = state.incoming()
            if operator == "cd":
                success = _cd_directories(words, incoming)
                state.update(success, set(incoming))
            else:
                for directory in sorted(incoming):
                    yield directory, words
                state.update(set(incoming), set(incoming))
            state.operator = ";"
    if scopes:
        raise NewFeatureError("cannot infer shell cwd: unclosed subshell")


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
        raise NewFeatureError("cannot infer shell cwd for cd with CDPATH or PWD overrides")
    return words[index:]


def _require_supported_cwd_commands(commands: list[list[str]]) -> None:
    if any(words[0] == "cd" for words in commands) and any(words in (["|"], ["&"]) for words in commands):
        raise NewFeatureError("cannot infer shell cwd for cd in a pipeline or background command")
    if any(words[0] in _CONTROL_WORDS for words in commands):
        raise NewFeatureError("cannot infer shell cwd through shell control flow; use simple commands")


def _cd_directories(words: list[str], directories: set[Path]) -> set[Path]:
    arguments = words[1:]
    if arguments[:1] == ["--"]:
        arguments = arguments[1:]
    if (
        len(arguments) != 1
        or arguments[0].startswith("-")
        or any(character in arguments[0] for character in "$`*?[")
    ):
        raise NewFeatureError("cannot infer shell cwd for nonliteral cd; use cd -- <literal-path>")
    target = Path(arguments[0]).expanduser()
    if os.environ.get("CDPATH") and not target.is_absolute() and not arguments[0].startswith(("./", "../")):
        raise NewFeatureError("cannot infer shell cwd for relative cd with CDPATH")
    # Shell cd uses logical parent paths; resolve() would follow symlinks before removing `..`
    candidates = {Path(os.path.abspath(directory / target)) for directory in directories}  # noqa: PTH100
    return {candidate for candidate in candidates if candidate.is_dir()}
