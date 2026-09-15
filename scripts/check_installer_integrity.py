#!/usr/bin/env python3

# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.


from __future__ import annotations

import re
import sys
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parent.parent

INSTALLER_SCRIPTS = [
    REPO_ROOT / "scripts" / "install.ps1",
    REPO_ROOT / "scripts" / "install.sh",
]

INSTALL_PS1 = REPO_ROOT / "scripts" / "install.ps1"
INSTALL_SH = REPO_ROOT / "scripts" / "install.sh"
STARTUP_PY = REPO_ROOT / "startup.py"
STANDALONE_BAT = REPO_ROOT / "scripts" / "start-giljoai.bat"

UTF8_BOM = b"\xef\xbb\xbf"


def check_no_bom() -> list[str]:
    failures: list[str] = []
    for path in INSTALLER_SCRIPTS:
        if not path.exists():
            continue
        head = path.read_bytes()[:3]
        if head == UTF8_BOM:
            failures.append(
                f"{path.relative_to(REPO_ROOT)}: starts with UTF-8 BOM. "
                f"Re-save as UTF-8 without BOM, or run: "
                f"python -c \"p=open(r'{path}','rb');d=p.read();p.close();"
                f"open(r'{path}','wb').write(d[3:] if d[:3]==b'\\xef\\xbb\\xbf' else d)\""
            )
    return failures


def check_bat_entry_point() -> list[str]:
    failures: list[str] = []
    if not INSTALL_PS1.exists():
        return failures
    text = INSTALL_PS1.read_text(encoding="utf-8", errors="replace")
    if "start-giljoai.bat" not in text:
        return failures
    if "python -m api.run_api" in text:
        failures.append(
            "install.ps1: start-giljoai.bat heredoc invokes "
            "'python -m api.run_api'. It MUST invoke 'python startup.py "
            "--verbose' so the desktop shortcut runs the canonical entry "
            "point (frontend launch, browser auto-open, migrations)."
        )
    if "python startup.py" not in text:
        failures.append(
            "install.ps1: start-giljoai.bat heredoc does not "
            "invoke 'python startup.py'. The launcher and the post-install "
            "text instruction must run the same canonical entry point."
        )
    return failures


def find_unconditional_pause(bat_text: str) -> list[int]:
    depth = 0
    offenders: list[int] = []

    for line_no, raw in enumerate(bat_text.splitlines(), start=1):
        line = raw.strip()
        lowered = line.lower()
        if not line or lowered.startswith(("rem ", "::", "@rem ")):
            continue

        if line.startswith(")"):
            if not line.endswith("("):
                depth = max(0, depth - 1)
            continue

        if re.match(r"^@?(if|for)\b", lowered) and line.endswith("("):
            depth += 1
            continue

        if re.match(r"^@?pause\b", lowered) and depth == 0:
            offenders.append(line_no)

    return offenders


def check_standalone_bat() -> list[str]:
    failures: list[str] = []
    if not STANDALONE_BAT.exists():
        return failures
    text = STANDALONE_BAT.read_text(encoding="utf-8", errors="replace")

    if "python -m api.run_api" in text:
        failures.append(
            "scripts/start-giljoai.bat: invokes 'python -m api.run_api'. It MUST "
            "invoke 'startup.py' so the launcher runs the canonical entry point "
            "(frontend launch, browser auto-open, migrations), matching the "
            "launcher install.ps1 writes."
        )
    if "startup.py" not in text:
        failures.append(
            "scripts/start-giljoai.bat: does not invoke 'startup.py'. The "
            "committed launcher and the one install.ps1 writes must run the "
            "same canonical entry point."
        )
    if not re.search(r'cd\s+/d\s+"%~dp0\.\.', text):
        failures.append(
            'scripts/start-giljoai.bat: does not cd to the parent of scripts/ '
            '(expected: cd /d "%~dp0.."). The venv and startup.py live in the '
            "repository root, so a launcher that stays in scripts/ cannot find "
            "either of them."
        )
    if not re.search(r"venv[\\/]Scripts[\\/]python\.exe", text):
        failures.append(
            "scripts/start-giljoai.bat: does not launch via "
            r"'venv\Scripts\python.exe'. Calling a bare 'python' runs whatever "
            "is first on PATH -- on a fresh Windows that is the Store stub, "
            "which prints 'Python was not found' and opens the Store."
        )

    unconditional = find_unconditional_pause(text)
    if unconditional:
        lines = ", ".join(str(n) for n in unconditional)
        failures.append(
            f"scripts/start-giljoai.bat:{lines}: 'pause' runs unconditionally, so "
            "it also fires on the SUCCESS path and leaves a 'Press any key' "
            "window sitting on top of a running server. Pause only inside a "
            "failure branch (see the errorlevel block), so a double-clicked "
            "launcher still shows its error instead of flashing shut."
        )

    return failures


