# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.


import subprocess
import sys
import tomllib
from importlib import metadata
from pathlib import Path


PACKAGE_NAME = "giljo-mcp"


def _checkout_version(project_root: Path) -> str | None:
    try:
        with (project_root / "pyproject.toml").open("rb") as fh:
            return tomllib.load(fh)["project"]["version"]
    except (OSError, KeyError, tomllib.TOMLDecodeError):
        return None


def package_record_is_stale(project_root: Path) -> bool:
    wanted = _checkout_version(project_root)
    if wanted is None:
        return False
    try:
        return metadata.version(PACKAGE_NAME) != wanted
    except metadata.PackageNotFoundError:
        return False


def refresh_package_record(project_root: Path) -> bool:
    result = subprocess.run(
        [sys.executable, "-m", "pip", "install", "-e", str(project_root), "--no-deps", "--quiet"],
        capture_output=True,
        text=True,
        timeout=120,
        check=False,
    )
    return result.returncode == 0
