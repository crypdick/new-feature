#!/usr/bin/env python3
"""Reject pushes to main that do not change the project version."""

import os
import subprocess  # noqa: S404 - Git is the data source for this Git hook.
import sys
import tomllib

MAIN = "refs/heads/main"
NULL_SHA = "0" * 40


def version_at(commit: str) -> str:
    """Read project version from a commit."""
    data = subprocess.check_output(["git", "show", f"{commit}:pyproject.toml"])
    return str(tomllib.loads(data.decode())["project"]["version"])


def main() -> int:
    """Check the ref update exposed by prek's pre-push environment."""
    if os.environ.get("PRE_COMMIT_REMOTE_BRANCH") != MAIN:
        return 0
    local_sha = os.environ["PRE_COMMIT_TO_REF"]
    remote_sha = os.environ["PRE_COMMIT_FROM_REF"]
    if NULL_SHA in (local_sha, remote_sha) or version_at(local_sha) == version_at(remote_sha):
        print("Push blocked: bump version first with `uv version --bump patch`.", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