def check_startup_import_order() -> list[str]:
    failures: list[str] = []
    if not STARTUP_PY.exists():
        return failures
    lines = STARTUP_PY.read_text(encoding="utf-8").splitlines()

    guard_line = None
    third_party_lines: list[tuple[int, str]] = []

    for idx, line in enumerate(lines, start=1):
        stripped = line.strip()
        if stripped.startswith("#") or not stripped:
            continue
        if "ensure_project_virtualenv()" in stripped and not stripped.startswith("def "):
            guard_line = idx
        if stripped.startswith(("import click", "from click")):
            third_party_lines.append((idx, stripped))
        if stripped.startswith(("import colorama", "from colorama")):
            third_party_lines.append((idx, stripped))

    if guard_line is None:
        failures.append(
            "startup.py: ensure_project_virtualenv() invocation not found. "
            "The venv relaunch guard must be called at module level before "
            "any third-party imports."
        )
        return failures

    for line_no, code in third_party_lines:
        if line_no < guard_line:
            failures.append(
                f"startup.py:{line_no}: '{code}' is imported BEFORE "
                f"ensure_project_virtualenv() (line {guard_line}). Fresh-shell "
                f"installs without an activated venv will crash with "
                f"ModuleNotFoundError before the relaunch guard can fire. "
                f"Move this import below the guard."
            )

    return failures


def check_staging_inside_target() -> list[str]:
    failures: list[str] = []

    if INSTALL_SH.exists():
        sh_text = INSTALL_SH.read_text(encoding="utf-8", errors="replace")
        if not re.search(r'staging_dir\s*=\s*"\$\{target_dir\}/', sh_text):
            failures.append(
                "install.sh: atomic-extract staging_dir is not created INSIDE "
                '${target_dir} (expected staging_dir="${target_dir}/.giljo-staging-$$"). '
                "A sibling \"${target_dir}.new\" crashes the default $HOME install "
                "with a permission error in the root-owned parent (INF-9102). "
                "Stage as a hidden child of target_dir."
            )

    if INSTALL_PS1.exists():
        ps1_text = INSTALL_PS1.read_text(encoding="utf-8", errors="replace")
        if not re.search(r"stagingDir\s*=\s*Join-Path\s+\$TargetDir", ps1_text):
            failures.append(
                "install.ps1: atomic-extract $stagingDir is not created INSIDE "
                '$TargetDir (expected $stagingDir = Join-Path $TargetDir ".giljo-staging-$PID"). '
                'A sibling "$TargetDir.new" crashes the default $HOME install '
                "with a permission error in the admin-owned parent (INF-9102). "
                "Stage as a hidden child of $TargetDir."
            )

    return failures


def check_no_errexit_fatal_shopt() -> list[str]:
    failures: list[str] = []
    if not INSTALL_SH.exists():
        return failures
    sh_text = INSTALL_SH.read_text(encoding="utf-8", errors="replace")

    for m in re.finditer(r"\$\((?P<body>[^()]*\bshopt\s+-p\b[^()]*)\)", sh_text):
        body = m.group("body")
        if "|| true" in body or "|| :" in body:
            continue
        line_no = sh_text.count("\n", 0, m.start()) + 1
        failures.append(
            f"install.sh:{line_no}: `$({body.strip()})` captures `shopt -p` in a "
            "bare command substitution. `shopt -p <opt>` exits 1 when the option "
            "is unset, so under `set -euo pipefail` this silently kills the "
            "installer at file-install (INF-9106). Append `|| true` inside the "
            "substitution (or wrap the capture in `set +e`/`set -e`)."
        )

    return failures


def main() -> int:
    all_failures: list[str] = []
    all_failures += check_no_bom()
    all_failures += check_bat_entry_point()
    all_failures += check_standalone_bat()
    all_failures += check_startup_import_order()
    all_failures += check_staging_inside_target()
    all_failures += check_no_errexit_fatal_shopt()

    if not all_failures:
        print("[OK] Installer integrity checks passed.")
        return 0

    print("[FAIL] Installer integrity checks failed:\n")
    for failure in all_failures:
        print(f"  - {failure}\n")
    return 1


if __name__ == "__main__":
    sys.exit(main())
