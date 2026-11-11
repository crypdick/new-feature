from __future__ import annotations

import os
import subprocess

import pytest

from new_feature.errors import NewFeatureError
from new_feature.rule_checker import should_block
from new_feature.shell_commands import commands_with_cwd
from tests.conftest import init_git_repo


@pytest.fixture
def checkouts(tmp_path):
    target, feature = tmp_path / "target", tmp_path / "feature"
    target.mkdir()
    init_git_repo(target)
    subprocess.run(["git", "worktree", "add", "-b", "feature", str(feature)], cwd=target, check=True)
    return target, feature


@pytest.mark.parametrize("directory_link", [False, True])
def test_content_write_follows_symlinks_into_protected_checkout(checkouts, directory_link):
    target, feature = checkouts
    link = feature / "link"
    link.symlink_to(target if directory_link else target / "README.md", target_is_directory=directory_link)
    path = link / "README.md" if directory_link else link
    assert should_block("target-branch", {"kind": "file_edit", "cwd": str(feature), "paths": [str(path)]})
    for command in (f"echo changed > {path}", f"tee {path}", f"touch {path}"):
        assert should_block("target-branch", {"kind": "shell", "cwd": str(feature), "command": command})
    assert (target / "README.md").read_text() == "# demo\n"


@pytest.mark.parametrize(
    "command", ["rm link", "mv link moved", "ln -sf elsewhere link", "sed -i s/demo/changed/ link"]
)
@pytest.mark.parametrize("directory_link", [False, True])
def test_entry_write_does_not_follow_final_symlink(checkouts, command, directory_link):
    target, feature = checkouts
    (feature / "link").symlink_to(
        target if directory_link else target / "README.md", target_is_directory=directory_link
    )
    blocked = should_block("target-branch", {"kind": "shell", "cwd": str(feature), "command": command})
    assert blocked == (directory_link and command.startswith("ln "))


@pytest.mark.parametrize(
    "command", ["rm link", "mv link moved", "ln -sf elsewhere link", "sed -i s/demo/changed/ link"]
)
def test_entry_write_protects_symlink_owned_by_target_checkout(checkouts, command):
    target, feature = checkouts
    (target / "link").symlink_to(feature / "README.md")
    assert should_block("target-branch", {"kind": "shell", "cwd": str(target), "command": command})


@pytest.mark.parametrize("group", ["(cd {feature} && true);", "((cd {feature}));", "(cd {feature}); (true);"])
def test_subshell_cd_does_not_escape_scope(checkouts, group):
    target, feature = checkouts
    prefix = group.format(feature=feature)
    event = {"kind": "shell", "cwd": str(target), "command": f"{prefix} git merge feature"}
    assert should_block("target-merge", event)
    event["command"] = f"{prefix} echo changed > README.md"
    assert should_block("target-branch", event)


@pytest.mark.parametrize("separator", [";", "||"])
def test_failed_cd_keeps_original_directory(checkouts, separator):
    target, _ = checkouts
    command = f"cd missing {separator} git merge feature"
    assert should_block("target-merge", {"kind": "shell", "cwd": str(target), "command": command})


def test_short_circuit_lists_preserve_possible_directories(checkouts):
    target, feature = checkouts
    event = {"kind": "shell", "cwd": str(target)}
    assert not should_block("target-merge", {**event, "command": f"cd {feature} && git merge main"})
    assert should_block("target-merge", {**event, "command": f"cd {feature} && true; git merge feature"})
    assert should_block("target-merge", {**event, "command": f"cd {feature} && false || git merge feature"})
    assert should_block("target-merge", {**event, "command": f"true || cd {feature} && git merge feature"})


@pytest.mark.parametrize(
    "command",
    [
        "cd -; git status",
        "cd; git status",
        "cd $W && git status",
        "cd feature | cat",
        "cd feature & git status",
        "if true; then git status; fi",
    ],
)
def test_unknown_directory_transitions_fail_explicitly(checkouts, command):
    target, _ = checkouts
    with pytest.raises(NewFeatureError, match="cannot infer shell cwd"):
        should_block("target-branch", {"kind": "shell", "cwd": str(target), "command": command})


def test_directory_scopes_match_supported_shell_behavior(checkouts):
    target, feature = checkouts
    command = f"cd {feature} && (cd {target} && git status); git status"
    reached = [(directory, words) for directory, words in commands_with_cwd(command, cwd=target)]
    assert (target, ["git", "status"]) in reached
    assert (feature, ["git", "status"]) in reached
    assert list(commands_with_cwd("git status | cat", cwd=target)) == [
        (target, ["git", "status"]),
        (target, ["cat"]),
    ]


