# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.


from __future__ import annotations

import importlib
from unittest.mock import AsyncMock, MagicMock

import pytest


def _reload_with_mode(monkeypatch, mode: str):
    monkeypatch.setenv("GILJO_MODE", mode)
    import api.app_state as app_state_module

    importlib.reload(app_state_module)
    import api.endpoints.setup_security as setup_security_module

    importlib.reload(setup_security_module)
    return setup_security_module


def _stub_session(total_users: int = 0, admin_users: int = 0):
    session = MagicMock()
    results = [
        MagicMock(scalar=MagicMock(return_value=total_users)),
        MagicMock(scalar=MagicMock(return_value=admin_users)),
    ]
    session.execute = AsyncMock(side_effect=results)
    return session


@pytest.mark.asyncio
async def test_saas_mode_exposes_sentry_dsn_and_environment(monkeypatch):
    monkeypatch.setenv("SENTRY_DSN_FRONTEND", "https://example/0")
    module = _reload_with_mode(monkeypatch, "saas")

    response = await module.get_setup_security_status(db=_stub_session())

    assert response["sentryDsn"] == "https://example/0"
    assert response["environment"] == "saas"


@pytest.mark.asyncio
async def test_ce_mode_returns_null_sentry_dsn(monkeypatch):
    monkeypatch.setenv("SENTRY_DSN_FRONTEND", "https://example/0")
    module = _reload_with_mode(monkeypatch, "ce")

    response = await module.get_setup_security_status(db=_stub_session())

    assert response["sentryDsn"] is None
    assert response["environment"] == "ce"


@pytest.mark.asyncio
async def test_saas_mode_without_dsn_returns_null(monkeypatch):
    monkeypatch.delenv("SENTRY_DSN_FRONTEND", raising=False)
    module = _reload_with_mode(monkeypatch, "saas")

    response = await module.get_setup_security_status(db=_stub_session())

    assert response["sentryDsn"] is None
    assert response["environment"] == "saas"


@pytest.mark.asyncio
async def test_unset_mode_defaults_to_ce_environment(monkeypatch):
    monkeypatch.delenv("GILJO_MODE", raising=False)
    monkeypatch.setenv("SENTRY_DSN_FRONTEND", "https://example/0")
    import api.app_state as app_state_module

    importlib.reload(app_state_module)
    import api.endpoints.setup_security as setup_security_module

    importlib.reload(setup_security_module)

    response = await setup_security_module.get_setup_security_status(db=_stub_session())

    assert response["sentryDsn"] is None
    assert response["environment"] == "ce"
