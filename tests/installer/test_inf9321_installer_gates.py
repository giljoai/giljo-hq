# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.


from __future__ import annotations

import importlib.util
import re
import shutil
import subprocess
import sys
from pathlib import Path

import pytest


REPO_ROOT = Path(__file__).resolve().parents[2]
INSTALL_PS1 = REPO_ROOT / "scripts" / "install.ps1"
STANDALONE_BAT = REPO_ROOT / "scripts" / "start-giljoai.bat"
INTEGRITY = REPO_ROOT / "scripts" / "check_installer_integrity.py"

assert INSTALL_PS1.exists() and STANDALONE_BAT.exists() and INTEGRITY.exists(), (
    "scripts/install.ps1, scripts/start-giljoai.bat or scripts/check_installer_integrity.py is "
    "missing. All three ship to CE via the export_ce.sh preserve list, so this is a rename or a "
    "move -- point this module at the new location rather than skipping."
)


def _load_integrity():
    spec = importlib.util.spec_from_file_location("giljo_check_installer_integrity", INTEGRITY)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


BROKEN_BAT = (
    '@echo off\ntitle Giljo HQ Server\ncd /d "%~dp0"\ncall venv\\Scripts\\activate.bat\npython -m api.run_api\npause\n'
)




def _final_verification_block() -> str:
    text = INSTALL_PS1.read_text(encoding="utf-8", errors="replace")
    match = re.search(r"# Final verification of winget-installed items.*?\n    \}", text, re.DOTALL)
    assert match, (
        "could not find the post-winget verification loop in install.ps1 (anchored on the "
        "'Final verification of winget-installed items' comment). If it moved, follow it; do not "
        "delete this test, which is the only thing pinning the stub-aware check."
    )
    block = match.group(0)
    assert "$wingetItems" in block, f"the anchored block is not the verification loop:\n{block}"
    return block


def test_post_winget_verification_rejects_a_store_stub():
    block = _final_verification_block()
    code = "\n".join(line for line in block.splitlines() if not line.strip().startswith("#"))

    assert "Test-RealCommand" in code, (
        "the post-winget verification uses the stub-blind Test-CommandExists again. A Windows "
        "Store app-execution-alias satisfies it, so a failed winget install reports success and "
        "the install dies later, further from the cause."
    )
    assert "Test-CommandExists" not in code, f"the verification loop still calls Test-CommandExists:\n{code}"


def test_test_real_command_rejects_windowsapps_and_test_command_exists_does_not():
    text = INSTALL_PS1.read_text(encoding="utf-8", errors="replace")

    real = re.search(r"function Test-RealCommand \{.*?\n\}", text, re.DOTALL)
    exists = re.search(r"function Test-CommandExists \{.*?\n\}", text, re.DOTALL)
    assert real and exists, "one of the two command-probe helpers is gone from install.ps1"

    assert "WindowsApps" in real.group(0), (
        "Test-RealCommand no longer rejects WindowsApps stubs, which is its entire purpose"
    )
    assert "WindowsApps" not in exists.group(0), (
        "Test-CommandExists now filters WindowsApps too. That looks like a tidy-up but it breaks "
        "the installer: winget itself lives in WindowsApps, so every winget probe would report "
        "missing and the install would abort on machines that have it."
    )


def test_winget_probes_still_use_the_stub_blind_check():
    text = INSTALL_PS1.read_text(encoding="utf-8", errors="replace")
    offenders = [line.strip() for line in text.splitlines() if "Test-RealCommand" in line and '"winget"' in line]
    assert not offenders, (
        "install.ps1 probes for winget with Test-RealCommand: " + "; ".join(offenders) + ". winget "
        "ships as an MSIX whose launcher lives in WindowsApps, so that check is false wherever "
        "winget is actually present, and the installer would abort with 'winget is required'."
    )


@pytest.mark.skipif(
    shutil.which("pwsh") is None and shutil.which("powershell") is None, reason="no PowerShell host available"
)
def test_test_real_command_behaviour_on_a_real_host():
    shell = shutil.which("pwsh") or shutil.which("powershell")
    source = INSTALL_PS1.read_text(encoding="utf-8", errors="replace")
    func = re.search(r"function Test-RealCommand \{.*?\n\}", source, re.DOTALL)
    assert func

    script = (
        func.group(0)
        + "\n"
        + "$c = Get-Command winget -ErrorAction SilentlyContinue\n"
        + "if (-not $c) { Write-Output 'NOWINGET'; exit 0 }\n"
        + "if ($c.Source -notlike '*\\WindowsApps\\*') { Write-Output 'NOTASTUB'; exit 0 }\n"
        + "if (Test-RealCommand 'winget') { Write-Output 'ACCEPTED' } else { Write-Output 'REJECTED' }\n"
    )
    result = subprocess.run(
        [shell, "-NoProfile", "-NonInteractive", "-Command", script],
        capture_output=True,
        text=True,
        check=False,
        timeout=120,
    )
    verdict = result.stdout.strip().splitlines()[-1] if result.stdout.strip() else ""
    if verdict in {"NOWINGET", "NOTASTUB"}:
        pytest.skip(reason=f"no WindowsApps-backed command available to test against ({verdict})")
    assert verdict == "REJECTED", (
        "Test-RealCommand accepted a real WindowsApps app-execution-alias, so the Store stub "
        f"still passes as an installed tool. stdout={result.stdout!r} stderr={result.stderr!r}"
    )




