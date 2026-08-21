# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.

"""BE-8003l item 1: ``request_approval`` offers an inline approval to capable clients.

The shape, and why it is this shape
===================================
``request_approval`` parks: it creates a pending approval, flips the calling agent
to ``awaiting_user``, and returns. Only ``POST /api/approvals/{id}/decide`` clears
that gate. For a client that can be asked, MCP 2026-07-28's multi-round-trip
(MRTR) lets us ALSO offer the choice inline:

* **Round 1** runs today's path unchanged -- the row is created and the execution
  parked -- and then returns an ``InputRequiredResult`` carrying an
  ``ElicitRequest`` plus ``request_state`` naming the approval. A client that never
  retries leaves us in exactly today's world, so the fallback is not a code path
  we maintain, it is the absence of a second round.
* **Round 2** is a fresh ``tools/call`` echoing that state; the answer is resolved
  through the SAME atomic ``UserApprovalService.mark_decided`` the dashboard uses.
  There is NO second write path.

Two shapes exist for MRTR and only one fits (BE-8003l):
``Annotated[T, Resolve(fn)]`` fills a parameter by running a resolver BEFORE the
tool body -- which would ask the user before the approval row exists and, on a
decline, park nothing at all. The SDK also forbids combining the two channels
("a call has one input_required channel"). So the flow is driven by the body.

The gate is the protocol ERA first, capability second
=====================================================
``InputRequiredResult`` is not a legal ``tools/call`` result before 2026-07-28:
the SDK validates results against the NEGOTIATED revision, so returning one to a
2025-11-25 session is a **-32603 Internal error**, measured. The live fleet is
claude-code on a 2025-era revision, so a capability-only gate would have failed
every production approval. Capability alone LOOKS safe today only because
``stateless_http`` drops a handshake's declaration before ``tools/call`` -- an
accident of one transport flag, not an invariant. Hence both checks, era first.

``ctx.elicit()`` is deliberately gone. It is the server-initiated channel, which
on the modern era raises ``NoBackChannelError`` unconditionally and which our
``json_response`` transport never carried on the legacy era either. The BE-6038
prototype's constraint C1 predicted GA would make it work; GA replaced it.

Every miss -- not capable, options empty, a declined choice, a concurrent
dashboard decision, a malformed retry -- returns the original result unchanged.
This never raises into the tool.

Edition Scope: Both.
"""

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

# The first revision whose tools/call can carry an InputRequiredResult.
_MRTR_VERSION = "2026-07-28"

# Key of the single elicitation we embed, and the marker distinguishing OUR
# request_state from any other handler's. The state is sealed and args-bound by
# the SDK boundary before it reaches a client, so this is a routing tag, not a
# security control -- the tenant scope on mark_decided is what enforces access.
_ELICIT_KEY = "giljo_approval"
_STATE_KIND = "be8003l.approval"

# Kill switch, not a feature flag: the feature is gated STRUCTURALLY on the
# connection's era + capability, which is detectable. This exists so an operator
# can turn the inline offer off without a code change; it defaults to ON because
# a default-OFF flag would ship the same dormant prototype BE-8003l exists to
# retire.
_DISABLE_ENV = "GILJO_MRTR_APPROVAL"
_OFF_VALUES = {"0", "false", "no", "off"}


def _mrtr_enabled() -> bool:
    """False only when an operator has explicitly switched the inline offer off."""
    return os.getenv(_DISABLE_ENV, "").strip().lower() not in _OFF_VALUES


def _client_supports_inline_approval(ctx: Context) -> bool:
    """True only when this connection can actually carry the round-trip.

    Era first (returning an InputRequiredResult below 2026-07-28 is a -32603),
    then the declared elicitation capability. ``is_version_at_least`` returns
    False for any revision it does not know, so an unrecognised peer fails closed.

    Best-effort by contract: any probe failure means "not capable", which means
    today's park-and-refuse answer.
    """
    try:
        version = ctx.protocol_version
        if not version or not is_version_at_least(version, _MRTR_VERSION):
            return False
        capabilities = ctx.client_capabilities
        return getattr(capabilities, "elicitation", None) is not None
    except Exception:  # noqa: BLE001 - capability probe must never raise into the tool
        return False


def _normalize_options(options: list[dict] | None) -> list[dict]:
    """Keep only well-formed {id, label} option dicts with a non-empty id."""
    if not options:
        return []
    return [opt for opt in options if isinstance(opt, dict) and opt.get("id")]


