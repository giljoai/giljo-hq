# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.


from __future__ import annotations

import json
import re
import shutil
import subprocess
from pathlib import Path

import pytest


REPO_ROOT = Path(__file__).resolve().parents[2]
INSTALL_SH = REPO_ROOT / "scripts" / "install.sh"
INSTALL_PS1 = REPO_ROOT / "scripts" / "install.ps1"
PACKAGE_JSON = REPO_ROOT / "frontend" / "package.json"


def _engines_floor() -> str:
    engines = json.loads(PACKAGE_JSON.read_text(encoding="utf-8"))["engines"]["node"]
    match = re.fullmatch(r">=\s*(\d+\.\d+\.\d+)", engines.strip())
    assert match, f"frontend/package.json engines.node is not a plain >=X.Y.Z floor: {engines!r}"
    return match.group(1)


def test_install_sh_floor_is_the_engines_floor():
    source = INSTALL_SH.read_text(encoding="utf-8")
    match = re.search(r'^MIN_NODE_VERSION="(\d+\.\d+\.\d+)"', source, re.MULTILINE)
    assert match, 'scripts/install.sh has no MIN_NODE_VERSION="X.Y.Z"'
    assert match.group(1) == _engines_floor()
    assert "MIN_NODE_MAJOR" not in source, "a major-only Node check is still present in install.sh"


def test_install_ps1_floor_is_the_engines_floor():
    source = INSTALL_PS1.read_text(encoding="utf-8")
    match = re.search(r'^\$script:MIN_NODE_VERSION\s*=\s*"(\d+\.\d+\.\d+)"', source, re.MULTILINE)
    assert match, 'scripts/install.ps1 has no $script:MIN_NODE_VERSION = "X.Y.Z"'
    assert match.group(1) == _engines_floor()
    assert "MIN_NODE_MAJOR" not in source, "a major-only Node check is still present in install.ps1"


def test_install_sh_downloads_the_floor_version():
    source = INSTALL_SH.read_text(encoding="utf-8")
    pins = re.findall(r'local node_ver="([^"]+)"', source)
    assert pins == ["v${MIN_NODE_VERSION}"], f"install.sh's Node download is not tied to the floor: {pins}"


def _bash_version_at_least() -> str:
    source = INSTALL_SH.read_text(encoding="utf-8")
    match = re.search(r"^version_at_least\(\) \{\n.*?^\}\n", source, re.DOTALL | re.MULTILINE)
    assert match, "version_at_least() not found in scripts/install.sh"
    return match.group(0)


CASES = [
    ("22.23.3", True),
    ("22.23.10", True),
    ("22.24.0", True),
    ("24.0.0", True),
    ("22.23.2", False),
    ("22.22.0", False),
    ("22.12.0", False),
    ("20.19.5", False),
]


@pytest.mark.skipif(shutil.which("bash") is None, reason="bash not available")
@pytest.mark.parametrize(("have", "ok"), CASES)
def test_install_sh_compares_the_full_version(have, ok):
    script = _bash_version_at_least() + f'version_at_least "{have}" "22.23.3"\n'
    result = subprocess.run(["bash", "-c", script], capture_output=True, text=True, timeout=30, check=False)
    assert (result.returncode == 0) is ok, result.stderr


def _ps_function() -> str:
    source = INSTALL_PS1.read_text(encoding="utf-8")
    match = re.search(r"^function Test-NodeVersionMeetsFloor \{\n.*?^\}\n", source, re.DOTALL | re.MULTILINE)
    assert match, "Test-NodeVersionMeetsFloor not found in scripts/install.ps1"
    return match.group(0)


@pytest.mark.skipif(shutil.which("pwsh") is None, reason="pwsh not available")
def test_install_ps1_compares_the_full_version():
    probes = ";".join(f'Write-Output (Test-NodeVersionMeetsFloor "v{have}")' for have, _ in CASES)
    script = (
        '$script:MIN_NODE_VERSION = "22.23.3"\n'
        + _ps_function()
        + probes
        + ';Write-Output (Test-NodeVersionMeetsFloor "not a version")'
    )
    result = subprocess.run(
        ["pwsh", "-NoProfile", "-NonInteractive", "-Command", script],
        capture_output=True,
        text=True,
        timeout=60,
        check=False,
    )
    assert result.returncode == 0, result.stderr
    assert result.stdout.split() == [str(ok) for _, ok in CASES] + ["False"]
