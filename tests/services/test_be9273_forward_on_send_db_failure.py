# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.


from __future__ import annotations

import logging
import random
import uuid
from datetime import UTC, datetime, timedelta
from unittest.mock import MagicMock

import pytest
from sqlalchemy import select
from sqlalchemy.exc import SQLAlchemyError

from giljo_mcp.database import DatabaseManager
from giljo_mcp.models.agent_identity import AgentExecution, AgentJob
from giljo_mcp.models.comm import CommThread
from giljo_mcp.models.products import Product
from giljo_mcp.models.projects import Project
from giljo_mcp.models.tasks import Message, MessageAcknowledgment, MessageRecipient
from giljo_mcp.services.message_routing_service import MessageRoutingService
from giljo_mcp.tenant import TenantManager
from tests.helpers.test_db_helper import purge_tenant_rows


pytestmark = pytest.mark.asyncio


def _routing_service(db_manager: DatabaseManager, tenant_key: str) -> MessageRoutingService:
    tenant_manager = MagicMock()
    tenant_manager.get_current_tenant.return_value = tenant_key
    return MessageRoutingService(
        db_manager=db_manager,
        tenant_manager=tenant_manager,
        websocket_manager=None,
        test_session=None,
    )


async def _seed(db_manager: DatabaseManager, tenant_key: str) -> tuple[str, str, str, str]:
    async with db_manager.get_session_async(tenant_key=tenant_key) as session:
        product = Product(
            id=str(uuid.uuid4()),
            tenant_key=tenant_key,
            name="BE-9273 forward-on-send DB-failure Product",
            description="forward-on-send DB failure",
            product_memory={},
        )
        session.add(product)
        await session.flush()

        project = Project(
            id=str(uuid.uuid4()),
            tenant_key=tenant_key,
            product_id=product.id,
            name="BE-9273 forward-on-send DB-failure Project",
            description="forward-on-send DB failure",
            mission="test",
            status="active",
            created_at=datetime.now(UTC),
            series_number=random.randint(1, 9000),
        )
        session.add(project)
        await session.flush()

        orch_job = AgentJob(
            job_id=str(uuid.uuid4()),
            tenant_key=tenant_key,
            project_id=project.id,
            job_type="orchestrator",
            mission="orchestrator mission",
            status="active",
        )
        session.add(orch_job)
        orchestrator = AgentExecution(
            agent_id=str(uuid.uuid4()),
            job_id=orch_job.job_id,
            tenant_key=tenant_key,
            agent_display_name="orchestrator",
            status="working",
            started_at=datetime.now(UTC) - timedelta(minutes=5),
            messages_sent_count=0,
            messages_waiting_count=0,
            messages_read_count=0,
        )
        session.add(orchestrator)

        dead_job = AgentJob(
            job_id=str(uuid.uuid4()),
            tenant_key=tenant_key,
            project_id=project.id,
            job_type="tester",
            mission="tester mission",
            status="active",
        )
        session.add(dead_job)
        dead = AgentExecution(
            agent_id=str(uuid.uuid4()),
            job_id=dead_job.job_id,
            tenant_key=tenant_key,
            agent_display_name="tester",
            status="closed",
            started_at=datetime.now(UTC) - timedelta(minutes=5),
            completed_at=datetime.now(UTC),
            messages_sent_count=0,
            messages_waiting_count=0,
            messages_read_count=0,
        )
        session.add(dead)
        await session.flush()

        thread = CommThread(
            id=str(uuid.uuid4()),
            tenant_key=tenant_key,
            serial=random.randint(1, 90000),
            subject="BE-9273 forward-on-send DB failure thread",
            status="open",
            project_id=project.id,
        )
        session.add(thread)
        await session.flush()

        msg = Message(
            tenant_key=tenant_key,
            project_id=project.id,
            thread_id=thread.id,
            from_agent_id="some-implementer",
            from_display_name="implementer",
            content="This must not vanish if the forward write fails.",
            status="pending",
            requires_action=True,
            created_at=datetime.now(UTC),
        )
        session.add(msg)
        await session.flush()
        session.add(MessageRecipient(message_id=msg.id, agent_id=dead.agent_id, tenant_key=tenant_key))
        await session.flush()

        project_id = project.id
        orchestrator_agent_id = orchestrator.agent_id
        dead_agent_id = dead.agent_id
        message_id = msg.id
        await session.commit()

    return project_id, orchestrator_agent_id, dead_agent_id, message_id


