from __future__ import annotations

import pytest

from new_feature.errors import NewFeatureError
from new_feature.hook_install import ensure_runner


def executable(path, body):
    path.write_text("#!/bin/sh\n" + body)
    path.chmod(0o755)


@pytest.mark.parametrize("version", [None, "0.3.3", "0.4.0"])
def test_runner_is_upgraded_before_registration(tmp_path, monkeypatch, version):
    monkeypatch.setenv("PATH", str(tmp_path))
    log = tmp_path / "calls"
    monkeypatch.setenv("CALL_LOG", str(log))
    runner = tmp_path / "i-insist"
    if version:
        executable(
            runner,
            f'if [ "$1" = "--version" ]; then echo "i-insist {version}"; else echo ensure >> "$CALL_LOG"; fi\n',
        )
    executable(tmp_path / "uv", 'printf "%s\\n" "$*" >> "$CALL_LOG"\n')
    # The bootstrap stub need only create a usable runner for the missing case.
    if version is None:
        monkeypatch.setenv("RUNNER_BIN", str(runner))
        executable(
            tmp_path / "uv",
            """printf '%s\\n' "$*" >> "$CALL_LOG"
printf '#!/bin/sh\\necho ensure >> "$CALL_LOG"\\n' > "$RUNNER_BIN"
/bin/chmod +x "$RUNNER_BIN"
""",
        )
    ensure_runner()
    expected = ["ensure"] if version == "0.4.0" else ["tool install --upgrade i-insist>=0.4.0", "ensure"]
    assert log.read_text().splitlines() == expected


def test_disabled_runner_aborts_migration(tmp_path, monkeypatch):
    monkeypatch.setenv("PATH", str(tmp_path))
    executable(
        tmp_path / "i-insist", 'if [ "$1" = "--version" ]; then echo "i-insist 0.4.0"; else exit 2; fi\n'
    )
    with pytest.raises(NewFeatureError, match="enable its hooks"):
        ensure_runner()
