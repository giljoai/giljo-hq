# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.


from __future__ import annotations

import re
import subprocess
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[2]

_DUMP_SUFFIXES = (".dump", ".backup", ".pgdump")

_URL_CRED_RE = re.compile(r"(?i)\b(?:postgres|postgresql|mysql|mongodb|redis|amqp)://[^\s:@/]+:[^\s@/{<>]{12,}@[^\s/]+")

_PGPASSWORD_RE = re.compile(r"""PGPASSWORD\s*=\s*["']?(?P<val>[^"'\s]+)""")
_PGPASSWORD_SAFE_PREFIXES = ("$", "{", "%", "<")
_PGPASSWORD_PLACEHOLDERS = ("your", "xxx", "changeme", "example", "placeholder", "redacted")

_SCRIPT_PREFIXES = ("scripts/", "internal/")
_SCRIPT_SUFFIXES = (".sh", ".ps1", ".bat")


def _tracked_files() -> list[str]:
    out = subprocess.run(["git", "ls-files"], cwd=REPO_ROOT, check=True, capture_output=True, text=True)
    return out.stdout.splitlines()


def test_dotenv_is_not_tracked() -> None:
    tracked = set(_tracked_files())
    assert ".env" not in tracked, (
        ".env is tracked in git -- it holds live DB credentials. Untrack it "
        "(`git rm --cached .env`); only .env.example (placeholders) may be tracked."
    )


def test_backups_dir_has_no_tracked_files() -> None:
    offenders = [p for p in _tracked_files() if p.startswith("backups/")]
    assert not offenders, (
        f"{len(offenders)} file(s) tracked under backups/ -- this is the exact "
        f"SEC-3001b incident (committed pg_dump snapshots carrying live creds). "
        f"Untrack them:\n  " + "\n  ".join(offenders[:20])
    )


def test_no_database_dump_tracked_anywhere() -> None:
    offenders = [p for p in _tracked_files() if p.lower().endswith(_DUMP_SUFFIXES)]
    assert not offenders, (
        f"{len(offenders)} pg_dump data dump(s) tracked "
        f"(SEC-3001b leak class). Untrack them (git rm --cached):\n  " + "\n  ".join(offenders[:20])
    )


def test_no_inline_db_credential_in_tracked_scripts() -> None:
    candidates = [
        p
        for p in _tracked_files()
        if p.startswith(_SCRIPT_PREFIXES) and p.endswith(_SCRIPT_SUFFIXES) and "/tests/" not in p and "/test_" not in p
    ]

    findings: list[str] = []
    for rel in candidates:
        path = REPO_ROOT / rel
        try:
            text = path.read_text(encoding="utf-8", errors="ignore")
        except OSError:
            continue

        for lineno, line in enumerate(text.splitlines(), start=1):
            if _URL_CRED_RE.search(line):
                findings.append(f"{rel}:{lineno}: inline credential in connection URL")

            m = _PGPASSWORD_RE.search(line)
            if m:
                val = m.group("val")
                low = val.lower()
                is_var = val.startswith(_PGPASSWORD_SAFE_PREFIXES)
                is_placeholder = any(low.startswith(ph) for ph in _PGPASSWORD_PLACEHOLDERS)
                if not is_var and not is_placeholder:
                    findings.append(f"{rel}:{lineno}: literal PGPASSWORD assignment")

    assert not findings, (
        "Inline DB credential(s) found in tracked operator scripts (SEC-3001b). "
        "Pass the password via PGPASSWORD env var / .pgpass instead:\n  " + "\n  ".join(findings[:20])
    )
