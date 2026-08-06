# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.

"""Regression test for module-import side effects in `api/`.

Closes seq 100 (load_dotenv at module scope) and seq 97
(api/__init__.py import-time DATABASE_URL mutation) from
the ACTION_REQUIRED audit.

Importing `api` and `api.app` MUST NOT mutate `os.environ` or read any
`.env` file. All such side effects belong in the FastAPI lifespan.
"""

from __future__ import annotations

import subprocess
import sys
import textwrap
from pathlib import Path


_PROJECT_ROOT = Path(__file__).resolve().parents[3]


def _run_in_subprocess(script: str) -> subprocess.CompletedProcess[str]:
    """Run a Python snippet in a fresh interpreter rooted at the project.

    Reimport-in-process pollutes SQLAlchemy metadata and module-level state
    that downstream unit tests depend on; subprocess isolation is the only
    way to observe import-time side effects without breaking the rest of the
    suite.
    """
    return subprocess.run(  # noqa: S603 -- controlled inputs, no shell
        [sys.executable, "-c", textwrap.dedent(script)],
        cwd=str(_PROJECT_ROOT),
        capture_output=True,
        text=True,
        timeout=60,
        check=False,
    )


def test_importing_api_does_not_mutate_os_environ() -> None:
    """`import api` and `import api.app` must leave os.environ untouched."""
    script = """
        import json
        import os
        import sys

        sys.path.insert(0, ".")
        before = dict(os.environ)

        import api  # noqa: F401
        import api.app  # noqa: F401

        after = dict(os.environ)
        added = {k: after[k] for k in after if k not in before}
        changed = {k: (before[k], after[k]) for k in before if k in after and before[k] != after[k]}
        removed = [k for k in before if k not in after]
        print("MUTATIONS=" + json.dumps({"added": added, "changed": changed, "removed": removed}))
    """
    result = _run_in_subprocess(script)
    assert result.returncode == 0, f"subprocess failed:\nstdout={result.stdout}\nstderr={result.stderr}"
    marker = next(line for line in result.stdout.splitlines() if line.startswith("MUTATIONS="))
    import json

    diff = json.loads(marker[len("MUTATIONS=") :])
    assert diff == {"added": {}, "changed": {}, "removed": []}, (
        f"Importing api / api.app mutated os.environ: {diff}. "
        "Move side effects (load_dotenv, environ assignment) into the FastAPI lifespan."
    )


def test_importing_api_does_not_call_load_dotenv() -> None:
    """No dotenv entry point may be invoked during import of api / api.app."""
    script = """
        import sys
        from unittest.mock import MagicMock

        sys.path.insert(0, ".")

        import dotenv
        import dotenv.main

        sentinel = MagicMock()
        dotenv.load_dotenv = sentinel
        dotenv.main.load_dotenv = sentinel

        import api  # noqa: F401
        import api.app  # noqa: F401

        print("DOTENV_CALLS=" + str(sentinel.call_count))
    """
    result = _run_in_subprocess(script)
    assert result.returncode == 0, f"subprocess failed:\nstdout={result.stdout}\nstderr={result.stderr}"
    marker = next(line for line in result.stdout.splitlines() if line.startswith("DOTENV_CALLS="))
    call_count = int(marker[len("DOTENV_CALLS=") :])
    assert call_count == 0, (
        f"load_dotenv was invoked {call_count} time(s) during api import. "
        "Relocate it into the FastAPI lifespan startup phase."
    )
