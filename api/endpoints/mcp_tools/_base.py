# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.


import asyncio
import functools
import hashlib
import inspect
import logging
import os
import re
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime
from typing import Any

from mcp.server.caching import CacheHint
from mcp.server.mcpserver import Context, MCPServer
from mcp.server.mcpserver.exceptions import MCPServerError
from mcp.server.request_state import RequestStateSecurity
from pydantic import BaseModel
from starlette.requests import Request as StarletteRequest

from api.endpoints.mcp_tools._call_metrics import record_tool_call
from api.endpoints.mcp_tools._harness import (  # noqa: F401
    _HARNESS_PARAM_DESCRIPTION,
    _detected_harness,
    _persisted_harness,
    _resolve_preset_name,
    get_session_capabilities,
)

from api.endpoints.mcp_tools._silence_scope import NON_SILENCE_CLEARING_TOOLS, SILENCE_CLEARING_TOOLS  # noqa: F401
from giljo_mcp import __version__ as _giljo_version
from giljo_mcp import branding
from giljo_mcp.exceptions import BaseGiljoError, CodedRefusalError, ValidationError
from giljo_mcp.schemas.jsonb_validators import GitCommitShaRequiredError
from giljo_mcp.services._comm_thread_wake_mixin import MAX_WAIT_SECONDS as _INTENTIONAL_LONGPOLL_MAX_SECONDS
from giljo_mcp.services._mcp_wire_bounds import CursorRejectedError
from giljo_mcp.services.debounce import should_run
from giljo_mcp.services.memory_entry_write_validator import MemoryEntryWriteValidationError
from giljo_mcp.tenant_guard import TenantIsolationError
from giljo_mcp.tools.slash_command_templates import SKILLS_VERSION as _SKILLS_VERSION


_SANITIZED_TOOL_ERROR = (
    "The server hit an unexpected internal error handling this request. "
    "Full details were logged server-side (no SQL, parameters, or stack trace are "
    "exposed to agents). Retry the call; if it persists, report the tool name."
)

_NOT_FOUND_TOOL_ERROR = "The requested resource was not found, or you do not have access to it."

_CLEAN_VALIDATION_ERRORS: tuple[type[Exception], ...] = (
    ValueError,
    TypeError,
    MemoryEntryWriteValidationError,
)

_SQL_LEAK_SIGNATURE = re.compile(
    r"\[SQL:"
    r"|\[SQL parameters:"
    r"|\[parameters:"
    r"|Background on this error at: https://sqlalche\.me"
    r"|(?:INSERT\s+INTO|UPDATE\s+\S+\s+SET|DELETE\s+FROM|SELECT\b.+?\bFROM)"
    r"\b.*?\b(?:parameters|params|bind[_ ]?params?)\b\s*[=:]",
    re.IGNORECASE | re.DOTALL,
)


MCP_ID_MAX = 64
MCP_NAME_MAX = 200
MCP_SHORT_TEXT_MAX = 2_000
MCP_MESSAGE_MAX = 20_000
MCP_DESCRIPTION_MAX = 20_000
MCP_MISSION_MAX = 100_000
MCP_LIST_ITEMS_MAX = 100


HELD_TOOL_CEILING_SECONDS = _INTENTIONAL_LONGPOLL_MAX_SECONDS + 3

TOOL_CEILING_ERROR = "TOOL_CEILING_EXCEEDED"
_TOOL_CEILING_MESSAGE = (
    "This tool call was still running after {ceiling}s and was stopped so it could not "
    "hold the connection pool or the request open indefinitely. It may have partially "
    "completed -- check its effect via a status/read tool before retrying."
)

MCP_MAX_RESULT_SIZE_CHARS = 500_000
MCP_HEAVY_TOOL_META: dict[str, int] = {"anthropic/maxResultSizeChars": MCP_MAX_RESULT_SIZE_CHARS}


GIT_COMMITS_DESC = (
    "Commits from this project's branch. Each entry needs a non-empty title. Pass "
    "{sha, message, author?, pr_url?} dicts, or tab-separated '<sha>\\t<subject>\\t<author>' "
    "lines from: git log --format='%H%x09%s%x09%an' <base>..HEAD"
)

CURSOR_DESC = (
    "Continue where a previous list stopped: pass back the `next_cursor` from that "
    "response, with the SAME filters. Keep going until `truncated` is false and every "
    "row will have been returned exactly once. Changing a filter mid-walk is refused "
    "rather than silently answered from the wrong set; start over instead."
)

