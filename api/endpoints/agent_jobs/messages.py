# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.


import logging

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi import status as http_status

from giljo_mcp.auth.dependencies import get_current_active_user
from giljo_mcp.exceptions import ResourceNotFoundError
from giljo_mcp.models import User
from giljo_mcp.services.job_query_service import JobQueryService
from giljo_mcp.utils.log_sanitizer import sanitize

from .dependencies import get_job_query_service


logger = logging.getLogger(__name__)
router = APIRouter()


def _resolve_sender_display_name(from_agent: str, agent_lookup: dict[str, str]) -> str:
    if not from_agent:
        return "Unknown"

    if from_agent == "user":
        return "User"
    if from_agent == "system":
        return "System"

    if from_agent in agent_lookup:
        return agent_lookup[from_agent]

    if from_agent.lower() in ["orchestrator", "implementer", "analyzer", "tester", "reviewer", "documenter"]:
        return from_agent.capitalize()

    return from_agent


@router.get("/{job_id}/messages")
async def get_job_messages(
    job_id: str,
    limit: int = Query(50, ge=1, le=200, description="Maximum messages to retrieve (default 50, max 200)"),
    current_user: User = Depends(get_current_active_user),
    job_query_service: JobQueryService = Depends(get_job_query_service),
):
    """
    Get messages for an agent job (for MessageAuditModal).

    Returns messages where the agent is sender or recipient.
    All messages are filtered by tenant_key for multi-tenant isolation.

    Args:
        job_id: Agent job ID to retrieve messages for
        limit: Maximum messages to retrieve (default 50, max 200)
        current_user: Authenticated user (from dependency)
        job_query_service: Service for job queries (from dependency)

    Returns:
        Dictionary with job_id, agent_id, and messages list

    Raises:
        HTTPException 404: Job not found or access denied
        HTTPException 500: Failed to retrieve messages

    Example:
        GET /api/agent-jobs/{job_id}/messages?limit=100
    """
    logger.debug(
        "User %s retrieving messages for job %s (limit=%s)",
        sanitize(current_user.username),
        sanitize(job_id),
        sanitize(limit),
    )

    try:
        result = await job_query_service.get_job_messages(
            tenant_key=current_user.tenant_key,
            job_id=job_id,
            limit=limit,
        )
    except ResourceNotFoundError:
        logger.warning("Job %s not found for tenant %s", sanitize(job_id), sanitize(current_user.tenant_key))
        raise HTTPException(status_code=http_status.HTTP_404_NOT_FOUND, detail="Job not found") from None

    agent_id = result["agent_id"]
    agent_lookup = result["agent_lookup"]
    messages = result["messages"]

    logger.info(
        "Retrieved %d messages for job %s (agent_id=%s, tenant=%s)",
        len(messages),
        sanitize(job_id),
        agent_id,
        sanitize(current_user.tenant_key),
    )

    message_list = []
    for m in messages:
        raw_from_agent = m.from_agent_id or "unknown"
        resolved_from = _resolve_sender_display_name(raw_from_agent, agent_lookup)
        is_outbound = raw_from_agent == agent_id

        recipient_ids = [r.agent_id for r in m.recipients] if m.recipients else []
        to_agent_id = recipient_ids[0] if recipient_ids else None
        if m.message_type == "broadcast":
            resolved_to = "All Agents"
        elif to_agent_id and to_agent_id in agent_lookup:
            resolved_to = agent_lookup[to_agent_id]
        else:
            resolved_to = to_agent_id or "Unknown"

        message_list.append(
            {
                "id": str(m.id),
                "from": resolved_from,
                "from_agent": raw_from_agent,
                "from_agent_id": raw_from_agent if raw_from_agent in agent_lookup else None,
                "to_agents": recipient_ids,
                "to": resolved_to,
                "to_agent_id": to_agent_id,
                "content": m.content[:500] if m.content else "",
                "status": m.status,
                "created_at": m.created_at.isoformat(),
                "direction": "outbound" if is_outbound else "inbound",
                "message_type": m.message_type,
            }
        )

    return {
        "job_id": job_id,
        "agent_id": agent_id,
        "messages": message_list,
    }
