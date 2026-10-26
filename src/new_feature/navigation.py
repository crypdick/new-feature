"""Print exact worktree paths and shell completion for managed features."""

from __future__ import annotations

import sys
from pathlib import Path  # noqa: TC003 - beartype requires annotation types at runtime

from new_feature.control_checkout import require_managed_worktree
from new_feature.errors import NewFeatureError
from new_feature.manifest import load_manifest
from new_feature.slug import feature_key, slugify

_COMMANDS = "create setup merge exec teardown list status doctor path prune changes completion install-rules"
_FEATURE_COMMANDS = "create merge exec teardown path changes"

_BASH_COMPLETION = r"""_new_feature() {
    local current="${COMP_WORDS[COMP_CWORD]}"
    COMPREPLY=()
    if (( COMP_CWORD == 1 )); then
        mapfile -t COMPREPLY < <(compgen -W '@COMMANDS@' -- "$current")
    elif (( COMP_CWORD == 2 )); then
        case "${COMP_WORDS[1]}" in
            create|merge|exec|teardown|path|changes)
                mapfile -t COMPREPLY < <(compgen -W "$(new-feature completion --features 2>/dev/null)" -- "$current")
                ;;
            completion)
                mapfile -t COMPREPLY < <(compgen -W 'bash zsh fish' -- "$current")
                ;;
        esac
    fi
}
complete -F _new_feature new-feature
"""

_ZSH_COMPLETION = r"""_new_feature() {
    if (( CURRENT == 2 )); then
        compadd -- @COMMANDS@
    elif (( CURRENT == 3 )); then
        case "$words[2]" in
            create|merge|exec|teardown|path|changes)
                local -a features
                features=("${(@f)$(new-feature completion --features 2>/dev/null)}")
                compadd -- "${features[@]}"
                ;;
            completion) compadd -- bash zsh fish ;;
        esac
    fi
}
compdef _new_feature new-feature
"""

_FISH_COMPLETION = r"""
complete -c new-feature -f
complete -c new-feature -n '__fish_use_subcommand' -a '@COMMANDS@'
complete -c new-feature -n '__fish_seen_subcommand_from @FEATURE_COMMANDS@; and test (count (commandline -opc)) -eq 2' -a '(new-feature completion --features 2>/dev/null)'
complete -c new-feature -n '__fish_seen_subcommand_from completion' -a 'bash zsh fish'
"""


def print_feature_path(root: Path, name: str) -> int:
    """Print one absolute path, requiring its recorded checkout and branch to exist."""
    record = load_manifest(root).features.get(feature_key(slugify(name)))
    if record is None:
        raise NewFeatureError(f"unknown feature: {name}")
    # NOTE: README.md documents exact normalized names and live checkout verification.
    worktree = require_managed_worktree(root, root / record.worktree, record.branch)
    sys.stdout.write(f"{worktree}\n")
    return 0


def print_feature_completions(root: Path) -> int:
    """Print sorted managed slugs without mutating repository state."""
    for slug in sorted(record.slug for record in load_manifest(root).features.values()):
        sys.stdout.write(f"{slug}\n")
    return 0


def print_shell_completion(shell: str) -> int:
    """Print shell code that queries managed feature names at completion time."""
    scripts = {"bash": _BASH_COMPLETION, "zsh": _ZSH_COMPLETION, "fish": _FISH_COMPLETION}
    if shell not in scripts:
        raise NewFeatureError(f"unsupported completion shell: {shell}")
    sys.stdout.write(
        scripts[shell].replace("@COMMANDS@", _COMMANDS).replace("@FEATURE_COMMANDS@", _FEATURE_COMMANDS)
    )
    return 0
