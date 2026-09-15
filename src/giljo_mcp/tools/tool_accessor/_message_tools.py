# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.


from __future__ import annotations

from typing import Any

from giljo_mcp.exceptions import ResourceNotFoundError, ValidationError


class MessageToolsMixin:


    async def request_approval(
        self,
        job_id: str,
        project_id: str,
        reason: str,
        options: list[dict],
        context: dict | None = None,
        tenant_key: str | None = None,
    ) -> dict[str, Any]:
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