READ_PRODUCT_ID_DESC = (
    "Product UUID to {what}. Omit to use your default product. PASS IT WHEN YOU KNOW "
    "YOUR PRODUCT: the default is shared, mutable state -- another session, or the user "
    "changing it in the dashboard, moves it mid-session. An id that is not one of your "
    "own products is rejected; it never falls back to the default."
)

_POSTHOOK_DEBOUNCE_SECONDS = 30


def _parse_iso_datetime_param(s: str) -> datetime | None:
    if not s:
        return None
    try:
        parsed = datetime.fromisoformat(s.replace("Z", "+00:00"))
    except (ValueError, TypeError) as exc:
        raise ValidationError(f"Invalid ISO-8601 datetime '{s}'. Expected e.g. '2026-01-01T00:00:00Z'.") from exc
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=UTC)


logger = logging.getLogger(__name__)

_TOOLS_LIST_CACHE_TTL_MS = 60_000


def _request_state_security() -> RequestStateSecurity:
    secret = os.getenv("JWT_SECRET") or os.getenv("GILJO_MCP_SECRET_KEY") or os.getenv("SECRET_KEY")
    if not secret:
        logger.warning(
            "No JWT_SECRET/GILJO_MCP_SECRET_KEY/SECRET_KEY set; sealing MCP requestState under a "
            "per-process ephemeral key. Multi-worker deployments will refuse cross-worker retries."
        )
        return RequestStateSecurity.ephemeral()
    derived = hashlib.sha256(b"giljo/mcp/request-state/v1|" + secret.encode()).digest()
    return RequestStateSecurity(keys=[derived])


mcp = MCPServer(
    name=branding.MCP_ALIAS,
    instructions=f"{branding.DESCRIPTOR}. {branding.TWO_HUB_DISAMBIGUATION}",
    version=_giljo_version,
    cache_hints={"tools/list": CacheHint(ttl_ms=_TOOLS_LIST_CACHE_TTL_MS, scope="private")},
    request_state_security=_request_state_security(),
)


from api.endpoints.mcp_tools._scopes import (  # noqa: E402,F401  (re-export surface)
    _CORE_PROFILE_TOOLS,
    _HITL_FENCED_TOOLS,
    _LAUNCH_GATE_TOOLS,
    _LISTING_PROFILE_TOOLS,
    _ORCHESTRATOR_PROFILE_TOOLS,
    _STANDARD_PROFILE_TOOLS,
    PROFILE_CORE,
    PROFILE_FULL,
    PROFILE_LISTING,
    PROFILE_ORCHESTRATOR,
    PROFILE_STANDARD,
    SCOPE_AGENT,
    SCOPE_READ,
    SCOPE_WRITE,
    TOOL_PROFILES,
    TOOL_SCOPES,
    _normalize_scopes,
    _profile_toolset_from_request,
    _profile_toolset_from_state,
    _scopes_from_request,
)




def _get_tool_accessor():
    from api.app_state import state

    if not state.tool_accessor:
        raise RuntimeError("Tool accessor not initialized")
    return state.tool_accessor


def _get_tenant_manager():
    from api.app_state import state

    return state.tenant_manager


def _resolve_tenant(ctx: Context) -> str:
    request: StarletteRequest = ctx.request_context.request
    tenant_key = request.scope.get("state", {}).get("tenant_key")
    if not tenant_key:
        raise RuntimeError("No tenant_key in request state -- auth middleware missing")
    return tenant_key


def _resolve_user_id(ctx: Context) -> str | None:
    request: StarletteRequest = ctx.request_context.request
    return request.scope.get("state", {}).get("user_id")


def _set_tenant_context(tenant_key: str) -> None:
    _get_tenant_manager().set_current_tenant(tenant_key)



ToolResolver = Callable[[Any], Callable[..., Awaitable[Any]]]

