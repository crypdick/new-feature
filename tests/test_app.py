from __future__ import annotations

import pytest

from new_feature.app import main


def test_main_delegates_to_cli_help() -> None:
    with pytest.raises(SystemExit) as exc_info:
        main(["--help"])

    assert exc_info.value.code == 0