def test_committed_launcher_runs_the_canonical_entry_point():
    text = STANDALONE_BAT.read_text(encoding="utf-8", errors="replace")
    assert "python -m api.run_api" not in text
    assert "startup.py" in text
    assert re.search(r"venv[\\/]Scripts[\\/]python\.exe", text), (
        "the launcher calls a bare 'python'. On a fresh Windows the first python on PATH is the "
        "Store stub, which prints 'Python was not found' and opens the Store."
    )
    assert re.search(r'cd\s+/d\s+"%~dp0\.\.', text), (
        "the launcher does not cd out of scripts/. The venv and startup.py are one level up, so "
        "as written it cannot find either."
    )


def test_committed_launcher_pauses_only_on_failure():
    integrity = _load_integrity()
    text = STANDALONE_BAT.read_text(encoding="utf-8", errors="replace")
    assert integrity.find_unconditional_pause(text) == []
    assert "pause" in text.lower(), "the launcher never pauses, so a double-click failure is invisible"


def test_pause_detector_sees_the_success_path_pause():
    integrity = _load_integrity()

    assert integrity.find_unconditional_pause(BROKEN_BAT) == [6], (
        "the pause detector does not flag the unconditional pause in the old launcher"
    )
    guarded = "@echo off\nif errorlevel 1 (\n    echo failed\n    pause\n)\n"
    assert integrity.find_unconditional_pause(guarded) == [], (
        "the pause detector flags a pause that IS inside a failure branch, so it would reject the fix"
    )
    one_liner = "@echo off\nif errorlevel 1 pause\n"
    assert integrity.find_unconditional_pause(one_liner) == []
    nested = "@echo off\nif exist x (\n    if errorlevel 1 (\n        pause\n    )\n)\n"
    assert integrity.find_unconditional_pause(nested) == []


def test_integrity_check_goes_red_on_the_old_launcher(tmp_path: Path):
    scripts = tmp_path / "scripts"
    scripts.mkdir()
    shutil.copy(INTEGRITY, scripts / "check_installer_integrity.py")
    (scripts / "start-giljoai.bat").write_text(BROKEN_BAT, encoding="utf-8")

    result = subprocess.run(
        [sys.executable, str(scripts / "check_installer_integrity.py")],
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 1, (
        "the integrity check PASSED a tree containing the exact launcher this fix replaced:\n" + result.stdout
    )
    assert "start-giljoai.bat" in result.stdout
    assert "api.run_api" in result.stdout
    assert "pause" in result.stdout


def test_integrity_check_passes_the_real_repo():
    result = subprocess.run(
        [sys.executable, str(INTEGRITY)],
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, "installer integrity checks fail on the current tree:\n" + result.stdout




def test_existing_install_prompt_is_gated_on_unattended():
    text = INSTALL_PS1.read_text(encoding="utf-8", errors="replace")
    func = re.search(r"function Confirm-UpdateAction \{.*?\n\}", text, re.DOTALL)
    assert func, "Confirm-UpdateAction is gone from install.ps1"
    body = func.group(0)

    prompt = re.search(r"^\s*\$\w+\s*=\s*Read-Host\b", body, re.MULTILINE)
    assert prompt, "test is pinned to the wrong function -- no Read-Host assignment found in it"

    gate = body.find('$env:GILJO_UNATTENDED -eq "1"')
    assert gate != -1, (
        "Confirm-UpdateAction prompts with Read-Host and is not gated on GILJO_UNATTENDED, so an "
        "unattended install against a non-clean target blocks forever with nobody to answer."
    )
    assert gate < prompt.start(), (
        "the GILJO_UNATTENDED gate sits AFTER the Read-Host prompt, so the unattended run still "
        "blocks before it is ever reached."
    )


def test_unattended_existing_install_aborts_rather_than_guessing():
    text = INSTALL_PS1.read_text(encoding="utf-8", errors="replace")
    func = re.search(r"function Confirm-UpdateAction \{.*?\n\}", text, re.DOTALL)
    assert func
    parts = func.group(0).split('$env:GILJO_UNATTENDED -eq "1"', 1)
    assert len(parts) == 2, (
        "Confirm-UpdateAction has no GILJO_UNATTENDED branch at all, so an unattended install "
        "against a non-clean target blocks forever on the Read-Host prompt."
    )
    after_gate = parts[1]
    gated = re.split(r"^\s*\$\w+\s*=\s*Read-Host\b", after_gate, maxsplit=1, flags=re.MULTILINE)[0]

    assert "Exit-WithError" in gated, (
        "the unattended branch does not fail loudly. Returning 'update' would modify an install we "
        "were not asked to touch, 'reinstall' would destroy it, and 'cancel' would exit 0 having "
        "installed nothing while the previous install's artifacts still satisfy the lab's checks."
    )
    assert "-Update" in gated, "the abort message does not tell the caller how to proceed deliberately"
