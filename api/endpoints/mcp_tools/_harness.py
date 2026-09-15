# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.


from typing import TYPE_CHECKING

from mcp.server.mcpserver import Context
from starlette.requests import Request as StarletteRequest


if TYPE_CHECKING:
    from mcp.types import ClientCapabilities

from giljo_mcp.harness_resolver import preset_from_client_info
from giljo_mcp.platform_registry import GENERIC_HARNESS, harness_from_client_info, select_effective_preset


def _persisted_harness(ctx: Context) -> str | None:
    try:
        request: StarletteRequest = ctx.request_context.request
        value = request.scope.get("state", {}).get("resolved_harness")
        return value if isinstance(value, str) and value else None
    except Exception:  # noqa: BLE001 - detection is a render hint, never raise into the tool
        return None


def _detected_harness(ctx: Context) -> str:
    try:
        client_info = ctx.session.client_params.client_info
        live = harness_from_client_info(getattr(client_info, "name", None), getattr(client_info, "version", None))
    except Exception:  # noqa: BLE001 - detection is a render hint, never raise into the tool
        live = GENERIC_HARNESS
    if live != GENERIC_HARNESS:
        return live
    return _persisted_harness(ctx) or GENERIC_HARNESS


def _persisted_preset(ctx: Context) -> str | None:
    try:
        request: StarletteRequest = ctx.request_context.request
        value = request.scope.get("state", {}).get("resolved_preset")
        return value if isinstance(value, str) and value else None
    except Exception:  # noqa: BLE001 - detection is a render hint, never raise into the tool
        return None


def _detected_preset(ctx: Context) -> str | None:
    try:
        client_info = ctx.session.client_params.client_info
        live = preset_from_client_info(getattr(client_info, "name", None), getattr(client_info, "version", None))
    except Exception:  # noqa: BLE001 - detection is a render hint, never raise into the tool
        live = None
    return live or _persisted_preset(ctx)


_TASKS_EXPERIMENTAL_KEY = "io.modelcontextprotocol/tasks"


def _protocol_capabilities(ctx: Context) -> "ClientCapabilities | None":
    from mcp.types import ClientCapabilities

    try:
        declared = ctx.client_capabilities
    except Exception:  # noqa: BLE001 - capability read must never raise into the tool
        return None
    return declared if isinstance(declared, ClientCapabilities) else None


def get_session_capabilities(ctx: Context) -> dict[str, bool | str | None]:
    from mcp.types import ClientCapabilities, ElicitationCapability

    def _probe(cap: ClientCapabilities) -> bool:
        try:
            return bool(ctx.session.check_client_capability(cap))
        except Exception:  # noqa: BLE001 - capability probe must never raise into the tool
            return False

    declared = _protocol_capabilities(ctx)

    def _supports_elicitation() -> bool:
        if declared is not None:
            return declared.elicitation is not None
        return _probe(ClientCapabilities(elicitation=ElicitationCapability()))

    def _supports_tasks() -> bool:
        if declared is not None:
            return declared.tasks is not None or _TASKS_EXPERIMENTAL_KEY in (declared.experimental or {})
        return _probe(ClientCapabilities(experimental={_TASKS_EXPERIMENTAL_KEY: {}}))

    return {
        "elicitation": _supports_elicitation(),
        "tasks": _supports_tasks(),
        "harness": _detected_harness(ctx),
        "preset": _detected_preset(ctx),
    }


_HARNESS_PARAM_DESCRIPTION = "Session type when there is no terminal: web_sandbox | desktop_app | chat. Omit for a CLI."


def _resolve_preset_name(harness: str, ctx: Context) -> str | None:
    capabilities = get_session_capabilities(ctx) if ctx is not None else None
    preset = select_effective_preset(harness, capabilities)
    return preset.execution_mode if preset is not None else None
