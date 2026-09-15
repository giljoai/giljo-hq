# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.


from __future__ import annotations

import json
import logging
import os
from typing import Any

from mcp.server.elicitation import render_elicitation_schema
from mcp.server.mcpserver import Context
from mcp_types import ElicitRequest, ElicitRequestFormParams, InputRequiredResult
from mcp_types.version import is_version_at_least
from pydantic import Field as PField
from pydantic import create_model


logger = logging.getLogger(__name__)

_MRTR_VERSION = "2026-07-28"

_ELICIT_KEY = "giljo_approval"
_STATE_KIND = "be8003l.approval"

_DISABLE_ENV = "GILJO_MRTR_APPROVAL"
_OFF_VALUES = {"0", "false", "no", "off"}


def _mrtr_enabled() -> bool:
    return os.getenv(_DISABLE_ENV, "").strip().lower() not in _OFF_VALUES


def _client_supports_inline_approval(ctx: Context) -> bool:
    try:
        version = ctx.protocol_version
        if not version or not is_version_at_least(version, _MRTR_VERSION):
            return False
        capabilities = ctx.client_capabilities
        return getattr(capabilities, "elicitation", None) is not None
    except Exception:  # noqa: BLE001 - capability probe must never raise into the tool
        return False


def _normalize_options(options: list[dict] | None) -> list[dict]:
    if not options:
        return []
    return [opt for opt in options if isinstance(opt, dict) and opt.get("id")]


def _build_choice_schema(options: list[dict]):
    return create_model(
        "InlineApprovalResponse",
        choice=(
            str,
            PField(
                description="Selected option id",
                json_schema_extra={
                    "enum": [opt["id"] for opt in options],
                    "enumNames": [opt.get("label") or opt["id"] for opt in options],
                },
            ),
        ),
    )


def _format_message(reason: str, options: list[dict]) -> str:
    lines = [reason, "", "Options:"]
    lines.extend(f"  - {opt.get('label') or opt['id']} (id: {opt['id']})" for opt in options)
    return "\n".join(lines)


def _build_input_required(reason: str, options: list[dict], approval_id: str) -> InputRequiredResult:
    schema = _build_choice_schema(options)
    return InputRequiredResult(
        input_requests={
            _ELICIT_KEY: ElicitRequest(
                method="elicitation/create",
                params=ElicitRequestFormParams(
                    mode="form",
                    message=_format_message(reason, options),
                    requested_schema=render_elicitation_schema(schema),
                ),
            )
        },
        request_state=json.dumps({"kind": _STATE_KIND, "approval_id": approval_id}),
    )


def _pending_approval_id(request_state: str | None) -> str | None:
    if not request_state:
        return None
    try:
        state = json.loads(request_state)
    except (TypeError, ValueError):
        return None
    if not isinstance(state, dict) or state.get("kind") != _STATE_KIND:
        return None
    approval_id = state.get("approval_id")
    return approval_id if isinstance(approval_id, str) and approval_id else None


def _chosen_option_id(ctx: Context) -> str | None:
    try:
        responses = ctx.input_responses or {}
    except Exception:  # noqa: BLE001 - never raise into the tool
        return None
    answer = responses.get(_ELICIT_KEY)
    if answer is None or getattr(answer, "action", None) != "accept":
        return None
    content = getattr(answer, "content", None)
    if not isinstance(content, dict):
        return None
    choice = content.get("choice")
    return choice if isinstance(choice, str) and choice else None


async def _decide_inline(ctx: Context, approval_id: str, option_id: str) -> bool:
    from api.endpoints.mcp_tools._base import _get_tool_accessor, _resolve_tenant, _resolve_user_id
    from giljo_mcp.exceptions import ResourceNotFoundError, ValidationError

    try:
        accessor = _get_tool_accessor()
        tenant_key = _resolve_tenant(ctx)
        user_id = _resolve_user_id(ctx)
        await accessor._user_approval_service.mark_decided(
            tenant_key=tenant_key,
            approval_id=approval_id,
            option_id=option_id,
            user_id=user_id,
            decided_via="mcp",
        )
        return True
    except (ValidationError, ResourceNotFoundError):
        logger.info("[BE-8003l] inline decide superseded (concurrent/absent) approval=%s", approval_id)
        return False
    except Exception:  # noqa: BLE001 - any write failure falls back to the async path
        logger.warning("[BE-8003l] inline decide failed approval=%s; async fallback", approval_id, exc_info=True)
        return False


async def resolve_pending_inline_approval(ctx: Context | None, options: list[dict] | None) -> dict[str, Any] | None:
    if ctx is None:
        return None
    try:
        approval_id = _pending_approval_id(ctx.request_state)
    except Exception:  # noqa: BLE001 - a context without the attribute is round one
        return None
    if approval_id is None:
        return None

    pending = {"approval_id": approval_id, "status": "pending"}
    choice = _chosen_option_id(ctx)
    if choice is None or choice not in {opt["id"] for opt in _normalize_options(options)}:
        return pending
    if not await _decide_inline(ctx, approval_id, choice):
        return pending
    return {"approval_id": approval_id, "status": "decided", "decided_option_id": choice, "surface": "inline"}


def maybe_offer_approval_inline(
    ctx: Context | None,
    approval_result: Any,
    *,
    reason: str,
    options: list[dict] | None,
) -> Any:
    if ctx is None or not _mrtr_enabled():
        return approval_result
    if not isinstance(approval_result, dict):
        return approval_result
    approval_id = approval_result.get("approval_id")
    if not approval_id or approval_result.get("status") != "pending":
        return approval_result

    norm_options = _normalize_options(options)
    if not norm_options or not _client_supports_inline_approval(ctx):
        return approval_result

    try:
        return _build_input_required(reason, norm_options, approval_id)
    except Exception:  # noqa: BLE001 - building the offer is best-effort
        logger.warning("[BE-8003l] inline approval offer failed to build; async fallback", exc_info=True)
        return approval_result