def _build_choice_schema(options: list[dict]):
    """Single-field model whose ``choice`` is a constrained string of option ids.

    Deliberately a ``str`` carrying ``enum``/``enumNames`` rather than a python
    ``Enum`` field. The spec's ``PrimitiveSchemaDefinition`` admits no ``$ref``,
    and pydantic renders ANY enum-typed field as ``$ref: #/$defs/...`` -- the SDK's
    own ``render_elicitation_schema`` rejects that outright, measured. (That is
    also a second reason the BE-6038 prototype could never have worked: its enum
    model would have been refused at render time even if the transport had carried
    the round-trip.) This form renders as
    ``{"type": "string", "enum": [...], "enumNames": [...]}`` -- spec-valid, and
    still the FE-1330 label convention for host rendering.

    Nothing is trusted from the client's answer: the returned id is checked against
    the caller's own option list before any write.
    """
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
    """The round-1 marker: one embedded elicitation plus the state to echo back.

    ``render_elicitation_schema`` rather than ``model_json_schema()``: the spec
    restricts an elicitation's ``requestedSchema`` to PRIMITIVE definitions, and
    pydantic's default rendering hoists an enum into ``$defs`` behind a ``$ref``,
    which no client is required to follow. The SDK's own renderer inlines it and
    raises if a field would not be spec-valid.
    """
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
    """Read the approval id out of a round-2 echo, or None if it is not ours.

    The SDK's ``RequestStateBoundary`` has already unsealed and verified this --
    the handler only ever sees plaintext it minted, bound to this tool, these
    arguments, and this principal. So the parsing here is for shape, not trust.
    """
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
    """The option the user accepted on round 2, or None for declined/cancelled/absent.

    A retry that carries no answer returns None and the caller reports the approval
    still pending -- it must NOT re-ask, or a client that cannot answer loops.
    """
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
    """Resolve the approval inline through the existing atomic write path.

    Returns True on a successful decide; False when the row was already resolved
    (concurrent dashboard decision), absent, or the write failed -- in which case
    the caller falls back to the async ``awaiting_user`` path.
    """
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
        )
        return True
    except (ValidationError, ResourceNotFoundError):
        # Not pending (dashboard won the race) or gone -> already resolved elsewhere.
        logger.info("[BE-8003l] inline decide superseded (concurrent/absent) approval=%s", approval_id)
        return False
    except Exception:  # noqa: BLE001 - any write failure falls back to the async path
        logger.warning("[BE-8003l] inline decide failed approval=%s; async fallback", approval_id, exc_info=True)
        return False


async def resolve_pending_inline_approval(ctx: Context | None, options: list[dict] | None) -> dict[str, Any] | None:
    """Round 2: settle the approval this retry is answering, WITHOUT re-dispatching.

    Returns the tool's response dict when this call is a retry of an inline offer,
    or ``None`` when it is an ordinary first-round call the caller should dispatch
    normally. Returning ``None`` is what keeps a retry from minting a second
    approval row -- the caller MUST consult this before dispatch.
    """
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
    # Declined, cancelled, or a retry carrying no answer: the row stays parked for
    # the dashboard and we do NOT ask again.
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
    """Round 1: offer the choice inline when the connection can carry it.

    Returns either an ``InputRequiredResult`` (capable client) or
    ``approval_result`` unchanged (everyone else, and every miss). The approval row
    is already created and parked either way, so this only ever ADDS an offer.
    NEVER raises.
    """
    if ctx is None or not _mrtr_enabled():
        return approval_result
    if not isinstance(approval_result, dict):
        return approval_result
    approval_id = approval_result.get("approval_id")
    if not approval_id or approval_result.get("status") != "pending":
        # Covers the BE-6081 ORCHESTRATOR_ONLY_APPROVAL rejection, which carries no
        # approval to offer, and an already-decided row.
        return approval_result

    norm_options = _normalize_options(options)
    if not norm_options or not _client_supports_inline_approval(ctx):
        return approval_result

    try:
        return _build_input_required(reason, norm_options, approval_id)
    except Exception:  # noqa: BLE001 - building the offer is best-effort
        logger.warning("[BE-8003l] inline approval offer failed to build; async fallback", exc_info=True)
        return approval_result
