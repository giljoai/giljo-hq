# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.


import json
import uuid
from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock

import pytest

from giljo_mcp.models import Product
from giljo_mcp.services.product_service import ProductService
from tests.fixtures.base_fixtures import TestData


def _mock_ws():
    mock_ws = MagicMock()
    mock_ws.broadcast_to_tenant = AsyncMock()
    return mock_ws


@pytest.mark.asyncio
async def test_create_product_emits_product_created(db_session, db_manager):
    tenant_key = TestData.generate_tenant_key()
    mock_ws = _mock_ws()
    service = ProductService(db_manager, tenant_key=tenant_key, websocket_manager=mock_ws, test_session=db_session)

    product = await service.create_product(name="Live Wire")

    mock_ws.broadcast_to_tenant.assert_called_once()
    call_args = mock_ws.broadcast_to_tenant.call_args
    assert call_args.kwargs["tenant_key"] == tenant_key
    assert call_args.kwargs["event_type"] == "product:created"
    assert call_args.kwargs["data"]["product_id"] == str(product.id)
    assert call_args.kwargs["data"]["name"] == "Live Wire"


@pytest.mark.asyncio
async def test_update_product_emits_product_updated(db_session, db_manager):
    tenant_key = TestData.generate_tenant_key()
    product = Product(
        id=str(uuid.uuid4()),
        name="Original Name",
        tenant_key=tenant_key,
        is_active=False,
        created_at=datetime.now(UTC),
        updated_at=datetime.now(UTC),
    )
    db_session.add(product)
    await db_session.commit()

    mock_ws = _mock_ws()
    service = ProductService(db_manager, tenant_key=tenant_key, websocket_manager=mock_ws, test_session=db_session)

    await service.update_product(product.id, name="Renamed")

    mock_ws.broadcast_to_tenant.assert_called_once()
    call_args = mock_ws.broadcast_to_tenant.call_args
    assert call_args.kwargs["tenant_key"] == tenant_key
    assert call_args.kwargs["event_type"] == "product:updated"
    assert call_args.kwargs["data"]["product_id"] == str(product.id)
    assert call_args.kwargs["data"]["name"] == "Renamed"


@pytest.mark.asyncio
async def test_create_and_update_are_graceful_with_no_websocket_manager(db_session, db_manager):
    tenant_key = TestData.generate_tenant_key()
    service = ProductService(db_manager, tenant_key=tenant_key, websocket_manager=None, test_session=db_session)

    product = await service.create_product(name="No WS Manager")
    await service.update_product(product.id, name="Still fine")


@pytest.mark.asyncio
async def test_product_created_and_updated_payloads_stay_well_under_the_envelope_cap(db_session, db_manager):
    envelope_cap_bytes = 7999
    tenant_key = TestData.generate_tenant_key()
    mock_ws = _mock_ws()
    service = ProductService(db_manager, tenant_key=tenant_key, websocket_manager=mock_ws, test_session=db_session)

    product = await service.create_product(name="Cap Check")
    created_payload = mock_ws.broadcast_to_tenant.call_args.kwargs["data"]
    assert len(json.dumps(created_payload)) < envelope_cap_bytes

    mock_ws.broadcast_to_tenant.reset_mock()
    await service.update_product(product.id, name="Cap Check Renamed")
    updated_payload = mock_ws.broadcast_to_tenant.call_args.kwargs["data"]
    assert len(json.dumps(updated_payload)) < envelope_cap_bytes
