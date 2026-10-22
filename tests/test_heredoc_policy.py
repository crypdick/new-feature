from __future__ import annotations

import pytest

from new_feature.rule_checker import should_block
from tests.conftest import init_git_repo


@pytest.mark.parametrize("delimiter", ["'ENDNOTE'", '"ENDNOTE"', "ENDNOTE", r"\ENDNOTE"])
@pytest.mark.parametrize(
    "body",
    [
        "Use `sudoplz <command>`; never bypass approval.",
        "Don't edit this.",
        "git worktree add demo\ngit merge topic\nrm README.md",
    ],
)
def test_heredoc_prose_is_not_shell_code(tmp_path, delimiter, body):
    init_git_repo(tmp_path)
    command = f"obsidian-knowledge write wiki/note.md <<{delimiter}\n{body}\nENDNOTE\n"
    event = {"kind": "shell", "cwd": str(tmp_path), "command": command}
    for rule in ("target-branch", "target-merge", "worktree-add", "worktree-remove"):
        assert not should_block(rule, event)


@pytest.mark.parametrize(
    "command",
    [
        "cat <<'END' > README.md\nDon't parse this\nEND\n",
        "cat <<END\nx\nEND\ntouch README.md",
        "cat <<-END\n\trm ignored\n\tEND\ntouch README.md",
        "cat <<A <<'B'\nrm ignored\nA\nDon't parse this\nB\ntouch README.md",
        "cat <<'END'\nunmatched ' quote\nEND\ncat <<NEXT\nx\nNEXT\ntouch README.md",
    ],
)
def test_heredocs_preserve_real_writes(tmp_path, command):
    init_git_repo(tmp_path)
    assert should_block("target-branch", {"kind": "shell", "cwd": str(tmp_path), "command": command})


@pytest.mark.parametrize(
    "command",
    [
        "echo '<<' END\ntouch README.md",
        'echo "<<END"\ntouch README.md',
        "cat <<'-END'\n-END\ntouch README.md",
        "cat <<E'N'D\nDon't parse this\nEND\ntouch README.md",
        "cat <<''\nDon't parse this\n\ntouch README.md",
        "cat <<< 'text'\ntouch README.md",
        "echo 'multiline\ntext'\ntouch README.md",
        "echo continued \\\ntext\ntouch README.md",
    ],
)
def test_shell_quoting_preserves_following_writes(tmp_path, command):
    init_git_repo(tmp_path)
    assert should_block("target-branch", {"kind": "shell", "cwd": str(tmp_path), "command": command})


def test_multiple_vault_writes_with_reused_delimiter(tmp_path):
    init_git_repo(tmp_path)
    command = "\n".join(
        f"obsidian-knowledge write {path} --replace <<'ENDNOTE'\n{body}\nENDNOTE"
        for path, body in (
            ("wiki/host/memory/sudo.md", "Use `sudoplz <command>`; never bypass approval."),
            ("wiki/host/memory/MEMORY.md", "Ricardo's askpass calls use a password-only service."),
            ("Utility/obsidian-knowledge/changelog/session.md", "Updated host guidance → [[sudo]]."),
        )
    )
    assert not should_block("target-branch", {"kind": "shell", "cwd": str(tmp_path), "command": command})


@pytest.mark.parametrize(
    ("rule", "tail"),
    [
        ("target-merge", "git merge topic"),
        ("worktree-add", "git worktree add demo"),
        ("worktree-remove", "git worktree remove demo"),
    ],
)
def test_heredocs_preserve_following_git_guards(tmp_path, rule, tail):
    init_git_repo(tmp_path)
    command = f"cat <<'END'\nDon't parse this\nEND\n{tail}"
    assert should_block(rule, {"kind": "shell", "cwd": str(tmp_path), "command": command})