TOOL_DISPATCH: dict[str, ToolResolver] = {
    "create_project": lambda acc: functools.partial(
        acc._project_service.create_project_for_mcp, websocket_manager=acc._websocket_manager
    ),
    "list_projects": lambda acc: functools.partial(
        acc._project_service.list_projects_for_mcp, websocket_manager=acc._websocket_manager
    ),
    "update_project_metadata": lambda acc: functools.partial(
        acc._project_service.update_project_metadata_for_mcp, websocket_manager=acc._websocket_manager
    ),
    "create_task": lambda acc: functools.partial(
        acc._task_service.create_task_for_mcp,
        db_manager=acc.db_manager,
        websocket_manager=acc._websocket_manager,
    ),
    "update_task": lambda acc: acc._task_service.update_task_for_mcp,
    "list_tasks": lambda acc: acc._task_service.list_tasks_for_mcp,
    "update_roadmap_metadata": lambda acc: acc._roadmap_service.upsert_metadata,
    "get_roadmap": lambda acc: acc._roadmap_service.get_roadmap,
    "create_thread": lambda acc: acc._comm_thread_service.create_thread,
    "update_thread": lambda acc: acc._comm_thread_service.update_thread,
    "post_to_thread": lambda acc: acc._comm_thread_service.post_to_thread,
    "get_my_turn": lambda acc: acc._comm_thread_service.get_my_turn,
    "await_my_turn": lambda acc: acc._comm_thread_service.await_my_turn,
    "get_participant_liveness": lambda acc: acc._comm_thread_service.get_participant_liveness,
    "pass_baton": lambda acc: acc._comm_thread_service.pass_baton,
    "list_threads": lambda acc: acc._comm_thread_service.list_threads,
    "get_thread_history": lambda acc: acc._comm_thread_service.get_thread_history,
    "search_threads": lambda acc: acc._comm_thread_service.search_threads,
    "get_staging_instructions": lambda acc: acc._mission_service.get_staging_instructions,
    "get_job_mission": lambda acc: acc._mission_service.get_agent_mission,
    "update_job_mission": lambda acc: acc._mission_service.update_agent_mission,
    "get_workflow_status": lambda acc: acc._workflow_status_service.get_workflow_status,
    "report_progress": lambda acc: acc._progress_service.report_progress,
    "complete_job": lambda acc: acc._job_completion_service.complete_job,
    "close_job": lambda acc: acc._agent_state_service.close_job,
    "reactivate_job": lambda acc: acc._agent_state_service.reactivate_job,
    "dismiss_reactivation": lambda acc: acc._agent_state_service.dismiss_reactivation,
    "spawn_job": lambda acc: acc._orchestration_service.spawn_job,
}


def _resolve_tool_func(accessor: Any, method_name: str) -> Callable[..., Awaitable[Any]]:
    resolver = TOOL_DISPATCH.get(method_name)
    if resolver is not None:
        return resolver(accessor)
    return getattr(accessor, method_name)



VALIDATION_ERROR = "VALIDATION_ERROR"
CONSTRAINT_NON_EMPTY = "non_empty"
CONSTRAINT_INVALID_CHOICE = "invalid_choice"
CONSTRAINT_MUTUALLY_EXCLUSIVE = "mutually_exclusive"


def validation_rejection(*, field: str, constraint: str, message: str) -> dict[str, Any]:
    return {
        "success": False,
        "error": VALIDATION_ERROR,
        "field": field,
        "constraint": constraint,
        "message": message,
    }


def blank_text_rejection(field: str, *, entity: str) -> dict[str, Any] | None:
    return validation_rejection(
        field=field,
        constraint=CONSTRAINT_NON_EMPTY,
        message=f"{entity} {field} is required and cannot be empty or whitespace-only.",
    )


def pydantic_validation_rejection(exc: Exception) -> dict[str, Any]:
    errors = exc.errors() if hasattr(exc, "errors") else []
    if not errors:
        return validation_rejection(field="", constraint="invalid", message=str(exc))
    first = errors[0]
    loc = ".".join(str(part) for part in first.get("loc", ()) if part is not None)
    ctx = first.get("ctx") or {}
    constraint = str(first.get("type", "invalid"))
    msg = str(first.get("msg", "Invalid value"))
    if constraint == "string_too_long" and "max_length" in ctx:
        msg = f"Must be at most {ctx['max_length']} characters."
    elif constraint == "missing":
        msg = "This argument is required."
    return validation_rejection(field=loc, constraint=constraint, message=f"{loc}: {msg}" if loc else msg)


def _held_tool_ceiling_response(method_name: str) -> dict[str, Any]:
    logger.warning(
        "MCP tool dispatch '%s' exceeded the %ss held-request ceiling; cancelled",
        method_name,
        HELD_TOOL_CEILING_SECONDS,
    )
    return {
        "success": False,
        "error": TOOL_CEILING_ERROR,
        "message": _TOOL_CEILING_MESSAGE.format(ceiling=HELD_TOOL_CEILING_SECONDS),
    }