@pytest.mark.parametrize("contents", [("first\n", "other\n"), ("text \n", "text  \n")])
def test_post_check_detects_changed_content_with_preserved_metadata(checkouts, contents):
    target, _ = checkouts
    readme = target / "README.md"
    readme.write_text(contents[0])
    before = readme.stat()
    event = {"kind": "shell", "cwd": str(target), "command": "python edit.py", "tool_use_id": "content"}
    assert not should_block("target-branch", event)
    readme.write_text(contents[1])
    os.utime(readme, ns=(before.st_atime_ns, before.st_mtime_ns))
    assert should_block("target-shell-changes", event)


def test_post_check_ignores_metadata_only_change(checkouts):
    target, _ = checkouts
    readme = target / "README.md"
    readme.write_text("dirty\n")
    event = {"kind": "shell", "cwd": str(target), "command": "python edit.py", "tool_use_id": "metadata"}
    assert not should_block("target-branch", event)
    before = readme.stat()
    os.utime(readme, ns=(before.st_atime_ns, before.st_mtime_ns + 1_000_000))
    assert not should_block("target-shell-changes", event)


@pytest.mark.parametrize("command", [") git status", "(git status"])
def test_unbalanced_subshell_fails_explicitly(checkouts, command):
    target, _ = checkouts
    with pytest.raises(NewFeatureError, match="cannot infer shell cwd"):
        list(commands_with_cwd(command, cwd=target))


@pytest.mark.parametrize("command", ["diff <(printf test) README.md", "printf test > >(cat)"])
def test_process_substitution_is_rejected_with_actionable_diagnostic(checkouts, command):
    target, _ = checkouts
    with pytest.raises(NewFeatureError, match="process substitution; use simple commands"):
        should_block("target-branch", {"kind": "shell", "cwd": str(target), "command": command})


def test_quoted_shell_operators_are_arguments(checkouts):
    target, _ = checkouts
    command = "echo '(' ')' '&&' ';' '||' '<(' '>('"
    assert list(commands_with_cwd(command, cwd=target)) == [
        (target, ["echo", "(", ")", "&&", ";", "||", "<(", ">("])
    ]


def test_snapshot_diff_failure_is_not_permission(checkouts, monkeypatch):
    from new_feature import hook_policy

    target, _ = checkouts
    (target / "README.md").write_text("dirty\n")
    original = hook_policy.subprocess.run

    def failing_diff(argv, **kwargs):
        if "--binary" in argv:
            return subprocess.CompletedProcess(argv, 1, "", "cannot read diff")
        return original(argv, **kwargs)

    monkeypatch.setattr(hook_policy.subprocess, "run", failing_diff)
    with pytest.raises(OSError, match="cannot fingerprint tracked changes"):
        should_block("target-branch", {"kind": "shell", "cwd": str(target), "command": "git status"})


def test_comments_are_not_commands(checkouts):
    target, _ = checkouts
    command = "echo '# not a comment'; # cd missing\ngit status"
    assert list(commands_with_cwd(command, cwd=target)) == [
        (target, ["echo", "# not a comment"]),
        (target, ["git", "status"]),
    ]


@pytest.mark.parametrize("command", ["mv README.md link", "ln -sf elsewhere link", "install README.md link"])
def test_directory_destination_follows_symlink(checkouts, command):
    target, feature = checkouts
    (feature / "link").symlink_to(target, target_is_directory=True)
    assert should_block("target-branch", {"kind": "shell", "cwd": str(feature), "command": command})


@pytest.mark.parametrize(
    "command",
    [
        "mv -T README.md link",
        "ln -sfT elsewhere link",
        "ln --no-dereference -sf elsewhere link",
        "install -T README.md link",
    ],
)
def test_no_directory_destination_replaces_link_itself(checkouts, command):
    target, feature = checkouts
    (feature / "link").symlink_to(target, target_is_directory=True)
    assert not should_block("target-branch", {"kind": "shell", "cwd": str(feature), "command": command})


def test_sed_explicit_symlink_following_protects_content(checkouts):
    target, feature = checkouts
    (feature / "link").symlink_to(target / "README.md")
    event = {"kind": "shell", "cwd": str(feature), "command": "sed --follow-symlinks -i s/demo/changed/ link"}
    assert should_block("target-branch", event)


