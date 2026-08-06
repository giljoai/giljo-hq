# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.

"""INF-9321 — three installer gates that passed when they should have failed.

1. Post-winget verification accepted a Store stub
   ---------------------------------------------
   The prereq check learned to treat a Windows Store app-execution-alias
   (``...\\WindowsApps\\python.exe``) as "missing" so winget installs the real
   thing. The verification AFTER that install kept using the weaker
   ``Test-CommandExists``, which the very stub we routed around satisfies. A
   winget install that failed, or that landed python behind the stub on PATH,
   passed the gate and died later, further from the cause.

   The fix must NOT be applied to the ``winget`` probes themselves: winget ships
   as an MSIX whose launcher lives in WindowsApps, so ``Test-RealCommand
   "winget"`` is false on every machine that has it, and a blanket swap would
   abort the installer for everyone. Both directions are pinned below.

2. The committed launcher was never checked
   ----------------------------------------
   ``check_installer_integrity.py`` guarded the launcher heredoc INSIDE
   install.ps1 but not ``scripts/start-giljoai.bat``, which ships to users and
   had drifted to ``python -m api.run_api`` plus an unconditional ``pause`` --
   the exact shape that guard exists to forbid. It also cd'd to its own
   directory (``scripts/``), where there is no venv and no startup.py.

3. An unattended install could hang forever
   ----------------------------------------
   ``Confirm-UpdateAction`` prompts with ``Read-Host`` when it finds an existing
   install. Under ``GILJO_UNATTENDED=1`` there is no console to answer it, so an
   automated run against a non-clean target blocked until someone killed it.

Every check here is verified against a planted defect rather than trusted: the
integrity checks are run over a temporary tree containing the OLD broken
launcher and asserted to go red.
"""

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

# All three files are preserved into the CE export by export_ce.sh, so a CE
# checkout has them. Their absence is a rename, not a stripped tree.
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


# The launcher exactly as it was before this fix -- the planted defect every
# assertion below is measured against.
BROKEN_BAT = (
    '@echo off\ntitle Giljo HQ Server\ncd /d "%~dp0"\ncall venv\\Scripts\\activate.bat\npython -m api.run_api\npause\n'
)


# --- 1. Test-RealCommand, in both directions --------------------------------


def _final_verification_block() -> str:
    """The post-winget verification loop, isolated from the rest of install.ps1."""
    text = INSTALL_PS1.read_text(encoding="utf-8", errors="replace")
    # Anchored on the comment, not on 'foreach ($item in $wingetItems)': that
    # header appears TWICE (the install loop and this verification loop), and a
    # non-greedy match from the first one swallows everything in between --
    # including unrelated Test-CommandExists calls that have nothing to do with
    # this gate.
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
    """The gate the stub used to satisfy."""
    block = _final_verification_block()
    # Comments are stripped first: the comment above this loop explains why
    # Test-CommandExists is the WRONG helper here, and matching that text would
    # fail the fix for documenting itself.
    code = "\n".join(line for line in block.splitlines() if not line.strip().startswith("#"))

    assert "Test-RealCommand" in code, (
        "the post-winget verification uses the stub-blind Test-CommandExists again. A Windows "
        "Store app-execution-alias satisfies it, so a failed winget install reports success and "
        "the install dies later, further from the cause."
    )
    assert "Test-CommandExists" not in code, f"the verification loop still calls Test-CommandExists:\n{code}"


def test_test_real_command_rejects_windowsapps_and_test_command_exists_does_not():
    """The two helpers must stay DIFFERENT -- that difference is the whole fix."""
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
    """winget's own launcher is in WindowsApps -- probing it strictly aborts every install."""
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
    """Run the helper for real, rather than trusting a reading of its source.

    Uses winget as the live specimen: it is a genuine WindowsApps-backed command,
    so a correct Test-RealCommand reports it FALSE while Get-Command finds it. If
    winget is not installed, the discriminating pair cannot be formed and the
    static assertions above stand alone.
    """
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


# --- 2. the committed launcher, and the guard that now covers it ------------


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
    """A success-path pause parks a 'Press any key' window on a running server."""
    integrity = _load_integrity()
    text = STANDALONE_BAT.read_text(encoding="utf-8", errors="replace")
    assert integrity.find_unconditional_pause(text) == []
    # ...but it must still pause SOMEWHERE, or a double-clicked launcher that
    # fails flashes shut before the user can read the error.
    assert "pause" in text.lower(), "the launcher never pauses, so a double-click failure is invisible"


def test_pause_detector_sees_the_success_path_pause():
    """The detector itself, against the old launcher and against a guarded one."""
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
    """The gate, run end to end over a tree carrying the pre-fix launcher.

    Without this the new check could be vacuous -- passing because it looks at
    the wrong path, or because its patterns never match anything.
    """
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
    """The other side: the fixed launcher must actually satisfy the new gate."""
    result = subprocess.run(
        [sys.executable, str(INTEGRITY)],
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, "installer integrity checks fail on the current tree:\n" + result.stdout


# --- 3. the unattended prompt -----------------------------------------------


def test_existing_install_prompt_is_gated_on_unattended():
    text = INSTALL_PS1.read_text(encoding="utf-8", errors="replace")
    func = re.search(r"function Confirm-UpdateAction \{.*?\n\}", text, re.DOTALL)
    assert func, "Confirm-UpdateAction is gone from install.ps1"
    body = func.group(0)

    # The blocking STATEMENT, not the string "Read-Host" -- the comment
    # explaining this gate names it too, and matching that would compare the
    # gate's position against its own docs.
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
    """Neither silent overwrite nor a silent no-op: both are worse than stopping.

    Returning 'cancel' here would exit 0 with nothing installed, and the lab's
    artifact check would still find the OLD install's venv and config.yaml --
    a green run that installed nothing. Exit-WithError is what makes it loud.
    """
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