def _missing_commit_identifier_response(exc: GitCommitShaRequiredError, method_name: str) -> dict[str, Any]:
    logger.info("MCP tool '%s' refused a commit with no identifier", method_name)
    return validation_rejection(field=exc.field, constraint=exc.constraint, message=str(exc))


async def _call_tool(ctx: Context, method_name: str, kwargs: dict[str, Any]) -> Any:
    tenant_key = _resolve_tenant(ctx)
    _set_tenant_context(tenant_key)

    record_tool_call(tenant_key, method_name)

    accessor = _get_tool_accessor()
    tool_func = _resolve_tool_func(accessor, method_name)

    sig = inspect.signature(tool_func)
    if "tenant_key" in sig.parameters:
        kwargs["tenant_key"] = tenant_key
    else:
        kwargs.pop("tenant_key", None)

    try:
        result = await asyncio.wait_for(tool_func(**kwargs), timeout=HELD_TOOL_CEILING_SECONDS)
    except TimeoutError:
        return _held_tool_ceiling_response(method_name)
    except CursorRejectedError as exc:
        logger.info("MCP tool '%s' refused a continuation cursor: %s", method_name, exc.code)
        return {"success": False, "error": exc.code, "message": str(exc)}
    except GitCommitShaRequiredError as exc:
        return _missing_commit_identifier_response(exc, method_name)
    except CodedRefusalError as exc:
        logger.info("MCP tool '%s' refused with %s", method_name, exc.code)
        return exc.as_refusal()
    except BaseGiljoError as exc:
        if exc.default_status_code < 500:
            raise
        logger.exception("MCP tool dispatch '%s' failed with a server-side error", method_name)
        raise MCPServerError(_SANITIZED_TOOL_ERROR) from exc
    except MCPServerError:
        raise
    except TenantIsolationError as exc:
        logger.warning("MCP tool dispatch '%s' blocked by tenant isolation guard", method_name)
        raise MCPServerError(_NOT_FOUND_TOOL_ERROR) from exc
    except _CLEAN_VALIDATION_ERRORS as exc:
        if _SQL_LEAK_SIGNATURE.search(str(exc)):
            logger.exception(
                "MCP tool dispatch '%s' raised a ValueError/TypeError carrying a "
                "SQL/bind-parameter leak signature; sanitizing before it reaches the agent",
                method_name,
            )
            raise MCPServerError(_SANITIZED_TOOL_ERROR) from exc
        raise
    except Exception as exc:
        logger.exception("MCP tool dispatch '%s' raised an unexpected error", method_name)
        raise MCPServerError(_SANITIZED_TOOL_ERROR) from exc

    job_id = kwargs.get("job_id")
    if job_id and should_run("mcp_posthooks", job_id, _POSTHOOK_DEBOUNCE_SECONDS):
        try:
            from api.app_state import state as app_state
            from giljo_mcp.services.heartbeat import touch_heartbeat
            from giljo_mcp.services.silence_detector import auto_clear_silent

            ws_manager = getattr(app_state, "websocket_manager", None)
            async with app_state.db_manager.get_session_async() as db:
                if method_name in SILENCE_CLEARING_TOOLS:
                    try:
                        await auto_clear_silent(db, job_id, ws_manager, tenant_key=tenant_key)
                    except (OSError, RuntimeError, ValueError, TypeError, AttributeError, KeyError):
                        logger.warning("auto_clear_silent failed for job_id=%s (non-blocking)", job_id)

                try:
                    await touch_heartbeat(db, job_id, tenant_key=tenant_key)
                except (OSError, RuntimeError, ValueError, TypeError, AttributeError, KeyError):
                    logger.debug("heartbeat update failed for job_id=%s (non-blocking)", job_id)
        except (OSError, RuntimeError, ValueError, TypeError, AttributeError, KeyError):
            logger.debug("post-hooks failed for job_id=%s (non-blocking)", job_id)

    if isinstance(result, BaseModel):
        result = result.model_dump(mode="json")

    if isinstance(result, dict):
        meta = result.get("_meta")
        if not isinstance(meta, dict):
            meta = {}
        meta["skills_version"] = _SKILLS_VERSION
        result["_meta"] = meta
    return result
