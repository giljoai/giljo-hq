# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.

"""TSK-9209 — the downloads package's ``__file__``-derived asset anchors must
resolve to the REPO ROOT, not to ``api/``.

Failing layer this regression-locks: ``api/endpoints/downloads.py`` computed
``installer/templates`` and ``logs`` by walking ``Path(__file__).parent`` three
levels up. Splitting the module into the ``api/endpoints/downloads/`` package
(IMP-9169 §3.1) put every submodule ONE LEVEL DEEPER, so an unadjusted walk lands
on ``api/installer/templates`` and ``api/logs`` -- neither of which exists.

Why this needs a test rather than a careful reading: the failure is SILENT.
Nothing raises. ``download_slash_commands`` guards its template reads with
``.exists()``, so a wrong anchor just skips them and ships a ZIP quietly missing
install.sh / install.ps1; the log endpoints simply 404 on a real log file. Route
tests, import tests and the app-surface lock all stay green.

The remaining five modules in the IMP-9169 extraction plan face the same trap, so
this pins the invariant rather than the incident.
"""

from __future__ import annotations

import io
import zipfile
from pathlib import Path

from fastapi import FastAPI
from fastapi.testclient import TestClient

from api.endpoints import downloads
from api.endpoints.downloads import bundles


REPO_ROOT = Path(__file__).resolve().parents[2]


def test_log_dir_anchor_resolves_to_repo_root():
    """``_LOG_DIR`` must point at <repo>/logs, not <repo>/api/logs."""
    assert downloads._LOG_DIR == REPO_ROOT / "logs", (
        f"_LOG_DIR resolved to {downloads._LOG_DIR}; the package sits one level "
        f"deeper than the old module, so the __file__ walk needs the extra .parent"
    )


def test_installer_templates_anchor_resolves_to_repo_root():
    """The installer/templates anchor used by the bundle routes must exist.

    Computed the same way the route bodies compute it -- from the DEFINING
    module's ``__file__`` -- so it tracks the real code rather than a copy of it.
    """
    anchor = Path(bundles.__file__).parent.parent.parent.parent / "installer" / "templates"

    assert anchor == REPO_ROOT / "installer" / "templates", f"installer/templates anchor resolved to {anchor}"
    assert anchor.is_dir(), (
        f"{anchor} does not exist -- the bundle routes would silently ship ZIPs without install scripts"
    )


def test_slash_commands_zip_still_carries_both_install_scripts():
    """Behavioral proof, because the structural check above can't catch a future
    route that stops using the shared anchor: a wrong anchor makes the .exists()
    guards fall through and the scripts vanish WITHOUT any error.
    """
    app = FastAPI()
    app.include_router(downloads.router)

    response = TestClient(app).get("/api/download/slash-commands.zip")
    assert response.status_code == 200

    with zipfile.ZipFile(io.BytesIO(response.content)) as archive:
        members = set(archive.namelist())

    assert "install.sh" in members, (
        f"install.sh missing from the ZIP -- installer/templates anchor is wrong. Members: {sorted(members)}"
    )
    assert "install.ps1" in members, (
        f"install.ps1 missing from the ZIP -- installer/templates anchor is wrong. Members: {sorted(members)}"
    )
