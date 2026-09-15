# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.


import sys
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT))


def test_postgresql_discovery_min_version_is_16() -> None:
    from installer.shared.postgres import PostgreSQLDiscovery

    assert PostgreSQLDiscovery.MIN_VERSION == 16


def test_database_installer_min_pg_version_is_16() -> None:
    import installer.core.database as db_mod

    assert db_mod.DatabaseInstaller.MIN_PG_VERSION == 16


def test_validate_version_rejects_pg15() -> None:
    from installer.shared.postgres import PostgreSQLDiscovery

    result = PostgreSQLDiscovery().validate_version(15)
    assert result["compatible"] is False
    assert result["severity"] == "error"
    assert "16" in result["message"]


def test_validate_version_accepts_pg16() -> None:
    from installer.shared.postgres import PostgreSQLDiscovery

    result = PostgreSQLDiscovery().validate_version(16)
    assert result["compatible"] is True
    assert result["severity"] == "warning"


def test_validate_version_recommends_pg18() -> None:
    from installer.shared.postgres import PostgreSQLDiscovery

    result = PostgreSQLDiscovery().validate_version(18)
    assert result["compatible"] is True
    assert result["severity"] == "ok"
