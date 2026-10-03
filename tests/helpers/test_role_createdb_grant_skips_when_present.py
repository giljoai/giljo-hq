# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.


from __future__ import annotations

from typing import Any

import pytest

from tests.helpers.test_db_helper import APP_ROLES, PostgreSQLTestHelper


class _Result:
    def __init__(self, value: Any) -> None:
        self._value = value

    def scalar(self) -> Any:
        return self._value


class _RecordingConn:
    def __init__(self, rolcreatedb: bool | None) -> None:
        self.rolcreatedb = rolcreatedb
        self.statements: list[str] = []

    async def execute(self, statement: Any, params: dict | None = None) -> _Result:
        sql = str(statement)
        self.statements.append(sql)
        return _Result(self.rolcreatedb if "rolcreatedb" in sql else None)


def _alters(conn: _RecordingConn) -> list[str]:
    return [sql for sql in conn.statements if sql.startswith("ALTER ROLE")]


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("rolcreatedb", "expected_alters", "expected_grants"),
    [(True, 0, True), (False, len(APP_ROLES), True), (None, 0, False)],
    ids=["already_createdb", "lacks_createdb", "role_absent"],
)
async def test_createdb_is_granted_only_when_missing(rolcreatedb, expected_alters, expected_grants) -> None:
    conn = _RecordingConn(rolcreatedb)

    await PostgreSQLTestHelper._ensure_app_role_grants(conn, "giljo_mcp_test_gw0")

    assert len(_alters(conn)) == expected_alters
    assert any(sql.startswith("GRANT CONNECT") for sql in conn.statements) is expected_grants