async def _purge_messages(db_manager: DatabaseManager, tenant_key: str) -> None:
    from sqlalchemy import delete

    async with db_manager.get_session_async(tenant_key=tenant_key) as session:
        await session.execute(delete(Message).where(Message.tenant_key == tenant_key))
        await session.execute(delete(CommThread).where(CommThread.tenant_key == tenant_key))
        await session.commit()


async def _is_acked(db_manager: DatabaseManager, tenant_key: str, message_id: str, agent_id: str) -> bool:
    async with db_manager.get_session_async(tenant_key=tenant_key) as session:
        row = (
            await session.execute(
                select(MessageAcknowledgment.id).where(
                    MessageAcknowledgment.tenant_key == tenant_key,
                    MessageAcknowledgment.message_id == message_id,
                    MessageAcknowledgment.agent_id == agent_id,
                )
            )
        ).scalar_one_or_none()
        return row is not None


async def _message_still_exists(db_manager: DatabaseManager, tenant_key: str, message_id: str) -> bool:
    async with db_manager.get_session_async(tenant_key=tenant_key) as session:
        row = (
            await session.execute(select(Message.id).where(Message.id == message_id, Message.tenant_key == tenant_key))
        ).scalar_one_or_none()
        return row is not None


async def test_db_failure_does_not_propagate_uncaught(db_manager, monkeypatch: pytest.MonkeyPatch) -> None:
    tenant_key = TenantManager.generate_tenant_key()
    try:
        _project_id, orchestrator_agent_id, dead_agent_id, message_id = await _seed(db_manager, tenant_key)
        routing_service = _routing_service(db_manager, tenant_key)

        async def _raise_db_error(*_args, **_kwargs):
            raise SQLAlchemyError("simulated forward-persist failure")

        monkeypatch.setattr(
            "giljo_mcp.services.message_routing_service.forward_action_required_to_orchestrator",
            _raise_db_error,
        )

        outcome = await routing_service.auto_block_for_thread_post(
            message_id=message_id,
            to_participant=dead_agent_id,
            sender_display_name="implementer",
            requires_action=True,
            tenant_key=tenant_key,
        )

        assert list(outcome) == []
        assert outcome.notice is not None, "the sender must be told the forward did not happen -- never left blank"
        assert "error" in outcome.notice.lower() or "failed" in outcome.notice.lower()

        assert not await _is_acked(db_manager, tenant_key, message_id, dead_agent_id)

        assert await _message_still_exists(db_manager, tenant_key, message_id)
        assert orchestrator_agent_id
    finally:
        await _purge_messages(db_manager, tenant_key)
        await purge_tenant_rows(db_manager, tenant_key)


async def test_db_failure_is_logged_with_message_id_and_destination(
    db_manager, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    tenant_key = TenantManager.generate_tenant_key()
    try:
        _project_id, orchestrator_agent_id, dead_agent_id, message_id = await _seed(db_manager, tenant_key)
        routing_service = _routing_service(db_manager, tenant_key)

        async def _raise_db_error(*_args, **_kwargs):
            raise SQLAlchemyError("simulated forward-persist failure")

        monkeypatch.setattr(
            "giljo_mcp.services.message_routing_service.forward_action_required_to_orchestrator",
            _raise_db_error,
        )

        with caplog.at_level(logging.ERROR, logger="giljo_mcp.services.message_routing_service"):
            await routing_service.auto_block_for_thread_post(
                message_id=message_id,
                to_participant=dead_agent_id,
                sender_display_name="implementer",
                requires_action=True,
                tenant_key=tenant_key,
            )

        matching = [
            r
            for r in caplog.records
            if "BE-9273" in r.getMessage() and "forward-on-send redirect raised" in r.getMessage()
        ]
        assert len(matching) == 1, (
            f"expected exactly one structured failure log line, got: {[r.getMessage() for r in caplog.records]}"
        )
        logged = matching[0].getMessage()
        assert message_id in logged, "log line must include the message id"
        assert orchestrator_agent_id in logged, "log line must include the intended destination (orchestrator agent_id)"
        assert dead_agent_id in logged, "log line must include the dead original recipient"
        assert matching[0].exc_info is not None
    finally:
        await _purge_messages(db_manager, tenant_key)
        await purge_tenant_rows(db_manager, tenant_key)