def test_cd_preserves_logical_symlink_parent(checkouts):
    target, feature = checkouts
    (feature / "subdir").mkdir()
    (target / "link").symlink_to(feature / "subdir", target_is_directory=True)
    event = {"kind": "shell", "cwd": str(target), "command": "cd link/.. && git merge feature"}
    assert should_block("target-merge", event)
    event["command"] = "cd link && cd .. && git merge feature"
    assert should_block("target-merge", event)
    event["command"] = "cd link && git merge main"
    assert not should_block("target-merge", event)


@pytest.mark.parametrize(
    "prefix", ["command", "builtin", "X=1", "command -p", "builtin --", "X=1 command builtin"]
)
def test_current_shell_prefix_cd_changes_directory(checkouts, prefix):
    target, feature = checkouts
    event = {"kind": "shell", "cwd": str(feature), "command": f"{prefix} cd {target} && git merge feature"}
    assert should_block("target-merge", event)


@pytest.mark.parametrize("prefix", ["env", "sudo", "command -v", "command -V"])
def test_external_or_query_prefix_does_not_change_shell_directory(checkouts, prefix):
    target, feature = checkouts
    event = {"kind": "shell", "cwd": str(feature), "command": f"{prefix} cd {target}; git merge feature"}
    assert not should_block("target-merge", event)


@pytest.mark.parametrize("prefix", ["CDPATH=/elsewhere", "PWD=/elsewhere"])
def test_directory_environment_override_fails_explicitly(checkouts, prefix):
    target, _ = checkouts
    with pytest.raises(NewFeatureError, match="cannot infer shell cwd"):
        list(commands_with_cwd(f"{prefix} cd nested && git status", cwd=target))


def test_inherited_cdpath_is_not_guessed(checkouts, monkeypatch):
    target, _ = checkouts
    monkeypatch.setenv("CDPATH", "/elsewhere")
    with pytest.raises(NewFeatureError, match="cannot infer shell cwd"):
        list(commands_with_cwd("cd nested && git status", cwd=target))
    assert list(commands_with_cwd(f"cd {target} && git status", cwd=target)) == [(target, ["git", "status"])]
    assert list(commands_with_cwd("cd ./ && git status", cwd=target)) == [(target, ["git", "status"])]


@pytest.mark.parametrize("change", ["binary", "executable-mode", "symlink"])
def test_post_check_fingerprints_git_visible_content_and_type(checkouts, change):
    target, _ = checkouts
    readme = target / "README.md"
    if change == "binary":
        readme.write_bytes(b"first\x00\n")
    elif change == "symlink":
        readme.unlink()
        readme.symlink_to("first")
    else:
        readme.write_text("dirty\n")
    event = {"kind": "shell", "cwd": str(target), "command": "python edit.py", "tool_use_id": change}
    assert not should_block("target-branch", event)
    if change == "binary":
        readme.write_bytes(b"other\x00\n")
    elif change == "symlink":
        readme.unlink()
        readme.symlink_to("other")
    else:
        readme.chmod(0o755)
    assert should_block("target-shell-changes", event)


@pytest.mark.parametrize(
    "command",
    [
        "(cd {feature} && true); pwd -P",
        "cd missing; pwd -P",
        "cd link/.. && pwd -P",
        "cd link && cd .. && pwd -P",
        "command cd {feature} && pwd -P",
        "builtin cd {feature} && pwd -P",
        "X=1 cd {feature} && pwd -P",
        "cd {feature} && (cd {target} && pwd -P); pwd -P",
    ],
)
def test_inferred_directories_include_actual_bash_directories(checkouts, command):
    target, feature = checkouts
    (feature / "subdir").mkdir()
    (target / "link").symlink_to(feature / "subdir", target_is_directory=True)
    command = command.format(target=target, feature=feature)
    inferred = {
        str(directory.resolve())
        for directory, words in commands_with_cwd(command, cwd=target)
        if words == ["pwd", "-P"]
    }
    env = {key: value for key, value in os.environ.items() if key != "BASH_ENV"}
    result = subprocess.run(
        ["bash", "--noprofile", "--norc", "-c", command],
        cwd=target,
        env={**env, "CDPATH": ""},
        capture_output=True,
        text=True,
        check=True,
    )
    assert set(result.stdout.splitlines()) <= inferred
