# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.

"""Message + user-approval domain tools mixin for ToolAccessor (BE-6042a split)."""

from __future__ import annotations

from typing import Any

from giljo_mcp.exceptions import ResourceNotFoundError, ValidationError


class MessageToolsMixin:
    """User-approval adapter tools. Composed into ToolAccessor.

    BE-6118: the pure send_message / receive_messages / get_messages pass-throughs
    were deleted here (``_call_tool`` dispatched them straight to
    MessageRoutingService / MessageService via ``TOOL_DISPATCH``). BE-9012d then
    hard-removed those 3 tools + MessageService entirely (bus retirement).
    ``request_approval`` — which validates input through ``RequestApprovalInput``
    before the service call — stays.

    BE-9499d added ``decide_approval``: the harness-side door that clears
    ``awaiting_user``. It validates through ``DecideApprovalInput`` and calls the
    SAME ``UserApprovalService.mark_decided`` the REST ``/decide`` endpoint
    (api/endpoints/approvals.py) and the dormant MRTR elicitation round-2 path
    (api/endpoints/mcp_tools/_inline_approval.py) already use — one writer, three
    doors.
    """

    # User Approval Tools (BE-5029)

    async def request_approval(
        self,
        job_id: str,
        project_id: str,
        reason: str,
        options: list[dict],
        context: dict | None = None,
        tenant_key: str | None = None,
    ) -> dict[str, Any]:
        """Create a pending user approval and flip the calling agent to awaiting_user.

        Input is validated through ``RequestApprovalInput`` (closed schema, length
        caps, unique option ids) before reaching the service. The service performs
        the insert + status flip + WebSocket broadcast atomically.

        BE-9054 (a): orchestrator-only. A worker job's request is converted here
        into the BE-6081 Tier-2 structured domain rejection (``{"success": False,
        "error": "ORCHESTRATOR_ONLY_APPROVAL", ...}``) — a deliberate,
        agent-actionable declined request that reaches the agent as normal tool
        content, not isError. The dashboard's Approve/Reject card binds only to
        the orchestrator's job, so a worker approval would be an unreachable dead
        end (awaiting_user with no UI able to clear it).
        """
        from giljo_mcp.schemas.user_approval import RequestApprovalInput

        if tenant_key is None:
            raise ValidationError("tenant_key is required")

        validated = RequestApprovalInput(
            job_id=job_id,
            project_id=project_id,
            reason=reason,
            options=options,
            context=context,
        )
        try:
            approval = await self._user_approval_service.create_pending(
                tenant_key=tenant_key,
                job_id=validated.job_id,
                project_id=validated.project_id,
                reason=validated.reason,
                options=[opt.model_dump() for opt in validated.options],
                context=validated.context,
            )
        except ValidationError as exc:
            if exc.error_code != "ORCHESTRATOR_ONLY_APPROVAL":
                raise
            return {
                "success": False,
                "error": "ORCHESTRATOR_ONLY_APPROVAL",
                "calling_agent_role": (exc.context or {}).get("job_type", "unknown"),
                "message": (
                    "request_approval is orchestrator-only: the dashboard approval card binds to "
                    "the orchestrator's job, so a worker approval would park you in awaiting_user "
                    "with nothing able to clear it. Your status was NOT changed. Post the decision "
                    "to your coordination thread instead (post_to_thread with requires_action=true, "
                    "directed to your orchestrator) and let the orchestrator decide or escalate to "
                    "the user."
                ),
            }
        return {
            "approval_id": approval.id,
            "status": approval.status,
        }

    async def decide_approval(
        self,
        approval_id: str,
        option_id: str,
        user_id: str | None = None,
        tenant_key: str | None = None,
    ) -> dict[str, Any]:
        """Resolve a pending user approval from the harness, clearing awaiting_user.

        Input is validated through ``DecideApprovalInput`` (closed schema, length
        caps) before reaching the service. Calls the SAME
        ``UserApprovalService.mark_decided`` the dashboard's decide button uses —
        no parallel write path. ``user_id`` is the resolved MCP session
        user (``None`` for a legacy API-key session with no user back-reference,
        matching the REST endpoint's ``current_user.id`` semantics as closely as
        the transport allows).

        A not-found, already-decided, or invalid option_id is a deliberate,
        agent-actionable BE-6081 Tier-2 rejection (mirrors the REST endpoint's
        404/409/422 mapping) — returned as structured content, never raised.
        """
        from giljo_mcp.schemas.user_approval import DecideApprovalInput

        if tenant_key is None:
            raise ValidationError("tenant_key is required")

        validated = DecideApprovalInput(approval_id=approval_id, option_id=option_id)
        try:
            decided = await self._user_approval_service.mark_decided(
                tenant_key=tenant_key,
                approval_id=validated.approval_id,
                option_id=validated.option_id,
                user_id=user_id,
                decided_via="mcp",
            )
        except ResourceNotFoundError as exc:
            return {
                "success": False,
                "error": "APPROVAL_NOT_FOUND",
                "message": str(exc),
            }
        except ValidationError as exc:
            if "is not pending" in exc.message:
                return {
                    "success": False,
                    "error": "APPROVAL_ALREADY_DECIDED",
                    "message": exc.message,
                }
            return {
                "success": False,
                "error": "APPROVAL_OPTION_INVALID",
                "message": exc.message,
            }
        return {
            "approval_id": decided.id,
            "status": decided.status,
            "decided_option_id": decided.decided_option_id,
            "job_id": decided.job_id,
            "project_id": decided.project_id,
        }
