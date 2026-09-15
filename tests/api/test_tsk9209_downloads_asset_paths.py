# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.


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
    assert downloads._LOG_DIR == REPO_ROOT / "logs", (
        f"_LOG_DIR resolved to {downloads._LOG_DIR}; the package sits one level "
        f"deeper than the old module, so the __file__ walk needs the extra .parent"
    )


def test_installer_templates_anchor_resolves_to_repo_root():
    anchor = Path(bundles.__file__).parent.parent.parent.parent / "installer" / "templates"

    assert anchor == REPO_ROOT / "installer" / "templates", f"installer/templates anchor resolved to {anchor}"
    assert anchor.is_dir(), (
        f"{anchor} does not exist -- the bundle routes would silently ship ZIPs without install scripts"
    )


def test_slash_commands_zip_still_carries_both_install_scripts():
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
